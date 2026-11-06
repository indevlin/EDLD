"""tui/blocks/commander.py — Commander window (Textual).

Info, Ranks and Wallet, then Ships, Modules, Carrier and S. Carrier. What each
shows is core/windows/commander.py, drawn the same way in the desktop window
and on a paired EDAM device; this file draws it and owns the home search.
"""
from __future__ import annotations
from textual.app     import ComposeResult
from textual.widgets import Label, TabbedContent, TabPane, Static
from textual.containers import VerticalScroll, Horizontal
from tui.block_base  import TuiBlock

# Moved to core; kept importable from here.
from core.ui_helpers import fmt_shield, hull_css, pp_rank_progress  # noqa: F401
from core.windows.ship import fmt_health as _fmt_health  # noqa: F401


class CommanderBlock(TuiBlock):
    BLOCK_TITLE = "COMMANDER"

    def compose(self) -> ComposeResult:
        yield Label("", id="cmdr-hdr1", classes="block-title")
        yield Label("", id="cmdr-hdr2", classes="block-title")
        with TabbedContent(id="cmdr-tabs"):
            with TabPane("Info", id="tab-info"):
                yield VerticalScroll(id="info-scroll")
            with TabPane("Ranks", id="tab-ranks"):
                yield VerticalScroll(id="ranks-scroll")
            # Everything about the commander — who they are, what they have
            # ranked, and what they own — behind one set of tabs.
            with TabPane("Wallet", id="tab-wallet"):
                yield VerticalScroll(id="wallet-scroll")
            with TabPane("Ships", id="tab-ships"):
                yield VerticalScroll(id="assets-ships-scroll")
            with TabPane("Modules", id="tab-modules"):
                yield VerticalScroll(id="assets-modules-scroll")
            # The carriers' panes are hidden unless one is owned: an empty
            # tab implying a carrier the commander does not own reads like a
            # bug.
            with TabPane("Carrier", id="tab-carrier"):
                yield VerticalScroll(id="assets-carrier-scroll")
            with TabPane("S. Carrier", id="tab-sqcarrier"):
                yield VerticalScroll(id="assets-sqcarrier-scroll")
        with Horizontal(id="cmdr-footer"):
            yield Static(">> Set Home System", id="cmdr-home-btn", classes="footer-lbl")
            yield Label("", id="cmdr-home-lbl", classes="dim")

    def refresh_data(self) -> None:
        from core.windows import commander as W
        hdr1, hdr2 = W.headers(self.core)
        hdr2 = hdr2.replace("[", r"\[")       # the squadron tag is not markup
        self._set_label("cmdr-hdr1", hdr1.replace("[IN", r"\[IN"))
        self._set_label("cmdr-hdr2", hdr2)
        self._fill("#info-scroll", W.info(self.core).rows)
        self._fill("#ranks-scroll", W.ranks(self.core).rows)
        self._fill("#wallet-scroll", W.wallet(self.core).rows)
        self._fill("#assets-ships-scroll", W.ships(self.core).rows)
        self._fill("#assets-modules-scroll", W.modules(self.core).rows)
        for pane_id, scroll_id, tab in (
                ("tab-carrier", "#assets-carrier-scroll", W.carrier(self.core)),
                ("tab-sqcarrier", "#assets-sqcarrier-scroll", W.squadron_carrier(self.core))):
            try:
                self.query_one(f"#{pane_id}", TabPane).display = tab is not None
            except Exception:
                pass
            if tab is not None:
                self._fill(scroll_id, tab.rows)
        home = W.home_line(self.core)[1]
        if home:
            self._set_label("cmdr-home-lbl", home)

    def _fill(self, selector: str, rows) -> None:
        try:
            scroll = self.query_one(selector, VerticalScroll)
        except Exception:
            return
        scroll.remove_children()
        widgets = self.render_rows(rows)
        if widgets:
            scroll.mount(*widgets)

    def _set_label(self, widget_id: str, text: str) -> None:
        try:
            self.query_one(f"#{widget_id}", Label).update(text)
        except Exception:
            pass

    # ── Footer: home search ───────────────────────────────────────────────────

    def on_click(self, event) -> None:
        if str(getattr(event.widget, "id", "")) != "cmdr-home-btn":
            return
        event.stop()
        cmdr_plugin = self.core._plugins.get("commander")
        spansh      = self.core._plugins.get("spansh")
        if not spansh:
            return

        def _on_select(result: dict | None) -> None:
            if not result or not cmdr_plugin:
                return
            cmdr_plugin.set_home_location(
                result.get("name", ""),
                result.get("system", ""),
                result.get("star_pos"),
            )
            name = result.get("name", "")
            try:
                self.query_one("#cmdr-home-lbl", Label).update(
                    f"→ {name}" if name else ""
                )
            except Exception:
                pass

        from tui.search_modal import SearchModal
        self.app.push_screen(SearchModal(
            title        = "Set Home Location",
            placeholder  = "System or station name…",
            search_fn    = spansh.search_home,
            result_label = lambda r: (
                f"{'🚉' if r.get('is_station') else '⭐'} {r['name']}"
                + (f"  {r.get('system', '')}" if r.get("is_station") else "")
            ),
            callback     = _on_select,
        ))
