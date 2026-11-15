"""core/massacre.py — kills credited to each massacre mission.

A kill of a ship of a mission's target faction, in the mission's target
system, is credited to one mission per source faction: the oldest of that
faction's missions not yet complete. A kill is a ``Bounty`` naming the
victim's faction, or a ``CommitCrime`` murder of a pilot whose faction a
full scan (``ShipTargeted`` stage 3) gave. A mission is held one short of
its count until ``MissionRedirected``, which sets it to its count.

A kill made before a scan completes writes neither. The one such kill that
shows is the locked target dropping at no hull: it is credited when exactly
one massacre target faction is held for this system and no Bounty or murder
for that pilot follows within a few seconds. Other unscanned kills are not
seen, so between redirects the count is a floor.

Pure logic: no state, no I/O.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

#: Events the ledger reads.
EVENTS = ("Location", "FSDJump", "CarrierJump", "SupercruiseEntry",
          "ShipTargeted", "Bounty", "CommitCrime",
          "MissionAccepted", "MissionRedirected",
          "MissionCompleted", "MissionFailed", "MissionAbandoned")

#: Hull left, in percent, at or under which a dropped lock is a kill.
DEAD_HULL = 1.0
#: Seconds a dropped lock waits for its Bounty or murder.
SETTLE_S = 3


def _secs(ts) -> float | None:
    try:
        return datetime.fromisoformat(str(ts).replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


#: Bounty targets that are not ships.
_NOT_SHIPS = ("suitai", "skimmer", "scavenger", "drone")


def is_massacre(name) -> bool:
    return "Mission_Massacre" in str(name or "")


def target_label(raw) -> str:
    """$MissionUtil_FactionTag_Pirate; → Pirate."""
    s = str(raw or "")
    if s.startswith("$") and s.endswith(";"):
        inner = s[1:-1]
        s = inner.rsplit("_", 1)[-1] if "_" in inner else inner
    return s.strip()


@dataclass
class Mission:
    mid: int
    source: str
    target_faction: str
    target_system: str
    kill_count: int
    accepted_at: str = ""
    target_type: str = ""
    wing: bool = False
    credited: int = 0
    done: bool = False

    @property
    def order(self) -> tuple:
        return (self.accepted_at or "", self.mid)


class MassacreLedger:
    """Credited kills per massacre mission."""

    def __init__(self) -> None:
        self.missions: dict[int, Mission] = {}
        self.system: str | None = None
        self._pilots: dict[str, str] = {}
        self._lock: dict | None = None          # name, stage, hull
        self._pending: dict | None = None       # name, at
        self._ended: dict[str, float] = {}      # pilot → when a Bounty or murder named them
        self.unscanned = 0

    # ── Missions ──────────────────────────────────────────────────────────────

    def accept(self, mid, source="", target_faction="", target_system="",
               kill_count=0, accepted_at="", target_type="", wing=False) -> None:
        """Add a mission; seen again, it keeps its credit and gains what was
        missing."""
        mid = int(mid)
        m = self.missions.get(mid)
        if m is None:
            self.missions[mid] = Mission(mid, source or "", target_faction or "",
                                         target_system or "", int(kill_count or 0),
                                         accepted_at or "", target_type or "", bool(wing))
            return
        m.source = m.source or source or ""
        m.target_faction = m.target_faction or target_faction or ""
        m.target_system = m.target_system or target_system or ""
        m.kill_count = m.kill_count or int(kill_count or 0)
        m.accepted_at = m.accepted_at or accepted_at or ""
        m.target_type = m.target_type or target_type or ""
        m.wing = m.wing or bool(wing)

    def mark_done(self, mid) -> bool:
        m = self.missions.get(int(mid))
        if m is None or m.done:
            return False
        m.done, m.credited = True, m.kill_count
        return True

    def drop(self, mid) -> bool:
        return self.missions.pop(int(mid), None) is not None

    def credited(self, mid) -> int:
        m = self.missions.get(int(mid))
        return m.credited if m else 0

    # ── Kills ─────────────────────────────────────────────────────────────────

    def kill(self, victim_faction: str) -> bool:
        """One kill of ``victim_faction`` here. True if it was credited."""
        if not victim_faction:
            return False
        oldest: dict[str, Mission] = {}
        for m in self.missions.values():
            if m.done or m.target_faction != victim_faction:
                continue
            if m.target_system and self.system and m.target_system != self.system:
                continue
            o = oldest.get(m.source)
            if o is None or m.order < o.order:
                oldest[m.source] = m
        changed = False
        for m in oldest.values():
            if m.credited < m.kill_count - 1:
                m.credited += 1
                changed = True
        return changed

    def _sole_target(self) -> str:
        here = {m.target_faction for m in self.missions.values()
                if not m.done and m.target_faction
                and (not m.target_system or not self.system or m.target_system == self.system)}
        return next(iter(here)) if len(here) == 1 else ""

    def _settle(self, now: float | None, force: bool = False) -> bool:
        """Credit the dropped lock if nothing named it in time."""
        p = self._pending
        if p is None:
            return False
        if p["name"] in self._ended:
            self._pending = None
            return False
        if not force and (now is None or p["at"] is None or now - p["at"] <= SETTLE_S):
            return False
        self._pending = None
        faction = self._sole_target()
        if faction and self.kill(faction):
            self.unscanned += 1
            return True
        return False

    def _ended_now(self, name, at) -> None:
        if name:
            self._ended[str(name)] = at if at is not None else 0.0
        if self._lock and self._lock["name"] == name:
            self._lock = None

    def _track(self, event, at) -> None:
        if not event.get("TargetLocked"):
            lock, self._lock = self._lock, None
            if (lock and lock["stage"] < 3 and lock["hull"] is not None
                    and lock["hull"] <= DEAD_HULL and lock["name"] not in self._ended):
                self._pending = {"name": lock["name"], "at": at}
            return
        name = event.get("PilotName_Localised") or event.get("PilotName")
        if not name:
            return
        if not self._lock or self._lock["name"] != name:
            self._lock = {"name": str(name), "stage": 0, "hull": None}
        self._lock["stage"] = max(self._lock["stage"], int(event.get("ScanStage", 0) or 0))
        if "HullHealth" in event:
            try:
                self._lock["hull"] = float(event["HullHealth"])
            except (TypeError, ValueError):
                pass

    def _remember(self, event) -> None:
        faction = event.get("Faction")
        if not faction or event.get("ScanStage", 0) < 3:
            return
        for key in ("PilotName_Localised", "PilotName"):
            if event.get(key):
                self._pilots[str(event[key])] = str(faction)

    def _victim(self, event) -> str:
        for key in ("Victim_Localised", "Victim"):
            name = event.get(key)
            if name and str(name) in self._pilots:
                return self._pilots[str(name)]
        return ""

    # ── Events ────────────────────────────────────────────────────────────────

    def apply(self, event: dict) -> bool:
        """Feed one journal event. True if a mission's credit changed."""
        ev = event.get("event")
        at = _secs(event.get("timestamp", ""))
        changed = False
        if ev == "MissionRedirected":
            changed = self._settle(at, force=True)
        elif ev not in ("Bounty", "CommitCrime"):
            changed = self._settle(at)
        if at is not None:
            self._ended = {n: t for n, t in self._ended.items() if at - t <= 60}
        return self._apply(ev, event, at) or changed

    def _apply(self, ev, event, at) -> bool:
        if ev in ("Location", "FSDJump", "CarrierJump"):
            system = event.get("StarSystem")
            if system and system != self.system:
                self._pilots.clear()
            self.system = system or self.system
            self._lock = self._pending = None
            return False
        if ev == "SupercruiseEntry":
            self._pilots.clear()
            self._lock = self._pending = None
            return False
        if ev == "ShipTargeted":
            self._remember(event)
            self._track(event, at)
            return False
        if ev == "Bounty":
            self._ended_now(event.get("PilotName_Localised") or event.get("PilotName"), at)
            target = str(event.get("Target") or "").lower()
            if any(t in target for t in _NOT_SHIPS):
                return False
            return self.kill(str(event.get("VictimFaction") or ""))
        if ev == "CommitCrime":
            if event.get("CrimeType") != "murder":
                return False
            faction = self._victim(event)
            self._ended_now(event.get("Victim_Localised") or event.get("Victim"), at)
            return self.kill(faction)
        if ev == "MissionAccepted":
            if not is_massacre(event.get("Name")) or event.get("MissionID") is None:
                return False
            self.accept(event["MissionID"], event.get("Faction", ""),
                        event.get("TargetFaction", ""), event.get("DestinationSystem", ""),
                        event.get("KillCount", 0), event.get("timestamp", ""),
                        event.get("TargetType_Localised") or event.get("TargetType", ""),
                        event.get("Wing", False))
            return True
        if ev == "MissionRedirected":
            return event.get("MissionID") is not None and self.mark_done(event["MissionID"])
        if ev in ("MissionCompleted", "MissionFailed", "MissionAbandoned"):
            return event.get("MissionID") is not None and self.drop(event["MissionID"])
        return False


def rebuild(events, active, until: str = "") -> MassacreLedger:
    """A ledger from journal events in order, up to ``until``, keeping only
    the missions in ``active``."""
    want = {int(m) for m in active}
    ledger = MassacreLedger()
    for ev in events:
        if until and str(ev.get("timestamp", "")) >= until:
            break
        ledger.apply(ev)
    for mid in list(ledger.missions):
        if mid not in want:
            ledger.drop(mid)
    return ledger
