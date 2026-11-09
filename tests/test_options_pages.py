"""tests/test_options_pages.py — Options picks its pages from a column down the
left, in both front ends.
"""
from __future__ import annotations

import asyncio
import os
import queue
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

CORE = ["General", "Notifications", "Discord", "Appearance", "Data", "Display"]

# Loaded in this order, which is not the alphabetical one: the column sorts.
SPEC = [("components.navigation", "NavigationPlugin"),      # Routes
        ("components.callouts", "CalloutsPlugin"),           # Callouts
        ("components.edsm_gaps", "EDSMGapsPlugin"),          # EDSM Log
        ("components.backups", "BackupsPlugin")]             # Backups
EXTRA = ["Backups", "Callouts", "EDSM Log", "Routes"]


def _core(tmp_path):
    import importlib
    from core.config import ConfigManager, load_config_file
    from core.core_api import CoreAPI
    from core.emit import Emitter
    from core.state import MonitorState, SessionData
    cfg = tmp_path / "config.toml"
    body = (ROOT / "example.config.toml").read_text(encoding="utf-8")
    cfg.write_text(body.replace('JournalFolder = ""', f'JournalFolder = "{tmp_path}"', 1),
                   encoding="utf-8")
    mgr = ConfigManager(load_config_file(cfg), cfg, config_profile=None)
    state = MonitorState()
    core = CoreAPI(state=state, active_session=SessionData(), lifetime=SessionData(),
                   cfg_mgr=mgr, emitter=Emitter(mgr, state), gui_queue=queue.Queue(),
                   journal_dir=tmp_path, ui_mode="textual")
    plugins = {}
    for mod, cls in SPEC:
        C = getattr(importlib.import_module(mod), cls)
        p = C.__new__(C)
        p.core = SimpleNamespace(load_setting=lambda s, d, warn=False: dict(d))
        plugins[cls] = p
    core._plugins = plugins
    return core


# ── Desktop window ────────────────────────────────────────────────────────────

@pytest.fixture
def qt():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def _dialog(tmp_path, edcars=False):
    from gui.preferences import PreferencesDialog
    return PreferencesDialog(_core(tmp_path), theme="default", edcars=edcars)


@pytest.mark.parametrize("edcars", [False, True])
def test_gui_pages_are_a_column_not_tabs(qt, tmp_path, edcars):
    from PySide6.QtWidgets import QPushButton, QTabBar, QTabWidget
    dlg = _dialog(tmp_path, edcars)
    assert dlg.page_labels() == CORE + EXTRA
    assert not dlg.findChildren(QTabWidget) and not dlg.findChildren(QTabBar)
    pills = [b for b in dlg.findChildren(QPushButton) if b.objectName() in ("prefPill", "edcarsPill")]
    want = [p.upper() for p in CORE + EXTRA] if edcars else CORE + EXTRA
    assert [b.text() for b in pills] == want
    for i, b in enumerate(pills):
        b.click()
        assert dlg._pages.currentIndex() == i and b.isChecked()
        assert dlg.current_page() == (CORE + EXTRA)[i]


@pytest.mark.parametrize("edcars", [False, True])
def test_gui_every_selector_fits_at_the_smallest_size(qt, tmp_path, edcars):
    from PySide6.QtWidgets import QApplication, QPushButton, QWidget
    dlg = _dialog(tmp_path, edcars)
    dlg.show()
    dlg.resize(dlg.minimumSize())
    QApplication.processEvents()
    nav = dlg.findChild(QWidget, "prefNav")
    pills = [b for b in dlg.findChildren(QPushButton) if b.objectName() in ("prefPill", "edcarsPill")]
    for b in pills:
        assert b.isVisible() and b.height() >= b.sizeHint().height() - 1
        assert b.geometry().bottom() <= nav.height()
    dlg.close()


def test_gui_keys_move_between_pages(qt, tmp_path):
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    dlg = _dialog(tmp_path)
    dlg.show()
    dlg._step(1)
    assert dlg.current_page() == "Notifications"
    dlg._step(-2)
    assert dlg.current_page() == EXTRA[-1]          # wraps
    # The shortcuts themselves: an offscreen window is never the active one,
    # so a key press would not reach a window shortcut.
    from PySide6.QtGui import QShortcut
    keys = {s.key().toString(): s for s in dlg.findChildren(QShortcut)}
    assert {"Ctrl+PgDown", "Ctrl+PgUp", "Ctrl+Tab", "Ctrl+Shift+Tab"} <= set(keys)
    keys["Ctrl+PgDown"].activated.emit()
    assert dlg.current_page() == "General"
    keys["Ctrl+Shift+Tab"].activated.emit()
    assert dlg.current_page() == EXTRA[-1]
    keys["Ctrl+Tab"].activated.emit()
    assert dlg.current_page() == "General"
    # Down on a focused selector opens the next page, as on the rail.
    pill = dlg._nav.button(0)
    pill.setFocus()
    QTest.keyClick(pill, Qt.Key_Down)
    assert dlg.current_page() == "Notifications"
    dlg.show_page("Data")
    assert dlg.current_page() == "Data"
    dlg.close()


def test_gui_edcars_skin_survives_a_theme_preview(qt, tmp_path):
    from gui.edcars import _RailFill
    from gui.preferences import EDCARS_SKIN
    dlg = _dialog(tmp_path, edcars=True)
    assert dlg.objectName() == EDCARS_SKIN
    assert len(dlg.findChildren(_RailFill)) == 1
    dlg._restyle("default-blue")
    css = dlg.styleSheet()
    assert f"#{EDCARS_SKIN} QPushButton#edcarsPill" in css
    from gui.edcars import Ink
    assert dlg.findChildren(_RailFill)[0].ink.accent == Ink("default-blue").accent
    plain = _dialog(tmp_path)
    assert plain.objectName() != EDCARS_SKIN and not plain.findChildren(_RailFill)
    assert "QPushButton#prefPill" in plain.styleSheet()


def test_gui_preview_keeps_the_column_styled():
    """The Appearance page's live preview used to set the bare theme sheet,
    which would drop the column's rules."""
    src = (ROOT / "gui" / "preferences.py").read_text(encoding="utf-8")
    assert "self.setStyleSheet(stylesheet(val))" not in src
    assert "self._restyle(val)" in src


# ── Terminal dashboard ────────────────────────────────────────────────────────

def _run_tui(core, steps, size=(120, 30)):
    pytest.importorskip("textual")
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
        async with app.run_test(size=size) as pilot:
            await pilot.pause(0.5)
            await steps(app, pilot, seen)

    asyncio.run(go())
    return seen


def test_tui_pages_are_a_column_in_the_desktop_order(tmp_path):
    pytest.importorskip("textual")
    from textual.widgets import ContentSwitcher, OptionList, Tabs

    async def steps(app, pilot, seen):
        scr = app.screen
        nav = scr.query_one("#pref-nav", OptionList)
        seen["labels"] = scr.page_labels()
        seen["options"] = [str(nav.get_option_at_index(i).prompt)
                           for i in range(nav.option_count)]
        sw = scr.query_one("#pref-pages", ContentSwitcher)
        seen["ids"] = [c.id for c in sw.children]
        seen["tabs"] = len(scr.query(Tabs))
        seen["nav_h"] = nav.size.height
        seen["focus"] = app.focused is nav

    seen = _run_tui(_core(tmp_path), steps)
    assert seen["labels"] == seen["options"] == CORE + EXTRA
    assert seen["tabs"] == 0
    assert set(seen["ids"]) >= {"pref-tab-general", "pref-tab-display", "pref-tab-routes"}
    # Every page's name is on screen at once in a 30-row terminal.
    assert seen["nav_h"] >= len(CORE + EXTRA)
    assert seen["focus"]


def test_tui_keys_move_between_pages(tmp_path):
    pytest.importorskip("textual")

    async def steps(app, pilot, seen):
        scr = app.screen
        await pilot.press("down")
        await pilot.pause(0.1)
        seen["down"] = scr.current_page()
        await pilot.press("ctrl+pagedown")
        await pilot.pause(0.1)
        seen["next"] = scr.current_page()
        await pilot.press("ctrl+pageup", "ctrl+pageup", "ctrl+pageup")
        await pilot.pause(0.1)
        seen["wrap"] = scr.current_page()
        scr.show_page("Routes")
        await pilot.pause(0.1)
        seen["named"] = scr.current_page()
        seen["hl"] = scr.query_one("#pref-nav").highlighted

    seen = _run_tui(_core(tmp_path), steps)
    assert seen["down"] == "Notifications"
    assert seen["next"] == "Discord"
    assert seen["wrap"] == EXTRA[-1]
    assert seen["named"] == "Routes"
    assert seen["hl"] == (CORE + EXTRA).index("Routes")


def test_tui_opening_options_still_records_nothing(tmp_path):
    """Switching pages mounts nothing new, so it is not an edit either."""
    pytest.importorskip("textual")

    async def steps(app, pilot, seen):
        scr = app.screen
        for lab in scr.page_labels():
            scr.show_page(lab)
            await pilot.pause(0.05)
        seen["pending"] = dict(scr._pending)

    assert _run_tui(_core(tmp_path), steps)["pending"] == {}
