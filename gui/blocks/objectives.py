"""gui/blocks/objectives.py — Objectives window (Qt)."""
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

        # Collapse state carried over from the Colonization window.
        self._expanded: dict[int, bool] = {}
        self._expanded_sys: dict[str, bool] = {}
        self._colon_scroll = RowScroll()
        self._tabs.addTab(self._colon_scroll, "Colonization")

        layout.addWidget(self._tabs, 1)

    def row_action(self, action: str) -> None:
        """clear:<market id> → colonisation.clear_site."""
        plugin = (getattr(self.core, "_plugins", None) or {}).get("colonisation")
        if plugin is not None and action.startswith("clear:"):
            plugin.clear_site(int(action.split(":", 1)[1]))
            self.refresh_data()

    def refresh_data(self) -> None:
        # What the window shows is core/windows/objectives.py, drawn the same
        # way in the terminal dashboard and on EDAM.
        from core.windows import objectives as W
        self._missions.set_rows(self.render_rows(W.missions(self.core).rows))
        self._refresh_colonisation()

    def _on_hdr_click(self, *, system_name=None, market_id=None) -> None:
        """Collapse or expand the group whose header was clicked."""
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
