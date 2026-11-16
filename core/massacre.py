"""core/massacre.py — kills credited to each massacre mission.

A kill of a ship of a mission's target faction, in the mission's target
system, is credited to one mission per source faction: the oldest of that
faction's missions not yet complete. A kill is a ``Bounty`` naming the
victim's faction, a ``FactionKillBond`` naming it (a conflict zone kill), or
a ``CommitCrime`` murder of a pilot whose faction a full scan
(``ShipTargeted`` stage 3) gave. A mission is held one short of
its count until ``MissionRedirected``, which sets it to its count.

A kill made before a scan completes writes neither. The one such kill that
shows is the locked target dropping at no hull: it is credited when exactly
one massacre target faction is held for this system and no Bounty or murder
for that pilot, and no bond, follows within a few seconds.

Every kill counts once for each source faction, so a redirect that uncovers
kills the journal missed says those kills happened within the span its
mission was current, and they count for every other source faction current
over the same span. Each redirect is kept as a constraint: the kills missed
in (became current, redirected] number exactly kill count less those seen.
A current mission is credited the fewest missed kills its own span must hold
under every constraint, the kills missed never decreasing over time: a
system of difference constraints, solved as a shortest path. Wing missions
add no constraint once a wing is joined during them, since a wingmate's kill
counts for them alone.

Pure logic: no state, no I/O.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

#: Events the ledger reads.
EVENTS = ("Location", "FSDJump", "CarrierJump", "SupercruiseEntry",
          "ShipTargeted", "Bounty", "FactionKillBond", "CommitCrime",
          "MissionAccepted", "MissionRedirected",
          "MissionCompleted", "MissionFailed", "MissionAbandoned",
          "WingJoin", "WingAdd", "WingLeave")

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
    seen: int = 0               # kills seen credited to it, uncapped
    hidden: int = 0             # kills missed it must hold, from redirects
    since: int | None = None    # event index from which it could take kills
    waiting: bool = False       # current, but not yet in its target system
    winged: bool = False        # a wing was joined while it was current
    done: bool = False

    @property
    def order(self) -> tuple:
        return (self.accepted_at or "", self.mid)

    @property
    def credited(self) -> int:
        if self.done:
            return self.kill_count
        return max(0, min(self.kill_count - 1, self.seen + self.hidden))

    @credited.setter
    def credited(self, value: int) -> None:
        self.seen, self.hidden = int(value), 0


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
        self._n = 0                             # events applied
        self._wing = False
        # (target faction, target system) → [(from, to, kills missed)]
        self._spans: dict[tuple, list] = {}

    # ── Missions ──────────────────────────────────────────────────────────────

    def accept(self, mid, source="", target_faction="", target_system="",
               kill_count=0, accepted_at="", target_type="", wing=False) -> None:
        """Add a mission; seen again, it keeps its credit and gains what was
        missing."""
        mid = int(mid)
        m = self.missions.get(mid)
        if m is None:
            m = self.missions[mid] = Mission(mid, source or "", target_faction or "",
                                             target_system or "", int(kill_count or 0),
                                             accepted_at or "", target_type or "", bool(wing))
            if self._current(m.source, m.target_faction) is m:
                self._make_current(m)
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
        missed = m.kill_count - m.seen
        if (m.since is not None and m.since < self._n and missed >= 0
                and m.target_faction and not (m.wing and m.winged)):
            self._spans.setdefault(self._key(m), []).append((m.since, self._n, missed))
        m.done = True
        nxt = self._current(m.source, m.target_faction)
        if nxt is not None and nxt.since is None and not nxt.waiting:
            self._make_current(nxt)
        self._resolve(self._key(m))
        return True

    # ── Kills missed, from redirects ──────────────────────────────────────────

    @staticmethod
    def _key(m: Mission) -> tuple:
        return (m.target_faction, m.target_system)

    def _make_current(self, m: Mission) -> None:
        """``m`` is its faction's current mission: it can take kills from now,
        or from its arrival in its target system."""
        m.winged = self._wing
        if not m.target_system or not self.system or m.target_system == self.system:
            m.since, m.waiting = self._n, False
        else:
            m.since, m.waiting = None, True

    def _arrived(self) -> None:
        for m in self.missions.values():
            if m.waiting and not m.done and m.target_system == self.system:
                m.since, m.waiting = self._n, False
                m.winged = m.winged or self._wing

    def _current(self, source: str, target_faction: str) -> Mission | None:
        """The oldest unfinished mission of ``source`` against ``target_faction``."""
        best = None
        for m in self.missions.values():
            if not m.done and m.source == source and m.target_faction == target_faction:
                if best is None or m.order < best.order:
                    best = m
        return best

    def _resolve(self, key: tuple) -> None:
        """Each current mission of a stream credited the kills missed its span
        must hold."""
        current = [m for m in self.missions.values()
                   if not m.done and self._key(m) == key and m.since is not None]
        spans = self._spans.get(key, [])
        if not current:
            self._spans.pop(key, None)
            return
        start = min(m.since for m in current)
        spans = [c for c in spans if c[1] > start]
        self._spans[key] = spans
        for m in current:
            m.hidden = least_missed(spans, m.since, self._n)

    def drop(self, mid) -> bool:
        m = self.missions.pop(int(mid), None)
        if m is None:
            return False
        nxt = self._current(m.source, m.target_faction)
        if nxt is not None and nxt.since is None and not nxt.waiting:
            self._make_current(nxt)
        return True

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
        for m in oldest.values():
            m.seen += 1
        return bool(oldest)

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
        self._n += 1
        changed = False
        if ev == "MissionRedirected":
            changed = self._settle(at, force=True)
        elif ev not in ("Bounty", "FactionKillBond", "CommitCrime"):
            changed = self._settle(at)
        if at is not None:
            self._ended = {n: t for n, t in self._ended.items() if at - t <= 60}
        return self._apply(ev, event, at) or changed

    def _apply(self, ev, event, at) -> bool:
        if ev in ("WingJoin", "WingAdd"):
            self._wing = True
            for m in self.missions.values():
                if not m.done and m.since is not None:
                    m.winged = True
            return False
        if ev == "WingLeave":
            self._wing = False
            return False
        if ev in ("Location", "FSDJump", "CarrierJump"):
            system = event.get("StarSystem")
            if system and system != self.system:
                self._pilots.clear()
            self.system = system or self.system
            self._lock = self._pending = None
            self._arrived()
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
        if ev == "FactionKillBond":
            # No pilot is named: a bond while a dropped lock waits is its kill.
            self._pending = None
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


def least_missed(spans, a: int, b: int) -> int:
    """The fewest kills missed in (a, b] over every nondecreasing count that
    meets each span (from, to, missed) exactly: −(shortest path b → a), with
    an edge to → from of −missed and from → to of +missed for each span and
    a zero edge from each point to the one before it."""
    if b <= a or not spans:
        return 0
    pts = sorted({a, b} | {x for x, _y, _v in spans} | {y for _x, y, _v in spans})
    at = {p: i for i, p in enumerate(pts)}
    edges = [(i + 1, i, 0) for i in range(len(pts) - 1)]
    for x, y, v in spans:
        edges.append((at[x], at[y], v))
        edges.append((at[y], at[x], -v))
    inf = float("inf")
    dist = [inf] * len(pts)
    dist[at[b]] = 0
    for _ in range(len(pts)):
        moved = False
        for u, w, c in edges:
            if dist[u] + c < dist[w]:
                dist[w] = dist[u] + c
                moved = True
        if not moved:
            break
    else:
        return 0                        # spans disagree: claim nothing
    d = dist[at[a]]
    return 0 if d == inf else max(0, int(-d))


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
