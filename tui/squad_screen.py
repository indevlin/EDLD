"""tui/squad_screen.py — Squad Goals in the terminal: the squadron's events and
standings (core/windows/squad.events_tab), read only.

Ctrl+U opens it while it applies (signed in to Frontier, in a squadron); Escape
or Ctrl+U closes it. Leaders run events from the desktop window.
"""
from __future__ import annotations

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Label

from tui.block_base import TuiBlock


class SquadBlock(TuiBlock):
    BLOCK_TITLE = "SQUAD GOALS · BETA"

    def _compose_body(self) -> ComposeResult:
        yield VerticalScroll(id="squad-scroll")

    def on_mount(self) -> None:
        self.refresh_data()
        self.set_interval(5, self.refresh_data)

    def refresh_data(self) -> None:
        from core.windows import squad as W
        try:
            scroll = self.query_one("#squad-scroll", VerticalScroll)
        except Exception:
            return
        scroll.remove_children()
        widgets = self.render_rows(W.events_tab(self.core).rows)
        if widgets:
            scroll.mount(*widgets)


class SquadScreen(ModalScreen):
    BINDINGS = [
        Binding("escape", "dismiss", "Close"),
        Binding("ctrl+u", "dismiss", "Close"),
    ]

    def __init__(self, core, **kw) -> None:
        super().__init__(**kw)
        self._core = core

    def compose(self) -> ComposeResult:
        with Vertical(id="squad-outer"):
            yield Label("Ctrl+U or Esc to close · leaders run events from EDLD's desktop window", classes="dim")
            yield SquadBlock(self._core, id="block-squad")
