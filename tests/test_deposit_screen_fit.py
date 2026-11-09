"""tests/test_deposit_screen_fit.py — the deposit form fits a short terminal.
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

pytest.importorskip("textual")

from core.deposit_form import FIELDS  # noqa: E402


class _Plugin:
    def form_for_here(self):
        return ({f.key: "" for f in FIELDS} | {"commodity": "Rhodplumsite", "notes": "Hilly"},
                "Editing Rhodplumsite (37d47981a986)")

    def submit_form(self, raw):
        return ""


@pytest.mark.parametrize("rows", [24, 30, 40, 60])
def test_save_and_cancel_are_whole_and_on_screen(rows):
    from textual.app import App
    from tui.deposit_screen import DepositScreen
    from tui.theme import build_css
    seen = {}

    class Host(App):
        CSS = build_css("default")

        def on_mount(self):
            self.push_screen(DepositScreen(SimpleNamespace(), _Plugin()))

    async def go():
        app = Host()
        async with app.run_test(size=(110, rows)) as pilot:
            await pilot.pause(0.4)
            dialog = app.screen.query_one("#deposit-dialog").content_region
            for bid in ("#dep-save", "#dep-cancel"):
                b = app.screen.query_one(bid)
                row = b.parent.content_region
                seen[bid] = (b.region, dialog, row)
    asyncio.run(go())
    for bid, (region, dialog, row) in seen.items():
        assert region.height == 3
        # Whole: inside the button row and inside the dialog, which is on screen.
        assert row.y <= region.y and region.bottom <= row.bottom, \
            f"{bid} clipped by its row at {rows} rows: {region} in {row}"
        assert dialog.y <= region.y and region.bottom <= dialog.bottom, \
            f"{bid} cut off by the dialog at {rows} rows: {region} in {dialog}"
        assert dialog.bottom <= rows
