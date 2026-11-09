"""components/edsm_gaps.py — fill the gaps in the commander's EDSM flight log.
"""
from __future__ import annotations

import json
import re
import threading
import time
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

from core.plugin_loader import BasePlugin
from core.settings_spec import Action, Heading, Setting, SettingsSpecMixin

EDSM_LOGS_URL = "https://www.edsm.net/api-logs-v1/get-logs"
_MATCH_S = 120
_WEEK = timedelta(days=7)
_REQUEST_GAP_S = 3
_NAME_RE = re.compile(r"Journal\.(\d{4}-\d{2}-\d{2})T")


def _ts(s) -> datetime | None:
    for fmt in ("%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(str(s), fmt).replace(tzinfo=timezone.utc)
        except (TypeError, ValueError):
            continue
    return None


def journal_jumps(journal_dir: Path, since: datetime) -> list[dict]:
    """Every FSDJump and CarrierJump in the journals since ``since``, each
    carrying the ship and game version current when it was written."""
    out: list[dict] = []
    for path in sorted(Path(journal_dir).glob("Journal*.log")):
        m = _NAME_RE.search(path.name)
        if m:
            try:
                day = datetime.strptime(m.group(1), "%Y-%m-%d").replace(tzinfo=timezone.utc)
            except ValueError:
                day = None
            if day is not None and day < since - timedelta(days=1):
                continue
        meta: dict = {}
        ship_id = None
        try:
            lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            continue
        for line in lines:
            try:
                ev = json.loads(line)
            except ValueError:
                continue
            name = ev.get("event")
            if name in ("Fileheader", "LoadGame"):
                for k_from, k_to in (("gameversion", "gameversion"), ("build", "build"),
                                     ("Odyssey", "odyssey"), ("Horizons", "horizons")):
                    if k_from in ev:
                        meta[k_to] = ev[k_from]
                if name == "LoadGame" and ev.get("ShipID") is not None:
                    ship_id = ev.get("ShipID")
            elif name in ("Loadout", "ShipyardSwap"):
                ship_id = ev.get("ShipID", ship_id)
            elif name in ("FSDJump", "CarrierJump"):
                t = _ts(ev.get("timestamp"))
                if t is None or t < since:
                    continue
                out.append({"event": ev, "time": t, "meta": dict(meta), "ship_id": ship_id})
    return out


class EDSMGapsPlugin(SettingsSpecMixin, BasePlugin):
    PLUGIN_NAME = "edsm_gaps"
    PLUGIN_DISPLAY = "EDSM Flight Log Gaps"
    PLUGIN_VERSION = "1.0.0"
    PLUGIN_DESCRIPTION = "Sends EDSM the jumps in your journals that its flight log is missing."
    SUBSCRIBED_EVENTS: list = []

    SETTINGS_SECTION = "EDSMGaps"
    SETTINGS_TAB = ("pref-tab-edsmgaps", "EDSM Log")
    SETTINGS = (
        Heading("EDSM flight log",
                "Jumps the journals hold that EDSM does not, sent through the EDSM uploads."),
        Setting("Days", "Days to check", int, 30),
        Action("fill-gaps", "Find and fill gaps"),
    )

    def on_load(self, core) -> None:
        super().on_load(core)
        self._busy = threading.Lock()
        self.last_result = ""

    def _edsm(self):
        return (getattr(self.core, "_plugins", None) or {}).get("edsm")

    def _get_logs(self, cmdr: str, key: str, start: datetime, end: datetime) -> list | None:
        q = urllib.parse.urlencode({
            "commanderName": cmdr, "apiKey": key, "showId": 1,
            "startDateTime": start.strftime("%Y-%m-%d %H:%M:%S"),
            "endDateTime": end.strftime("%Y-%m-%d %H:%M:%S")})
        try:
            req = urllib.request.Request(f"{EDSM_LOGS_URL}?{q}", headers={"User-Agent": "EDLD/1.0"})
            with urllib.request.urlopen(req, timeout=20) as resp:
                body = json.loads(resp.read().decode("utf-8"))
        except Exception as exc:
            from core import debug as _dbg
            _dbg.log(f"  [EDSM gaps] get-logs failed: {type(exc).__name__}: {exc}")
            return None
        if int(body.get("msgnum") or 0) != 100:
            from core import debug as _dbg
            _dbg.log(f"  [EDSM gaps] get-logs refused ({body.get('msgnum')}): {body.get('msg')}")
            return None
        return body.get("logs") or []

    def find_gaps(self, days: int) -> tuple[list[dict], str]:
        edsm = self._edsm()
        if edsm is None or not getattr(edsm, "_enabled", False):
            return [], "EDSM uploads are off: turn them on with an API key first."
        cmdr = (getattr(self.core.state, "pilot_name", "") or "").strip()
        if not cmdr:
            return [], "The commander is not known yet."
        now = datetime.now(timezone.utc)
        since = now - timedelta(days=max(1, min(int(days), 3650)))
        jumps = journal_jumps(Path(self.core.journal_dir), since)
        if not jumps:
            return [], "No jumps in the journals for those days."
        logged: list[tuple[datetime, str, int]] = []
        start = since
        while start < now:
            end = min(start + _WEEK, now)
            got = self._get_logs(cmdr, edsm._key, start, end)
            if got is None:
                return [], "EDSM could not be asked for the flight log."
            for g in got:
                t = _ts(g.get("date"))
                if t is not None:
                    logged.append((t, str(g.get("system") or "").lower(),
                                   int(g.get("systemId64") or 0)))
            start = end
            if start < now:
                time.sleep(_REQUEST_GAP_S)
        missing = []
        for j in jumps:
            ev = j["event"]
            name = str(ev.get("StarSystem") or "").lower()
            addr = int(ev.get("SystemAddress") or 0)
            if not any(abs((t - j["time"]).total_seconds()) <= _MATCH_S
                       and ((addr and a == addr) or n == name) for t, n, a in logged):
                missing.append(j)
        return missing, ""

    def fill_gaps(self, days: int) -> str:
        if not self._busy.acquire(blocking=False):
            return "Already checking."
        try:
            missing, err = self.find_gaps(days)
            if err:
                return err
            if not missing:
                return f"EDSM has every jump of the last {days} days."
            edsm = self._edsm()
            sender = getattr(edsm, "_sender", None)
            if sender is None:
                return "EDSM uploads are not running."
            for j in missing:
                ev = {k: v for k, v in j["event"].items() if not k.startswith("_")}
                ev["_systemName"] = ev.get("StarSystem")
                if ev.get("SystemAddress") is not None:
                    ev["_systemAddress"] = ev["SystemAddress"]
                if ev.get("StarPos") is not None:
                    ev["_systemCoordinates"] = ev["StarPos"]
                if j["ship_id"] is not None:
                    ev["_shipId"] = j["ship_id"]
                for k, v in j["meta"].items():
                    ev.setdefault(k, v)
                if "build" in ev:
                    ev.setdefault("gamebuild", ev["build"])
                sender.push(ev)
            sender.flush()
            first = min(j["time"] for j in missing).strftime("%Y-%m-%d")
            return f"{len(missing)} jump{'s' if len(missing) != 1 else ''} since {first} sent to EDSM."
        finally:
            self._busy.release()

    def settings_action(self, action_id: str) -> str:
        if action_id != "fill-gaps":
            return ""
        days = int(self.settings().get("Days", 30) or 30)

        def _work():
            self.last_result = self.fill_gaps(days)
            from core import callout
            callout.say(self.core, "Automation", "📒", f"EDSM flight log: {self.last_result}",
                        sigil="-  EDSM")
        threading.Thread(target=_work, daemon=True, name="edsm-gaps").start()
        return "Checking — the result is reported when done."
