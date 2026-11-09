"""tests/test_session_launch_boundary.py — a game launch ends the last session.
"""
from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from components.commander import CommanderPlugin  # noqa: E402
from components.income import ActivityIncomePlugin  # noqa: E402
from components.session_stats import SessionStatsPlugin  # noqa: E402
from core.state import MonitorState, SessionData  # noqa: E402

UTC = timezone.utc
LOAD = datetime(2026, 10, 14, 4, 27, 43, tzinfo=UTC)
SOLD = datetime(2026, 10, 14, 6, 50, 0, tzinfo=UTC)
QUIT = datetime(2026, 10, 14, 7, 2, 35, tzinfo=UTC)
LAUNCH = datetime(2026, 10, 15, 1, 53, 4, tzinfo=UTC)


class Storage:
    def __init__(self):
        self.data = {}

    def read_json(self, *a):
        return dict(self.data)

    def write_json(self, data, *a):
        self.data = dict(data)


def _core():
    state = MonitorState()
    core = SimpleNamespace(
        state=state, gui_queue=None, session_providers=[], _plugins={},
        active_session=SessionData(), notify_levels={}, journal_dir=Path("/nonexistent"),
        emitter=SimpleNamespace(emit=lambda **k: None))
    core.plugin_call = (lambda name, method, *a, **k:
                        getattr(core._plugins[name], method)(*a, **k))
    clock = SessionStatsPlugin()
    clock.storage = Storage()
    clock.core = core
    clock.on_load(core)
    income = ActivityIncomePlugin()
    income.core = core
    income._reset_counters()
    cmdr = CommanderPlugin.__new__(CommanderPlugin)
    cmdr.core = core
    core.session_providers.append(income)
    # The loader's order: component files alphabetically.
    core._plugins.update(commander=cmdr, income=income, session_stats=clock)
    return core, clock, income, cmdr


def _feed(core, events):
    """What core.journal does with each event: set the clock, dispatch."""
    for when, ev in events:
        core.state.event_time = when
        ev = {"_logtime": when, **ev}
        for plugin in core._plugins.values():
            if ev["event"] in plugin.SUBSCRIBED_EVENTS:
                plugin.on_event(ev, core.state)


LAST_NIGHT = [
    (LOAD, {"event": "LoadGame", "Commander": "Merrick Calbruin",
            "Ship": "type9", "GameMode": "Solo", "Credits": 751_897_248}),
    (SOLD, {"event": "MarketSell", "Type": "platinum", "Count": 900,
            "TotalSale": 153_005_520, "AvgPricePaid": 0}),
    (QUIT, {"event": "Shutdown"}),
]


def test_last_night_is_the_session_until_the_game_is_launched():
    core, clock, income, _ = _core()
    _feed(core, LAST_NIGHT)
    assert income.total_income == 153_005_520
    assert clock.session_duration_seconds() == (QUIT - LOAD).total_seconds()


def test_a_launch_long_after_the_last_session_starts_a_new_one():
    core, clock, income, _ = _core()
    _feed(core, LAST_NIGHT + [
        (LAUNCH, {"event": "Fileheader", "part": 1, "gameversion": "4.4.1.1"})])
    assert income.total_income == 0
    assert clock.session_duration_seconds() == 0
    # The overlay shows the balance and nothing for the session.
    panel = income.overlay_panel("income", None)
    assert panel is None or all(label != "Session:" for label, _ in panel.rows)


def test_the_new_session_starts_when_a_mode_is_picked():
    core, clock, income, _ = _core()
    play = LAUNCH + timedelta(minutes=22)
    _feed(core, LAST_NIGHT + [
        (LAUNCH, {"event": "Fileheader", "part": 1}),
        (play, {"event": "LoadGame", "Ship": "type9", "GameMode": "Solo"}),
        (play + timedelta(hours=1), {"event": "MarketSell", "TotalSale": 1_000_000,
                                     "AvgPricePaid": 0}),
    ])
    assert clock._session_start_time == play
    assert income.total_income == 1_000_000


def test_a_relaunch_after_a_crash_continues_the_session():
    core, clock, income, _ = _core()
    back = QUIT + timedelta(minutes=4)
    _feed(core, LAST_NIGHT + [
        (back, {"event": "Fileheader", "part": 1}),
        (back + timedelta(minutes=1), {"event": "LoadGame", "Ship": "type9"}),
    ])
    assert income.total_income == 153_005_520
    assert clock._session_start_time == LOAD


def test_a_continued_journal_is_not_a_launch():
    """Part 2 of a journal is the same session in a new file."""
    core, clock, income, _ = _core()
    _feed(core, LAST_NIGHT[:2])
    core.state.last_shutdown_time = SOLD
    _feed(core, [(SOLD + timedelta(minutes=30), {"event": "Fileheader", "part": 2})])
    assert income.total_income == 153_005_520
