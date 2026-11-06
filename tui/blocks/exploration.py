"""tui/blocks/exploration.py — Exploration + Exobiology window (Textual TUI).

Shows the system the commander is currently in: honk / scan / map state, each
body's current and max-if-mapped cartographic value, high-value-mappable
highlights, and system totals — and, indented beneath any body carrying
biological signals, that body's exobiology detail.

The two used to be separate windows, which meant every body with bio signals
was listed twice: once for its cartographic value and again for its flora.
Nesting the biology under the body it belongs to removes the duplication and
keeps a body's full story in one place.

Location comes from the explo_sync component, cartographic data from
core.explo_view and biological data from core.exobio_view.
"""
from __future__ import annotations

from textual.app        import ComposeResult
from textual.widgets    import Label
from textual.containers import VerticalScroll

from tui.block_base    import TuiBlock
# Moved to core/windows/exploration.py; kept importable from here.
from core.windows.exploration import (  # noqa: F401
    abbr as _abbr, arrow as _arrow, markers as _markers, short as _fmt,
    value_range as _range,
)


class ExplorationBlock(TuiBlock):
    BLOCK_TITLE = "EXPLORATION"

    def _compose_body(self) -> ComposeResult:
        yield Label("—", id="explo-system", classes="section-hdr")
        yield Label("", id="explo-summary", classes="dim")
        yield VerticalScroll(id="explo-bodies")

    def refresh_data(self) -> None:
        # What the window shows is core/windows/exploration.py, drawn the
        # same way in the desktop window and on EDAM.
        from core.windows.exploration import view
        v = view(self.core)
        try:
            self.query_one("#explo-system", Label).update(v["title"])
            self.query_one("#explo-summary", Label).update(v["summary"])
            scroll = self.query_one("#explo-bodies", VerticalScroll)
        except Exception:
            return
        scroll.remove_children()
        widgets = self.render_rows(v["rows"])
        if widgets:
            scroll.mount(*widgets)
