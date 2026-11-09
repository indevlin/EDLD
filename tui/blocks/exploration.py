"""tui/blocks/exploration.py — Exploration + Exobiology window (Textual TUI).
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
