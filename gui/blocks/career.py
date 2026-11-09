"""gui/blocks/career.py — Career block (Qt).

The Credits tab carries the journal-derived earnings/spending ledger.
"""

from __future__ import annotations

from PySide6.QtWidgets import QTabWidget

from gui.block_base import GuiBlock, RowScroll

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
