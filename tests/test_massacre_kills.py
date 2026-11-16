"""tests/test_massacre_kills.py — kills credited to massacre missions."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.massacre import MassacreLedger, rebuild  # noqa: E402

SYS, TGT = "Vequess", "Vequess Brotherhood"


def _ev(t, event, **kw):
    return {"timestamp": f"2026-11-15T{t}Z", "event": event, **kw}


def _accept(t, mid, src, kc, tgt=TGT, system=SYS, wing=False):
    return _ev(t, "MissionAccepted", Name="Mission_Massacre", MissionID=mid, Faction=src,
               TargetFaction=tgt, DestinationSystem=system, KillCount=kc, Reward=1_000_000,
               TargetType="$MissionUtil_FactionTag_Pirate;", Wing=wing)


def _bounty(t, pilot="P", faction=TGT, target="python"):
    return _ev(t, "Bounty", PilotName_Localised=pilot, VictimFaction=faction,
               Target=target, TotalReward=100_000)


def _arrive(t, system=SYS):
    return _ev(t, "FSDJump", StarSystem=system)


def _feed(ledger, events):
    for e in events:
        ledger.apply(e)
    return ledger


def _stack():
    return [_arrive("10:00:00", "Cemiess"),
            _accept("10:00:01", 1, "A", 3), _accept("10:00:02", 2, "A", 2),
            _accept("10:00:03", 3, "B", 4), _arrive("10:05:00")]


def test_a_kill_goes_to_the_oldest_mission_of_each_source_faction():
    L = _feed(MassacreLedger(), _stack() + [_bounty("10:06:00"), _bounty("10:06:10")])
    assert (L.credited(1), L.credited(2), L.credited(3)) == (2, 0, 2)


def test_a_mission_is_held_one_short_until_it_redirects():
    L = _feed(MassacreLedger(), _stack() + [_bounty(f"10:06:{i:02d}") for i in range(3)])
    assert L.credited(1) == 2 and L.credited(2) == 0
    L.apply(_ev("10:06:03", "MissionRedirected", MissionID=1))
    assert L.credited(1) == 3 and L.missions[1].done
    L.apply(_bounty("10:06:04"))
    assert L.credited(2) == 1 and L.credited(3) == 3


def test_kills_elsewhere_or_of_another_faction_or_not_ships_do_not_count():
    events = _stack()[:-1] + [_bounty("10:04:00"), _arrive("10:05:00"),
                              _bounty("10:06:00", faction="Someone Else"),
                              _bounty("10:06:05", target="skimmerdrone"),
                              _bounty("10:06:06", target="suitai_soldier")]
    L = _feed(MassacreLedger(), events)
    assert (L.credited(1), L.credited(3)) == (0, 0)


def test_a_murder_counts_for_the_faction_its_victim_was_scanned_as():
    events = _stack() + [
        _ev("10:06:00", "ShipTargeted", TargetLocked=True, ScanStage=3, PilotName_Localised="Q",
            Faction=TGT, LegalStatus="Clean", HullHealth=100.0),
        _ev("10:06:20", "CommitCrime", CrimeType="murder", Faction="Law", Victim="Q", Bounty=10000),
        _ev("10:06:30", "CommitCrime", CrimeType="murder", Faction="Law", Victim="Unscanned"),
        _ev("10:06:40", "CommitCrime", CrimeType="assault", Faction="Law", Victim="Q"),
    ]
    L = _feed(MassacreLedger(), events)
    assert (L.credited(1), L.credited(3)) == (1, 1)


def _lost_lock(t0, hull, then):
    return [_ev(f"10:07:{t0:02d}", "ShipTargeted", TargetLocked=True, ScanStage=2,
                PilotName_Localised="Quick", HullHealth=hull),
            _ev(f"10:07:{t0 + 1:02d}", "ShipTargeted", TargetLocked=False)] + then


def test_an_unscanned_target_dropping_at_no_hull_is_a_kill():
    L = _feed(MassacreLedger(), _stack() + _lost_lock(0, 0.0, [_ev("10:07:09", "Music")]))
    assert (L.credited(1), L.credited(3), L.unscanned) == (1, 1, 1)


def test_an_unscanned_kill_is_not_counted_twice_when_its_bounty_follows():
    L = _feed(MassacreLedger(), _stack() + _lost_lock(0, 0.0, [_bounty("10:07:02", pilot="Quick"),
                                                             _ev("10:07:09", "Music")]))
    assert (L.credited(1), L.unscanned) == (1, 0)


def test_a_target_dropped_with_hull_left_or_two_target_factions_is_not_a_kill():
    L = _feed(MassacreLedger(), _stack() + _lost_lock(0, 40.0, [_ev("10:07:09", "Music")]))
    assert L.credited(1) == 0
    L = _feed(MassacreLedger(), _stack() + [_accept("10:00:04", 4, "C", 5, tgt="Other")]
              + _lost_lock(0, 0.0, [_ev("10:07:09", "Music")]))
    assert L.credited(1) == 0 and L.unscanned == 0


def test_a_redirect_settles_a_dropped_lock_at_once():
    L = _feed(MassacreLedger(), [_arrive("10:00:00"), _accept("10:00:01", 1, "A", 1),
                                 _accept("10:00:02", 2, "A", 3)]
              + _lost_lock(0, 0.0, [_ev("10:07:01", "MissionRedirected", MissionID=1)]))
    # The kill went to mission 1 (held one short at 0 of 1), then the
    # redirect completed it; mission 2 is untouched.
    assert L.credited(1) == 1 and L.credited(2) == 0


def test_rebuild_keeps_only_the_held_missions_and_stops_at_the_snapshot():
    events = _stack() + [_bounty("10:06:00"), _ev("10:06:01", "MissionCompleted", MissionID=9),
                         _bounty("10:30:00")]
    L = rebuild(events, [1, 3], until="2026-11-15T10:20:00Z")
    assert set(L.missions) == {1, 3} and (L.credited(1), L.credited(3)) == (1, 1)


# ── The component, at login ───────────────────────────────────────────────────

def test_the_component_rebuilds_kills_from_the_journals_at_login(tmp_path):
    from tests.test_missions_board import _component
    from core.journal_index import forget
    first = _stack() + [_bounty("10:06:00"), _bounty("10:06:10")]
    (tmp_path / "Journal.2026-11-15T095900.01.log").write_text(
        "".join(json.dumps(e) + "\n" for e in first), encoding="utf-8")
    snap = {"timestamp": "2026-11-15T12:00:00Z", "event": "Missions", "Failed": [],
            "Complete": [], "Active": [{"MissionID": m, "Name": "Mission_Massacre",
                                        "Expires": 9999} for m in (1, 2, 3)]}
    forget()
    try:
        p, state, _said = _component(journal_dir=tmp_path)
        p.on_event(snap, state)
        L = state.massacre_ledger
        assert (L.credited(1), L.credited(2), L.credited(3)) == (2, 0, 2)
        p.on_event(_arrive("12:01:00"), state)
        p.on_event(_bounty("12:02:00"), state)
        assert (L.credited(1), L.credited(3)) == (2, 3)
        p.on_event(_ev("12:02:01", "MissionRedirected", MissionID=1, Name="Mission_Massacre"), state)
        assert L.credited(1) == 3 and state.massacre_redirected == {1}
    finally:
        forget()


def _bond(t, faction=TGT):
    return _ev(t, "FactionKillBond", Reward=26007, AwardingFaction="Ally", VictimFaction=faction)


def test_a_conflict_zone_bond_is_a_kill_of_its_victim_faction():
    L = _feed(MassacreLedger(), _stack() + [_bond("10:06:00"), _bond("10:06:05", faction="Other")])
    assert (L.credited(1), L.credited(3)) == (1, 1)


def test_a_bond_after_a_dropped_lock_is_that_kill_not_another():
    L = _feed(MassacreLedger(), _stack() + _lost_lock(0, 0.0, [_bond("10:07:02"),
                                                             _ev("10:07:09", "Music")]))
    assert (L.credited(1), L.unscanned) == (1, 0)
