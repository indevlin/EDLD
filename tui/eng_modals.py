"""tui/eng_modals.py — the Engineering window's dialogs (Textual).

    TargetModal    paste a link or SLEF; the build is read on a worker thread
    NewPlanModal   the hull a planned build is for
    ShoppingModal  trades that cover what is short, and where to make them

The terminal counterparts of gui/eng_dialogs.py.
"""
from __future__ import annotations

import threading
from typing import Callable, Optional

from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Button, Label, Select, TextArea

from core.windows.engineering import IMPORT_HINT


class TargetModal(ModalScreen):
    """Read a build from what is pasted; ``on_build(build)`` on success."""

    BINDINGS = [Binding("escape", "dismiss", "Cancel")]

    def __init__(self, title: str, read: Callable[[str], tuple],
                 on_build: Callable[[dict], None], current: str = "", **kw) -> None:
        super().__init__(**kw)
        self._title = title
        self._read = read
        self._on_build = on_build
        self._current = current
        self._busy = False

    def compose(self) -> ComposeResult:
        with Vertical(id="eng-modal-outer"):
            yield Label(f" {self._title} ", classes="block-title")
            yield Label(IMPORT_HINT, classes="dim eng-modal-hint")
            yield TextArea(self._current, id="eng-import-text")
            yield Label("", id="eng-import-status", classes="dim")
            with Horizontal(classes="eng-modal-buttons"):
                yield Button("Import", id="eng-import-ok", variant="primary")
                yield Button("Close", id="eng-import-cancel")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        bid = event.button.id
        event.stop()
        if bid == "eng-import-cancel":
            self.dismiss()
        elif bid == "eng-import-ok" and not self._busy:
            text = self.query_one("#eng-import-text", TextArea).text.strip()
            if not text:
                self._status("Nothing to import.")
                return
            self._busy = True
            self._status("Reading the build…")
            threading.Thread(target=self._work, args=(text,), daemon=True,
                             name="eng-import").start()

    def _work(self, text: str) -> None:
        try:
            build, warnings = self._read(text)
            self.app.call_from_thread(self._done, build, warnings, None)
        except Exception as exc:
            self.app.call_from_thread(self._done, None, None, str(exc) or type(exc).__name__)

    def _done(self, build, warnings, error) -> None:
        self._busy = False
        if error:
            self._status(Text(error))
            return
        self._on_build(build)
        if warnings:
            self._status(Text("Imported, with notes:\n" + "\n".join(warnings[:6])))
            return
        self.dismiss()

    def _status(self, text) -> None:
        try:
            self.query_one("#eng-import-status", Label).update(text)
        except Exception:
            pass


class NewPlanModal(ModalScreen):
    """Pick the hull a planned build is for; ``on_choice(ship id)``."""

    BINDINGS = [Binding("escape", "dismiss", "Cancel")]

    def __init__(self, types: list[tuple[str, str]], on_choice: Callable[[str], None],
                 **kw) -> None:
        super().__init__(**kw)
        self._types = types
        self._on_choice = on_choice

    def compose(self) -> ComposeResult:
        with Vertical(id="eng-modal-outer", classes="eng-modal-small"):
            yield Label(" New planned build ", classes="block-title")
            yield Label("Which hull is the build for?", classes="dim")
            yield Select([(Text(name), key) for key, name in self._types],
                         id="eng-plan-type", prompt="Hull")
            with Horizontal(classes="eng-modal-buttons"):
                yield Button("OK", id="eng-plan-ok", variant="primary")
                yield Button("Cancel", id="eng-plan-cancel")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        event.stop()
        if event.button.id == "eng-plan-ok":
            value = self.query_one("#eng-plan-type", Select).value
            if isinstance(value, str):
                self.dismiss()
                self._on_choice(value)
                return
        self.dismiss()


class ShoppingModal(ModalScreen):
    """The shopping list, the nearest traders filled in when they arrive."""

    BINDINGS = [Binding("escape", "dismiss", "Close")]

    def __init__(self, block, key: str, kinds: list[str],
                 find: Optional[Callable[[list], dict]], **kw) -> None:
        super().__init__(**kw)
        self._block = block
        self._key = key
        self._kinds = kinds
        self._find = find

    def compose(self) -> ComposeResult:
        with Vertical(id="eng-modal-outer"):
            yield Label(" Shopping list ", classes="block-title")
            yield Label("Trades are suggestions, from what you hold beyond the build's "
                        "own needs.", id="eng-shop-note", classes="dim")
            yield VerticalScroll(id="eng-shop-rows")
            with Horizontal(classes="eng-modal-buttons"):
                yield Button("Close", id="eng-shop-close")

    def on_mount(self) -> None:
        from core.windows import engineering as EW
        self._show(EW.shopping(self._block.core, self._key))
        if self._kinds and self._find is not None:
            self._note("Finding the nearest traders…")
            threading.Thread(target=self._work, daemon=True, name="eng-traders").start()

    def _work(self) -> None:
        try:
            found = self._find(self._kinds)
        except Exception:
            found = {}
        self.app.call_from_thread(self._traders, found)

    def _traders(self, found) -> None:
        from core.windows import engineering as EW
        self._note("Trades are suggestions, from what you hold beyond the build's own needs.")
        self._show(EW.shopping(self._block.core, self._key, found or {}))

    def _show(self, rows) -> None:
        try:
            scroll = self.query_one("#eng-shop-rows", VerticalScroll)
        except Exception:
            return
        scroll.remove_children()
        widgets = self._block.render_rows(rows)
        if widgets:
            scroll.mount(*widgets)

    def _note(self, text: str) -> None:
        try:
            self.query_one("#eng-shop-note", Label).update(text)
        except Exception:
            pass

    def on_button_pressed(self, event: Button.Pressed) -> None:
        event.stop()
        self.dismiss()
