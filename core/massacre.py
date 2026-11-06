"""
core/massacre.py — kills credited against a massacre stack.

How the game credits a kill
───────────────────────────
A kill of a ship belonging to a mission's target faction, in the mission's
target system, is credited to one mission per source faction: the oldest of
that faction's missions still short of its count. Every source faction in the
stack sees the same kill, so the stack completes when its tallest faction —
the stack height — has been fed that many kills. Missions from one faction
complete in the order they were accepted.

What the journal shows of it
────────────────────────────
Two things, and only one of them is exact.

``MissionRedirected`` is written the moment a mission reaches its count. That
is exact: when the third of a faction's missions redirects, that faction has
been credited with exactly the first three missions' kill counts.

``Bounty`` is written for a kill that pays a bounty. It is *not* written for
every kill the game credits. Measured over every massacre stack in the
journals this was written against (about 180 redirects), Bounty events
accounted for roughly 70 % of the credited kills; at the moment a mission
redirected there was often no Bounty at all, only the target lock dropping
(``ShipTargeted`` with ``TargetLocked`` false). A count of Bounty events is a
floor, never the answer, which is why counting them alone never matched the
game.

So the count here is anchored: each mission's credited kills rise with every
qualifying Bounty, held one short of its count (only a redirect says a
mission is done), and snap to the exact figure when it redirects. Every
source faction sees every kill, so a faction whose missions were held from
the moment kills became possible for another (the pilot's arrival in the
target system, not the moment of acceptance: a stack is taken at a station and
flown to) is never shown fewer kills than that other — the kills a redirect
uncovers reach the rest of the stack that way.

Measured the same way, two stronger rules were tried and dropped, because
they read high: carrying a redirect's uncovered kills straight to every other
faction's current mission, with or without excluding factions anchored in the
meantime. A reading that runs ahead of the game is worse than one that lags
it. The rule kept never read high on any of those 178 redirects (no Bounty
met a mission already at its cap unless that mission redirected within three
seconds), and just before a redirect read on average under two kills low.

Pure logic: no state, no I/O. components/missions.py feeds it events, live
and replayed from the journals, and core/windows/objectives.py draws it.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable


@dataclass
class _Mission:
    mid: int
    source: str
    kill_count: int
    target_faction: str
    target_system: str
    accepted_at: str = ""
    credited: int = 0
    done: bool = False

    @property
    def order(self) -> tuple:
        # Oldest first. A mission whose acceptance was never seen (journals
        # gone) has no time and sorts first: it was there before the rest.
        return (self.accepted_at or "", self.mid)


def is_massacre(name) -> bool:
    return "Mission_Massacre" in str(name or "")


class MassacreLedger:
    """Credited kills per massacre mission."""

    def __init__(self) -> None:
        self.missions: dict[int, _Mission] = {}
        # (time, system) each time the pilot arrived somewhere: a kill in a
        # system can only have been made while there.
        self._visits: list[tuple[str, str]] = []

    def arrive(self, system: str, at: str = "") -> None:
        """The pilot is in ``system`` from ``at`` (FSDJump, Location,
        CarrierJump)."""
        if system and (not self._visits or self._visits[-1][1] != system):
            self._visits.append((at or "", system))

    def _kills_possible_from(self, t: str, system: str) -> str:
        """The first moment at or after ``t`` a kill in ``system`` could have
        been made: ``t`` if the pilot was there, else their next arrival
        there. ``t`` itself when it cannot be told."""
        if not system or not self._visits:
            return t
        here = None
        for at, where in self._visits:
            if at <= t:
                here = where
            elif where == system:
                return t if here == system else at
        return t

    # ── Feeding it ────────────────────────────────────────────────────────────

    def accept(self, mid, source: str, kill_count, target_faction: str,
               target_system: str = "", accepted_at: str = "") -> None:
        """A mission joins the stack. Seen again (a replay), it keeps what it
        has been credited; details missing the first time are filled in."""
        mid = int(mid)
        kc = int(kill_count or 0)
        m = self.missions.get(mid)
        if m is None:
            self.missions[mid] = _Mission(mid, source or "", kc, target_faction or "",
                                          target_system or "", accepted_at or "")
            return
        m.source = m.source or source or ""
        m.kill_count = m.kill_count or kc
        m.target_faction = m.target_faction or target_faction or ""
        m.target_system = m.target_system or target_system or ""
        m.accepted_at = m.accepted_at or accepted_at or ""

    def _current(self, source: str, faction: str, system: str | None = None):
        """The mission of ``source`` a kill of ``faction`` would be credited
        to: its oldest one targeting that faction still short of its count."""
        best = None
        for m in self.missions.values():
            if m.done or m.source != source or m.target_faction != faction:
                continue
            if system and m.target_system and m.target_system != system:
                continue
            if best is None or m.order < best.order:
                best = m
        return best

    def kill(self, victim_faction: str, system: str | None = None) -> bool:
        """A Bounty: credit a kill of ``victim_faction`` in ``system`` (None:
        not known, so not checked). True when it counted for the stack."""
        if not victim_faction:
            return False
        counted = False
        for source in {m.source for m in self.missions.values()}:
            m = self._current(source, victim_faction, system)
            if m is None:
                continue
            counted = True
            # One short at most: only a redirect says a mission is done.
            if m.credited < m.kill_count - 1:
                m.credited += 1
        if counted:
            self._level()
        return counted

    def redirect(self, mid, at: str = "") -> None:
        """A mission reached its count: its figure is exact from here, and
        the factions held as long as it are raised to match (``_level``)."""
        m = self.missions.get(int(mid))
        if m is None or m.done:
            return
        m.credited = m.kill_count
        m.done = True
        self._level()

    def _level(self) -> None:
        """Every faction sees every kill, so one whose missions against a
        target all began no later than another's has been credited at least
        as many: raise it to that, on its current mission (still one short;
        the missions after it wait for its redirect)."""
        groups: dict[tuple, list[_Mission]] = {}
        for m in self.missions.values():
            groups.setdefault((m.source, m.target_faction), []).append(m)
        held = {k: min(x.order for x in v)[0] for k, v in groups.items()}
        # From when each group could first have been credited a kill.
        start = {k: self._kills_possible_from(held[k], v[0].target_system)
                 for k, v in groups.items()}
        made = {k: sum(x.credited for x in v) for k, v in groups.items()}
        for key, ms in groups.items():
            floor = max((made[o] for o in groups
                         if o != key and o[1] == key[1] and held[key] <= start[o]),
                        default=0)
            if floor <= made[key]:
                continue
            current = min((x for x in ms if not x.done), key=lambda x: x.order, default=None)
            if current is not None:
                current.credited = min(current.kill_count - 1,
                                       current.credited + floor - made[key])

    def mark_done(self, mid) -> None:
        """Known to be complete without its redirect being replayed."""
        m = self.missions.get(int(mid))
        if m is not None:
            m.credited, m.done = m.kill_count, True

    def remove(self, mid) -> None:
        """Turned in, abandoned or failed: off the stack, credit and all."""
        self.missions.pop(int(mid), None)

    def keep_only(self, mids: Iterable) -> None:
        live = {int(x) for x in mids}
        for mid in [k for k in self.missions if k not in live]:
            self.remove(mid)

    # ── Reading it ────────────────────────────────────────────────────────────

    def credited(self, mid) -> int:
        m = self.missions.get(int(mid))
        return m.credited if m else 0

    def by_source(self) -> dict[str, tuple[int, int]]:
        """Source faction → (kills credited, kills required)."""
        out: dict[str, list[int]] = {}
        for m in self.missions.values():
            cur_tot = out.setdefault(m.source, [0, 0])
            cur_tot[0] += m.credited
            cur_tot[1] += m.kill_count
        return {k: (v[0], v[1]) for k, v in out.items()}

    def stack(self) -> tuple[int, int]:
        """(kills made against the stack, stack height). Every faction sees
        every kill, so the kills made are the most any faction has been
        credited; the height is the tallest faction's total."""
        rows = self.by_source().values()
        if not rows:
            return 0, 0
        return max(c for c, _t in rows), max(t for _c, t in rows)


# ── Rebuilt from the journals ────────────────────────────────────────────────

#: What a rebuild reads.
REBUILD_EVENTS = ("MissionAccepted", "MissionRedirected", "MissionCompleted",
                  "MissionAbandoned", "MissionFailed", "Bounty",
                  "FSDJump", "Location", "CarrierJump")


def apply(ledger: MassacreLedger, ev: dict, system: str | None) -> str | None:
    """One journal event into ``ledger``; returns the system the pilot is in
    after it. The single path both a rebuild and the live component use."""
    name = ev.get("event")
    if name in ("FSDJump", "Location", "CarrierJump"):
        if ev.get("StarSystem"):
            ledger.arrive(ev["StarSystem"], ev.get("timestamp", ""))
        return ev.get("StarSystem") or system
    if name == "MissionAccepted" and is_massacre(ev.get("Name")):
        ledger.accept(ev.get("MissionID", 0), ev.get("Faction", ""), ev.get("KillCount", 0),
                      ev.get("TargetFaction", ""), ev.get("DestinationSystem", ""),
                      ev.get("timestamp", ""))
    elif name == "MissionRedirected" and ev.get("MissionID") is not None:
        ledger.redirect(ev["MissionID"], ev.get("timestamp", ""))
    elif name in ("MissionCompleted", "MissionAbandoned", "MissionFailed") \
            and ev.get("MissionID") is not None:
        ledger.remove(ev["MissionID"])
    elif name == "Bounty":
        ledger.kill(ev.get("VictimFaction", ""), system)
    return system


def rebuild(events: Iterable[dict], active: Iterable, until: str = "") -> tuple[MassacreLedger, str | None]:
    """A ledger for the ``active`` massacre missions from journal events in
    order, stopping before ``until`` (the login snapshot: what follows it is
    replayed live). Returns the ledger and the last system seen."""
    ledger = MassacreLedger()
    active = {int(x) for x in active}
    system = None
    for ev in events:
        if until and str(ev.get("timestamp", "")) >= until:
            break
        system = apply(ledger, ev, system)
    ledger.keep_only(active)
    return ledger, system


def journal_events_since_oldest(journal_dir, active: Iterable) -> Iterable[dict]:
    """REBUILD_EVENTS from the journal holding the oldest active mission's
    acceptance onward, in order. Reads nothing earlier than it needs."""
    from core.journal_index import index_for, journal_sort_key
    idx = index_for(journal_dir)
    want = {int(x) for x in active}
    if not want:
        return []
    first = None
    for fname, ev in idx.events(("MissionAccepted",), newest_first=True):
        mid = ev.get("MissionID")
        if mid is not None and int(mid) in want:
            first = fname
            want.discard(int(mid))
            if not want:
                break
    files = sorted(idx.files(), key=journal_sort_key)
    if first is not None:
        files = [f for f in files if journal_sort_key(f) >= journal_sort_key(first)]
    return (ev for _f, ev in idx.events(REBUILD_EVENTS, files=files))
