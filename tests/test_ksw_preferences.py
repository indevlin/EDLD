"""tests/test_ksw_preferences.py — Session Mgmt has a preferences page in both front ends.
"""
from __future__ import annotations

import ast
import re
import os
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from components.ksw import CFG_DEFAULTS, KswPlugin  # noqa: E402

TUI_KEYS = {"Enabled", "QuitOnSLFDead", "QuitOnLowFuel", "QuitOnLowFuelPercent",
            "QuitOnLowHull", "QuitOnLowHullThreshold"}


def _plugin(**settings):
    cfg = {**CFG_DEFAULTS, **settings}
    p = KswPlugin.__new__(KswPlugin)
    p.core = SimpleNamespace(
        load_setting=lambda section, defaults, warn=True, include_extra=False: dict(cfg))
    return p


def test_tui_page_still_covers_the_six_settings():
    src = (ROOT / "tui" / "preferences.py").read_text(encoding="utf-8")
    found = set(re.findall(r'\("SessionMgmt",\s*"(\w+)"', src))
    assert found == TUI_KEYS


def test_gui_tab_is_discoverable_with_no_arguments():
    entry = _plugin().gui_preferences_tab()
    assert entry[0] == _plugin().tui_preferences_tab()[0] == "pref-tab-ksw"
    assert entry[1] == "Session Mgmt"
    assert callable(entry[2])


def test_gui_page_builds_and_records_every_setting():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication, QComboBox, QLineEdit
    from gui.preferences import PreferencesDialog

    QApplication.instance() or QApplication([])
    recorded = {}

    class Dlg:
        _bool_combo = PreferencesDialog._bool_combo
        _text_edit = PreferencesDialog._text_edit

        def _record(self, section, key, value):
            recorded[(section, key)] = value

    page = _plugin(QuitOnLowFuelPercent=25).gui_preferences_tab()[2](Dlg())
    combos = page.findChildren(QComboBox)
    edits = page.findChildren(QLineEdit)
    assert len(combos) == 4 and len(edits) == 2
    assert edits[0].text() == "25"
    for c in combos:
        c.setCurrentIndex(1)
    edits[0].setText("30")
    edits[1].setText("15")
    assert {k for (s, k) in recorded if s == "SessionMgmt"} == TUI_KEYS
    assert recorded[("SessionMgmt", "Enabled")] is True
    assert recorded[("SessionMgmt", "QuitOnLowFuelPercent")] == 30
    assert recorded[("SessionMgmt", "QuitOnLowHullThreshold")] == 15


def test_gui_builder_only_reaches_for_dialog_helpers_that_exist():
    gui_src = (ROOT / "gui" / "preferences.py").read_text(encoding="utf-8")
    tree = ast.parse((ROOT / "components" / "ksw.py").read_text(encoding="utf-8"))
    reached = {n.attr for n in ast.walk(tree)
               if isinstance(n, ast.Attribute) and isinstance(n.value, ast.Name)
               and n.value.id == "dlg"}
    assert reached
    for attr in reached:
        assert f"def {attr}" in gui_src
