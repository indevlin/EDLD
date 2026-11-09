"""tui/sell_modal.py — the sell table as a modal popup.

Shows what the currently quoted market pays for each commodity, highest
first, under a heading naming that market.

Two tabs.  Mineable opens first and is the short answer to the question
actually asked on arriving with a hold full of ore: of the things that can be
dug up, what does this place pay most for.  All Items is the same table
unfiltered, for everything else being carried.

Opened and closed with Ctrl+S, and closed with Escape.
"""

from __future__ import annotations

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Label, TabbedContent, TabPane

from core.sell_table import render_columns

#: Tab ids, also used by the tests to address a pane by name.
TAB_MINEABLE = "sell-tab-mineable"
TAB_ALL = "sell-tab-all"


class SellModal(ModalScreen):
    """Two-column sell table.  Dismiss with Ctrl+S or Escape."""

    BINDINGS = [
        Binding("escape", "dismiss", "Close"),
        Binding("ctrl+s", "dismiss", "Close"),
    ]

    def __init__(self, table: dict, **kw) -> None:
        super().__init__(**kw)
        self._table = table or {}

    def compose(self) -> ComposeResult:
        label = self._table.get("source_label") or "Galactic Average"
        mineable = render_columns(self._table, mineable_only=True)
        every = render_columns(self._table)

        with Vertical(id="sell-outer"):
            yield Label(f" {label} ", id="sell-title", classes="block-title")
            yield Label("Ctrl+S or Esc to close", id="sell-hint", classes="dim")
            # Mineable is named as the initial tab rather than merely declared
            # first, so the window opens on it whatever order Textual mounts.
            with TabbedContent(initial=TAB_MINEABLE, id="sell-tabs"):
                with TabPane(f"Mineable ({len(mineable)})", id=TAB_MINEABLE):
                    yield from self._pane(mineable, "mineable", "sell-rows-mineable")
                with TabPane(f"All Items ({len(every)})", id=TAB_ALL):
                    yield from self._pane(every, "all", "sell-rows-all")

    def _pane(self, rows, kind: str, dom_id: str) -> ComposeResult:
        with VerticalScroll(id=dom_id, classes="sell-rows"):
            if not rows:
                yield Label(self._empty_text(kind), classes="dim")
            # Textual CSS has no :nth-child, so the stripe is a class applied
            # here rather than a selector in the stylesheet.
            for i, (name, price) in enumerate(rows):
                stripe = " sell-row-alt" if i % 2 else ""
                with Horizontal(classes=f"sell-row{stripe}"):
                    yield Label(name, classes="sell-name")
                    yield Label(price, classes="sell-price")

    @staticmethod
    def _empty_text(kind: str) -> str:
        if kind == "mineable":
            return "No mineable goods bought here."
        return "No prices available yet."
