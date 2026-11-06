"""
tests/test_settings_spec_tabs.py — every component that describes its
settings once (core/settings_spec.py) gets the same Options tab in both
front ends, saved to the same keys.

For each: the desktop page is built and every setting it draws is recorded
under the component's section; the terminal page is composed and every
widget id it draws is one its bindings save. A setting drawn but not saved —
or saved but not drawn — is the drift the spec exists to prevent.
"""
from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.settings_spec import Action, Setting  # noqa: E402

SPEC_COMPONENTS = [
    ("components.callouts", "CalloutsPlugin"),
    ("components.backups", "BackupsPlugin"),
    ("components.edsm_gaps", "EDSMGapsPlugin"),
    ("components.automation", "AutomationPlugin"),
    ("components.navigation", "NavigationPlugin"),
]


def _plugin(mod, cls):
    import importlib
    C = getattr(importlib.import_module(mod), cls)
    p = C.__new__(C)
    p.core = SimpleNamespace(load_setting=lambda s, d, warn=False: dict(d))
    return p


@pytest.mark.parametrize("mod,cls", SPEC_COMPONENTS)
def test_gui_page_records_every_setting(mod, cls):
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication, QPushButton
    from gui.preferences import PreferencesDialog
    QApplication.instance() or QApplication([])
    recorded = {}

    class Dlg:
        _bool_combo = PreferencesDialog._bool_combo
        _text_edit = PreferencesDialog._text_edit
        _choice_pairs = PreferencesDialog._choice_pairs

        def _record(self, section, key, value):
            recorded[(section, key)] = value

    p = _plugin(mod, cls)
    tid, title, build = p.gui_preferences_tab()
    page = build(Dlg())
    assert tid == p.SETTINGS_TAB[0] and title == p.SETTINGS_TAB[1]
    buttons = [b.text() for b in page.findChildren(QPushButton)]
    assert buttons == [s.label for s in p.SETTINGS if isinstance(s, Action)]
    # Change every widget; each change must land under the component's keys.
    from PySide6.QtWidgets import QComboBox, QLineEdit
    for c in page.findChildren(QComboBox):
        c.setCurrentIndex((c.currentIndex() + 1) % max(c.count(), 1))
    for e in page.findChildren(QLineEdit):
        e.setText("7")
    keys = {s.key for s in p.SETTINGS if isinstance(s, Setting)}
    assert {k for (sec, k) in recorded if sec == p.SETTINGS_SECTION} == keys


@pytest.mark.parametrize("mod,cls", SPEC_COMPONENTS)
def test_tui_page_draws_exactly_what_it_saves(mod, cls):
    pytest.importorskip("textual")
    from textual.app import App
    from textual.widgets import Button, Input, Select

    p = _plugin(mod, cls)
    tid, title, compose = p.tui_preferences_tab()
    bindings = p.preferences_bindings()

    class Host(App):
        def compose(self):
            yield from compose()

    async def run():
        app = Host()
        async with app.run_test() as pilot:
            await pilot.pause()
            drawn = {w.id for w in app.query(Select)} | {w.id for w in app.query(Input)}
            buttons = {w.id for w in app.query(Button)}
            return drawn, buttons

    drawn, buttons = asyncio.run(run())
    assert drawn == set(bindings)
    assert all(sec == p.SETTINGS_SECTION for sec, _k, _t in bindings.values())
    for bid in buttons:
        assert p.preferences_action.__func__ is not None
        assert bid.startswith(tid)
