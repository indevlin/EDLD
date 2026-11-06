"""
gui/blocks/objectives.py — Objectives window (Qt).

What the commander has taken on and has yet to finish: the mission board, and
colonisation construction sites awaiting deliveries.  Both are work with an
end state, which is what separates them from the running totals in the Session
window and from the ship's own contents.
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QTabWidget

from gui.block_base import GuiBlock, RowScroll


# Moved to core/windows/objectives.py; kept importable from here.
from core.windows.objectives import (  # noqa: E402,F401
    fmt_reward as _fmt_rew, strip_target_type as _strip_target_type,
)


class ObjectivesBlock(GuiBlock):
    BLOCK_TITLE = "OBJECTIVES"

    def _build_body(self, layout) -> None:
        self._tabs = QTabWidget()
        self._tabs.setDocumentMode(True)

        self._missions = RowScroll()
        self._tabs.addTab(self._missions, "Missions")

        # Collapse state carried over from the Colonisation window.
        self._expanded: dict[int, bool] = {}
        self._expanded_sys: dict[str, bool] = {}
        self._colon_scroll = RowScroll()
        self._tabs.addTab(self._colon_scroll, "Colonisation")

        layout.addWidget(self._tabs, 1)

    def refresh_data(self) -> None:
        # What the window shows is core/windows/objectives.py, drawn the same
        # way in the terminal dashboard and on EDAM.
        from core.windows import objectives as W
        self._missions.set_rows(self.render_rows(W.missions(self.core).rows))
        self._refresh_colonisation()

    def _on_hdr_click(self, *, system_name=None, market_id=None) -> None:
        """Collapse or expand the group whose header was clicked.

        Qt does not bubble clicks from plain labels the way the terminal side
        walks up from the clicked widget, so ClickableHdr hands the identity
        of the group straight back here.
        """
        if market_id is not None:
            self._expanded[market_id] = not self._expanded.get(market_id, True)
        elif system_name is not None:
            self._expanded_sys[system_name] = not self._expanded_sys.get(
                system_name, True)
        else:
            return
        self._refresh_colonisation()

    def _refresh_colonisation(self) -> None:
        from core.windows import objectives as W
        tab = W.colonisation(self.core, self._expanded, self._expanded_sys)
        self._colon_scroll.set_rows(self.render_rows(tab.rows, on_toggle=self._on_hdr_click))
