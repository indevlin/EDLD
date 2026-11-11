"""
tui/block_base.py — Base class for all EDLD Textual dashboard blocks.

Every block:
  - Subclasses TuiBlock (a Textual Widget)
  - Receives the CoreAPI reference for data access
  - Implements refresh_data() called by the app on gui_queue events
  - Uses compose() to build its static widget tree once

Helper widgets:
  KVRow   — key/value display row with optional color class on value
  SepRow  — zero-height spacer (grouping without consuming a line)
  HRule   — visible one-row horizontal rule
  SecHdr  — bold section header
"""

from __future__ import annotations
from typing import TYPE_CHECKING

from textual         import events, on
from textual.app     import ComposeResult
from textual.widget  import Widget
from textual.widgets import Label, Static

if TYPE_CHECKING:
    from core.core_api import CoreAPI


# ── Helpers ───────────────────────────────────────────────────────────────────

# One definition, in core/windows, shared with the models every interface
# draws.
from core.windows import cr as _fmt_credits, health_cls as _health_cls, num as _fmt  # noqa: E402,F401


# ── Widget helpers ────────────────────────────────────────────────────────────

class KVRow(Widget):
    """Single key / value display row. Call set_value() to update."""

    DEFAULT_CSS = "KVRow { height: 1; layout: horizontal; padding: 0 1; }"

    def __init__(self, key: str, value: str = "—",
                 val_classes: str = "val", **kw) -> None:
        super().__init__(**kw)
        self._key_text  = key
        self._val_text  = value
        self._val_cls   = val_classes

    def compose(self) -> ComposeResult:
        yield Label(self._key_text, classes="key")
        yield Label(self._val_text, id=f"val-{self.id}", classes=self._val_cls)

    def set_value(self, text: str, classes: str = "val") -> None:
        try:
            lbl = self.query_one(f"#val-{self.id}", Label)
            lbl.update(text)
            lbl.set_classes(classes)
        except Exception:
            pass

    def set_key(self, text: str) -> None:
        try:
            self.query_one(".key", Label).update(text)
        except Exception:
            pass


class SepRow(Static):
    """Thin separator line."""
    DEFAULT_CSS = "SepRow { height: 0; padding: 0; }"

    def __init__(self, **kw) -> None:
        super().__init__("─" * 40, classes="sep", **kw)


class HRule(Static):
    """Visible full-width horizontal rule.

    Distinct from SepRow, which is a zero-height spacer the Commander block
    relies on for grouping without consuming a line.
    """
    DEFAULT_CSS = "HRule { height: 1; padding: 0 1; }"

    def __init__(self, width: int = 60, **kw) -> None:
        super().__init__("─" * width, classes="sep", **kw)


class SecHdr(Static):
    """Bold section header label."""
    DEFAULT_CSS = "SecHdr { height: 1; padding: 0 1; margin-top: 0; }"

    def __init__(self, title: str, **kw) -> None:
        super().__init__(title.upper(), classes="section-hdr", **kw)


class HdrRow(Widget):
    """Section header fused with its primary value on one row.

    The key is rendered in accent color (bold) on the left.
    """

    DEFAULT_CSS = "HdrRow { height: 1; layout: horizontal; padding: 0 1; }"

    def __init__(self, key: str, value: str = "", **kw) -> None:
        super().__init__(**kw)
        self._key_text = key.upper()
        self._val_text = value

    def compose(self) -> ComposeResult:
        yield Label(self._key_text, classes="hdr-key")
        yield Label(self._val_text, id=f"hdrval-{self.id}", classes=self._val_cls)

    _val_cls = "val"


class TableHdr(HdrRow):
    """A table's heading row: what each row is as a section header on the
    left, the column headings over the values in the same accent. EDAM
    draws its head rows the same way."""

    _val_cls = "val hdr-val"

    def set_value(self, text: str, classes: str = "val") -> None:
        try:
            lbl = self.query_one(f"#hdrval-{self.id}", Label)
            lbl.update(text)
            lbl.set_classes(classes)
        except Exception:
            pass


# ── TuiBlock base ─────────────────────────────────────────────────────────────

class TuiBlock(Widget):
    """
    Base class for all EDLD TUI blocks.

    Subclasses must implement:
      _compose_body() → ComposeResult  — yields body widgets
      refresh_data()                   — updates content from core

    The block title is rendered as a .block-title label automatically.
    """

    BLOCK_TITLE: str = "Block"

    def __init__(self, core: "CoreAPI", **kw) -> None:
        super().__init__(**kw)
        self.core  = core
        self.state = core.state

    def compose(self) -> ComposeResult:
        yield Label(self.BLOCK_TITLE, classes="block-title")
        yield from self._compose_body()

    def _compose_body(self) -> ComposeResult:
        return
        yield  # make it a generator

    def refresh_data(self) -> None:
        """Override to update displayed values. Called on each relevant queue event."""
        pass

    @on(events.Click)
    def _press_row(self, event: events.Click) -> None:
        """Click inside a row carrying row_action → row_action(id)."""
        w = getattr(event, "widget", None)
        while w is not None and w is not self:
            action = getattr(w, "row_action", None)
            if isinstance(action, str) and action:
                self.row_action(action)
                return
            w = w.parent

    def row_action(self, action: str) -> None:
        """A row's action (R.kv(..., action=…)). Blocks override."""

    def render_rows(self, rows) -> list:
        """Widgets for rows from core/windows: the same rows the desktop
        window and EDAM draw."""
        from textual.widgets import Label
        from core.windows import cells_text, iter_render, table_text
        out: list = []
        for kind, row, widths in iter_render(rows):
            if kind == "hdr":
                out.append(SecHdr(row[1]))
            elif kind == "kv":
                w = KVRow(row[1], row[2], val_classes=row[3] if len(row) > 3 else "val")
                if len(row) > 4 and row[4]:
                    w.row_action = row[4]  # type: ignore[attr-defined]
                out.append(w)
            elif kind == "text":
                out.append(Label(row[1], classes=row[2] if len(row) > 2 else ""))
            elif kind == "rule":
                out.append(HRule())
            elif kind == "note":
                # The indent as left padding, one cell per letter.
                indent = row[2] if len(row) > 2 else ""
                w = KVRow(row[1], "", val_classes=row[3] if len(row) > 3 else "dim")
                w.styles.padding = (0, 1, 0, 1 + len(indent))
                out.append(w)
            elif kind == "toggle":
                # The block walks up from a clicked widget to the heading
                # and reads which group it is.
                hdr = SecHdr(row[1])
                if row[2] == "system":
                    hdr.system_name = row[3]  # type: ignore[attr-defined]
                else:
                    hdr.market_id = row[3]  # type: ignore[attr-defined]
                out.append(hdr)
            elif kind == "table":
                # A heading, not a dim line: in the accent, as EDAM draws it.
                out.append(TableHdr(row[1], table_text(row[2])))
            elif kind == "cells":
                w = KVRow(row[1], cells_text(widths, row[2]),
                          val_classes=row[3] if len(row) > 3 else "val")
                if len(row) > 4 and row[4]:
                    w.row_action = row[4]  # type: ignore[attr-defined]
                out.append(w)
        return out

    # ── Convenience formatters (delegates to core) ────────────────────────────

    def fmt_credits(self, n) -> str:
        return _fmt_credits(n)

    def fmt_duration(self, s: float) -> str:
        from core.emit import fmt_duration
        return fmt_duration(int(s)) if s else "—"
