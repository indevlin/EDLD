"""
core/server/protocol.py — what goes over the wire, and how it is built.

Framing
-------
UTF-8 JSON, one object per line (NDJSON), over TLS.  The same framing the
overlay renderer already uses, chosen for the same reasons: trivially parsed on
every platform, readable in a packet capture of the decrypted stream, and no
library needed on either end.  Lines longer than :data:`MAX_LINE` are refused.

Every message has a ``t`` (type).  See docs/SERVER.md for the full list.

The model
---------
A snapshot is a ``header`` plus a list of ``panels``.  The header is what the
client shows at all times — commander, squadron, ship, where they are, whether
the game is running — and what it needs to draw EDCARS (``edcars``), the
Navigation window's forms (``tools``) and the Helm panel (``controls`` and
``helm``).  A panel is one tab of a
desktop window, with that tab's title and rows:

* every window's tabs — :mod:`core.windows.wire`, from the model the desktop
  window and the terminal dashboard draw (core/windows), so a device shows
  the same tabs with the same rows
* ``ship`` — the vessel's name, the component's own overlay panel
* ``status`` — hull, shields, fuel, for the Dashboard style
* ``alerts`` — the Alerts pane

Nothing here decides what a number means or how to format it.  That is the
components' job, and the mobile client shows what they produced, the same way
the TUI and the desktop window do.  A panel added to a component appears on the
device without anything being written twice.

Changes are sent per panel: when a panel's content differs from what was last
published it is sent again whole.  Panels are small, and whole-panel updates
mean the client never has to reconcile a partial one.
"""

from __future__ import annotations

import datetime as _dt
import hashlib
import json
import re
import time
from typing import Any, Callable

from core.server import PROTOCOL_VERSION

MAX_LINE = 1 << 20            # 1 MiB
_SLUG = re.compile(r"[^a-z0-9]+")


# ── Framing ───────────────────────────────────────────────────────────────────

class ProtocolError(ValueError):
    pass


def encode(msg: dict) -> bytes:
    return (json.dumps(msg, separators=(",", ":"), ensure_ascii=False,
                       default=str) + "\n").encode("utf-8")


def decode(line: bytes) -> dict:
    if len(line) > MAX_LINE:
        raise ProtocolError("line too long")
    try:
        msg = json.loads(line.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as exc:
        raise ProtocolError(f"not JSON: {exc}") from exc
    if not isinstance(msg, dict) or not isinstance(msg.get("t"), str):
        raise ProtocolError("not a message")
    return msg


# ── Rows and panels ───────────────────────────────────────────────────────────

def slug(text: str) -> str:
    return _SLUG.sub("-", str(text).lower()).strip("-") or "section"


def _row(label: Any, value: Any, rate: Any = None, kind: str = "kv") -> dict:
    return {"label": "" if label is None else str(label),
            "value": "" if value is None else str(value),
            "rate": None if not rate else str(rate),
            "kind": kind}


def rows_from_model(rows: list) -> list[dict]:
    """Rows from core.summary_model, which are already in wire shape."""
    out = []
    for r in rows or []:
        if not isinstance(r, dict):
            continue
        out.append(_row(r.get("label"), r.get("value"), r.get("rate"),
                        str(r.get("kind") or "kv")))
    return out


def rows_from_overlay(rows: list) -> list[dict]:
    """Rows from an overlay Panel: ``(label, value)`` pairs.

    An empty label is a full-width line and an empty value is a heading, the
    same convention the overlay draws with.
    """
    out = []
    for pair in rows or []:
        try:
            label, value = pair
        except (TypeError, ValueError):
            continue
        if not label:
            out.append(_row("", value, kind="line"))
        elif value in (None, ""):
            out.append(_row(label, "", kind="sub"))
        else:
            out.append(_row(label, value))
    return out


def panel(pid: str, title: str, group: str, rows: list[dict],
          order: int = 100) -> dict:
    return {"id": pid, "title": title, "group": group,
            "order": order, "rows": rows}


def digest(obj: Any) -> str:
    return hashlib.sha1(json.dumps(obj, sort_keys=True, default=str)
                        .encode("utf-8")).hexdigest()


# ── Building from a running EDLD ──────────────────────────────────────────────

def _iso(dt) -> str | None:
    if isinstance(dt, _dt.datetime):
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=_dt.timezone.utc)
        return dt.astimezone(_dt.timezone.utc).isoformat(timespec="seconds")
    return None


class SnapshotBuilder:
    """Builds headers and panels from CoreAPI.

    Each source is isolated: one that raises is logged once per distinct fault
    and its panels are left out, so a broken component costs the device one
    panel, not the connection.
    """

    #: How often the game-running check may run.  It can fall back to a
    #: process scan, which is not something to do every second.
    GAME_CHECK_S = 5.0

    def __init__(self, core, journal_dir=None, log: Callable[[str], None] | None = None,
                 kill_allowed: Callable[[], tuple[bool, str]] | None = None):
        self.core = core
        self.journal_dir = journal_dir
        self._log = log or (lambda m: None)
        self._kill_allowed = kill_allowed or (lambda: (False, "disabled"))
        self._faults: set[str] = set()
        self._game_running = False
        self._game_checked = 0.0
        self._alert_ts: dict[tuple, str] = {}
        self._theme_id: str | None = None
        self._theme_cache: dict | None = None

    def _fault(self, where: str, exc: BaseException) -> None:
        sig = f"{where}: {type(exc).__name__}: {exc}"
        if sig not in self._faults:
            self._faults.add(sig)
            self._log(f"[server] {sig}")

    # ── header ────────────────────────────────────────────────────────────────

    def game_running(self) -> bool:
        now = time.monotonic()
        if now - self._game_checked >= self.GAME_CHECK_S:
            self._game_checked = now
            try:
                from core.journal import _ed_client_running
                self._game_running = bool(_ed_client_running(self.journal_dir))
            except Exception as exc:
                self._fault("game check", exc)
        return self._game_running

    def header(self) -> dict:
        s = getattr(self.core, "state", None)
        g = lambda name, default=None: getattr(s, name, default) if s else default
        kill_ok, kill_reason = self._kill_allowed()
        return {
            "cmdr": g("pilot_name"),
            "squadron": {
                "name": g("pilot_squadron_name") or None,
                "tag": g("pilot_squadron_tag") or None,
                "rank": g("pilot_squadron_rank") or None,
            } if g("pilot_squadron_name") else None,
            "ship": {
                "name": g("ship_name"),
                "ident": g("ship_ident"),
                "type": g("pilot_ship"),
            } if (g("ship_name") or g("pilot_ship")) else None,
            "system": g("pilot_system"),
            # The body or station within the system. Read from a field nothing
            # ever set until 20261018, so a device was always sent null.
            "location": self._location(s),
            "mode": g("pilot_mode"),
            "game": {
                "running": self.game_running(),
                "lastEvent": _iso(g("event_time")),
            },
            "monitorError": g("monitor_error") or None,
            "endSession": {"available": kill_ok, "reason": kill_reason or None},
            # The Helm panel: what a device may press, when the commander
            # has allowed it (components/automation.py). Empty otherwise;
            # ``helm`` says why, and how its groups are labelled.
            "controls": self._controls(),
            "helm": self.helm(),
            # The Navigation window's forms (core/tooltab.py), for a device
            # to draw and have EDLD run: "cmd":"tool".
            "tools": self._tools(),
            "theme": self.theme(),
            "style": self.style(),
            "console": self.console(),
            "edcars": self.edcars(s),
        }

    def _tools(self) -> list[dict]:
        # One form that cannot be described leaves the rest; it used to take
        # them all with it.
        from core import tooltab
        try:
            tabs = tooltab.tabs(self.core)
        except Exception as exc:
            self._fault("tools", exc)
            return []
        out = []
        for t in tabs:
            try:
                out.append(tooltab.describe(t, self.core))
            except Exception as exc:
                self._fault(f"tool {t.id}", exc)
        return out

    def _controls(self) -> list[dict]:
        auto = (getattr(self.core, "_plugins", None) or {}).get("automation")
        if auto is None:
            return []
        try:
            return auto.controls()
        except Exception as exc:
            self._fault("controls", exc)
            return []

    @staticmethod
    def _location(s) -> str | None:
        if s is None:
            return None
        body = str(getattr(s, "pilot_body", "") or "")
        system = str(getattr(s, "pilot_system", "") or "")
        if body and system and body.startswith(system):
            body = body[len(system):].strip()
        return body or None

    def style(self) -> dict:
        """The style EDLD draws with, for a device set to follow it."""
        from core import edcars
        sid = edcars.style_for_mode(getattr(self.core, "ui_mode", ""))
        return {"id": sid, "name": dict(edcars.STYLES)[sid]}

    def console(self) -> dict:
        """The console EDCARS is dressed as (core/edcars.py CONSOLES). Its own
        field, not part of ``style``, so a device that knows only EDCARS
        still draws EDCARS."""
        from core import edcars
        cfg = getattr(getattr(self.core, "cfg", None), "ui_cfg", None) or {}
        cid = edcars.console_of(cfg)
        # Every console's name too, so a device can offer the choice without
        # spelling a name of its own.
        return {"id": cid, "name": edcars.CONSOLE_BY_ID[cid].name,
                "consoles": [{"id": c.id, "name": c.name} for c in edcars.CONSOLES]}

    def edcars(self, s) -> dict:
        """What a device needs to draw EDCARS the way the desktop window does.

        Sent whatever style EDLD itself uses, because a device can choose
        EDCARS on its own. The sections are fixed per release; the strip
        changes with the game and is part of the header's change tracking like
        the rest.
        """
        from core import edcars
        cfg = getattr(getattr(self.core, "cfg", None), "ui_cfg", None) or {}
        try:
            strip = [f.wire() for f in edcars.strip(s)]
            titles = edcars.title_forms(s)
        except Exception as exc:
            self._fault("edcars strip", exc)
            strip, titles = [], ["COMMANDER"]
        return {
            "name": edcars.EDCARS_NAME,
            "title": titles[0],
            # Shorter forms of the title, for a band too narrow for it.
            "titles": titles,
            "sections": edcars.wire_sections(),
            "omit": list(edcars.EDCARS_OMITS),
            "strip": strip,
            "alerts": edcars.alert_mode_of(cfg),
        }

    def helm(self) -> dict:
        """The Helm panel's name and groups, in drawing order, and — when a
        device has nothing to press — why, for its Helm section to say."""
        from core import helm
        note = ""
        auto = (getattr(self.core, "_plugins", None) or {}).get("automation")
        if auto is None:
            note = "Automation is not available in this EDLD."
        else:
            try:
                note = auto.controls_note()
            except Exception as exc:
                self._fault("helm note", exc)
        return {"name": helm.HELM_NAME, "section": helm.HELM_SECTION,
                "groups": helm.wire_groups(), "note": note or None}

    def theme(self) -> dict | None:
        """The theme EDLD is drawing with, so a device can follow it.

        Resolved once per theme setting and cached: a custom theme is a CSS
        file to parse, and the header is rebuilt every tick while a device is
        connected.  Changing the theme in Preferences changes the setting,
        which is what the cache is keyed on.
        """
        cfg = getattr(getattr(self.core, "cfg", None), "ui_cfg", None) or {}
        tid = str(cfg.get("Theme", "default") or "default")
        if tid != self._theme_id:
            try:
                from core.palette import wire_theme
                self._theme_cache = wire_theme(tid)
            except Exception as exc:
                self._fault("theme", exc)
                self._theme_cache = None
            self._theme_id = tid
        return self._theme_cache

    # ── panels ────────────────────────────────────────────────────────────────

    def panels(self) -> list[dict]:
        out: list[dict] = []
        out += self._status_panel()
        out += self._overlay_panels()
        out += self._alerts_panel()
        # Every window, tab by tab, from the model the desktop window and the
        # terminal dashboard draw (core/windows).
        from core.windows import wire
        out += wire.panels(self.core, self._fault)
        return out

    def _status_panel(self) -> list[dict]:
        s = getattr(self.core, "state", None)
        if s is None:
            return []
        rows: list[dict] = []
        try:
            hull = getattr(s, "ship_hull", None)
            if hull is not None:
                rows.append(_row("Hull", f"{float(hull):.0f}%"))
            shields = getattr(s, "ship_shields", None)
            if shields is not None:
                recharging = getattr(s, "ship_shields_recharging", False)
                rows.append(_row("Shields", "Recharging" if recharging
                                 else ("Up" if shields else "Down")))
            fuel = getattr(s, "fuel_current", None)
            tank = getattr(s, "fuel_tank_size", None)
            if fuel is not None and tank:
                rows.append(_row("Fuel", f"{fuel:.1f} / {float(tank):.0f} t "
                                         f"({100 * fuel / float(tank):.0f}%)"))
        except Exception as exc:
            self._fault("status panel", exc)
            return []
        return [panel("status", "Status", "status", rows, 10)] if rows else []

    def _overlay_panels(self) -> list[dict]:
        """The components' own overlay panels that carry no scope setting.

        Activity panels are left out here — their figures arrive richer through
        the session and career models — and so is anything whose content
        depends on an overlay-only setting, which a device has no way to set.
        """
        from core.overlay_panels import context_from
        try:
            from core.surface_survey import POSITIONS
            pos = POSITIONS.latest()
        except Exception:
            pos = None
        ctx = context_from(pos, getattr(self.core, "state", None))
        out = []
        order = 20
        for comp in list(getattr(self.core, "_plugins", {}).values()):
            # "commander" is left out: the header already carries it.
            for pid in ("ship",):
                if pid not in (getattr(comp, "OVERLAY_PANELS", ()) or ()):
                    continue
                try:
                    p = comp.overlay_panel(pid, ctx)
                except Exception as exc:
                    self._fault(f"{pid} panel", exc)
                    continue
                if p is None or p.is_empty():
                    continue
                out.append(panel(pid, p.title or pid.title(), "vessel",
                                 rows_from_overlay(p.rows), order))
                order += 1
        return out

    def _alerts_panel(self) -> list[dict]:
        alerts = getattr(self.core, "_plugins", {}).get("alerts")
        if alerts is None:
            return []
        try:
            items = alerts.get_alerts()
        except Exception as exc:
            self._fault("alerts", exc)
            return []
        # Each alert carries when it happened, not how long ago: an age would
        # change every second and resend the panel with it.  The device turns
        # the time into "4m ago" itself.
        mono_now, wall_now = time.monotonic(), time.time()
        rows = []
        for a in items:
            row = _row("", f"{a.get('emoji', '')} {a.get('text', '')}".strip(),
                       kind="line")
            if a.get("urgent"):
                row["urgent"] = True
            mono = a.get("mono_time")
            if mono is not None:
                # Converted once per alert and remembered: recomputing it each
                # build lets clock jitter flip the rounded second, which would
                # resend the panel for nothing.
                key = (float(mono), row["value"])
                ts = self._alert_ts.get(key)
                if ts is None:
                    at = wall_now - (mono_now - float(mono))
                    ts = _dt.datetime.fromtimestamp(
                        round(at), _dt.timezone.utc).isoformat(timespec="seconds")
                    self._alert_ts[key] = ts
                row["ts"] = ts
            rows.append(row)
        if len(self._alert_ts) > 64:            # forget alerts long gone
            live = {float(a["mono_time"]) for a in items
                    if a.get("mono_time") is not None}
            self._alert_ts = {k: v for k, v in self._alert_ts.items()
                              if k[0] in live}
        return [panel("alerts", "Alerts", "alerts", rows, 15)] if rows else []

def _now_iso() -> str:
    return _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds")


class ChangeTracker:
    """Remembers what was last published and reports what changed."""

    def __init__(self):
        self.seq = 0
        self._header_digest: str | None = None
        self._panel_digests: dict[str, str] = {}
        self.header: dict = {}
        self.panels: dict[str, dict] = {}

    def update(self, header: dict, panels: list[dict]) -> dict | None:
        """Fold in a fresh build.  Returns a ``panels`` message, or None."""
        upsert, remove = [], []
        new = {p["id"]: p for p in panels}
        for pid, p in new.items():
            d = digest(p)
            if self._panel_digests.get(pid) != d:
                self._panel_digests[pid] = d
                upsert.append(p)
        for pid in list(self._panel_digests):
            if pid not in new:
                del self._panel_digests[pid]
                remove.append(pid)
        hd = digest(header)
        header_changed = hd != self._header_digest
        self._header_digest = hd
        self.header, self.panels = header, new
        if not (upsert or remove or header_changed):
            return None
        self.seq += 1
        msg = {"t": "panels", "seq": self.seq, "ts": _now_iso(),
               "upsert": upsert, "remove": remove}
        if header_changed:
            msg["header"] = header
        return msg

    def snapshot(self) -> dict:
        return {"t": "snapshot", "v": PROTOCOL_VERSION, "seq": self.seq,
                "ts": _now_iso(), "header": self.header,
                "panels": list(self.panels.values())}
