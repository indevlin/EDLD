"""
components/edcmdr.py — publishes to ED Commanders (edcmdr.com) through EDCMDR-core.

EDLD reads the journals; this component builds each commander's categories from
them with edcmdr_core.state and hands them to edcmdr_core's publisher, which
enrolls, verifies and pushes only the sections switched on, each on its delay.

At its first tick the publisher thread replays every journal in EDLD's journal
folder from the shared journal index (core/journal_index.py), routed to each
journal's commander. Live events, and EDLD's own startup replay of the current
journal, are queued by on_event and applied after that, on the same thread;
applying an event twice leaves the state unchanged.

Keys and sharing settings are EDCMDR's own (its config directory), shared with
the EDCMDR client, so the two publish as one installation, one at a time.
Options → ED Commanders edits them: what is saved there is written to that
settings file for every commander EDLD has a profile for, and a change made in
the client is copied back into Options.

One sign-in: EDLD's own Frontier CAPI sign-in verifies the commander with ED
Commanders (EDCMDR-core verifies by itself once it is there), keeps squadron
membership current, and lets the server read Frontier's journal for Squad
Goals. There is no second sign-in in the browser.

Squad Goals: EDCMDR-core reads the commander's events and, while one is open,
has the server read Frontier's journal. The Squad Goals window
(gui/squad_goals.py; core/windows/squad.py, also on EDAM and in the terminal)
shows them to a commander signed in to Frontier and in a squadron, and gives
the squadron's verified leader the event form. Options → ED Commanders holds
the take-part switch and invitation codes.

Release builds sign pushes with EDLD's own build key, written to
core/_edcmdr_build.py by the release workflow and removed after the build.
Source runs read $EDCMDR_BUILD_KEY or ~/.config/edcmdr/build.key.

Config [EDCMDR]:
    Enabled = false   # opt-in; the rest of the section is written by Options
"""

from __future__ import annotations

import collections
import hashlib
import json
import time
import webbrowser
from pathlib import Path

from core import debug as _dbg
from core.plugin_loader import BasePlugin
from core.settings_spec import Action, Heading, Setting, SettingsSpecMixin
from core.state import EDLD_DATA_DIR, VERSION

try:
    from edcmdr_core import keys as _keys
    from edcmdr_core.proto import Client, ProtoError
    from edcmdr_core.publisher import Publisher
    from edcmdr_core.settings import EVENTS_HELP, LABELS, Settings, from_flat, to_flat
    from edcmdr_core.spec import DELAY_LABELS, DELAYS, SHAREABLE, SPEC
    from edcmdr_core.state import EVENTS, Commander
    _CORE_ERROR = ""
except Exception as _e:  # pragma: no cover - only without the dependency
    _CORE_ERROR = f"edcmdr-core is not installed ({_e})"
    EVENTS, SHAREABLE, DELAYS, DELAY_LABELS, LABELS = frozenset(), [], [0], {0: "None"}, {}
    EVENTS_HELP = ""
    SPEC = {"powers": [], "undelayed": [], "limits": {}, "event_metrics": []}
    Publisher = object

PLUGIN_VERSION = "2.0.0"
FORGET_WINDOW = 30
RECRUITING = (("", "—"), ("open", "Open"), ("invite", "By invitation"), ("closed", "Closed"))


def _settings_spec() -> tuple:
    rows = [c for c in SHAREABLE if c != "presence"] + (["presence"] if "presence" in SHAREABLE else [])
    delay_choices = tuple((str(d), DELAY_LABELS.get(d, str(d))) for d in DELAYS)
    spec: list = [
        Heading("ED Commanders",
                "Publishes the sections you switch on to edcmdr.com, each after its delay. Nothing is "
                "published until you switch it on, and switching a section off deletes it from the site. "
                "EDLD and the EDCMDR client share keys and these settings; only one publishes at a time."),
        Setting("Enabled", "Enable ED Commanders", bool, False, help="Takes effect after a restart."),
        Heading("Sharing", "Applies to every commander EDLD has a profile for. Delays are enforced by "
                           "edcmdr.com, not only by this computer."),
    ]
    for c in rows:
        spec.append(Setting(f"Share_{c}", LABELS.get(c, c), bool, False))
        if c not in SPEC.get("undelayed", []) and c != "presence":
            spec.append(Setting(f"Delay_{c}", "    delay", "choice", "0", choices=delay_choices))
    spec += [
        Setting("Wealth", "Include net worth and carrier bank balances", bool, False,
                help="With lifetime statistics only."),
        Setting("NameHistory", "Let my earlier commander names find my page", bool, False),
        Setting("SquadEvents", LABELS.get("events", "Take part in my squadron's events"), bool, True,
                help=EVENTS_HELP),
        Heading("Your commander", "Acts on the commander you are playing, or the last one EDLD saw."),
        Action("verify", "Verify with Frontier",
               help="Uses EDLD's own Frontier sign-in (Options › Services › Frontier CAPI): one sign-in for both. "
                    "Needed for leaderboards, Squad Goals and squadron-leader settings. EDLD verifies by itself "
                    "once you are signed in; press this to take the commander over from another installation."),
        Action("open", "Open my page"),
        Action("push", "Push now"),
        Action("status", "Status"),
        Heading("Codex portrait", "A screenshot of the Codex hub with your commander tile highlighted: choose it "
                                  "with Browse…, save, then Send portrait. Sending one switches portrait sharing on."),
        Setting("PortraitFile", "Screenshot file", "file", "",
                filter="Images (*.png *.jpg *.jpeg *.bmp *.webp);;All files (*)"),
        Action("portrait", "Send portrait"),
        Heading("Squadron", "For a verified squadron leader: what your squadron's page shows."),
        Setting("SqHome", "Home system", str, ""),
        Setting("SqPower", "Power", "choice", "", choices=(("", "—"),) + tuple((p, p) for p in SPEC.get("powers", []))),
        Setting("SqFactions", "Supported factions (comma separated)", str, ""),
        Setting("SqRecruiting", "Recruiting", "choice", "", choices=RECRUITING),
        Setting("SqTagline", "Tagline", str, ""),
        Action("squadron", "Save squadron"),
        Heading("Squad Goals",
                "Your squadron's events are under the Squad Goals menu once you are signed in to Frontier "
                "(Options › Services › Frontier CAPI) and in a squadron; a leader runs them from there. If you were "
                "invited to an event, paste the code here."),
        Setting("JoinCode", "Invitation code", str, ""),
        Action("ev_join", "Use invitation"),
        Heading("Forget"),
        Action("forget", "Forget on EDCMDR",
               help=f"Deletes everything edcmdr.com holds for this commander. Press twice within {FORGET_WINDOW} s."),
    ]
    return tuple(spec)


def _digest(v) -> str:
    return hashlib.sha256(json.dumps(v, sort_keys=True).encode()).hexdigest()


def _embedded_build_key() -> str | None:
    try:
        from core import _edcmdr_build  # type: ignore[attr-defined]
        return _edcmdr_build.BUILD_KEY
    except ImportError:
        return None


def _image_bytes(path: Path, limit: int) -> bytes:
    """The screenshot as JPEG (at most 2560 px wide, quality 85) where Qt is installed; otherwise a PNG or JPEG
    as it is, when it is small enough."""
    raw = path.read_bytes()
    try:
        from PySide6.QtCore import QBuffer, QIODevice
        from PySide6.QtGui import QImage
        im = QImage()
        if im.loadFromData(raw):
            if im.width() > 2560:
                im = im.scaledToWidth(2560)
            buf = QBuffer()
            buf.open(QIODevice.OpenModeFlag.WriteOnly)
            im.save(buf, "JPEG", 85)
            return bytes(buf.data())
    except ImportError:
        pass
    if path.suffix.lower() not in (".jpg", ".jpeg", ".png") or (limit and len(raw) > limit):
        raise ValueError("Use a PNG or JPEG screenshot under 1.5 MB (the desktop window converts others).")
    return raw


class _Host(Publisher):
    """edcmdr_core's publisher, fed by the plugin."""

    def __init__(self, plugin: "EDCMDRPlugin", settings, client):
        super().__init__(settings, client)
        self.plugin = plugin

    def poll(self) -> None:
        self.plugin._poll()

    def commanders(self):
        return self.plugin.cmdrs

    def presence_of(self, fid: str) -> dict:
        c = self.plugin.cmdrs.get(fid)
        return c.presence(self.plugin._game_running()) if c else {"in_game": False}


class EDCMDRPlugin(SettingsSpecMixin, BasePlugin):
    PLUGIN_NAME = "edcmdr"
    PLUGIN_DISPLAY = "ED Commanders"
    PLUGIN_VERSION = PLUGIN_VERSION
    PLUGIN_DESCRIPTION = "Publishes the sections you choose to edcmdr.com"
    SUBSCRIBED_EVENTS: list[str] = sorted(EVENTS)

    SETTINGS_SECTION = "EDCMDR"
    SETTINGS_TAB = ("pref-tab-edcmdr", "ED Commanders")
    SETTINGS = _settings_spec()

    def on_load(self, core) -> None:
        super().on_load(core)
        self.engine = None
        self.cmdrs: dict[str, Commander] = {}
        self.queue: collections.deque = collections.deque()
        self.live_fid = ""
        self.replayed = False
        self.forget_armed: tuple[str, float] = ("", 0.0)
        self.synced = self.storage.read_json("sync") if getattr(self, "storage", None) else {}
        self.reason = "off in Options → ED Commanders"
        if _CORE_ERROR:
            self.reason = f"unavailable: {_CORE_ERROR}"
            return
        if not bool(core.cfg.app_settings.get("PrimaryInstance", True)):
            self.reason = "not the primary instance"
            return
        if not self.settings()["Enabled"]:
            return
        try:
            client = Client("EDLD", VERSION, _keys.load_build_key(_embedded_build_key()))
        except Exception as e:
            self.reason = f"unavailable: {e}"
            _dbg.info(f"  [EDCMDR] {self.reason}")
            return
        self.engine = _Host(self, Settings(), client)
        self.engine.frontier_token = self._frontier_token
        self.engine.start()
        _dbg.info(f"  [EDCMDR] publishing to {client.base}")

    def on_unload(self) -> None:
        if self.engine is not None:
            self.engine.shutdown()

    # ── events ──────────────────────────────────────────────────────────────
    def on_event(self, event: dict, state) -> None:
        if self.engine is None:
            return
        ev = {k: v for k, v in event.items() if not k.startswith("_")}
        if ev.get("event") in ("Commander", "NewCommander") and isinstance(ev.get("FID"), str):
            self.live_fid = ev["FID"]
        fid = self.live_fid or str(getattr(state, "pilot_fid", "") or "")
        if fid:
            self.queue.append((fid, ev))
            self.engine._wake.set()

    def _poll(self) -> None:
        """Publisher thread: the history once, then whatever EDLD has dispatched since."""
        if not self.replayed:
            self._replay()
            self.replayed = True
        while self.queue:
            fid, ev = self.queue.popleft()
            self.cmdrs.setdefault(fid, Commander(fid)).handle(ev)
        self._sync_prefs()

    def _replay(self) -> None:
        from core.journal_index import index_for
        t0 = time.monotonic()
        try:
            idx = index_for(Path(self.core.journal_dir))
            owner: dict[str, str | None] = {}
            last = None
            heads = {}
            for name, ev in idx.events({"Fileheader", "Commander", "NewCommander"}):
                h = heads.setdefault(name, {"fid": None, "part": None})
                if ev["event"] == "Fileheader" and isinstance(ev.get("part"), int):
                    h["part"] = ev["part"]
                elif ev["event"] in ("Commander", "NewCommander") and h["fid"] is None:
                    h["fid"] = ev.get("FID")
            for name in idx.files():
                h = heads.get(name, {"fid": None, "part": None})
                fid = h["fid"] or (last if isinstance(h["part"], int) and h["part"] >= 2 else None)
                owner[name] = fid
                last = fid
            n = 0
            for name, ev in idx.events(EVENTS):
                fid = owner.get(name)
                if fid:
                    self.cmdrs.setdefault(fid, Commander(fid)).handle(ev)
                    n += 1
            for c in self.cmdrs.values():
                c.loaded = True
            _dbg.info(f"  [EDCMDR] {n} journal events for {len(self.cmdrs)} commander(s) "
                      f"in {time.monotonic() - t0:.1f} s")
        except Exception as e:
            _dbg.info(f"  [EDCMDR] history replay failed: {e}")

    def _game_running(self) -> bool:
        try:
            from core.journal import _ed_client_running
            return bool(_ed_client_running(Path(self.core.journal_dir)))
        except Exception:
            return False

    def _frontier_token(self, fid: str):
        """EDLD's own Frontier sign-in for the commander it is signed in as: lets the publisher confirm a
        renamed squadron, and keep membership current, without the player verifying again."""
        try:
            if getattr(self.core.state, "pilot_fid", "") != fid:
                return None
            capi = getattr(getattr(self.core, "data", None), "capi", None)
            return capi._valid_token() if capi is not None else None
        except Exception:
            return None

    # ── sharing settings: Options ↔ EDCMDR's settings file ──────────────────
    def _profiles(self) -> list[str]:
        try:
            have = {p.name for p in (EDLD_DATA_DIR / "commanders").iterdir() if p.name.startswith("F")}
        except OSError:
            have = set()
        return [f for f in self.cmdrs if f in have] or ([self._current()] if self._current() else [])

    def _current(self) -> str:
        return str(getattr(self.core.state, "pilot_fid", "") or "") or self.live_fid or next(iter(self.cmdrs), "")

    def _flat_config(self) -> dict:
        s = self.settings()
        return {k: (int(v) if k.startswith("Delay_") and str(v).lstrip("-").isdigit() else v)
                for k, v in s.items() if k.startswith(("Share_", "Delay_")) or k in ("Wealth", "NameHistory", "SquadEvents")}

    def _sync_prefs(self) -> None:
        """Options saved since the last sync win and go to every profile's commander; otherwise a change made
        in the client is copied into Options."""
        fid = self._current()
        if not fid or self.engine is None:
            return
        mine = to_flat(from_flat(self._flat_config()))   # same keys and rules on both sides
        theirs = to_flat(self.engine.settings.prefs(fid))
        dm, dt = _digest(mine), _digest(theirs)
        if dm == self.synced.get("config") and dt == self.synced.get("file"):
            return
        if dm != self.synced.get("config") and self.synced.get("config") is not None:
            prefs = from_flat(mine)
            for f in self._profiles():
                self.engine.set_prefs(f, prefs)
            theirs = to_flat(prefs)
        elif theirs != mine:
            self._write_config(theirs)
            mine = theirs
        self.synced = {"config": _digest(mine), "file": _digest(theirs)}
        try:
            self.storage.write_json(self.synced, "sync")
        except Exception:
            pass

    def _write_config(self, values: dict) -> None:
        import tomllib
        from core.config import config_to_toml
        cfg = self.core.cfg
        try:
            config = tomllib.loads(cfg.config_path.read_text(encoding="utf-8"))
            target = config.setdefault(cfg.config_profile, {}) if cfg.config_profile else config
            sec = target.setdefault(self.SETTINGS_SECTION, {})
            known = self.settings_defaults()
            sec.update({k: (str(v) if k.startswith("Delay_") else v) for k, v in values.items() if k in known})
            cfg.config_path.write_text(config_to_toml(config), encoding="utf-8")
            cfg.reload_now()
        except Exception as e:
            _dbg.info(f"  [EDCMDR] could not copy sharing settings into config.toml: {e}")

    # ── Options actions ─────────────────────────────────────────────────────
    def settings_action(self, action_id: str) -> str:
        if self.engine is None:
            return f"ED Commanders is {self.reason}."
        fid = self._current()
        if action_id == "status":
            return self.status()
        if action_id == "push":
            self.engine.push_now()
            return "Pushing every shared section now."
        if not fid:
            return "No commander yet: start the game, or wait for EDLD to read your journals."
        name = self.cmdrs[fid].name if fid in self.cmdrs else fid
        try:
            if action_id == "verify":
                return self._verify(fid, name)
            if action_id == "open":
                pub = self.engine.settings.commander(fid).get("pub_id")
                if not pub:
                    return f"CMDR {name} has no page yet: switch a section on and wait for the first push."
                url = f"{self.engine.client.base}/cmdr/{pub}"
                webbrowser.open(url)
                return url
            if action_id == "portrait":
                return self._portrait(fid, name)
            if action_id == "squadron":
                return self._squadron(fid)
            if action_id.startswith("ev_"):
                return self._event_action(fid, action_id[3:])
            if action_id == "forget":
                armed, at = self.forget_armed
                if armed != fid or time.time() - at > FORGET_WINDOW:
                    self.forget_armed = (fid, time.time())
                    return (f"Press Forget again within {FORGET_WINDOW} s to delete everything edcmdr.com holds "
                            f"for CMDR {name}. This cannot be undone.")
                self.forget_armed = ("", 0.0)
                err = self.engine.forget(fid)
                return f"Could not reach edcmdr.com: {err}" if err else f"CMDR {name} is forgotten on edcmdr.com."
        except ProtoError as e:
            return str(e)
        except (OSError, ValueError) as e:
            return f"Failed: {e}"
        return ""

    def _portrait(self, fid: str, name: str) -> str:
        path = Path(str(self.settings().get("PortraitFile") or "")).expanduser()
        if not path.is_file():
            return "Set Screenshot file to a Codex hub screenshot first, and save Options."
        jpeg = _image_bytes(path, int(SPEC.get("limits", {}).get("portrait_bytes", 0)))
        p = self.engine.settings.prefs(fid)
        if not p["share"].get("portrait"):
            p["share"]["portrait"] = True
            for f in self._profiles() or [fid]:
                self.engine.set_prefs(f, p)
        self.engine.push_portrait(fid, jpeg)
        return f"Portrait published for CMDR {name}."

    def _squadron(self, fid: str) -> str:
        c = next((x for x in self.engine.snapshot()["commanders"] if x["fid"] == fid), None)
        sid = c.get("leader_of") if c else None
        if sid is None:
            return "Only a verified squadron leader can save these. Verify with Frontier first."
        s = self.settings()
        limit = int(SPEC.get("limits", {}).get("factions", 5))
        details = {
            "home_system": str(s.get("SqHome") or "").strip() or None,
            "power": str(s.get("SqPower") or "") or None,
            "factions": [f.strip() for f in str(s.get("SqFactions") or "").split(",") if f.strip()][:limit],
            "recruiting": str(s.get("SqRecruiting") or "") or None,
            "tagline": str(s.get("SqTagline") or "").strip() or None,
        }
        self.engine.save_squadron(fid, details, sid)
        sq = (c or {}).get("leader_squadron") or {}
        return f"Saved for {sq.get('name') or 'your squadron'}. Its page shows it now."

    # ── Squad Goals ─────────────────────────────────────────────────────────
    def _capi(self):
        return getattr(getattr(self.core, "data", None), "capi", None)

    def signed_in(self) -> bool:
        """EDLD holds a Frontier (CAPI) sign-in, for the commander being played."""
        capi = self._capi()
        try:
            return bool(capi is not None and capi.is_connected())
        except Exception:
            return False

    def _verify(self, fid: str, name: str) -> str:
        """One sign-in: verify with EDLD's own Frontier sign-in, starting it if there is none yet."""
        if not self.signed_in():
            capi = self._capi()
            if capi is None:
                return "Switch on Frontier CAPI under Options › Services first."
            capi.authenticate()
            return (f"Sign in to Frontier in the browser that opened. EDLD verifies CMDR {name} with that "
                    f"sign-in as soon as it is done; nothing more to press.")
        try:
            self.engine.verify_with_token(fid)
        except ProtoError as e:
            if e.code == "signin":
                return ("EDLD's Frontier sign-in is for another commander or has ended: sign in again under "
                        "Options › Services › Frontier CAPI.")
            raise
        return f"CMDR {name} is verified with your Frontier sign-in."

    # ── Squad Goals ─────────────────────────────────────────────────────────
    def squad_view(self) -> dict:
        """What the Squad Goals window shows for the commander being played: state, note, events."""
        if self.engine is None:
            return {"state": "off", "reason": self.reason}
        fid = self._current()
        snap = next((c for c in self.engine.snapshot()["commanders"] if c["fid"] == fid), None)
        if snap is None:
            return {"state": "none"}
        if not self.engine.settings.prefs(fid).get("events", True):
            return {"state": "switched-off", "name": snap["name"]}
        if not snap["verified"]:
            return {"state": "unverified", "name": snap["name"]}
        return {"state": "on", "name": snap["name"], "note": snap.get("events_note"), "fid": fid,
                "pub_id": snap.get("pub_id"), "leader_of": snap.get("leader_of"),
                "leader_squadron": snap.get("leader_squadron"), **(snap.get("events") or {"events": None})}

    def squad_access(self) -> dict:
        """The Squad Goals window: signed in to Frontier, and in a squadron or invited to an event. Its leader
        tab: the squadron's verified leader as well."""
        if self.engine is None:
            return {"show": False, "lead": False, "why": f"ED Commanders is {self.reason}."}
        if not self.signed_in():
            return {"show": False, "lead": False, "why": "Sign in to Frontier under Options › Services › Frontier CAPI."}
        view = self.squad_view()
        in_squadron = bool(str(getattr(self.core.state, "pilot_squadron_name", "") or "").strip()
                           or view.get("member_of"))
        invited = any(e.get("invited") for e in view.get("events") or [])
        if not (in_squadron or invited):
            return {"show": False, "lead": False, "why": "You are not in a squadron."}
        lead = view.get("state") == "on" and view.get("leader_of") is not None
        return {"show": True, "lead": lead, "why": ""}

    def squad_admin(self, action: str, **body) -> dict:
        """A leader's call (see EDCMDR's PROTOCOL: save, close, finalize, cancel, invite, remove, restore,
        webhook, forget-webhook, announce, lookup). Raises ProtoError."""
        return self.engine.event_admin(self._current(), action, **body)

    def squad_join(self, code: str) -> dict:
        return self.engine.event_join(self._current(), code.strip())

    def squad_sync_now(self) -> None:
        self.engine.sync_events_now(self._current())

    def _event_action(self, fid: str, act: str) -> str:
        if act == "join":
            code = str(self.settings().get("JoinCode") or "").strip()
            if not code:
                return "Paste the invitation code into Invitation code and save Options first."
            j = self.engine.event_join(fid, code)
            return (f"You are in {j.get('event', {}).get('title') or 'the event'}. "
                    "It shows under the Squad Goals menu.")
        return ""

    # ── status ──────────────────────────────────────────────────────────────
    def get_summary_line(self) -> str | None:
        if self.engine is None:
            return None
        return f"ED Commanders: {self.engine.status}"

    def status(self) -> str:
        if self.engine is None:
            return f"ED Commanders is {self.reason}."
        snap = self.engine.snapshot()
        lines = [f"{snap['status']}" + ("" if snap["official"] else " (unofficial build: pushes are refused)")]
        if not self.replayed:
            lines.append("Reading your journals…")
        for c in snap["commanders"]:
            bits = ["verified" if c["verified"] else ("enrolled" if c["enrolled"] else "not published")]
            if c["last_push"]:
                bits.append("last push " + time.strftime("%H:%M", time.localtime(c["last_push"])))
            for k in ("verify", "blocked", "error", "events_note"):
                if c.get(k):
                    bits.append(str(c[k]))
            lines.append(f"CMDR {c['name']}: " + "; ".join(bits))
        return "\n".join(lines)
