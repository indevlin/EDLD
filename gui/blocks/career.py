"""
gui/blocks/career.py — Career block (Qt).

Nine tabs in fixed order — Summary, Combat, Explore, Exobio, Mining, Trade,
Credits, Carrier, PPlay.

The Summary tab is a genuine career summary: it pulls the headline figures
from every other tab into one place — wealth, combat, exploration, exobiology,
mining, trade, missions, on-foot, PowerPlay, fleet carrier, and the top earning
and spending categories — so the tab answers "how is my career going" without
tabbing through the other eight.  It is built from
``core.summary_model.career_sections()``.

That model is shared with the Session window, which renders the same sections
in the same order at session scope.  All other tabs are lifetime activity
sourced from the journal_history scan plus the most recent in-game Statistics
event.

The Credits tab carries the journal-derived earnings/spending ledger.  In-game
Statistics fields like ``Trading.Goods_Sold`` sit at zero for many commanders
even after hundreds of tonnes sold; journal events are authoritative.
"""

from __future__ import annotations

from PySide6.QtWidgets import QTabWidget

from gui.block_base import GuiBlock, RowScroll

#: Session leads: it is the tab you want at a glance mid-flight, where the
#: lifetime figures below it change on a scale of weeks.
from core.windows.career import TABS as _ALL_TABS  # noqa: E402


# Moved to core/windows/career.py; kept importable from here.
from core.windows.career import _fmt_distance, _fmt_pledged  # noqa: E402,F401


class CareerBlock(GuiBlock):
    BLOCK_TITLE = "CAREER"

    def _build_body(self, layout) -> None:
        self._tabs = QTabWidget()
        self._tabs.setDocumentMode(True)
        self._panes: dict[str, RowScroll] = {}
        for title, key in _ALL_TABS:
            scroll = RowScroll()
            self._panes[key] = scroll
            self._tabs.addTab(scroll, title)
        layout.addWidget(self._tabs, 1)

    # ── Refresh ───────────────────────────────────────────────────────────────
    #
    # What each tab shows is core/windows/career.py, drawn the same way in the
    # terminal dashboard and on EDAM.

    def refresh_data(self) -> None:
        from core.windows import career as W
        for tab in W.tabs(self.core):
            self._repopulate(tab.id, self.render_rows(tab.rows))

    def _repopulate(self, key: str, rows: list) -> None:
        scroll = self._panes.get(key)
        if scroll is None:
            return
        scroll.set_rows(rows or [self.text("—", "dim")])
