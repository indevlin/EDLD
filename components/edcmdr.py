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

Squad Goals: EDCMDR-core reads the commander's events and, while one is open,
has the server read Frontier's journal with EDLD's own Frontier sign-in. The
Objectives window's Squad Goals tab shows them (core/windows/objectives.py,
also on EDAM); Options → ED Commanders holds the switch, invitation codes and
a verified leader's event controls.

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
import re
import time
import webbrowser
from datetime import datetime, timezone
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
#: Squad Goals measures: label, unit.
METRICS = {
    "mined_tons": ("Tons refined", "t"), "bounty_value": ("Bounty value earned", "cr"),
    "bond_value": ("Combat bond value earned", "cr"), "sold_tons": ("Tons sold", "t"),
    "sold_value": ("Credits from sales", "cr"), "construction_tons": ("Tons delivered to construction", "t"),
}


# ── Squad Goals: what Options fields hold, as the server wants it ────────────
def parse_utc(s: str) -> int:
    """'2026-12-01 18:00' or '2026-12-01' (UTC), or 'now', as a Unix time."""
    s = str(s or "").strip()
    if s.lower() == "now":
        return int(time.time())
    for f in ("%Y-%m-%d %H:%M", "%Y-%m-%dT%H:%M", "%Y-%m-%d"):
        try:
            return int(datetime.strptime(s, f).replace(tzinfo=timezone.utc).timestamp())
        except ValueError:
            pass
    raise ValueError(f"'{s}' is not a UTC date and time such as 2026-12-01 18:00.")


def parse_credits(s) -> int:
    """'100M', '1.5B', '250k', '100,000,000' or blank (0)."""
    t = str(s or "").strip().replace(",", "").replace(" ", "").lower().removesuffix("cr")
    if not t:
        return 0
    m = re.fullmatch(r"(\d+(?:\.\d+)?)([kmb]?)", t)
    if not m:
        raise ValueError(f"'{s}' is not an amount of credits such as 100M.")
    return int(float(m.group(1)) * {"": 1, "k": 1e3, "m": 1e6, "b": 1e9}[m.group(2)])


def parse_list(s) -> list[str]:
    return [x.strip() for x in str(s or "").split(",") if x.strip()]


def parse_weights(s) -> list[float]:
    try:
        return [float(x) for x in parse_list(s)]
    except ValueError:
        raise ValueError(f"'{s}' is not a list of weights such as 5, 3, 2.") from None


def parse_pairs(s, a: str, b: str, amount_a: bool = False) -> list[dict]:
    """'50:2, 100:1' → [{a: 50, b: 2}, …]; with amount_a the first of each pair may be 100M."""
    out = []
    for item in parse_list(s):
        x, sep, y = item.partition(":")
        try:
            if not sep:
                raise ValueError
            out.append({a: parse_credits(x) if amount_a else float(x), b: float(y)})
        except ValueError:
            raise ValueError(f"'{item}' should be two numbers with a colon, such as 50:2.") from None
    return out


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
    metric_choices = tuple((m, METRICS.get(m, (m,))[0]) for m in SPEC.get("event_metrics", []) or METRICS)
    spec += [
        Setting("Wealth", "Include net worth and carrier bank balances", bool, False,
                help="With lifetime statistics only."),
        Setting("NameHistory", "Let my earlier commander names find my page", bool, False),
        Setting("SquadEvents", LABELS.get("events", "Take part in my squadron's events"), bool, True,
                help=EVENTS_HELP),
        Heading("Your commander", "Acts on the commander you are playing, or the last one EDLD saw."),
        Action("verify", "Verify with Frontier",
               help="Proves you hold this commander: needed for leaderboards and squadron-leader settings."),
        Action("open", "Open my page"),
        Action("push", "Push now"),
        Action("status", "Status"),
        Heading("Codex portrait", "A screenshot of the Codex hub with your commander tile highlighted. "
                                  "Sending one switches portrait sharing on."),
        Setting("PortraitFile", "Screenshot file", str, ""),
        Action("portrait", "Send portrait"),
        Heading("Squadron", "For a verified squadron leader: what your squadron's page shows."),
        Setting("SqHome", "Home system", str, ""),
        Setting("SqPower", "Power", "choice", "", choices=(("", "—"),) + tuple((p, p) for p in SPEC.get("powers", []))),
        Setting("SqFactions", "Supported factions (comma separated)", str, ""),
        Setting("SqRecruiting", "Recruiting", "choice", "", choices=RECRUITING),
        Setting("SqTagline", "Tagline", str, ""),
        Action("squadron", "Save squadron"),
        Heading("Squad Goals",
                "Your squadron's events show in Objectives → Squad Goals. Only what Frontier's own journal "
                "shows counts, read with EDLD's Frontier sign-in (Options → Services → Frontier CAPI)."),
        Setting("JoinCode", "Invitation code", str, ""),
        Action("ev_join", "Use invitation"),
        Action("ev_sync", "Update standings now"),
        Heading("Squad Goals: run an event",
                "For a verified squadron leader. Times are UTC, such as 2026-12-01 18:00. Leave Event id blank "
                "to make a new event; the one saved fills it in. Weights: 1st, 2nd, 3rd… never rising; bands "
                "for the rest as percent:weight (50:2, 100:1); tiers as squadron total:percent of the pool "
                "(10000:50, 25000:100). No places or bands shares the pool by amount."),
        Setting("EvId", "Event id", str, ""),
        Setting("EvTitle", "Title", str, ""),
        Setting("EvNote", "Note", str, ""),
        Setting("EvMetric", "Measure", "choice", "mined_tons", choices=metric_choices),
        Setting("EvStart", "Starts (UTC)", str, ""),
        Setting("EvEnd", "Ends (UTC)", str, ""),
        Setting("EvSystems", "Star systems (comma separated, blank for anywhere)", str, ""),
        Setting("EvMarkets", "Market ids (comma separated)", str, ""),
        Setting("EvCommodities", "Commodities (comma separated)", str, ""),
        Setting("EvPool", "Prize pool (credits, such as 100M)", str, ""),
        Setting("EvPlaces", "Place weights", str, ""),
        Setting("EvBands", "Band weights", str, ""),
        Setting("EvMin", "Least amount that qualifies", str, ""),
        Setting("EvTiers", "Squadron goal tiers", str, ""),
        Action("ev_save", "Save event"),
        Action("ev_close", "End event now"),
        Action("ev_finalize", "Finalize results",
               help="After the end, without waiting the 48 hours late journal days are read for."),
        Action("ev_cancel", "Cancel event"),
        Setting("InvKind", "Invitation for", "choice", "general",
                choices=(("general", "Anyone verified with the code"), ("personal", "One commander"))),
        Setting("InvName", "    commander name", str, ""),
        Setting("InvDays", "    expires after days (blank: when the event ends)", str, ""),
        Setting("InvUses", "    uses (blank: no limit)", str, ""),
        Action("ev_invite", "Make invitation"),
        Setting("MemberName", "Member", str, ""),
        Action("ev_remove", "Remove from events"),
        Action("ev_restore", "Restore to events"),
        Setting("Webhook", "Discord webhook (blank to remove)", str, "",
                help="Announces events opening, being cancelled and final standings. Kept encrypted by edcmdr.com."),
        Action("ev_webhook", "Save webhook"),
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
                v = self.engine.verify_start(fid)
                webbrowser.open(v["url"])
                return (f"CMDR {name}: code {v['code']}. Continue on edcmdr.com only if it shows the same code, "
                        f"then sign in with Frontier; EDLD finishes the rest. If no browser opened: {v['url']}")
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
    def squad_view(self) -> dict:
        """What the Squad Goals tab shows for the commander being played: state, note, events."""
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
        return {"state": "on", "name": snap["name"], "note": snap.get("events_note"),
                "pub_id": snap.get("pub_id"), **(snap.get("events") or {"events": None})}

    def _event_id(self, fid: str) -> str:
        eid = str(self.settings().get("EvId") or "").strip()
        if eid:
            return eid
        ev = (self.engine.events_of(fid) or {}).get("events") or []
        mine = [e for e in ev if e.get("leader") and e.get("state") in ("upcoming", "open", "settling", "closing")]
        if len(mine) == 1:
            return mine[0]["id"]
        raise ValueError("Set Event id (shown in Objectives → Squad Goals) and save Options first."
                         if mine else "You have no open event.")

    def _event_body(self) -> dict:
        s = self.settings()
        places, bands = parse_weights(s.get("EvPlaces")), parse_pairs(s.get("EvBands"), "pct", "w")
        return {
            "title": str(s.get("EvTitle") or "").strip(), "note": str(s.get("EvNote") or "").strip() or None,
            "metric": str(s.get("EvMetric") or ""), "starts": parse_utc(s.get("EvStart")),
            "ends": parse_utc(s.get("EvEnd")),
            "filters": {"systems": parse_list(s.get("EvSystems")),
                        "markets": [int(x) for x in parse_list(s.get("EvMarkets")) if x.isdigit()],
                        "commodities": parse_list(s.get("EvCommodities"))},
            "payout": {"pool": parse_credits(s.get("EvPool")), "places": places, "bands": bands,
                       "min": parse_credits(s.get("EvMin")),
                       "tiers": [{"target": int(t["target"]), "pct": int(t["pct"])}
                                 for t in parse_pairs(s.get("EvTiers"), "target", "pct", amount_a=True)]},
        }

    def _event_action(self, fid: str, act: str) -> str:
        e, s = self.engine, self.settings()
        if act == "sync":
            e.sync_events_now(fid)
            return "Reading your events, and your journal from Frontier, now."
        if act == "join":
            code = str(s.get("JoinCode") or "").strip()
            if not code:
                return "Paste the invitation code into Invitation code and save Options first."
            j = e.event_join(fid, code)
            return f"You are in {j.get('event', {}).get('title') or 'the event'}. It shows in Objectives → Squad Goals."
        if act == "save":
            body = self._event_body()
            if s.get("EvId"):
                body["id"] = str(s["EvId"]).strip()
            j = e.event_admin(fid, "save", **body)
            ev = j.get("event") or {}
            self._write_config({"EvId": ev.get("id", "")})
            return f"Saved {ev.get('title')}: event id {ev.get('id')}. Your squadron sees it in Objectives → Squad Goals."
        if act in ("close", "finalize", "cancel"):
            eid = self._event_id(fid)
            e.event_admin(fid, act, id=eid)
            if act == "cancel":
                self._write_config({"EvId": ""})
            return {"close": "Ended now. Late journal days are still read for 48 hours, then results are final.",
                    "finalize": "Results are final.", "cancel": "Cancelled."}[act]
        if act == "invite":
            kind = str(s.get("InvKind") or "general")
            body: dict = {"id": self._event_id(fid), "kind": kind}
            if kind == "personal":
                body["name"] = str(s.get("InvName") or "").strip()
            days = str(s.get("InvDays") or "").strip()
            if days:
                body["expires"] = int(time.time() + float(days) * 86400)
            uses = str(s.get("InvUses") or "").strip()
            if uses and kind == "general":
                body["max_uses"] = int(uses)
            j = e.event_admin(fid, "invite", **body)
            who = f"CMDR {j['for']} only" if j.get("for") else "anyone verified who has it"
            return f"Invitation code {j['code']} ({who}). They enter it under Options → ED Commanders → Invitation code."
        if act in ("remove", "restore"):
            name = str(s.get("MemberName") or "").strip()
            j = e.event_admin(fid, act, name=name)
            return (f"CMDR {j.get('removed')} no longer counts in your squadron's events." if act == "remove"
                    else f"CMDR {j.get('restored')} counts in your squadron's events again.")
        if act == "webhook":
            url = str(s.get("Webhook") or "").strip()
            j = e.event_admin(fid, "webhook", url=url, test=bool(url))
            if not j.get("webhook"):
                return "Webhook removed."
            return "Webhook saved" + (" and a test message posted." if j.get("tested") else
                                      ", but the test message did not go: check the address.")
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
