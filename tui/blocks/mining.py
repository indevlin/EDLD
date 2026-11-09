"""tui/blocks/mining.py — Mining window (Textual).

    Ring Hotspots   hotspots with a filter; Edit › (or the row) opens
                    HotspotScreen; Add hotspot opens it blank
    Surface Sites   surface survey deposits with a filter; Edit › opens
                    DepositScreen for that deposit
"""
from __future__ import annotations

from textual            import on
from textual.app        import ComposeResult
from textual.containers import Horizontal, VerticalScroll
from textual.widgets    import Input, Static, TabbedContent, TabPane

from tui.block_base     import TuiBlock


class MiningBlock(TuiBlock):
    BLOCK_TITLE = "MINING"

    def _compose_body(self) -> ComposeResult:
        with TabbedContent(id="mining-tabs"):
            with TabPane("Ring Hotspots", id="mining-tab-hotspots"):
                yield Input(placeholder="Filter", id="hotspots-filter")
                yield VerticalScroll(id="hotspots-scroll")
                with Horizontal(classes="mining-footer"):
                    yield Static(">> Add hotspot", id="hotspot-add-btn", classes="footer-lbl")
            with TabPane("Surface Sites", id="mining-tab-sites"):
                yield Input(placeholder="Filter", id="sites-filter")
                yield VerticalScroll(id="sites-scroll")

    def on_mount(self) -> None:
        self._shown: dict[str, list] = {}

    def _plugin(self, name: str):
        return (getattr(self.core, "_plugins", None) or {}).get(name)

    def row_action(self, action: str) -> None:
        """edit:<id> → HotspotScreen or DepositScreen, by the active tab."""
        if not action.startswith("edit:"):
            return
        rid = action.split(":", 1)[1]
        if self._active() == "mining-tab-hotspots":
            self._open_hotspot(rid)
            return
        plugin = self._plugin("surface_mining")
        if plugin is not None and hasattr(plugin, "form_for"):
            from tui.deposit_screen import DepositScreen
            self.app.push_screen(DepositScreen(self.core, plugin, dep_id=rid),
                                 lambda _r=None: self._reload())

    def _open_hotspot(self, hid: str | None) -> None:
        plugin = self._plugin("ring_hotspots")
        if plugin is None:
            return
        from tui.hotspot_screen import HotspotScreen
        self.app.push_screen(HotspotScreen(self.core, plugin, hid=hid),
                             lambda _r=None: self._reload())

    def on_click(self, event) -> None:
        if str(getattr(event.widget, "id", "")) == "hotspot-add-btn":
            self._open_hotspot(None)

    def _active(self) -> str:
        try:
            return self.query_one("#mining-tabs", TabbedContent).active
        except Exception:
            return ""

    def _reload(self) -> None:
        self._shown = {}
        self.refresh_data()

    def refresh_data(self) -> None:
        """Fills the active tab only; unchanged rows are not remounted."""
        from core.windows import mining as W
        tab = self._active()
        if tab == "mining-tab-hotspots":
            self._fill("hotspots", W.hotspots)
        elif tab == "mining-tab-sites":
            self._fill("sites", W.surface_sites)

    def _fill(self, name: str, fn) -> None:
        try:
            query = self.query_one(f"#{name}-filter", Input).value
            scroll = self.query_one(f"#{name}-scroll", VerticalScroll)
        except Exception:
            return
        rows = fn(self.core, query).rows
        if rows == self._shown.get(name):
            return
        self._shown[name] = rows
        scroll.remove_children()
        widgets = self.render_rows(rows)
        if widgets:
            scroll.mount(*widgets)

    @on(Input.Changed)
    def _filter_changed(self, _event) -> None:
        self.refresh_data()

    @on(TabbedContent.TabActivated, "#mining-tabs")
    def _tab_changed(self, _event) -> None:
        self.refresh_data()
