"""
core/server/service.py — the listener, connections, and change publishing.

Threads
-------
accept      takes connections and hands each to its own thread
connection  one per device: TLS handshake, pairing or hello, then commands
publisher   while any device is connected, rebuilds the model every
            :data:`TICK_S` and sends each device the panels that changed

The publisher does nothing at all while no device is connected, which is the
normal state: a glance-and-go client connects when the app opens and leaves
when it closes.

Trust
-----
Every connection is TLS 1.3.  The server presents its own certificate, which
devices pin by fingerprint.  Devices present theirs, which the server trusts
because each paired device's certificate is loaded as its own trust anchor, so
OpenSSL itself refuses any certificate that was never paired or has since been
revoked.  A connection presenting no certificate may do exactly one thing:
offer a pairing code, and only while a ticket from ``edld --pair`` is open.

Failures here are never silent.  A port that cannot be bound, a device that
fails the handshake, a component that throws while building a panel — each is
logged, and the ones a commander must act on are raised in the Alerts pane.
"""

from __future__ import annotations

import base64
import socket
import ssl
import sys
import threading
import time
from pathlib import Path
from typing import Callable

from core.server import PROTOCOL_VERSION
from core.server import identity as _identity
from core.server import pairing as _pairing
from core.server import protocol as _proto

TICK_S = 1.5
HANDSHAKE_TIMEOUT_S = 15
IDLE_TIMEOUT_S = 90            # a client pings every 30 s; three missed is gone
MAX_CONNECTIONS = 8

FEATURES = ("snapshot", "panels", "end_session", "press", "tool", "action")


def _is_loopback(host: str) -> bool:
    import ipaddress
    try:
        a = ipaddress.ip_address(host)
    except ValueError:
        return False
    mapped = getattr(a, "ipv4_mapped", None)
    return (mapped or a).is_loopback


def _edld_version() -> str:
    try:
        from core.state import VERSION
        return str(VERSION)
    except Exception:
        return ""


class _Client:
    def __init__(self, sock: ssl.SSLSocket, device: dict, addr):
        self.sock = sock
        self.device = device
        self.addr = addr
        self.lock = threading.Lock()
        self.alive = True

    def send(self, msg: dict) -> bool:
        data = _proto.encode(msg)
        with self.lock:
            if not self.alive:
                return False
            try:
                self.sock.sendall(data)
                return True
            except OSError:
                self.alive = False
                return False

    def close(self) -> None:
        with self.lock:
            self.alive = False
            try:
                self.sock.close()
            except OSError:
                pass


class ServerService:
    def __init__(self, core, *, directory: Path, settings: dict,
                 name: str, journal_dir=None,
                 log: Callable[[str], None] | None = None,
                 alert: Callable[[str], None] | None = None):
        self.core = core
        self.directory = Path(directory)
        self.settings = settings
        self.name = name
        self.journal_dir = journal_dir
        self._log = log or (lambda m: None)
        self._alert = alert or (lambda m: None)

        self.identity = _identity.load_or_create(self.directory, name)
        self.registry = _pairing.DeviceRegistry(self.directory)
        self.builder = _proto.SnapshotBuilder(core, journal_dir, self._log,
                                              kill_allowed=self.end_session_allowed)
        self.tracker = _proto.ChangeTracker()

        self._ctx: ssl.SSLContext | None = None
        self._ctx_lock = threading.Lock()
        self._model_lock = threading.Lock()
        self._clients: list[_Client] = []
        self._clients_lock = threading.Lock()
        self._conn_count = 0
        self._sock: socket.socket | None = None
        self._stop = threading.Event()
        self.bound: tuple[str, int] | None = None
        self.portmap = None
        self.duckdns = None
        self.firewall_advice: list[str] = []
        self.firewall_certain = False
        self._preclose_logged: dict[str, float] = {}
        self._handshake_fails: dict[tuple, tuple] = {}

    # ── lifecycle ─────────────────────────────────────────────────────────────

    def start(self) -> None:
        """Bind and start serving.  Raises OSError if the port cannot be had."""
        self._rebuild_context()
        self._sock = self._bind(str(self.settings.get("BindAddress", "") or ""),
                                int(self.settings.get("Port", 0) or 0))
        self.bound = self._sock.getsockname()[:2]
        threading.Thread(target=self._accept_loop, name="edld-server-accept",
                         daemon=True).start()
        threading.Thread(target=self._publish_loop, name="edld-server-publish",
                         daemon=True).start()

        # A firewall that drops new connections is the usual reason a phone on
        # the same network cannot pair, and nothing about it ever reaches
        # this process to be logged.  Say so up front.
        try:
            from core.server.firewall import check
            self.firewall_advice, self.firewall_certain = check(self.bound[1])
        except Exception as exc:
            self._log(f"[server] firewall check failed: {type(exc).__name__}: {exc}")
        for line in self.firewall_advice:
            self._log(f"[server] {line}")
        # Pushed at every start only when EDLD can see the port is blocked.
        # A firewall whose rules it cannot read — ufw, from an ordinary
        # account — would otherwise raise the same alert on every launch
        # long after the commander had opened the port.
        if self.firewall_certain:
            self._alert("This computer's firewall blocks devices — see "
                        "Options → Server, or run edld --pair")

        if bool(self.settings.get("PortMapping", False)):
            from core.server.portmap import PortMapper
            self.portmap = PortMapper(self.bound[1], log=self._log, alert=self._alert)
            self.portmap.start()
        domain = str(self.settings.get("DuckDNSDomain", "") or "")
        token = str(self.settings.get("DuckDNSToken", "") or "")
        if domain and token:
            from core.server.duckdns import DuckDNSUpdater
            self.duckdns = DuckDNSUpdater(domain, token, log=self._log,
                                          alert=self._alert)
            self.duckdns.start()

    def stop(self) -> None:
        if self._stop.is_set():
            return
        self._stop.set()
        for helper in (self.portmap, self.duckdns):
            if helper is not None:
                try:
                    helper.stop()
                except Exception as exc:
                    self._log(f"[server] stopping {type(helper).__name__}: {exc}")
        if self._sock is not None:
            # Shut down before closing: on Linux, closing a listening socket
            # does not wake a thread blocked in accept() on it, and the
            # socket goes on listening — and accepting — until that call
            # returns. A server started again in the same process could then
            # find its first connections answered by the old one, with the
            # old key.
            try:
                self._sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            try:
                self._sock.close()
            except OSError:
                pass
        with self._clients_lock:
            clients = list(self._clients)
        for c in clients:
            c.close()

    @staticmethod
    def _bind(address: str, port: int) -> socket.socket:
        """Listen on ``address``, or on every interface, IPv6 and IPv4, if blank."""
        def _opts(s: socket.socket) -> None:
            if sys.platform == "win32":
                # SO_REUSEADDR on Windows lets another process take the port
                # out from under us; exclusive use is the equivalent there.
                opt = getattr(socket, "SO_EXCLUSIVEADDRUSE", None)
                if opt is not None:
                    s.setsockopt(socket.SOL_SOCKET, opt, 1)
            else:
                s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

        if not address:
            if socket.has_ipv6:
                # has_ipv6 says Python was built with IPv6, not that this
                # machine has it: creating the socket can still fail.
                try:
                    s = socket.socket(socket.AF_INET6, socket.SOCK_STREAM)
                except OSError:
                    s = None
                try:
                    if s is None:
                        raise OSError("IPv6 unavailable")
                    _opts(s)
                    s.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 0)
                    s.bind(("::", port))
                    s.listen(16)
                    return s
                except OSError:
                    if s is not None:
                        s.close()
            address = "0.0.0.0"
        family, stype, proto, _c, sockaddr = socket.getaddrinfo(
            address, port, type=socket.SOCK_STREAM, flags=socket.AI_PASSIVE)[0]
        s = socket.socket(family, stype, proto)
        try:
            _opts(s)
            s.bind(sockaddr)
            s.listen(16)
        except OSError:
            s.close()
            raise
        return s

    # ── TLS ───────────────────────────────────────────────────────────────────

    def _rebuild_context(self) -> None:
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ctx.minimum_version = ssl.TLSVersion.TLSv1_3
        ctx.load_cert_chain(str(self.identity.cert_path),
                            str(self.identity.key_path))
        ctx.verify_mode = ssl.CERT_OPTIONAL
        # Each paired device's certificate is trusted as itself, not looked up
        # by name.  Without this OpenSSL finds a device's certificate by its
        # issuer name, and Android gives every keystore certificate the same
        # name and serial — so once two devices were paired, or one device had
        # paired twice, it found the first and refused every other device with
        # "self-signed certificate".  Who the device is was never decided by
        # the name: the key's fingerprint is checked against devices.json
        # after the handshake, and anything not listed there is refused.
        ctx.verify_flags |= ssl.VERIFY_X509_PARTIAL_CHAIN
        pem = "".join(_identity.der_to_pem(base64.b64decode(d["cert"]))
                      for d in self.registry.all())
        if pem:
            ctx.load_verify_locations(cadata=pem)
        with self._ctx_lock:
            self._ctx = ctx

    def _check_registry(self) -> None:
        """Pick up pairings and revocations made on disk, by any process."""
        if not self.registry.reload():
            return
        self._rebuild_context()
        known = {d["fingerprint"] for d in self.registry.all()}
        with self._clients_lock:
            clients = list(self._clients)
        for c in clients:
            if c.device.get("fingerprint") not in known:
                self._log(f"[server] {c.device.get('name')} was unpaired; "
                          f"disconnecting")
                c.send({"t": "error", "code": "revoked",
                        "message": "This device is no longer paired."})
                c.close()

    # ── accept ────────────────────────────────────────────────────────────────

    def _accept_loop(self) -> None:
        while not self._stop.is_set():
            try:
                conn, addr = self._sock.accept()
            except OSError:
                if self._stop.is_set():
                    return
                time.sleep(0.5)
                continue
            with self._clients_lock:
                if self._conn_count >= MAX_CONNECTIONS:
                    conn.close()
                    continue
                self._conn_count += 1
            threading.Thread(target=self._serve, args=(conn, addr),
                             name="edld-server-conn", daemon=True).start()

    def _serve(self, conn: socket.socket, addr) -> None:
        host = addr[0] if addr else "?"
        try:
            self._check_registry()
            conn.settimeout(HANDSHAKE_TIMEOUT_S)
            try:
                conn.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
            except OSError:
                pass
            with self._ctx_lock:
                ctx = self._ctx
            try:
                tls = ctx.wrap_socket(conn, server_side=True)
            except (ssl.SSLEOFError, ConnectionResetError):
                # Connected and hung up without a word.  From this machine that
                # is the port check edld --pair makes, and not worth a line.
                # From anywhere else it is a device that reached EDLD and gave
                # up, which is exactly what someone chasing a failed pairing
                # needs to see, so it is logged, once a minute per address.
                conn.close()
                if not _is_loopback(host):
                    now = time.monotonic()
                    if now - self._preclose_logged.get(host, -1e9) >= 60:
                        self._preclose_logged[host] = now
                        self._log(f"[server] {host} connected and closed before "
                                  f"TLS started")
                return
            except (ssl.SSLError, OSError) as exc:
                # The usual cause is a device whose pairing was revoked, or
                # something that is not an EDAM client at all.  A device that
                # keeps retrying would otherwise write this line every second
                # or two for as long as it is left, so the same failure from
                # the same address is logged once a minute with a count.
                conn.close()
                self._log_handshake_failure(host, exc)
                return
            self._session(tls, host)
        finally:
            with self._clients_lock:
                self._conn_count -= 1

    def _log_handshake_failure(self, host: str, exc: BaseException) -> None:
        key = (host, str(exc))
        now = time.monotonic()
        first, count = self._handshake_fails.get(key, (None, 0))
        if first is None or now - first >= 60:
            extra = f" ({count} more in the last minute)" if count else ""
            self._log(f"[server] TLS handshake from {host} failed: {exc}{extra}")
            self._handshake_fails[key] = (now, 0)
        else:
            self._handshake_fails[key] = (first, count + 1)

    # ── one connection ────────────────────────────────────────────────────────

    def _session(self, tls: ssl.SSLSocket, host: str) -> None:
        reader = tls.makefile("rb")
        der = tls.getpeercert(binary_form=True)
        device = None
        if der:
            device = self.registry.get(_identity.spki_fingerprint_der(der))

        def send(msg):
            try:
                tls.sendall(_proto.encode(msg))
            except OSError:
                pass

        try:
            first = self._read(reader)
        except (_proto.ProtocolError, OSError) as exc:
            self._log(f"[server] {host}: {exc}")
            tls.close()
            return
        if first is None:
            tls.close()
            return

        if first.get("t") == "pair":
            if device is not None:
                send({"t": "error", "code": "already-paired",
                      "message": "This device is already paired."})
            else:
                self._pair(first, send, host)
            tls.close()
            return

        if first.get("t") != "hello" or device is None:
            send({"t": "error", "code": "not-paired",
                  "message": "Pair this device with EDLD first."})
            tls.close()
            return

        if int(first.get("v", 0) or 0) < 1:
            send({"t": "error", "code": "version",
                  "message": f"This EDLD speaks protocol {PROTOCOL_VERSION}."})
            tls.close()
            return

        client = _Client(tls, device, host)
        self.registry.touch(device["fingerprint"])
        self._log(f"[server] {device.get('name')} connected from {host}")
        client.send({"t": "welcome", "v": PROTOCOL_VERSION,
                     "server": {"name": self.name, "edld": _edld_version()},
                     "device": {"id": _identity.short_id(device["fingerprint"]),
                                "name": device.get("name")},
                     "features": list(FEATURES)})
        with self._model_lock:
            self._refresh()
            client.send(self.tracker.snapshot())
        with self._clients_lock:
            self._clients.append(client)

        tls.settimeout(IDLE_TIMEOUT_S)
        try:
            while client.alive and not self._stop.is_set():
                try:
                    msg = self._read(reader)
                except _proto.ProtocolError as exc:
                    client.send({"t": "error", "code": "protocol",
                                 "message": str(exc)})
                    break
                if msg is None:
                    break
                self._handle(client, msg)
        except (OSError, socket.timeout):
            pass
        finally:
            with self._clients_lock:
                if client in self._clients:
                    self._clients.remove(client)
            client.close()
            self._log(f"[server] {device.get('name')} disconnected")

    @staticmethod
    def _read(reader) -> dict | None:
        line = reader.readline(_proto.MAX_LINE + 1)
        if not line:
            return None
        return _proto.decode(line)

    def _pair(self, msg: dict, send, host: str) -> None:
        ok, reason = _pairing.check_ticket(self.directory, str(msg.get("code", "")))
        if not ok:
            messages = {
                "no-ticket": "Pairing is not open. Run edld --pair on the computer.",
                "expired": "That code has expired. Run edld --pair again.",
                "locked": "Too many wrong codes. Run edld --pair again.",
                "wrong-code": "That code is not right.",
            }
            self._log(f"[server] pairing attempt from {host} refused: {reason}")
            send({"t": "error", "code": reason,
                  "message": messages.get(reason, "Pairing refused.")})
            return
        try:
            der = base64.b64decode(str(msg.get("cert", "")), validate=True)
        except (ValueError, TypeError):
            der = b""
        good, why = _identity.describe_device_cert(der) if der else (False, "no certificate")
        if not good:
            self._log(f"[server] pairing from {host} refused: {why}")
            send({"t": "error", "code": "bad-cert", "message": why})
            return
        fp = _identity.spki_fingerprint_der(der)
        dev = self.registry.add(fp, base64.b64encode(der).decode("ascii"),
                                str(msg.get("name", "") or "Device"))
        self._rebuild_context()
        self._log(f"[server] paired {dev['name']} ({_identity.short_id(fp)}) "
                  f"from {host}")
        self._alert(f"Paired {dev['name']}")
        send({"t": "paired", "device": {"id": _identity.short_id(fp),
                                        "name": dev["name"]},
              "server": {"name": self.name,
                         "fingerprint": self.identity.fingerprint}})

    def _handle(self, client: _Client, msg: dict) -> None:
        t = msg.get("t")
        if t == "ping":
            client.send({"t": "pong", "id": msg.get("id")})
        elif t == "snapshot":
            with self._model_lock:
                self._refresh()
                client.send(self.tracker.snapshot())
        elif t == "cmd":
            self._command(client, msg)
        elif t == "bye":
            client.alive = False
        else:
            client.send({"t": "error", "code": "unknown",
                         "message": f"Unknown message {t!r}"})

    # ── commands ──────────────────────────────────────────────────────────────

    def end_session_allowed(self) -> tuple[bool, str]:
        """Whether a device may end the game session right now, and why not.

        The same Solo-only rule session management enforces on its own
        triggers, checked here so the device can say why the button is
        unavailable, and enforced again by the session manager itself.
        """
        if not bool(self.settings.get("AllowEndSession", False)):
            return False, "disabled in EDLD settings"
        plugins = getattr(self.core, "_plugins", {}) or {}
        if plugins.get("ksw") is None:
            return False, "session management unavailable"
        state = getattr(self.core, "state", None)
        if (getattr(state, "pilot_mode", None) or "").lower() != "solo":
            return False, "only available in Solo"
        if not self.builder.game_running():
            return False, "game not running"
        return True, ""

    def _command(self, client: _Client, msg: dict) -> None:
        cid, cmd = msg.get("id"), msg.get("cmd")
        if cmd == "press":
            self._press(client, cid, str(msg.get("control") or ""))
            return
        if cmd == "tool":
            self._tool(client, cid, str(msg.get("tool") or ""), msg.get("values"))
            return
        if cmd == "action":
            self._action(client, cid, msg)
            return
        if cmd != "end_session":
            client.send({"t": "result", "id": cid, "ok": False,
                         "error": "unknown", "message": f"Unknown command {cmd!r}"})
            return
        if msg.get("confirm") is not True:
            client.send({"t": "result", "id": cid, "ok": False,
                         "error": "unconfirmed", "message": "Not confirmed."})
            return
        ok, why = self.end_session_allowed()
        if not ok:
            client.send({"t": "result", "id": cid, "ok": False,
                         "error": "refused", "message": why})
            return
        name = client.device.get("name") or "a paired device"
        self._log(f"[server] end_session requested by {name}")
        try:
            self.core._plugins["ksw"].flush_session(f"ended from {name}")
        except Exception as exc:
            self._log(f"[server] end_session failed: {type(exc).__name__}: {exc}")
            client.send({"t": "result", "id": cid, "ok": False,
                         "error": "failed", "message": str(exc)})
            return
        client.send({"t": "result", "id": cid, "ok": True})

    def _press(self, client: _Client, cid, control: str) -> None:
        """One Helm button: a key the commander allowed devices to press, or
        one of EDLD's own sequences. A honk holds the trigger for seconds, so
        it runs on a thread of its own and the answer follows; the device's
        session goes on meanwhile."""
        auto = (getattr(self.core, "_plugins", None) or {}).get("automation")
        if auto is None:
            client.send({"t": "result", "id": cid, "ok": False,
                         "error": "refused", "message": "automation unavailable"})
            return

        def _run() -> None:
            try:
                ok, why = auto.press_control(control)
            except Exception as exc:
                ok, why = False, f"{type(exc).__name__}: {exc}"
            if ok:
                client.send({"t": "result", "id": cid, "ok": True})
            else:
                client.send({"t": "result", "id": cid, "ok": False,
                             "error": "refused", "message": why})

        threading.Thread(target=_run, daemon=True, name="edld-press").start()

    def _tool(self, client: _Client, cid, tool_id: str, values) -> None:
        """Run one of the Navigation window's forms for a device. A plot can
        take minutes, so it runs on its own thread and the answer follows as
        a toolResult; the device's session goes on meanwhile."""
        from core import tooltab
        tab = next((t for t in tooltab.tabs(self.core) if t.id == tool_id), None)
        if tab is None or not isinstance(values, dict):
            client.send({"t": "result", "id": cid, "ok": False,
                         "error": "unknown", "message": f"No tool {tool_id!r}"})
            return
        name = client.device.get("name") or "a paired device"
        self._log(f"[server] {tab.title} run by {name}")
        client.send({"t": "result", "id": cid, "ok": True, "pending": True})

        def _work():
            result = tooltab.run(tab, self.core, {str(k): v for k, v in values.items()})
            client.send(tooltab.result_message(tab, cid, result))
        threading.Thread(target=_work, daemon=True, name=f"server-tool-{tool_id}").start()

    def _action(self, client: _Client, cid, msg: dict) -> None:
        """A button under a window's tabs (core/panel_actions.py): Follow,
        Copy Next, Clear Route, Set Target, Gal. Avg, Set Home. A search can
        take a while, so it runs on its own thread; the result carries what
        matched, for the device to choose from."""
        from core import panel_actions
        panel_id, action_id = str(msg.get("panel") or ""), str(msg.get("action") or "")
        text = msg.get("input")
        choice = msg.get("choice")
        device = client.device.get("fingerprint") or client.device.get("name") or ""

        def _work():
            try:
                res = panel_actions.run(self.core, panel_id, action_id, device=device,
                                        text=None if text is None else str(text),
                                        choice=None if choice is None else int(choice))
            except Exception as exc:
                res = {"ok": False, "message": f"{type(exc).__name__}: {exc}"}
            reply = {"t": "result", "id": cid, "ok": bool(res.get("ok")),
                     "message": res.get("message") or ""}
            if res.get("choices"):
                reply["choices"] = res["choices"]
            if not res.get("ok"):
                reply["error"] = "refused"
            client.send(reply)
            # Show what changed now, not at the next tick.
            with self._model_lock:
                update = self._refresh()
            if update is not None:
                with self._clients_lock:
                    clients = [c for c in self._clients if c.alive]
                for c in clients:
                    c.send(update)
        threading.Thread(target=_work, daemon=True, name="server-action").start()

    # ── publishing ────────────────────────────────────────────────────────────

    def _refresh(self) -> dict | None:
        """Rebuild the model.  Caller holds ``_model_lock``."""
        return self.tracker.update(self.builder.header(), self.builder.panels())

    def _publish_loop(self) -> None:
        while not self._stop.wait(TICK_S):
            try:
                self._check_registry()
            except Exception as exc:
                self._log(f"[server] registry reload failed: {exc}")
            with self._clients_lock:
                clients = [c for c in self._clients if c.alive]
            if not clients:
                continue
            try:
                with self._model_lock:
                    msg = self._refresh()
            except Exception as exc:
                self._log(f"[server] model build failed: "
                          f"{type(exc).__name__}: {exc}")
                continue
            if msg is None:
                continue
            for c in clients:
                if not c.send(msg):
                    c.close()

    # ── reporting ─────────────────────────────────────────────────────────────

    def describe(self) -> str:
        host, port = self.bound or ("?", 0)
        where = "all interfaces" if host in ("::", "0.0.0.0") else host
        n = len(self.registry.all())
        return (f"Server listening on {where}, port {port} — "
                f"{n} paired device{'s' if n != 1 else ''}")

    def status_lines(self) -> list[str]:
        """What the preferences pages show under the server's settings."""
        with self._clients_lock:
            connected = [c.device.get("name", "?") for c in self._clients if c.alive]
        out = [self.describe(),
               "Connected now: " + (", ".join(connected) if connected else "none")]
        out.append("Port forwarding: " + (self.portmap.status if self.portmap
                                          else "off (PortMapping)"))
        out.append("DuckDNS: " + (self.duckdns.status if self.duckdns
                                  else "off (no domain or token)"))
        if self.firewall_advice:
            out.append("Firewall: " + "\n".join(self.firewall_advice))
        return out
