"""tui/blocks/ship_info.py — Ship window (Textual).

The vessel's name, then Cargo, Modules and Engineering.
"""
from __future__ import annotations

from textual.app        import ComposeResult
from textual.widgets    import Label, Static, TabbedContent, TabPane
from textual.containers import VerticalScroll, Horizontal

from tui.block_base     import TuiBlock, SecHdr
from core.ui_helpers    import cargo_cols, fmt_cargo_cr, is_limpet
from core.windows.ship  import GRADES as _TABS, fmt_health as _fmt_health

# Re-exported from core.ui_helpers; imported from here by tests.
_is_limpet  = is_limpet
_fmt_cr     = fmt_cargo_cr
_cargo_cols = cargo_cols


class ShipInfoBlock(TuiBlock):
    BLOCK_TITLE = "SHIP"

    def compose(self) -> ComposeResult:
        # One header line naming the vessel.  The focus of this window is the
        # ship, not its condition, so the identity is the whole heading.
        yield Label("", id="sh-hdr1", classes="block-title")
        yield from self._compose_body()

    def _compose_body(self) -> ComposeResult:
        with TabbedContent(id="ship-tabs"):
            # Cargo leads: it changes constantly and is checked far more often
            # than a module list that only moves when something takes damage.
            with TabPane("Cargo", id="ship-tab-cargo"):
                yield from self._compose_cargo()
            with TabPane("Modules", id="ship-tab-modules"):
                yield SecHdr("Modules", id="sh-modules-hdr")
                yield VerticalScroll(id="sh-modules")
            with TabPane("Engineering", id="ship-tab-engineering"):
                yield from self._compose_engineering()

    def _compose_cargo(self) -> ComposeResult:
        # The panel prices every row against one market, so it has to say
        # which.  theme.py has carried rules for this row all along; the row
        # itself was never mounted, and the update was wrapped in a bare
        # except, so the label simply never appeared.
        with Horizontal(id="cargo-hdr-row"):
            yield Label("Cargo", id="cargo-title", classes="block-title")
            yield Label("", id="cargo-price-src", classes="block-title")
        with VerticalScroll(id="cargo-scroll"):
            yield Label("No cargo", id="cargo-empty")
        with Horizontal(id="cargo-footer"):
            yield Static(">> Set Target", id="cargo-target-btn",
                         classes="footer-lbl")
            yield Static(">> Gal. Avg", id="cargo-galavg-btn",
                         classes="footer-lbl")
            yield Label("", id="cargo-target-lbl", classes="dim")

    def on_click(self, event) -> None:
        wid = str(getattr(event.widget, "id", ""))

        if wid == "cargo-galavg-btn":
            # One control, both effects: drop the target market and stop
            # quoting whatever station happens to be underfoot.  Clearing the
            # target alone would fall back to the docked station's prices,
            # which is not what "galactic average" means.
            event.stop()
            self.core.state.cargo_price_galactic = True
            spansh = self.core._plugins.get("spansh")
            if spansh is not None:
                spansh.clear_target()
            self._refresh_cargo()
            return

        if wid != "cargo-target-btn":
            return
        event.stop()
        spansh = self.core._plugins.get("spansh")
        if spansh is None:
            return

        def _on_select(result: dict | None) -> None:
            if not result:
                return
            name    = result.get("name", "")
            raw_rec = result.get("_rec") or result
            spansh.set_target(name, result.get("system", ""), _record=raw_rec)

        from tui.search_modal import SearchModal
        self.app.push_screen(SearchModal(
            title        = "Set Target Market",
            placeholder  = "Station name…",
            search_fn    = spansh.search,
            result_label = lambda r: (
                f"{r['name']}  {r.get('system', '')}"
            ),
            callback     = _on_select,
        ))

    def _compose_engineering(self) -> ComposeResult:
        with TabbedContent(id="eng-tabs"):
            for key, label in _TABS:
                with TabPane(label, id=f"eng-pane-{key}"):
                    yield VerticalScroll(id=f"eng-scroll-{key}")


    # ── Refresh ───────────────────────────────────────────────────────────────

    def refresh_data(self) -> None:
        # The window's content is core/windows/ship.py, drawn here as it is
        # in the desktop window and on EDAM.
        from core.windows import ship as W
        self._set_label("sh-hdr1", W.header(self.core))
        mods = W.modules(self.core)
        try:
            self.query_one("#sh-modules-hdr", SecHdr).update(mods.heading)
        except Exception:
            pass
        self._fill("#sh-modules", mods.rows)
        src, target = W.price_source(self.core)
        try:
            self.query_one("#cargo-price-src", Label).update(f" {src} ")
            self.query_one("#cargo-target-lbl", Label).update(target)
        except Exception:
            pass
        self._fill("#cargo-scroll", W.cargo(self.core).rows)
        for page in W.engineering(self.core).pages:
            self._fill(f"#eng-scroll-{page.id}", page.rows)

    def _refresh_cargo(self) -> None:
        self.refresh_data()

    def _fill(self, selector: str, rows) -> None:
        try:
            scroll = self.query_one(selector, VerticalScroll)
        except Exception:
            return
        scroll.remove_children()
        widgets = self.render_rows(rows)
        if widgets:
            scroll.mount(*widgets)

    def _set_label(self, node_id: str, text: str) -> None:
        try:
            label = self.query_one(f"#{node_id}", Label)
            label.update(text)
            label.display = bool(text)
        except Exception:
            pass
