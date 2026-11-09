"""gui/block_base.py — Base class and row widgets for the Qt dashboard blocks.

    KVRow    key / value row
    SecHdr   section header
    HdrRow   section header fused with its primary value
    HRule    horizontal rule
    TextRow  free-standing line of (possibly marked-up) text
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from core.palette import rgb
from gui.markup import to_html
from gui.theme import classes_to_props

if TYPE_CHECKING:
    from core.core_api import CoreAPI


# ── Formatters ────────────────────────────────────────────────────────────────
# Identical to the TUI's.  Defined here rather than imported so the GUI does
# not depend on Textual being installed; the two are kept in step by their
# shared, small, and rarely-changing definition.

# One definition, in core/windows, shared with the models every interface
# draws.
from core.windows import cr as _fmt_credits, health_cls as _health_cls, num as _fmt  # noqa: E402,F401


def _restyle(widget: QWidget) -> None:
    """Re-run the stylesheet against a widget after its properties change."""
    style = widget.style()
    style.unpolish(widget)
    style.polish(widget)
    widget.update()


def _apply_classes(label: QLabel, classes: str) -> None:
    props = classes_to_props(classes)
    label.setProperty("role", props.get("role", "val"))
    label.setProperty("health", props.get("health", ""))
    _restyle(label)


# ── Row widgets ───────────────────────────────────────────────────────────────

class RowLabel(QLabel):
    """A label that renders Rich markup and never steals the layout's width."""

    def __init__(self, text: str = "", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._palette_map = rgb("default")
        self.setTextFormat(Qt.RichText)
        self.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.set_text(text)

    def set_palette_map(self, palette: dict) -> None:
        self._palette_map = palette

    def set_text(self, text: str) -> None:
        self.setText(to_html(text, self._palette_map))


class KVRow(QWidget):
    """Single key / value row: key on the left, value right-aligned."""

    def __init__(self, key: str = "", value: str = "—",
                 val_classes: str = "val", palette: dict | None = None,
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._palette = palette or rgb("default")

        lay = QHBoxLayout(self)
        lay.setContentsMargins(6, 0, 6, 0)
        lay.setSpacing(8)

        self._key = QLabel()
        self._key.setProperty("role", "key")
        self._key.setTextFormat(Qt.RichText)
        self._key.setWordWrap(False)
        self._key.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)

        self._val = QLabel()
        # Marks this label as a value column for the stylesheet.  Set here and
        # never touched by _apply_classes, so a value keeps its monospace face
        # through every color change.
        self._val.setProperty("col", "value")
        self._val.setTextFormat(Qt.RichText)
        self._val.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self._val.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self._val.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Preferred)

        lay.addWidget(self._key, 1)
        lay.addWidget(self._val, 0)

        self.set_key(key)
        self.set_value(value, val_classes)

    def set_key(self, text: str) -> None:
        self._key.setText(to_html(text, self._palette))

    def set_value(self, text: str, classes: str = "val") -> None:
        self._val.setText(to_html(text, self._palette))
        _apply_classes(self._val, classes)


class TableHdr(KVRow):
    """A table's heading row: what each row is, on the left, as a section
    header; the column headings over the values, in the same accent and in
    the value column's monospace face so they line up with the figures.
    EDAM draws its head rows the same way."""

    def __init__(self, key: str = "", value: str = "",
                 palette: dict | None = None, parent: QWidget | None = None) -> None:
        super().__init__(key, value, "val highlight", palette, parent)
        self._key.setProperty("role", "section")
        _restyle(self._key)
        # The section style pads its top; sit the headings on the same line.
        self._val.setAlignment(Qt.AlignRight | Qt.AlignBottom)

    def set_key(self, text: str) -> None:
        self._key.setText(to_html((text or "").upper(), self._palette))


class SecHdr(QLabel):
    """Bold, accent-coloured section header."""

    def __init__(self, title: str = "", palette: dict | None = None,
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._palette = palette or rgb("default")
        self.setProperty("role", "section")
        self.setTextFormat(Qt.RichText)
        self.setContentsMargins(6, 2, 6, 0)
        self.set_title(title)

    def set_title(self, title: str) -> None:
        # The TUI upper-cases section headers; matching that here keeps the
        # two dashboards reading identically.  Markup is left in place so a
        # header carrying color (Colonization's site rows) still renders.
        self.setText(to_html((title or "").upper(), self._palette))


class HdrRow(QWidget):
    """Section header fused with its primary value on one row."""

    def __init__(self, key: str = "", value: str = "",
                 palette: dict | None = None,
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._palette = palette or rgb("default")
        lay = QHBoxLayout(self)
        lay.setContentsMargins(6, 0, 6, 0)
        lay.setSpacing(8)

        self._key = QLabel()
        self._key.setProperty("role", "hdrkey")
        self._key.setTextFormat(Qt.RichText)
        self._val = QLabel()
        self._val.setProperty("role", "val")
        self._val.setTextFormat(Qt.RichText)
        self._val.setAlignment(Qt.AlignRight | Qt.AlignVCenter)

        lay.addWidget(self._key, 1)
        lay.addWidget(self._val, 0)

        self._key.setText(to_html((key or "").upper(), self._palette))
        self.set_value(value)

    def set_value(self, text: str, classes: str = "val") -> None:
        self._val.setText(to_html(text, self._palette))
        _apply_classes(self._val, classes)


class HRule(QFrame):
    """Visible horizontal rule."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setProperty("role", "rule")
        self.setFrameShape(QFrame.NoFrame)
        self.setFixedHeight(1)


class ClickableHdr(SecHdr):
    """A section header that toggles a collapsible group when clicked.

    Colonization renders a header per system and per construction site, each
    of which collapses.  The Qt side referenced this class but never defined
    it, so every GUI colonization render raised NameError — the window simply
    stayed empty.  The terminal side does the same job by walking up from the
    clicked widget in ``on_click``; Qt has no equivalent bubbling for plain
    labels, so the callback is carried on the header itself.

    ``system_name`` and ``market_id`` identify which group was clicked and are
    passed straight back to the callback.
    """

    def __init__(self, title: str = "", palette: dict | None = None,
                 on_click=None, *, system_name: str | None = None,
                 market_id: int | None = None,
                 parent: QWidget | None = None) -> None:
        super().__init__(title, palette, parent)
        self.system_name = system_name
        self.market_id = market_id
        self._on_click = on_click
        self.setCursor(Qt.PointingHandCursor)

    def mouseReleaseEvent(self, event) -> None:      # noqa: N802 (Qt naming)
        if self._on_click is not None and event.button() == Qt.LeftButton:
            try:
                self._on_click(system_name=self.system_name,
                               market_id=self.market_id)
            except Exception:
                pass
        super().mouseReleaseEvent(event)


class TextRow(RowLabel):
    """A free-standing line of text, optionally dimmed or marked up."""

    def __init__(self, text: str = "", classes: str = "",
                 palette: dict | None = None, wrap: bool = True,
                 parent: QWidget | None = None) -> None:
        super().__init__("", parent)
        if palette:
            self.set_palette_map(palette)
        self.setWordWrap(wrap)
        self.setContentsMargins(6, 0, 6, 0)
        self.set_text(text)
        _apply_classes(self, classes or "val")


# ── Scrolling body helper ─────────────────────────────────────────────────────

class RowScroll(QScrollArea):
    """A vertical scroll area that holds a stack of rows."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWidgetResizable(True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self._body = QWidget()
        self._lay = QVBoxLayout(self._body)
        self._lay.setContentsMargins(0, 2, 0, 2)
        self._lay.setSpacing(0)
        self._lay.addStretch(1)
        self.setWidget(self._body)

    def clear_rows(self) -> None:
        while self._lay.count() > 1:
            item = self._lay.takeAt(0)
            w = item.widget()
            if w is not None:
                w.setParent(None)
                w.deleteLater()

    def set_rows(self, rows: list[QWidget]) -> None:
        self.clear_rows()
        for i, w in enumerate(rows):
            self._lay.insertWidget(i, w)

    def add_row(self, w: QWidget) -> None:
        self._lay.insertWidget(self._lay.count() - 1, w)


# ── Block base ────────────────────────────────────────────────────────────────

class GuiBlock(QFrame):
    """Base class for every Qt dashboard block.

    Subclasses implement:

        _build_body(layout)  — construct the block's widgets once
        refresh_data()       — update them from ``self.core``

    which is the same contract ``TuiBlock`` defines, so a block's refresh
    logic reads the same in both trees.
    """

    BLOCK_TITLE: str = "Block"

    def __init__(self, core: "CoreAPI", theme: str = "default",
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.core = core
        self.state = core.state
        self.theme = theme
        self.palette_map = rgb(theme)

        self.setObjectName("block")
        self.setFrameShape(QFrame.NoFrame)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        self._title = QLabel(self.BLOCK_TITLE)
        self._title.setObjectName("blockTitle")
        outer.addWidget(self._title)

        body_host = QWidget()
        self._body_layout = QVBoxLayout(body_host)
        self._body_layout.setContentsMargins(0, 2, 0, 2)
        self._body_layout.setSpacing(0)
        outer.addWidget(body_host, 1)

        self._build_body(self._body_layout)

    # ── Construction hook ─────────────────────────────────────────────────────

    def _build_body(self, layout: QVBoxLayout) -> None:
        """Build the block's static widget tree.  Override in subclasses."""

    def refresh_data(self) -> None:
        """Update displayed values.  Override in subclasses."""

    def set_title(self, text: str) -> None:
        self._title.setText(text)

    # ── Row factories (palette pre-bound) ─────────────────────────────────────

    def kv(self, key: str, value: str = "—", classes: str = "val") -> KVRow:
        return KVRow(key, value, classes, palette=self.palette_map)

    def _make_pressable(self, w: QWidget, action: str) -> None:
        """Click on `w` calls row_action(action)."""
        w.setCursor(Qt.PointingHandCursor)
        w.mousePressEvent = (lambda ev, a=action:
                             self.row_action(a) if ev.button() == Qt.LeftButton else None)

    def row_action(self, action: str) -> None:
        """A row's action (R.kv(..., action=…)). Blocks override."""

    def hdr(self, title: str) -> SecHdr:
        return SecHdr(title, palette=self.palette_map)

    def text(self, body: str, classes: str = "", wrap: bool = True) -> TextRow:
        return TextRow(body, classes, palette=self.palette_map, wrap=wrap)

    def rule(self) -> HRule:
        return HRule()

    def scroll(self) -> RowScroll:
        return RowScroll()

    def render_rows(self, rows, on_toggle=None) -> list:
        """Widgets for rows from core/windows: the same rows the terminal
        dashboard and EDAM draw. ``on_toggle(system_name=…, market_id=…)``
        is called when a collapsible heading is clicked."""
        from core.windows import cells_text, iter_render, table_text
        out: list = []
        for kind, row, widths in iter_render(rows):
            if kind == "hdr":
                out.append(self.hdr(row[1]))
            elif kind == "kv":
                w = self.kv(row[1], row[2], row[3] if len(row) > 3 else "val")
                if len(row) > 4 and row[4]:
                    self._make_pressable(w, row[4])
                out.append(w)
            elif kind == "text":
                out.append(self.text(row[1], row[2] if len(row) > 2 else ""))
            elif kind == "rule":
                out.append(self.rule())
            elif kind == "toggle":
                key = {"system_name": row[3]} if row[2] == "system" else {"market_id": row[3]}
                out.append(ClickableHdr(row[1], self.palette_map, on_toggle, **key))
            elif kind == "table":
                # A heading, not a dim line: in the accent, as EDAM draws it.
                out.append(TableHdr(row[1], table_text(row[2]), palette=self.palette_map))
            elif kind == "cells":
                w = self.kv(row[1], cells_text(widths, row[2]),
                            row[3] if len(row) > 3 else "val")
                if len(row) > 4 and row[4]:
                    self._make_pressable(w, row[4])
                out.append(w)
        return out

    # ── Convenience formatters (mirrors TuiBlock) ─────────────────────────────

    def fmt_credits(self, n) -> str:
        return _fmt_credits(n)

    def fmt_duration(self, s: float) -> str:
        from core.emit import fmt_duration
        return fmt_duration(int(s)) if s else "—"
