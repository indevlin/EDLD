"""gui/blocks/mining.py — Mining window (Qt): Ring Hotspots, Surface Sites."""
from __future__ import annotations

from PySide6.QtWidgets import QTabWidget

from gui.block_base import GuiBlock


class MiningBlock(GuiBlock):
    BLOCK_TITLE = "MINING"

    def _build_body(self, layout) -> None:
        from gui.deposits_table import DepositsTable
        from gui.hotspots_table import HotspotsTable
        self._tabs = QTabWidget()
        self._tabs.setDocumentMode(True)
        self.hotspots = HotspotsTable(self.core)
        self.sites = DepositsTable(self.core)
        self._tabs.addTab(self.hotspots, "Ring Hotspots")
        self._tabs.addTab(self.sites, "Surface Sites")
        self._tabs.currentChanged.connect(lambda _i: self.refresh_data())
        layout.addWidget(self._tabs, 1)

    def refresh_data(self) -> None:
        """Reloads the visible tab only."""
        w = self._tabs.currentWidget()
        if w is not None and self.isVisible():
            w.refresh()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self.refresh_data()
