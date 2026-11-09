"""tests/test_engagement.py — a fighter shot down is not a fighter left behind,
and stolen cargo is not jettisoned cargo.
"""
from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core import engagement as E  # noqa: E402
from core.state import MonitorState  # noqa: E402
from components.ksw import CFG_DEFAULTS, KswPlugin  # noqa: E402
from core.config import CFG_DEFAULTS_NOTIFY  # noqa: E402


def _ev(ts, event, **kw):
    e = {"timestamp": f"2026-09-24T{ts}Z", "event": event, **kw}
    e["_logtime"] = datetime.fromisoformat(e["timestamp"])
    return e


def _ksw(state):
    p = KswPlugin.__new__(KswPlugin)
    flushed = []
    p.core = SimpleNamespace(
        state=state,
        load_setting=lambda *a, **k: {**CFG_DEFAULTS, "Enabled": True, "QuitOnSLFDead": True})
    p._session_enabled = True
    p._in_supercruise = False
    p._last_sc_exit_mono = None
    p._slf_lost_on_jump = None
    p.flush_session = lambda reason="": flushed.append(reason)
    return p, flushed


def _play(events, clock=None):
    state = MonitorState()
    state.in_preload = False
    state.pilot_mode = "Solo"
    ksw, flushed = _ksw(state)
    for e in events:
        E.note_event(state, e, e["_logtime"])
        if e["event"] in KswPlugin.SUBSCRIBED_EVENTS:
            ksw.on_event(e, state)
    return state, ksw, flushed


# ── Session management ───────────────────────────────────────────────────────

def test_lost_in_a_fight_ends_the_session():
    # 2026-06-26: attacked half a minute before the fighter went.
    _, _, flushed = _play([
        _ev("16:42:20", "UnderAttack", Target="You"),
        _ev("16:42:51", "FighterDestroyed")])
    assert flushed == ["SLF destroyed in combat"]


def test_lost_mining_as_the_ship_jumps_does_not():
    # 2026-10-25: mining, StartJump, the fighter left behind.
    _, _, flushed = _play([
        _ev("21:16:48", "EjectCargo", Type="drones", Count=4, Abandoned=False),
        _ev("21:19:34", "StartJump", JumpType="Supercruise"),
        _ev("21:19:35", "FighterDestroyed"),
        _ev("21:19:40", "SupercruiseEntry", StarSystem="X")])
    assert flushed == []


def test_out_of_range_with_no_fight_does_not():
    # 2026-06-27: nothing hostile, no jump; the fighter was simply lost.
    _, _, flushed = _play([
        _ev("10:00:14", "ShipTargeted", TargetLocked=True),
        _ev("10:01:13", "FighterDestroyed")])
    assert flushed == []


def test_escaping_a_fight_by_jumping_does_not():
    state, ksw, flushed = _play([
        _ev("05:11:56", "ShieldState", ShieldsUp=False),
        _ev("05:12:34", "HullDamage", Health=0.68, PlayerPilot=False, Fighter=True),
        _ev("05:12:34", "StartJump", JumpType="Supercruise"),
        _ev("05:12:34", "ReceiveText"),
        _ev("05:12:35", "FighterDestroyed")])
    assert flushed == [] and ksw._slf_lost_on_jump is not None
    for e in [_ev("05:12:40", "SupercruiseEntry", StarSystem="X")]:
        E.note_event(state, e, e["_logtime"])
        ksw.on_event(e, state)
    assert flushed == [] and ksw._slf_lost_on_jump is None


def test_a_jump_that_never_finishes_out_of_a_fight_does(monkeypatch):
    state, ksw, flushed = _play([
        _ev("05:12:30", "UnderAttack", Target="You"),
        _ev("05:12:34", "StartJump", JumpType="Supercruise"),
        _ev("05:12:35", "FighterDestroyed")])
    import components.ksw as K
    t0 = ksw._slf_lost_on_jump[1]
    monkeypatch.setattr(K.time, "monotonic", lambda: t0 + 5)
    ksw.tick(state)
    assert flushed == []
    monkeypatch.setattr(K.time, "monotonic", lambda: t0 + KswPlugin.JUMP_COMPLETE_S + 1)
    ksw.tick(state)
    assert flushed and "jump did not complete" in flushed[0]


def test_danger_from_status_json_counts_as_a_fight():
    state = MonitorState()
    E.note_status_flags(state, E.FLAG_IN_DANGER, "2026-09-24T05:00:01Z")
    assert E.in_combat(state, "2026-09-24T05:00:00Z")      # flag a second later
    assert E.in_combat(state, "2026-09-24T05:00:50Z")
    assert not E.in_combat(state, "2026-09-24T05:02:00Z")
    E.note_status_flags(state, 0, "2026-09-24T05:03:00Z")
    assert not E.in_combat(state, "2026-09-24T05:03:00Z")


# ── The fighter's own record, and the alerts ─────────────────────────────────

def _crew_plugin(state, emitted):
    from components.crew_slf import CrewSlfPlugin
    p = CrewSlfPlugin.__new__(CrewSlfPlugin)
    p.core = SimpleNamespace(gui_queue=None, state=state, cfg=None,
                             notify_levels={"FighterLost": 3},
                             emitter=SimpleNamespace(emit=lambda **k: emitted.append(k)))
    return p


def test_a_fighter_left_behind_is_not_counted_lost_but_is_gone():
    state = MonitorState()
    state.slf_deployed = True
    emitted = []
    p = _crew_plugin(state, emitted)
    for e in [_ev("21:19:34", "StartJump", JumpType="Supercruise"),
              _ev("21:19:34", "ReceiveText"),
              _ev("21:19:35", "FighterDestroyed")]:
        E.note_event(state, e, e["_logtime"])
        p.on_event(e, state)
    assert state.slf_deployed is False and state.slf_destroyed_count == 0
    assert emitted[-1]["loglevel"] == 1 and "left behind" in emitted[-1]["msg_term"]


def _alerts(state):
    state.in_preload = False
    from components.alerts import AlertsPlugin
    p = AlertsPlugin.__new__(AlertsPlugin)
    emitted = []
    from collections import deque
    p.alert_queue = deque(maxlen=50)
    p.core = SimpleNamespace(gui_queue=None, state=state, cfg=None,
                             notify_levels=dict(CFG_DEFAULTS_NOTIFY),
                             app_settings={},
                             emitter=SimpleNamespace(emit=lambda **k: emitted.append(k)))
    return p, emitted


def test_jettisoning_one_tonne_while_mining_is_not_theft():
    state = MonitorState()
    p, emitted = _alerts(state)
    e = _ev("21:16:32", "EjectCargo", Type="painite", Count=1, Abandoned=False)
    E.note_event(state, e, e["_logtime"])
    p.on_event(e, state)
    assert not [a for a in p.alert_queue if "stolen" in a["text"]]
    assert emitted and emitted[-1]["loglevel"] == 1
    assert emitted[-1]["msg_term"] == "Jettisoned 1 × Painite"


def test_cargo_taken_in_a_fight_is_theft():
    state = MonitorState()
    p, emitted = _alerts(state)
    for e in [_ev("21:16:20", "UnderAttack", Target="You"),
              _ev("21:16:32", "EjectCargo", Type="painite", Count=1, Abandoned=False)]:
        E.note_event(state, e, e["_logtime"])
        p.on_event(e, state)
    assert [a for a in p.alert_queue if a["text"] == "Cargo stolen! (Painite)"]


# ── Your own jettison, a pirate paid off, cargo taken ────────────────────────
#
# A limpet dump to make room was reported stolen: in a ring the game holds
# IsInDanger on while pirates scan and threaten, and that counted as a fight.

def _jettison(events, status=()):
    state = MonitorState()
    p, emitted = _alerts(state)
    for kind, *rest in sorted([("j", e["_logtime"], e) for e in events]
                              + [("s", E._utc(t), (f, g)) for t, f, g in status],
                              key=lambda x: x[1]):
        if kind == "s":
            flags, focus = rest[1]
            E.note_status_flags(state, flags, rest[0])
            E.note_gui_focus(state, focus, rest[0])
        else:
            e = rest[1]
            E.note_event(state, e, e["_logtime"])
            p.on_event(e, state)
    return p, emitted


def test_a_limpet_dump_while_pirates_scan_is_not_theft():
    # 2026-10-26: mining in a ring, danger flag on, limpets dumped from the panel.
    p, emitted = _jettison(
        [_ev("22:43:01", "EjectCargo", Type="drones", Type_Localised="Limpet",
             Count=30, Abandoned=False)],
        status=[("2026-09-24T22:42:10Z", E.FLAG_IN_DANGER, 0),
                ("2026-09-24T22:42:55Z", E.FLAG_IN_DANGER, 1),
                ("2026-09-24T22:43:03Z", E.FLAG_IN_DANGER, 0)])
    assert not [a for a in p.alert_queue if "stolen" in a["text"]]
    assert emitted[-1]["msg_term"] == "Jettisoned 30 × Limpet"


def test_the_danger_flag_alone_is_not_a_fight_for_cargo():
    # Replayed, or the panel not seen: no attack in the journal, no theft.
    p, emitted = _jettison(
        [_ev("22:56:22", "EjectCargo", Type="osmium", Count=5, Abandoned=False)],
        status=[("2026-09-24T22:56:00Z", E.FLAG_IN_DANGER, 0)])
    assert not [a for a in p.alert_queue if "stolen" in a["text"]]


def test_paying_off_a_pirate_is_not_theft():
    # 2026-10-25 00:50–00:51: Shrimpy demands 13t, fires, and is paid in gold.
    p, emitted = _jettison([
        _ev("00:50:34", "ReceiveText", Channel="npc", From_Localised="Shrimpy",
            Message="$Pirate_ThreatenUnits01:#units=13;"),
        _ev("00:51:08", "UnderAttack", Target="You"),
        _ev("00:51:20", "ReceiveText", Channel="npc", From_Localised="Shrimpy",
            Message="$Pirate_ReminderUnits01:#units=13;"),
        _ev("00:51:21", "EjectCargo", Type="gold", Count=1, Abandoned=False)])
    assert not [a for a in p.alert_queue if "stolen" in a["text"]]
    assert emitted[-1]["msg_term"] == "Jettisoned 1 × Gold for Shrimpy"
    assert emitted[-1]["loglevel"] == 2


def test_cargo_lost_while_shot_at_with_the_panel_shut_is_theft():
    p, emitted = _jettison(
        [_ev("10:00:00", "UnderAttack", Target="You"),
         _ev("10:00:20", "EjectCargo", Type="gold", Count=3, Abandoned=False)],
        status=[("2026-09-24T09:59:00Z", E.FLAG_IN_DANGER, 0)])
    assert [a for a in p.alert_queue if a["text"] == "Cargo stolen! (Gold)"]


def test_jettisoning_from_the_panel_in_a_fight_is_your_own():
    p, emitted = _jettison(
        [_ev("10:00:00", "UnderAttack", Target="You"),
         _ev("10:00:20", "EjectCargo", Type="drones", Type_Localised="Limpet",
             Count=10, Abandoned=False)],
        status=[("2026-09-24T10:00:12Z", E.FLAG_IN_DANGER, 1)])
    assert not [a for a in p.alert_queue if "stolen" in a["text"]]


def test_rocks_are_not_a_fight_for_cargo():
    # Bumping an asteroid takes hull and shields; it does not steal cargo.
    p, emitted = _jettison(
        [_ev("10:00:00", "HullDamage", Health=0.97, PlayerPilot=True, Fighter=False),
         _ev("10:00:01", "ShieldState", ShieldsUp=False),
         _ev("10:00:20", "EjectCargo", Type="drones", Count=10, Abandoned=False)])
    assert not [a for a in p.alert_queue if "stolen" in a["text"]]


def test_the_journal_path_agrees():
    # core/journal.py's own handler (no components) uses the same judgment.
    state = MonitorState()
    state.in_preload = False
    E.note_event(state, _ev("00:50:34", "ReceiveText", Channel="npc",
                            From_Localised="Shrimpy",
                            Message="$Pirate_ThreatenUnits01:#units=13;"))
    assert E.judge_jettison(state, "2026-09-24T00:51:21Z") == ("payment", "Shrimpy")
    assert E.judge_jettison(state, "2026-09-24T00:55:00Z") == ("own", "")
