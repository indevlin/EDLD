"""gui/eng_dialogs.py — the Engineering window's dialogs (Qt).

    TargetDialog    paste a link or SLEF; the build is read on a worker thread
    NewPlanDialog   the hull a planned build is for
    ShoppingDialog  trades that cover what is short, and where to make them

The Qt counterparts of tui/eng_modals.py.
"""
from __future__ import annotations

import threading
from typing import Callable, Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QComboBox, QDialog, QDialogButtonBox, QLabel, QPlainTextEdit, QPushButton,
    QVBoxLayout,
)

from gui.theme import stylesheet

from core.windows.engineering import IMPORT_HINT


def _dress(dlg: QDialog, theme: str) -> None:
    from gui.edcars import dialog_qss
    dlg.setStyleSheet(stylesheet(theme) + dialog_qss(theme))
    dlg.setWindowFlag(Qt.WindowCloseButtonHint, True)


class TargetDialog(QDialog):
    """Read a build from what is pasted. ``imported`` carries the build."""

    imported = Signal(object)
    _done = Signal(object, object, object)

    def __init__(self, parent, title: str, read: Callable[[str], tuple],
                 theme: str = "default", current: str = "") -> None:
        super().__init__(parent)
        self._read = read
        self.setWindowTitle(title)
        self.setMinimumSize(560, 320)
        _dress(self, theme)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(12, 12, 12, 12)
        lay.setSpacing(8)
        hint = QLabel(IMPORT_HINT)
        hint.setWordWrap(True)
        hint.setProperty("role", "dim")
        lay.addWidget(hint)
        self._text = QPlainTextEdit()
        self._text.setPlaceholderText("https://edsy.org/#/L=…")
        if current:
            self._text.setPlainText(current)
        lay.addWidget(self._text, 1)
        self._status = QLabel("")
        self._status.setWordWrap(True)
        self._status.setProperty("role", "dim")
        lay.addWidget(self._status)
        self._buttons = QDialogButtonBox(QDialogButtonBox.Cancel)
        self._ok = QPushButton("Import")
        self._ok.setDefault(True)
        self._buttons.addButton(self._ok, QDialogButtonBox.AcceptRole)
        self._buttons.accepted.connect(self._start)
        self._buttons.rejected.connect(self.reject)
        lay.addWidget(self._buttons)
        self._done.connect(self._finish)
        self._text.setFocus()

    def _start(self) -> None:
        text = self._text.toPlainText().strip()
        if not text:
            self._status.setText("Nothing to import.")
            return
        self._ok.setEnabled(False)
        self._status.setText("Reading the build…")

        def work():
            try:
                build, warnings = self._read(text)
                self._done.emit(build, warnings, None)
            except Exception as exc:
                self._done.emit(None, None, str(exc) or type(exc).__name__)
        threading.Thread(target=work, daemon=True, name="eng-import").start()

    def _finish(self, build, warnings, error) -> None:
        self._ok.setEnabled(True)
        if error:
            self._status.setText(error)
            return
        self.imported.emit(build)
        if warnings:
            self._status.setText("Imported, with notes:\n" + "\n".join(warnings[:6]))
            self._buttons.clear()
            close = self._buttons.addButton(QDialogButtonBox.Close)
            close.clicked.connect(self.accept)
            return
        self.accept()


class NewPlanDialog(QDialog):
    """Pick the hull a planned build is for. ``chosen`` carries its id."""

    chosen = Signal(str)

    def __init__(self, parent, types: list[tuple[str, str]], theme: str = "default") -> None:
        super().__init__(parent)
        self.setWindowTitle("New planned build")
        self.setMinimumWidth(360)
        _dress(self, theme)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(12, 12, 12, 12)
        lay.addWidget(QLabel("Which hull is the build for?"))
        self._combo = QComboBox()
        for key, name in types:
            self._combo.addItem(name, key)
        lay.addWidget(self._combo)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self._ok)
        buttons.rejected.connect(self.reject)
        lay.addWidget(buttons)

    def _ok(self) -> None:
        key = self._combo.currentData()
        if key:
            self.chosen.emit(str(key))
        self.accept()


class ShoppingDialog(QDialog):
    """The shopping list, with the nearest traders looked up on a worker
    thread and filled in when they arrive."""

    _traders = Signal(object)

    def __init__(self, parent, block, key: str, kinds: list[str],
                 find: Optional[Callable[[list], dict]], theme: str = "default") -> None:
        super().__init__(parent)
        from core.windows import engineering as EW
        from gui.block_base import RowScroll
        self._block = block
        self._key = key
        self.setWindowTitle("Shopping list")
        self.setMinimumSize(520, 460)
        _dress(self, theme)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(12, 12, 12, 12)
        self._note = QLabel("Trades are suggestions, from what you hold beyond the "
                            "build's own needs.")
        self._note.setWordWrap(True)
        self._note.setProperty("role", "dim")
        lay.addWidget(self._note)
        self._scroll = RowScroll()
        lay.addWidget(self._scroll, 1)
        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        buttons.rejected.connect(self.reject)
        buttons.accepted.connect(self.accept)
        lay.addWidget(buttons)
        self._scroll.set_rows(block.render_rows(EW.shopping(block.core, key)))
        self._traders.connect(self._show_traders)
        if kinds and find is not None:
            self._note.setText(self._note.text() + "  Finding the nearest traders…")

            def work():
                try:
                    found = find(kinds)
                except Exception:
                    found = {}
                self._traders.emit(found)
            threading.Thread(target=work, daemon=True, name="eng-traders").start()

    def _show_traders(self, found) -> None:
        from core.windows import engineering as EW
        self._note.setText("Trades are suggestions, from what you hold beyond the "
                           "build's own needs.")
        self._scroll.set_rows(self._block.render_rows(
            EW.shopping(self._block.core, self._key, found or {})))
