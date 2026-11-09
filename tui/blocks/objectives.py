"""tui/blocks/objectives.py — Objectives window (Textual).

    Missions        the massacre stack summarized by source faction, then
                    every other mission held, grouped by type
    Colonization    construction sites, their outstanding requirements and
                    delivery progress
    Deposits        surface survey deposits with a filter; a row opens
                    DepositScreen for that deposit
"""
from __future__ import annotations

from textual.app        import ComposeResult
from textual            import on
from textual.widgets    import Input, Label, TabbedContent, TabPane
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
            with TabPane("Colonization", id="obj-tab-colon"):
                yield VerticalScroll(id="colon-scroll")
            with TabPane("Deposits", id="obj-tab-deposits"):
                yield Input(placeholder="Filter", id="deposits-filter")
                yield VerticalScroll(id="deposits-scroll")

    def on_mount(self) -> None:
        # Collapse state carried over from the Colonization window:
        # market_id -> bool and system_name -> bool (True = expanded).
        self._expanded: dict[int, bool] = {}
        self._expanded_sys: dict[str, bool] = {}

    def row_action(self, action: str) -> None:
        """clear:<market id> → colonisation.clear_site; edit:<deposit id> →
        DepositScreen(dep_id)."""
        plugins = getattr(self.core, "_plugins", None) or {}
        if action.startswith("clear:"):
            plugin = plugins.get("colonisation")
            if plugin is not None:
                plugin.clear_site(int(action.split(":", 1)[1]))
                self.refresh_data()
        elif action.startswith("edit:"):
            plugin = plugins.get("surface_mining")
            if plugin is not None and hasattr(plugin, "form_for"):
                from tui.deposit_screen import DepositScreen
                self.app.push_screen(
                    DepositScreen(self.core, plugin, dep_id=action.split(":", 1)[1]),
                    lambda _r=None: self._reload_deposits())

    def _reload_deposits(self) -> None:
        self._deposit_rows = None
        self._refresh_deposits()

    def _deposits_visible(self) -> bool:
        try:
            return self.query_one("#objectives-tabs", TabbedContent).active == "obj-tab-deposits"
        except Exception:
            return False

    def _refresh_deposits(self) -> None:
        """Reads the survey store; only while the Deposits tab is active."""
        if not self._deposits_visible():
            return
        from core.windows import objectives as W
        try:
            query = self.query_one("#deposits-filter", Input).value
        except Exception:
            query = ""
        rows = W.deposits(self.core, query).rows
        if rows == getattr(self, "_deposit_rows", None):
            return
        self._deposit_rows = rows
        self._fill("#deposits-scroll", rows)

    @on(Input.Changed, "#deposits-filter")
    def _filter_changed(self, _event) -> None:
        self._refresh_deposits()

    @on(TabbedContent.TabActivated, "#objectives-tabs")
    def _tab_changed(self, _event) -> None:
        self._refresh_deposits()

    def refresh_data(self) -> None:
        # What the window shows is core/windows/objectives.py, drawn the same
        # way in the desktop window and on EDAM.
        from core.windows import objectives as W
        self._fill("#missions-scroll", W.missions(self.core).rows)
        self._fill("#colon-scroll", W.colonisation(self.core, self._expanded,
                                                   self._expanded_sys).rows)
        self._refresh_deposits()

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
