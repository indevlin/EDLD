"""
tests/test_tui_prefs_pending.py — opening Options is not an edit.

Textual posts a Changed message for every Input and Select as it mounts. The
terminal Options screen recorded each as a change, so opening it put every
setting on every tab into the pending set: the restart note showed before
anything was touched, Apply wrote every value — into the active profile, where
it then shadowed the global one — and restarted EDLD because Theme was among
them. Only a value that differs from what the control opened with is a change.
"""
from __future__ import annotations

import asyncio
import queue
import sys
import tomllib
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

pytest.importorskip("textual")


def _core(tmp_path, profile=None):
    from core.config import ConfigManager, load_config_file
    from core.core_api import CoreAPI
    from core.emit import Emitter
    from core.state import MonitorState, SessionData
    cfg = tmp_path / "config.toml"
    body = (ROOT / "example.config.toml").read_text(encoding="utf-8")
    cfg.write_text(body.replace('JournalFolder = ""', f'JournalFolder = "{tmp_path}"', 1),
                   encoding="utf-8")
    mgr = ConfigManager(load_config_file(cfg), cfg, config_profile=profile)
    state = MonitorState()
    return CoreAPI(state=state, active_session=SessionData(), lifetime=SessionData(),
                   cfg_mgr=mgr, emitter=Emitter(mgr, state), gui_queue=queue.Queue(),
                   journal_dir=tmp_path, ui_mode="textual"), cfg


def _run(core, steps):
    from textual.app import App
    from tui.preferences import PreferencesScreen
    from tui.theme import build_css
    seen = {}

    class Host(App):
        CSS = build_css("default")

        def on_mount(self):
            self.push_screen(PreferencesScreen(core))

    async def go():
        app = Host()
        async with app.run_test(size=(150, 46)) as pilot:
            await pilot.pause(0.5)
            await steps(app, pilot, seen)
    asyncio.run(go())
    return seen


def test_opening_records_nothing(tmp_path):
    core, _ = _core(tmp_path)

    async def steps(app, pilot, seen):
        seen["pending"] = dict(app.screen._pending)
        seen["restart"] = app.screen._restart_required
        from textual.widgets import Label
        seen["note"] = str(app.screen.query_one("#pref-restart-note", Label).render())
    seen = _run(core, steps)
    assert seen["pending"] == {}
    assert seen["restart"] is False
    assert "Restart" not in seen["note"]


def test_a_real_edit_is_recorded_and_undoing_it_drops_it(tmp_path):
    core, _ = _core(tmp_path)

    async def steps(app, pilot, seen):
        from textual.widgets import Input
        box = app.screen.query_one("#g-truncate", Input) \
            if app.screen.query("#g-truncate") else None
        if box is None:
            box = next(i for i in app.screen.query(Input) if i.value == "30")
        box.value = "42"
        await pilot.pause(0.2)
        seen["after_edit"] = dict(app.screen._pending)
        box.value = "30"
        await pilot.pause(0.2)
        seen["after_undo"] = dict(app.screen._pending)
    seen = _run(core, steps)
    assert seen["after_edit"] == {("Settings", "TruncateNames"): 42}
    assert seen["after_undo"] == {}


def test_apply_writes_only_what_changed_into_the_profile(tmp_path):
    core, cfg = _core(tmp_path, profile="EDP1")
    before = tomllib.loads(cfg.read_text(encoding="utf-8"))["EDP1"]
    core.restart_process = lambda: (_ for _ in ()).throw(AssertionError("restarted"))

    async def steps(app, pilot, seen):
        from textual.widgets import Input
        box = next(i for i in app.screen.query(Input) if i.value == "30")
        box.value = "42"
        await pilot.pause(0.2)
        app.screen._apply_changes()
        await pilot.pause(0.2)
    _run(core, steps)
    after = tomllib.loads(cfg.read_text(encoding="utf-8"))["EDP1"]
    added = {s: {k: v for k, v in sec.items() if before.get(s, {}).get(k) != v}
             for s, sec in after.items() if isinstance(sec, dict)}
    added = {s: d for s, d in added.items() if d}
    assert added == {"Settings": {"TruncateNames": 42}}
