"""tests/test_session_clock.py — one session, one clock, and resets that survive.
"""
from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from components.powerplay import ActivityPowerplayPlugin  # noqa: E402
from components.session_stats import SessionStatsPlugin  # noqa: E402

T0 = datetime(2026, 9, 27, 20, 18, 38, tzinfo=timezone.utc)      # LoadGame
RESET = datetime(2026, 9, 28, 1, 20, 12, tzinfo=timezone.utc)
END = datetime(2026, 9, 28, 6, 41, 23, tzinfo=timezone.utc)


class Storage:
    def __init__(self, data=None):
        self.data = data or {}

    def read_json(self, *a):
        return dict(self.data)

    def write_json(self, data, *a):
        self.data = dict(data)


def _core(reset_after=None):
    state = SimpleNamespace(event_time=None, in_preload=True, pp_power=None,
                            pp_rank=None, pp_merits_total=None)
    core = SimpleNamespace(state=state, gui_queue=None, session_providers=[],
                           _plugins={}, notify_levels={},
                           emitter=SimpleNamespace(emit=lambda **k: None))
    core.plugin_call = lambda name, method, *a, **k: getattr(core._plugins[name], method)(*a, **k)
    clock = SessionStatsPlugin()
    clock.storage = Storage({"reset_after": reset_after.isoformat()} if reset_after else {})
    clock.core = core
    clock.on_load(core)
    pp = ActivityPowerplayPlugin()
    pp.core = core
    pp.storage = Storage()
    pp._reset_counters()
    core.session_providers.append(pp)
    core._plugins.update(session_stats=clock, powerplay=pp)
    return core, clock, pp


def _replay(core, clock, pp, events):
    """What core.journal does for each event, in order."""
    for when, ev in events:
        core.state.event_time = when
        clock.before_event(when)
        ev = {"event": ev["event"], "_logtime": when, **ev}
        if ev["event"] == "LoadGame":
            # commander.py's automatic boundary, after a gap since Shutdown
            for p in core.session_providers:
                p.on_session_reset()
            clock.on_new_session(300)
            clock.on_event(ev, core.state)
        else:
            pp.on_event(ev, core.state)
    clock.after_preload()


SESSION = [
    (T0, {"event": "LoadGame"}),
    (T0 + timedelta(hours=2, minutes=10), {"event": "PowerplayMerits", "MeritsGained": 1417}),
    (RESET + timedelta(hours=3, minutes=34), {"event": "PowerplayMerits", "MeritsGained": 6589}),
    (RESET + timedelta(hours=5, minutes=16), {"event": "PowerplayMerits", "MeritsGained": 11840}),
    (END, {"event": "Music"}),
]


def test_rate_divides_by_the_session_not_the_first_merit():
    core, clock, pp = _core(RESET)
    _replay(core, clock, pp, SESSION)
    hours = (END - RESET).total_seconds() / 3600
    row = pp.get_summary_rows()[0]
    assert row["value"] == "18,429"
    assert row["rate"] == f"{round(18429 / hours):,} /hr"      # 3,443 /hr


def test_a_reset_survives_a_restart():
    """Replaying with the reset restored gives what the live run showed."""
    core, clock, pp = _core(RESET)
    _replay(core, clock, pp, SESSION)
    assert pp.merits_earned == 18429
    assert clock._session_start_time == RESET
    assert clock._reset_after == RESET                # not cleared by LoadGame


def test_without_a_reset_the_session_starts_at_loadgame():
    core, clock, pp = _core(None)
    _replay(core, clock, pp, SESSION)
    assert pp.merits_earned == 19846
    assert clock._session_start_time == T0


def test_a_reset_after_the_last_event_is_applied_when_replay_ends():
    late = END + timedelta(minutes=5)
    core, clock, pp = _core(late)
    _replay(core, clock, pp, SESSION)
    assert pp.merits_earned == 0
    assert clock._session_start_time == late


def test_a_later_game_session_still_supersedes_the_reset():
    core, clock, pp = _core(RESET)
    later = END + timedelta(hours=8)
    _replay(core, clock, pp, SESSION + [
        (later, {"event": "LoadGame"}),
        (later + timedelta(hours=1), {"event": "PowerplayMerits", "MeritsGained": 100}),
    ])
    assert pp.merits_earned == 100
    assert clock._reset_after is None
    assert clock._session_start_time == later


def test_a_manual_reset_is_logged(monkeypatch):
    import components.session_stats as S
    seen: list[str] = []
    monkeypatch.setattr(S, "_log_info", seen.append)
    core, clock, pp = _core(None)
    core.state.event_time = RESET
    clock.on_new_session(0)
    assert seen and "reset" in seen[0] and RESET.isoformat() in seen[0]


def test_every_activity_reads_the_same_clock():
    core, clock, pp = _core(None)
    clock._session_start_time = T0
    core.state.event_time = END
    assert pp._duration_seconds() == (END - T0).total_seconds()
