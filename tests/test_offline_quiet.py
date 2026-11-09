"""tests/test_offline_quiet.py — once EDLD has said the commander is not in the
game, it stops talking until they are.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.state import MonitorState  # noqa: E402


def _run(tmp_path, monkeypatch, seconds: int, later_lines=()):
    """Run monitor_journal's live loop over ``seconds`` of an idle journal,
    then append ``later_lines``. Returns (state, emitted messages)."""
    from core import journal as J
    from components.commander import CommanderPlugin

    jfile = tmp_path / "Journal.2026-10-23T120000.01.log"
    jfile.write_text(json.dumps({"event": "Fileheader"}) + "\n", encoding="utf-8")
    clock = [1000.0]
    ticks = [0]
    emitted: list[str] = []
    state = MonitorState()
    cmdr = CommanderPlugin.__new__(CommanderPlugin)
    from core.state import SessionData
    cmdr.core = SimpleNamespace(state=state, gui_queue=None, _plugins={},
                                session_providers=[], active_session=SessionData(),
                                plugin_call=lambda *a, **k: None,
                                emitter=SimpleNamespace(emit=lambda **k: None))
    cmdr._star_pos_live = False

    def handle(line, st, *a, **k):
        ev = json.loads(line)
        if ev["event"] in cmdr.SUBSCRIBED_EVENTS:
            cmdr.on_event(ev, st)

    pending = list(later_lines)

    def sleep(_s):
        ticks[0] += 1
        clock[0] += 60                       # a minute per idle poll
        if ticks[0] * 60 >= seconds:
            if pending:
                with open(jfile, "a", encoding="utf-8") as f:
                    f.write(pending.pop(0) + "\n")
                return
            raise KeyboardInterrupt

    monkeypatch.setattr(J, "handle_event", handle)
    monkeypatch.setattr(J.time, "sleep", sleep)
    monkeypatch.setattr(J.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(J, "_ed_client_running", lambda d=None: False)
    for name in ("bootstrap_last_session_end", "bootstrap_missions", "bootstrap_slf",
                 "bootstrap_crew", "bootstrap_hull", "load_session_state"):
        monkeypatch.setattr(J, name, lambda *a, **k: None)
    monkeypatch.setattr(J, "find_latest_journal", lambda d: jfile)
    emitter = SimpleNamespace(post_embed=lambda e: None,
                              emit=lambda **k: emitted.append(k["msg_term"]))
    cfg = SimpleNamespace(refresh=lambda: None, notify_levels={"x": 2})
    try:
        J.monitor_journal(jfile, state, None, None, emitter, cfg, None,
                          tmp_path, [jfile], clock[0])
    except KeyboardInterrupt:
        pass
    return state, emitted


def test_not_in_game_is_said_once_and_then_output_pauses(tmp_path, monkeypatch):
    state, emitted = _run(tmp_path, monkeypatch, seconds=4 * 3600)
    offline = [m for m in emitted if m.startswith("Not in game")]
    assert len(offline) == 1, emitted
    assert "client not detected" in offline[0]
    assert state.output_suspended is True


def test_loading_into_the_game_resumes_output(tmp_path, monkeypatch):
    load = json.dumps({"event": "LoadGame", "Commander": "X", "Ship": "Mandalay"})
    state, _ = _run(tmp_path, monkeypatch, seconds=2 * 3600, later_lines=[load])
    assert state.in_game is True and state.output_suspended is False


def _emitter(state):
    from core.emit import Emitter
    cfg = SimpleNamespace(discord_cfg={"WebhookURL": ""}, app_settings={})
    em = Emitter.__new__(Emitter)
    em._cfg, em._state, em.notify_test = cfg, state, False
    em._discord_hook, em._discord_up = None, False
    em._discord_update_pending, em._update_version = False, None
    return em


def test_the_emitter_is_silent_while_paused(capsys):
    state = MonitorState()
    em = _emitter(state)
    state.output_suspended = True
    em.emit(msg_term="Quarter-hour summary", loglevel=3)
    assert capsys.readouterr().out == ""
    state.output_suspended = False
    em.emit(msg_term="Back", loglevel=2)
    assert "Back" in capsys.readouterr().out


def test_no_summary_is_attempted_while_paused(monkeypatch):
    from core import journal as J
    calls = []
    monkeypatch.setattr(J, "emit_summary", lambda *a, **k: calls.append(1))
    state = MonitorState()
    state.in_preload = False
    state.output_suspended = True
    core = SimpleNamespace(session_providers=[], _plugins={},
                           plugin_call=lambda *a, **k: None)
    J.handle_event(json.dumps({"event": "Music", "MusicTrack": "MainMenu"}) + "\n",
                   state, None, None, None, None, None, Path("."),
                   plugin_dispatch={}, core=core)
    assert calls == []
    state.output_suspended = False
    J.handle_event(json.dumps({"event": "Music", "MusicTrack": "MainMenu"}) + "\n",
                   state, None, None, None, None, None, Path("."),
                   plugin_dispatch={}, core=core)
    assert calls == [1]
