"""
tests/test_crew_paid.py — when NPC crew were hired, and what they have been paid.

"Hired" showed the first CrewAssign, which can come days after CrewHire: a
crew member hired on 28 May showed as hired on 3 June. And the total was shown as exact whenever the first assignment
happened to be in the oldest journal, though the game's own Total Paid
includes wages the journal never records.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.state import MonitorState  # noqa: E402


def _journal(path: Path, events: list[dict]) -> None:
    path.write_text("".join(json.dumps(e) + "\n" for e in events), encoding="utf-8")


def _ev(ts, event, **kw):
    return {"timestamp": ts, "event": event, **kw}


def _boot(tmp_path):
    from core.journal import bootstrap_crew
    state = MonitorState()
    state.has_fighter_bay = True
    state.crew_name = "Camdyn Levy"
    bootstrap_crew(state, tmp_path)
    return state


def test_hired_is_the_crewhire_not_the_first_assignment(tmp_path):
    _journal(tmp_path / "Journal.2026-05-19T003353.01.log", [
        _ev("2026-05-19T01:00:00Z", "Fileheader")])
    _journal(tmp_path / "Journal.2026-05-28T132258.01.log", [
        _ev("2026-05-28T20:36:18Z", "CrewHire", Name="Camdyn Levy", CombatRank=0),
        _ev("2026-05-28T20:45:31Z", "NpcCrewPaidWage", NpcCrewName="Camdyn Levy", Amount=1000)])
    _journal(tmp_path / "Journal.2026-06-03T060000.01.log", [
        _ev("2026-06-03T06:31:14Z", "CrewAssign", Name="Camdyn Levy", Role="Active"),
        _ev("2026-06-03T07:00:00Z", "NpcCrewPaidWage", NpcCrewName="Camdyn Levy", Amount=500)])
    s = _boot(tmp_path)
    assert s.crew_hire_time == datetime(2026, 5, 28, 20, 36, 18, tzinfo=timezone.utc)
    assert s.crew_total_paid == 1500
    assert s.crew_paid_complete is True


def test_hired_before_the_journals_falls_back_to_first_assignment(tmp_path):
    _journal(tmp_path / "Journal.2026-06-03T060000.01.log", [
        _ev("2026-06-03T06:31:14Z", "CrewAssign", Name="Camdyn Levy", Role="Active"),
        _ev("2026-06-03T07:00:00Z", "NpcCrewPaidWage", NpcCrewName="Camdyn Levy", Amount=500)])
    s = _boot(tmp_path)
    assert s.crew_hire_time.day == 3 and s.crew_total_paid == 500
    assert s.crew_paid_complete is False


def test_paid_is_always_a_floor():
    from core.windows.crew import tab
    state = MonitorState()
    state.has_fighter_bay = True
    state.crew_name, state.crew_active = "Camdyn Levy", True
    state.crew_total_paid, state.crew_paid_complete = 749_678_540, True
    rows = {r[1]: r[2] for r in tab(SimpleNamespace(state=state, _plugins={})).rows
            if r[0] == "kv"}
    assert rows["Paid"].startswith("≥ ")


def test_a_crew_change_brings_its_own_hire_date():
    from components.crew_slf import CrewSlfPlugin
    p = CrewSlfPlugin.__new__(CrewSlfPlugin)
    state = MonitorState()
    p.core = SimpleNamespace(gui_queue=None, state=state, notify_levels={}, cfg=None)
    state.crew_name = "Old Hand"
    state.crew_hire_time = datetime(2026, 1, 1, tzinfo=timezone.utc)
    p.on_event({"timestamp": "2026-10-25T10:00:00Z", "event": "CrewHire",
                "Name": "New Face", "CombatRank": 0}, state)
    p.on_event({"timestamp": "2026-10-25T10:05:00Z", "event": "CrewAssign",
                "Name": "New Face", "Role": "Active"}, state)
    assert state.crew_name == "New Face"
    assert state.crew_hire_time == datetime(2026, 10, 25, 10, 0, tzinfo=timezone.utc)


def test_the_replay_does_not_count_the_bootstraps_wages_again(tmp_path):
    """The bootstrap counts every journal's wages, the current one's too, and
    the start-up replay of the current journal then counted that journal's
    again — in whichever interface replayed after the bootstrap, so the
    desktop window and the terminal dashboard disagreed. A wage after the
    bootstrap's newest still counts."""
    _journal(tmp_path / "Journal.2026-05-28T100000.01.log", [
        _ev("2026-05-28T10:00:00Z", "CrewHire", Name="Camdyn Levy", Cost=0, CombatRank=0),
        _ev("2026-05-29T10:00:00Z", "NpcCrewPaidWage", NpcCrewName="Camdyn Levy", Amount=1000),
    ])
    _journal(tmp_path / "Journal.2026-10-25T204906.01.log", [
        _ev("2026-10-26T02:00:00Z", "NpcCrewPaidWage", NpcCrewName="Camdyn Levy", Amount=500),
    ])
    state = _boot(tmp_path)
    assert state.crew_total_paid == 1500
    import importlib.util
    spec = importlib.util.spec_from_file_location("crew_slf_w", ROOT / "components" / "crew_slf.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    p = mod.CrewSlfPlugin.__new__(mod.CrewSlfPlugin)
    p.core = SimpleNamespace(state=state, gui_queue=None, notify_levels={}, cfg=None,
                             emitter=SimpleNamespace(emit=lambda **k: None))
    replayed = _ev("2026-10-26T02:00:00Z", "NpcCrewPaidWage", NpcCrewName="Camdyn Levy", Amount=500)
    p.on_event(dict(replayed), state)
    assert state.crew_total_paid == 1500
    p.on_event(_ev("2026-10-26T03:00:00Z", "NpcCrewPaidWage", NpcCrewName="Camdyn Levy",
                   Amount=250), state)
    assert state.crew_total_paid == 1750
