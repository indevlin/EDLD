"""
tui/blocks/objectives.py — Objectives window (Textual).

What the commander has taken on and has yet to finish: the mission board, and
colonisation construction sites awaiting deliveries.  Both are work with an
end state, which is what separates them from the running totals in the Session
window and from the ship's own contents.

    Missions        the massacre stack summarised by source faction, then
                    every other mission held, grouped by type
    Colonisation    construction sites, their outstanding requirements and
                    delivery progress

Missions previously shared the Session window and Colonisation shared Cargo.
Neither belonged there: a mission stack is not a session statistic, and a
depot's shopping list is not the hold.
"""
from __future__ import annotations

from textual.app        import ComposeResult
from textual.widgets    import Label, TabbedContent, TabPane
from textual.containers import VerticalScroll

from tui.block_base     import TuiBlock, KVRow, SecHdr


# Moved to core/windows/objectives.py; kept importable from here.
from core.windows.objectives import (  # noqa: E402,F401
    fmt_reward as _fmt_rew, strip_target_type as _strip_target_type,
)


class ObjectivesBlock(TuiBlock):
    BLOCK_TITLE = "OBJECTIVES"

    def _compose_body(self) -> ComposeResult:
        with TabbedContent(id="objectives-tabs"):
            with TabPane("Missions", id="obj-tab-missions"):
                yield VerticalScroll(id="missions-scroll")
            with TabPane("Colonisation", id="obj-tab-colon"):
                yield VerticalScroll(id="colon-scroll")

    def on_mount(self) -> None:
        # Collapse state carried over from the Colonisation window:
        # market_id -> bool and system_name -> bool (True = expanded).
        self._expanded: dict[int, bool] = {}
        self._expanded_sys: dict[str, bool] = {}

    def refresh_data(self) -> None:
        # What the window shows is core/windows/objectives.py, drawn the same
        # way in the desktop window and on EDAM.
        from core.windows import objectives as W
        self._fill("#missions-scroll", W.missions(self.core).rows)
        self._fill("#colon-scroll", W.colonisation(self.core, self._expanded,
                                                   self._expanded_sys).rows)

    def _fill(self, selector: str, rows) -> None:
        try:
            scroll = self.query_one(selector, VerticalScroll)
        except Exception:
            return
        scroll.remove_children()
        widgets = self.render_rows(rows)
        if widgets:
            scroll.mount(*widgets)

    def on_click(self, event) -> None:
        """Toggle collapse when a site or system header is clicked."""
        node = event.widget
        while node is not None:
            if isinstance(node, SecHdr):
                if hasattr(node, "market_id") and node.market_id is not None:
                    mid = node.market_id
                    self._expanded[mid] = not self._expanded.get(mid, True)
                    self.refresh_data()
                    return
                if hasattr(node, "system_name") and node.system_name is not None:
                    sn = node.system_name
                    self._expanded_sys[sn] = not self._expanded_sys.get(sn, True)
                    self.refresh_data()
                    return
            node = getattr(node, "parent", None)
