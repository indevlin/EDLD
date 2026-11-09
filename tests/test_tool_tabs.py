"""tests/test_tool_tabs.py — the Navigation window's Survey, Nearby and
Services tabs, drawn from one description in both front ends.
"""
from __future__ import annotations

import asyncio
import os
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core import tooltab as TT  # noqa: E402
from core.state import MonitorState  # noqa: E402


def _core():
    from components.finder import FinderPlugin
    import threading
    state = MonitorState()
    state.in_preload = False
    state.pilot_system, state.pilot_star_pos = "Sol", [0.0, 0.0, 0.0]
    spansh = SimpleNamespace(systems_near=lambda coords, radius: [
        {"id64": 1, "name": "Sol", "distance": 0.0, "body_count": 1, "bodies": [{"type": "Star"}]}])
    core = SimpleNamespace(state=state, gui_queue=None, journal_dir=Path("/nonexistent"),
                           plugin_call=lambda *a, **k: None, notify_levels={},
                           load_setting=lambda s, d, warn=False: dict(d))
    finder = FinderPlugin.__new__(FinderPlugin)
    finder.core, finder._dssa, finder._dssa_at = core, [], 0.0
    finder._lock, finder.known_status = threading.Lock(), {}
    core._plugins = {"finder": finder, "spansh": spansh}
    return core


def test_the_tabs_and_their_fields():
    tabs = {t.id: t for t in TT.tabs(_core())}
    assert list(tabs) == ["survey", "nearby", "services"]
    survey = tabs["survey"]
    keys = {f.key for f in survey.fields}
    assert {"kind", "from", "systems", "station", "capital"} <= keys
    vis = {f.key for f in survey.fields if TT.visible(survey, f, {"kind": "trade"})}
    assert "station" in vis and "systems" not in vis and "radius" not in vis
    vis = {f.key for f in survey.fields if TT.visible(survey, f, {"kind": "tourist"})}
    assert "systems" in vis and "capital" not in vis


def test_tui_draws_and_runs_a_tab():
    pytest.importorskip("textual")
    from textual.app import App
    from textual.widgets import Input, Label, Select
    from tui.blocks.navigation import NavigationBlock
    from tui.theme import build_css
    core = _core()

    class Host(App):
        CSS = build_css("default")

        def compose(self):
            yield NavigationBlock(core, id="nav")

    out = {}

    async def run():
        app = Host()
        async with app.run_test(size=(120, 60)) as pilot:
            await pilot.pause()
            block = app.query_one(NavigationBlock)
            ids = {w.id for w in app.query(Input)} | {w.id for w in app.query(Select)}
            out["fields"] = {i for i in ids if i and i.startswith("nav-tool-")}
            out["station_shown"] = app.query_one("#nav-tool-survey-f-station").display
            app.query_one("#nav-tool-survey-f-kind", Select).value = "trade"
            await pilot.pause()
            out["station_after"] = app.query_one("#nav-tool-survey-f-station").display
            block._refresh_tools()
            out["from"] = app.query_one("#nav-tool-nearby-f-from", Input).value
            block._launch_tool("nearby")
            for _ in range(50):
                await pilot.pause(0.05)
                if "reported" in str(app.query_one("#nav-tool-nearby-status", Label).render()):
                    break
            out["status"] = str(app.query_one("#nav-tool-nearby-status", Label).render())

    asyncio.run(run())
    expected = {f"nav-tool-{t.id}-f-{f.key}" for t in TT.tabs(core) for f in t.fields
                if f.kind != "check"}
    assert expected <= out["fields"]
    assert out["station_shown"] is False and out["station_after"] is True
    assert out["from"] == "Sol"
    assert "1 reported within 25 ly" in out["status"]


def test_gui_draws_and_runs_a_tab():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication, QComboBox, QLineEdit
    from gui.blocks.navigation import NavigationBlock
    app = QApplication.instance() or QApplication([])
    core = _core()
    block = NavigationBlock(core)
    names = {w.objectName() for w in block.findChildren(QLineEdit)} | \
            {w.objectName() for w in block.findChildren(QComboBox)}
    assert "nav-tool-survey-f-station" in names and "nav-tool-nearby-f-radius" in names
    block._refresh_tools()
    assert block.findChild(QLineEdit, "nav-tool-nearby-f-from").text() == "Sol"
    kind = block.findChild(QComboBox, "nav-tool-survey-f-kind")
    station = block._tool_widgets["survey"]["rows"]["station"]
    assert station.isHidden()
    kind.setCurrentIndex([kind.itemData(i) for i in range(kind.count())].index("trade"))
    app.processEvents()
    assert not station.isHidden()
    done = []
    block.tool_done.connect(lambda tid, res: done.append((tid, res)))
    block._launch_tool("nearby")
    deadline = time.time() + 5
    while not done and time.time() < deadline:
        app.processEvents()
        time.sleep(0.02)
    assert done and "1 reported within 25 ly" in done[0][1].status
