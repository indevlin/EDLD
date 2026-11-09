"""tests/test_tui_select_values.py — Selects that take the preferences screen down.

Ctrl+O closed EDLD in TUI mode while the same screen opened in GUI mode.
"""
from __future__ import annotations

import ast
import asyncio
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

pytest.importorskip("textual")

from tests.test_overlay import _plugin as _survey_plugin  # noqa: E402


def _mount(compose):
    """Mount a preferences tab's widgets in a real Textual app."""
    from textual.app import App
    from textual.containers import VerticalScroll

    seen = {}

    class Host(App):
        def compose(self):
            with VerticalScroll():
                yield from compose()

    async def run():
        app = Host()
        async with app.run_test() as pilot:
            await pilot.pause()
            seen["app"] = app
            from textual.widgets import Select
            seen["selects"] = {s.id: s for s in app.query(Select)}
            from tui.widget_values import widget_text
            seen["values"] = {i: widget_text(s) for i, s in seen["selects"].items()}

    asyncio.run(run())
    return seen


def test_the_survey_tab_mounts(tmp_path, monkeypatch):
    p = _survey_plugin(tmp_path, monkeypatch)
    _id, _label, compose = p.tui_preferences_tab()
    seen = _mount(compose)
    assert "srv-rec-amount" in seen["selects"]


def test_a_blank_select_reads_as_empty_not_select_null(tmp_path, monkeypatch):
    p = _survey_plugin(tmp_path, monkeypatch)
    _id, _label, compose = p.tui_preferences_tab()
    values = _mount(compose)["values"]
    assert values["srv-rec-amount"] == ""
    assert values["srv-rec-density"] == ""


def test_no_select_anywhere_is_built_with_value_none():
    """The shape of the bug, wherever it might be written next."""
    offenders = []
    for path in list((ROOT / "components").glob("*.py")) + list((ROOT / "tui").rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if (isinstance(node, ast.Call)
                    and getattr(node.func, "id", getattr(node.func, "attr", "")) == "Select"):
                for kw in node.keywords:
                    if (kw.arg == "value" and isinstance(kw.value, ast.Constant)
                            and kw.value.value is None):
                        offenders.append(f"{path.name}:{node.lineno}")
    assert not offenders, f"Select(value=None) mounts as a crash: {offenders}"


def test_widget_text_treats_every_blank_as_empty():
    from textual.widgets import Select
    from tui.widget_values import widget_text

    class W:
        def __init__(self, v):
            self.value = v

    for blank in (None, False, Select.BLANK, Select.NULL):
        assert widget_text(W(blank)) == ""
    assert widget_text(W("High")) == "High"
    assert widget_text(W(0)) == "0"
