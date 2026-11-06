"""
tests/test_combat_initial_alert.py — WarnNoKillsInitial.

The no-kill alert is timed from the last kill, so before the first kill of a
session it could never fire, and WarnNoKillsInitial — documented, defaulted,
read by nothing — was meant to cover that gap. It now does, timed from
dropping into a combat site and only while still there.
"""
from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import components.combat as combat_mod  # noqa: E402
from components.combat import CombatPlugin  # noqa: E402

RES = {"event": "SupercruiseDestinationDrop",
       "Type": "$MULTIPLAYER_SCENARIO78_TITLE;",
       "Type_Localised": "Resource Extraction Site [High]"}
CZ = {"event": "SupercruiseDestinationDrop",
      "Type": "$Warzone_PointRace_Med:#index=1;",
      "Type_Localised": "Conflict Zone [Medium Intensity]"}
STATION = {"event": "SupercruiseDestinationDrop", "Type": "Jameson Memorial",
           "Type_Localised": "Jameson Memorial"}


class Clock:
    t = 1000.0

    def __call__(self):
        return self.t


def _setup(monkeypatch, initial=5):
    clock = Clock()
    monkeypatch.setattr(combat_mod.time, "monotonic", clock)
    sent = []
    core = SimpleNamespace(
        app_settings={"WarnNoKills": 20, "WarnNoKillsInitial": initial,
                      "WarnCooldown": 15, "WarnKillRate": 0, "TruncateNames": 30},
        notify_levels={"InactiveAlert": 3, "RateAlert": 0},
        emitter=SimpleNamespace(emit=lambda **kw: sent.append(kw)),
        load_setting=lambda *a, **k: {"Enabled": False, "QuitOnNoKillsMinutes": 0},
        gui_queue=None,
        register_block=lambda *a, **k: None,
        register_session_provider=lambda *a, **k: None,
    )
    p = CombatPlugin()
    p.on_load(core)
    state = SimpleNamespace(in_game=True, in_preload=False, in_supercruise=False,
                            pilot_body=None, last_kill_mono=0.0, event_time=None)
    return p, state, clock, sent


def _drop(p, state, ev):
    p.on_event(dict(ev), state)
    state.pilot_body = ev["Type_Localised"]      # as journal.py sets it


def test_fires_once_after_the_initial_minutes_at_a_res(monkeypatch):
    p, state, clock, sent = _setup(monkeypatch)
    _drop(p, state, RES)
    clock.t += 4 * 60
    p.tick(state)
    assert not sent
    clock.t += 61
    p.tick(state)
    assert len(sent) == 1 and "Resource Extraction Site" in sent[0]["msg_term"]
    clock.t += 30 * 60
    p.tick(state)
    assert len(sent) == 1


def test_a_conflict_zone_counts_too(monkeypatch):
    p, state, clock, sent = _setup(monkeypatch)
    _drop(p, state, CZ)
    clock.t += 6 * 60
    p.tick(state)
    assert len(sent) == 1


def test_not_at_a_station_or_after_leaving_the_site(monkeypatch):
    p, state, clock, sent = _setup(monkeypatch)
    _drop(p, state, STATION)
    clock.t += 10 * 60
    p.tick(state)
    assert not sent
    _drop(p, state, RES)
    clock.t += 60
    state.pilot_body = None                       # left the site
    p.tick(state)
    clock.t += 10 * 60
    state.pilot_body = RES["Type_Localised"]
    p.tick(state)
    assert not sent


def test_a_kill_cancels_it(monkeypatch):
    p, state, clock, sent = _setup(monkeypatch)
    _drop(p, state, RES)
    p.kills = 1
    clock.t += 10 * 60
    p.tick(state)
    assert not sent


def test_zero_turns_it_off(monkeypatch):
    p, state, clock, sent = _setup(monkeypatch, initial=0)
    _drop(p, state, RES)
    clock.t += 60 * 60
    p.tick(state)
    assert not sent


def test_not_armed_while_reading_old_journals(monkeypatch):
    p, state, clock, sent = _setup(monkeypatch)
    state.in_preload = True
    _drop(p, state, RES)
    state.in_preload = False
    clock.t += 10 * 60
    p.tick(state)
    assert not sent
