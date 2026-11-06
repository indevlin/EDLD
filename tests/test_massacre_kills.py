"""
tests/test_massacre_kills.py — kills made against the massacre stack.

The game credits a kill to the oldest unfinished mission of each source
faction, and writes a Bounty for only some of the kills it credits; a
MissionRedirected is the one exact figure. core/massacre.py counts from
bounties, anchored on redirects. These pin that down, using the LHS 2637
stack of 2 November (two Alioth Independents missions, 2 and 6 kills) as
the game wrote it: eight kills credited, seven Bounty events.

Also here: the mission component's redirect and turn-in arms, which a
general arm before them used to shadow, and the rebuild at login, which must
never count a replayed kill twice.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core import massacre as M  # noqa: E402
from core.state import MonitorState  # noqa: E402


SRC, TGT, SYS = "Alioth Independents", "LHS 2637 Ring", "LHS 2637"
NAME = "Mission_Massacre_Legal_Military"


def _ev(ts, event, **kw):
    return {"timestamp": f"2026-11-02T{ts}Z", "event": event, **kw}


def _accept(ts, mid, kc, src=SRC, tgt=TGT, system=SYS, reward=500_000):
    return _ev(ts, "MissionAccepted", Faction=src, Name=NAME, TargetFaction=tgt,
               KillCount=kc, DestinationSystem=system, Reward=reward,
               TargetType="$MissionUtil_FactionTag_Pirate;", MissionID=mid)


def _bounty(ts, victim=TGT):
    return _ev(ts, "Bounty", VictimFaction=victim, TotalReward=50_000,
               Rewards=[{"Faction": "Perez Ring Brewery", "Reward": 50_000}])


def _redirect(ts, mid):
    return _ev(ts, "MissionRedirected", MissionID=mid, Name=NAME,
               NewDestinationSystem="Stheno")


#: The LHS 2637 stack as the journal has it. Mission 2 redirected after five
#: more qualifying bounties, not six: one credited kill left no Bounty.
LHS_2637 = [
    _accept("19:57:04", 1070241162, 2),
    _accept("19:57:09", 1070241171, 6),
    _ev("20:03:48", "FSDJump", StarSystem=SYS),
    _bounty("20:11:51"),
    _bounty("20:12:05", "Teliu Yuan Mafia"),
    _bounty("20:12:19", "Teliu Yuan Mafia"),
    _bounty("20:12:48"),
    _redirect("20:12:48", 1070241162),
    _bounty("20:12:55"),
    _bounty("20:17:57"),
    _bounty("20:18:08"),
    _bounty("20:19:06"),
    _bounty("20:22:41"),
    _redirect("20:22:41", 1070241171),
    _bounty("20:23:03"),
]


def _feed(events, ledger=None):
    ledger = ledger or M.MassacreLedger()
    system = None
    for e in events:
        system = M.apply(ledger, e, system)
    return ledger


# ── The ledger ────────────────────────────────────────────────────────────────

def test_a_kill_goes_to_the_oldest_unfinished_mission_of_each_source_faction():
    L = _feed([_accept("10:00:00", 1, 5), _accept("10:00:01", 2, 5),
               _accept("10:00:02", 3, 4, src="Other"),
               _ev("10:01:00", "FSDJump", StarSystem=SYS),
               _bounty("10:02:00"), _bounty("10:02:10")])
    assert (L.credited(1), L.credited(2), L.credited(3)) == (2, 0, 2)
    assert L.by_source() == {SRC: (2, 10), "Other": (2, 4)}
    assert L.stack() == (2, 10)


def test_another_faction_or_another_system_is_not_a_kill():
    L = _feed([_accept("10:00:00", 1, 5), _ev("10:01:00", "FSDJump", StarSystem="Sol"),
               _bounty("10:02:00"),                               # wrong system
               _ev("10:03:00", "FSDJump", StarSystem=SYS),
               _bounty("10:04:00", "Someone Else")])              # wrong faction
    assert L.credited(1) == 0


def test_the_lhs_2637_stack_never_reads_high_and_is_exact_at_each_redirect():
    L = M.MassacreLedger()
    system = None
    for e in LHS_2637:
        if e["event"] == "MissionRedirected":
            m = L.missions[e["MissionID"]]
            # Held one short: only the redirect says it is done.
            assert m.credited <= m.kill_count - 1
        system = M.apply(L, e, system)
        for m in L.missions.values():
            assert m.credited <= m.kill_count
    # Seven bounties, eight kills: the redirect made it exact.
    assert L.stack() == (8, 8)
    assert all(m.done for m in L.missions.values())


def test_mission_two_reads_one_low_until_its_redirect_uncovers_the_kill():
    before = [e for e in LHS_2637 if e["timestamp"] < "2026-11-02T20:22:41Z"]
    L = _feed(before)
    assert L.credited(1070241162) == 2 and L.credited(1070241171) == 4
    assert L.stack() == (6, 8)          # truly 7: one kill left no Bounty


def test_a_redirect_raises_the_factions_held_as_long_as_it():
    # A and B taken minutes apart at a station, then flown to the target
    # system; C taken there part way through.
    L = _feed([_ev("09:50:00", "Location", StarSystem="Stheno"),
               _accept("09:55:00", 1, 3, src="A"), _accept("09:58:00", 2, 10, src="B"),
               _ev("10:01:00", "FSDJump", StarSystem=SYS),
               _bounty("10:02:00"),
               _accept("10:05:00", 3, 10, src="C"),
               _redirect("10:06:00", 1)])
    # A's redirect says three kills, two unseen. B was held from the moment
    # kills there were possible, so saw them all; C, taken part way, may not
    # have, and is not credited them.
    assert L.credited(1) == 3 and L.credited(2) == 3 and L.credited(3) == 0


def test_a_faction_held_as_long_as_another_is_never_shown_fewer_kills():
    L = _feed([_ev("09:50:00", "Location", StarSystem="Stheno"),
               _accept("10:00:00", 1, 20, src="A"), _accept("10:00:31", 2, 20, src="B"),
               _ev("10:01:00", "FSDJump", StarSystem=SYS)])
    L.missions[1].credited = 9          # as if A had been carried further
    L.kill(TGT, SYS)
    assert L.credited(1) == 10 and L.credited(2) == 10


def test_turn_in_takes_a_mission_and_its_kills_off_the_stack():
    L = _feed(LHS_2637 + [_ev("21:34:43", "MissionCompleted", MissionID=1070241162)])
    assert list(L.missions) == [1070241171] and L.stack() == (6, 6)


def test_rebuild_stops_at_the_snapshot():
    snapshot = "2026-11-02T20:20:00Z"
    L, system = M.rebuild(iter(LHS_2637), [1070241162, 1070241171], until=snapshot)
    assert system == SYS
    # 20:12:55, 20:17:57, 20:18:08, 20:19:06 — not 20:22:41, after it.
    assert L.credited(1070241171) == 4


# ── The component ─────────────────────────────────────────────────────────────

class _Store:
    def __init__(self, data=None):
        self.data = dict(data or {})

    def read_json(self, *_a):
        return json.loads(json.dumps(self.data))

    def write_json(self, d, *_a):
        self.data = json.loads(json.dumps(d))


def _component(journal_dir=None, store=None):
    from components.missions import MissionsPlugin
    said: list[str] = []
    state = MonitorState()
    state.in_preload = False
    core = SimpleNamespace(
        state=state, gui_queue=None, journal_dir=journal_dir,
        notify_levels={"MissionUpdate": 1, "AllMissionsReady": 1},
        app_settings={"FullStackSize": 20},
        emitter=SimpleNamespace(emit=lambda **kw: said.append(kw.get("msg_term", ""))),
        register_block=lambda *a, **k: None)
    p = MissionsPlugin.__new__(MissionsPlugin)
    p.storage = store or _Store()
    p.core = core
    p._restore()
    return p, state, said


def _snapshot(ts, *mids):
    return {"timestamp": ts, "event": "Missions", "Failed": [], "Complete": [],
            "Active": [{"MissionID": m, "Name": NAME, "PassengerMission": False,
                        "Expires": 3600} for m in mids]}


def test_a_redirect_and_a_turn_in_update_the_stack_live():
    """Both used to be shadowed by the general arm before them."""
    p, state, said = _component()
    p.on_event(_snapshot("2026-11-02T19:00:00Z"), state)
    for e in LHS_2637[:8]:
        p.on_event(e, state)
    assert state.missions_complete == 1
    assert "Mission 1 of 2 complete (1 remaining)" in said
    p.on_event(_ev("21:34:43", "MissionCompleted", MissionID=1070241162, Name=NAME + "_name"),
               state)
    assert state.active_missions == [1070241171]
    assert list(state.mission_detail_map) == [1070241171]
    assert state.stack_value == 500_000
    assert state.massacre_ledger.stack() == (0, 6)


def _write(path: Path, events):
    path.write_text("".join(json.dumps(e) + "\n" for e in events), encoding="utf-8")


def test_a_restart_replays_without_counting_a_kill_twice(tmp_path):
    """Played across two journals; EDLD sees the second from its start
    twice, as two starts' preloads would."""
    first = LHS_2637[:9]                    # through redirect 1 and 20:12:55
    login = "2026-11-02T20:15:00Z"
    second = [{"timestamp": "2026-11-02T20:14:50Z", "event": "LoadGame"},
              {"timestamp": "2026-11-02T20:14:55Z", "event": "Location", "StarSystem": SYS},
              _snapshot(login, 1070241162, 1070241171)] + LHS_2637[9:12]
    _write(tmp_path / "Journal.2026-11-02T190000.01.log", first)
    _write(tmp_path / "Journal.2026-11-02T201450.01.log", second)

    store = _Store()
    counts = []
    for _start in range(2):
        p, state, _said = _component(tmp_path, store)
        state.in_preload = True
        for e in second:
            p.on_event(e, state)
        state.in_preload = False
        counts.append((state.massacre_ledger.credited(1070241162),
                       state.massacre_ledger.credited(1070241171),
                       state.missions_complete))
    # Redirect 1 came from the first journal's history; the second mission
    # has the 20:12:55 kill from history and the three after the login.
    assert counts[0] == (2, 4, 1)
    assert counts[1] == counts[0]


def test_a_redirect_made_while_edld_was_closed_counts_as_ready(tmp_path):
    _write(tmp_path / "Journal.2026-11-02T190000.01.log", LHS_2637[:8])
    _write(tmp_path / "Journal.2026-11-02T210000.01.log",
           [_snapshot("2026-11-02T21:00:00Z", 1070241162, 1070241171)])
    p, state, _said = _component(tmp_path)
    state.in_preload = True
    p.on_event(_snapshot("2026-11-02T21:00:00Z", 1070241162, 1070241171), state)
    assert state.missions_complete == 1
    assert state.massacre_ledger.missions[1070241162].done


# ── The window ────────────────────────────────────────────────────────────────

def _window(ledger, detail, done=0):
    from core.windows.objectives import missions
    s = MonitorState()
    s.mission_detail_map, s.active_missions = detail, list(detail)
    s.massacre_ledger, s.missions_complete = ledger, done
    return missions(SimpleNamespace(state=s, app_settings={"FullStackSize": 20})).rows


def test_the_window_shows_kills_made_against_kills_needed():
    L = _feed([e for e in LHS_2637 if e["timestamp"] < "2026-11-02T20:22:41Z"])
    detail = {mid: {"faction": SRC, "kill_count": m.kill_count, "reward": 500_000,
                    "target_faction": TGT} for mid, m in L.missions.items()}
    rows = _window(L, detail, done=1)
    cells = {r[1]: r[2] for r in rows if r[0] == "cells"}
    assert cells[SRC] == ["006 / 008", "1.0M"]
    assert cells["Stack height"] == ["006 / 008", "1.0M"]
    kv = {r[1]: r[2] for r in rows if r[0] == "kv"}
    assert kv == {"Missions accepted": "2 of 20", "Ready to turn in": "1 of 2"}
    # Nothing but kills under the Kills heading.
    assert [r[2][0][0].strip() for r in rows if r[0] == "table"] == ["Kills", "CUR / TOT"]


def test_a_tall_stack_widens_the_kills_column():
    L = M.MassacreLedger()
    L.accept(1, SRC, 1200, TGT, SYS)
    rows = _window(L, {1: {"faction": SRC, "kill_count": 1200, "reward": 1}})
    stack = next(r for r in rows if r[0] == "cells" and r[1] == "Stack height")
    assert stack[2][0] == "0000 / 1200"


# ── EDCARS: Settings on the rail ──────────────────────────────────────────────

def test_settings_is_the_last_pill_and_opens_options_without_leaving_the_section():
    pytest.importorskip("PySide6")
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication([])
    from gui.edcars import EdcarsRail, Ink
    opened = []
    rail = EdcarsRail(Ink("default"), lambda _sid: None, on_settings=lambda: opened.append(1))
    lay = rail.layout()
    widgets = [lay.itemAt(i).widget() for i in range(lay.count())]
    assert widgets.index(rail.settings) == len(rail.pills)       # after every section
    assert rail.settings.text() == "SETTINGS" and not rail.settings.isCheckable()
    rail.select("objectives")
    rail.settings.click()
    assert opened == [1] and rail.pills["objectives"].isChecked()
    # Without somewhere to send it, there is no pill.
    assert EdcarsRail(Ink("default"), lambda _sid: None).settings is None
