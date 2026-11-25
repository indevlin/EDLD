"""gui/block_base.py — Base class and row widgets for the Qt dashboard blocks.

    KVRow    key / value row
    SecHdr   section header
    HdrRow   section header fused with its primary value
    HRule    horizontal rule
    TextRow  free-standing line of (possibly marked-up) text
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import QEvent, QObject, Qt, QTimer
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
from gui import theme as _theme
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


# ── Row groups ────────────────────────────────────────────────────────────────
#
# The rows sharing a parent are one group: with [UI] ValuePlacement "manual"
# the value column sits where ValueFromLeft and ValueFromRight put it; with
# [UI] RowStripes every other row is striped, counting from each heading.
# Arranged once per event-loop pass, after the rows have been placed.

_PENDING: dict[int, QWidget] = {}

#: Each group's last placement, by id: (parent, placement). A row joining the
#: group takes it at once, so it is never drawn at the edge first.
_PLACED: dict[int, tuple] = {}


def _schedule(parent: "QWidget | None") -> None:
    if parent is None:
        return
    if not _PENDING:
        QTimer.singleShot(0, _flush)
    _PENDING[id(parent)] = parent


def _flush() -> None:
    pending = list(_PENDING.values())
    _PENDING.clear()
    for parent in pending:
        try:
            arrange_rows(parent)
        except RuntimeError:
            pass                  # deleted before its turn came
        except Exception as exc:
            # One group's fault leaves the others arranged.
            try:
                from core import debug as _debug
                _debug.exception("row arrangement failed", exc)
            except Exception:
                pass


def _set_prop(w: QWidget, name: str, value) -> None:
    if w.property(name) != value:
        w.setProperty(name, value)
        _restyle(w)


def arrange_rows(parent: QWidget) -> None:
    """Widths and stripes for the rows directly under ``parent``."""
    lay = parent.layout()
    if lay is None:
        return
    widgets = [lay.itemAt(i).widget() for i in range(lay.count())]
    # Hidden on purpose only: a row just added is hidden until the layout
    # shows it, and is placed now so it is first drawn where it belongs.
    widgets = [w for w in widgets if w is not None
               and not (w.isHidden() and w.testAttribute(Qt.WA_WState_ExplicitShowHide))]
    rows = [w for w in widgets if isinstance(w, (KVRow, HdrRow))]

    stripes = _theme.row_stripes()
    n, last = 0, False
    for w in widgets:
        if isinstance(w, KVRow) and not isinstance(w, TableHdr):
            last = stripes and n % 2 == 1
            n += 1
            _set_prop(w, "stripe", last)
        elif isinstance(w, NoteRow):
            _set_prop(w, "stripe", last)
        elif isinstance(w, (SecHdr, HdrRow, TableHdr, HRule)):
            n, last = 0, False

    place = _placement(parent, rows)
    _PLACED[id(parent)] = (parent, place)
    for r in rows:
        r._place(place)


#: A row's sides and the gap between its label and value (KVRow's layout).
_ROW_MARGIN = 6
_ROW_GAP = 8
_EDGE = (0, 0, False, _ROW_MARGIN, False)


class _ViewportWatch(QObject):
    """Arranges a group again when the viewport it is seen in resizes: the
    body inside may be held wide by the rows themselves and not resize."""

    def __init__(self, viewport: QWidget, parent_rows: QWidget) -> None:
        super().__init__(viewport)
        self._rows = parent_rows
        viewport.installEventFilter(self)

    def eventFilter(self, obj, ev) -> bool:
        if ev.type() == QEvent.Resize:
            _schedule(self._rows)
        return False


def _natural(label: QLabel) -> int:
    """A label's own width. Not its size hint: a rich-text label lays its
    text out at the width it was last given, so a column an arrangement once
    widened would keep itself wide."""
    from PySide6.QtGui import QTextDocument
    doc = QTextDocument()
    doc.setDocumentMargin(0)
    doc.setDefaultFont(label.font())
    doc.setHtml(label.text())
    m = label.contentsMargins()
    return int(doc.idealWidth() + 0.999) + m.left() + m.right() + 2 * label.margin()


def _pane_width(parent: QWidget) -> int:
    """The width the rows are seen in: a scroll area's viewport, not the
    body inside it, which the rows themselves may have widened."""
    from PySide6.QtWidgets import QAbstractScrollArea
    w = parent
    while w is not None:
        if isinstance(w, QAbstractScrollArea):
            vp = w.viewport()
            if getattr(parent, "_viewport_watch", None) is None:
                parent._viewport_watch = _ViewportWatch(vp, parent)
            return vp.width()
        w = w.parentWidget()
    return parent.width()


def _placement(parent: QWidget, rows) -> tuple:
    """(label width, value width, values left-aligned, right margin, value
    column stretched) for a group, by [UI] ValuePlacement: at the right
    edge, or by ValueFromLeft and ValueFromRight."""
    offsets = _theme.value_offsets()
    if offsets is None or offsets == (None, None):
        _MEASURED.pop(id(parent), None)
        return _EDGE
    width = max(_pane_width(parent), 1)
    kw = max((_natural(r._key) for r in rows), default=0)
    vw = max((_natural(r._val) for r in rows), default=0)
    _MEASURED[id(parent)] = (parent, width, kw, vw)
    f = fit(width, kw, vw, _theme.offset_px(offsets[0], width),
            _theme.offset_px(offsets[1], width))
    if offsets[0] is None:
        # From the right edge: the values end there, right-aligned.
        return 0, vw, False, f.margin, False
    if offsets[1] is None:
        # From the labels' left: the values start there, left-aligned.
        return f.kmin, vw, True, f.margin, False
    # Both: the column runs between them, the values right-aligned in it.
    return f.kmin, vw, False, f.margin, True


class Fit:
    """Where a group's offsets put its value column, after correction, and
    the most each can be in it without correction."""

    __slots__ = ("kmin", "margin", "left_out", "right_out", "max_left", "max_right")

    def __init__(self, kmin, margin, left_out, right_out, max_left, max_right):
        self.kmin, self.margin = kmin, margin
        self.left_out, self.right_out = left_out, right_out
        self.max_left, self.max_right = max_left, max_right

    @property
    def corrected(self) -> bool:
        return self.left_out or self.right_out


def fit(width: int, kw: int, vw: int, left, right) -> Fit:
    """The offsets, in pixels or None, for a pane ``width`` wide whose
    longest label and value are ``kw`` and ``vw``. The right edge is firm:
    an offset that would push the values past it, or a negative one, is
    corrected, the left giving way first."""
    room = width - 2 * _ROW_MARGIN - 2 * _ROW_GAP - vw
    max_left = max(room + _ROW_GAP, 0)
    kmin, left_out = 0, False
    if left is not None:
        want = left - _ROW_GAP
        kmin = max(kw, min(max(want, 0), room))
        left_out = left < 0 or want > room
    max_right = max(room - max(kmin, kw) + _ROW_MARGIN, 0)
    margin, right_out = _ROW_MARGIN, False
    if right is not None:
        margin = max(_ROW_MARGIN, min(max(right, 0), max_right))
        right_out = right < 0 or right > max_right
    return Fit(kmin, margin, left_out, right_out, max_left, max_right)


#: The groups placed by offsets, by id: (parent, pane width, longest label,
#: longest value), for fit_report().
_MEASURED: dict[int, tuple] = {}


def fit_report(offsets=None) -> "dict | None":
    """Whether ``offsets`` (from_left, from_right) as parse_offset gives them
    — the settings in force when None — are corrected in any window now on
    screen, and the most each could be in all of them: {"windows": n,
    "corrected": n, "max_left_px", "max_left_pct", "max_right_px",
    "max_right_pct"}. None while no window is placed by offsets."""
    if offsets is None:
        offsets = _theme.value_offsets() or (None, None)
    groups = []
    for key, (parent, _w, kw, vw) in list(_MEASURED.items()):
        try:
            if not parent.isVisible():
                continue
            width = _pane_width(parent)
        except RuntimeError:
            _MEASURED.pop(key, None)
            continue
        if width > 50:
            groups.append((width, kw, vw))
    if not groups:
        return None
    out = {"windows": len(groups), "corrected": 0, "left_out": 0,
           "negative": any(o is not None and o[0] < 0 for o in offsets)}
    lefts, rights, alone = [], [], []
    for width, kw, vw in groups:
        f = fit(width, kw, vw, _theme.offset_px(offsets[0], width),
                _theme.offset_px(offsets[1], width))
        out["corrected"] += bool(f.corrected)
        out["left_out"] += bool(f.left_out)
        lefts.append((f.max_left, f.max_left * 100.0 / width))
        rights.append((f.max_right, f.max_right * 100.0 / width))
        a = fit(width, kw, vw, None, None).max_right
        alone.append((a, a * 100.0 / width))
    out["max_left_px"] = int(min(px for px, _p in lefts))
    out["max_left_pct"] = int(min(p for _px, p in lefts))
    with_left = offsets[0] is not None and not out["left_out"]
    pick = rights if with_left else alone
    out["max_right_px"] = int(min(px for px, _p in pick))
    out["max_right_pct"] = int(min(p for _px, p in pick))
    out["right_with_left"] = with_left
    return out


def fit_advice(report: "dict | None") -> str:
    """A few lines for Options: what is corrected and the safe range, or ""
    when nothing is."""
    if not report or not report["corrected"]:
        return ""
    n = report["corrected"]
    tail = ("with that left" if report.get("right_with_left")
            else "with the left blank, less as the left grows")
    text = (f"Out of bounds in {n} window{'s' if n != 1 else ''} at "
            f"{'its' if n == 1 else 'their'} present size; the values are held "
            f"inside the right edge. Safe in every window on screen now: from the "
            f"labels' left 0 to {report['max_left_px']} px or "
            f"{report['max_left_pct']}%; from the right edge 0 to "
            f"{report['max_right_px']} px or {report['max_right_pct']}%, {tail}.")
    if report.get("negative"):
        text += " Below 0 counts as 0."
    return text


def rearrange(root: QWidget) -> None:
    """Every group of rows under ``root``, and its tables' stripes, again:
    after the settings change."""
    from PySide6.QtWidgets import QTableView
    parents = {}
    for cls in (KVRow, HdrRow):
        for w in root.findChildren(cls):
            if w.parentWidget() is not None:
                parents[id(w.parentWidget())] = w.parentWidget()
    for parent in parents.values():
        arrange_rows(parent)
    for table in root.findChildren(QTableView):
        table.setAlternatingRowColors(_theme.row_stripes())


class _GroupedRow(QWidget):
    """A row that takes part in its parent's group (arrange_rows)."""

    #: The value's vertical alignment; a table's headings sit at the bottom.
    _VALIGN = Qt.AlignVCenter

    def _init_group(self, lay: QHBoxLayout) -> None:
        self.setProperty("kvrow", True)
        self.setAttribute(Qt.WA_StyledBackground, True)
        self._lay = lay
        self._placed = _EDGE
        lay.addStretch(0)

    def event(self, ev) -> bool:
        t = ev.type()
        if t == QEvent.ParentChange:
            parent = self.parentWidget()
            last = _PLACED.get(id(parent)) if parent is not None else None
            if last is not None and last[0] is parent:
                self._place(last[1])
        if t in (QEvent.ParentChange, QEvent.ShowToParent,
                 QEvent.HideToParent, QEvent.Resize):
            _schedule(self.parentWidget())
        return super().event(ev)

    def _changed(self) -> None:
        if self.parentWidget() is not None and _theme.value_offsets() is not None:
            _schedule(self.parentWidget())

    def _place(self, place: tuple) -> None:
        kmin, vmin, left, margin, stretch_val = place
        self._key.setMinimumWidth(kmin)
        self._val.setMinimumWidth(vmin)
        if place == self._placed:
            return
        self._placed = place
        edge = place == _EDGE
        self._key.setSizePolicy(QSizePolicy.Expanding if edge or not kmin
                                else QSizePolicy.Preferred, QSizePolicy.Preferred)
        self._val.setSizePolicy(QSizePolicy.Expanding if stretch_val
                                else QSizePolicy.Preferred, QSizePolicy.Preferred)
        self._val.setAlignment((Qt.AlignLeft if left else Qt.AlignRight) | self._VALIGN)
        m = self._lay.contentsMargins()
        self._lay.setContentsMargins(m.left(), m.top(), margin, m.bottom())
        key_grows = edge or not kmin
        self._lay.setStretch(0, 1 if key_grows else 0)
        self._lay.setStretch(1, 1 if stretch_val else 0)
        self._lay.setStretch(2, 0 if key_grows or stretch_val else 1)


class KVRow(_GroupedRow):
    """Single key / value row: key on the left, value right-aligned at the
    right edge, or where [UI] ValuePlacement puts it."""

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
        self._init_group(lay)

        self.set_key(key)
        self.set_value(value, val_classes)

    def set_key(self, text: str) -> None:
        self._key.setText(to_html(text, self._palette))
        self._changed()

    def set_value(self, text: str, classes: str = "val") -> None:
        self._val.setText(to_html(text, self._palette))
        _apply_classes(self._val, classes)
        self._changed()


class NoteRow(QWidget):
    """A line under a row, set in by ``indent`` drawn unseen in the label's
    own face."""

    def __init__(self, body: str = "", indent: str = "", classes: str = "dim",
                 palette: dict | None = None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._palette = palette or rgb("default")
        # Striped with the row it sits under (arrange_rows).
        self.setProperty("kvrow", True)
        self.setAttribute(Qt.WA_StyledBackground, True)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(6, 0, 6, 0)
        lay.setSpacing(0)
        self._label = QLabel()
        self._label.setProperty("role", "key")
        self._label.setTextFormat(Qt.RichText)
        self._label.setWordWrap(False)
        self._label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self._label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        lay.addWidget(self._label, 1)
        self.set_note(body, indent, classes)

    def set_note(self, body: str, indent: str = "", classes: str = "dim") -> None:
        pad = to_html(indent, self._palette) if indent else ""
        if pad:
            pad = pad.replace(" ", "&nbsp;")
            pad = f'<span style="color: transparent;">{pad}</span>'
        tone = classes_to_props(classes).get("health", "")
        colour = {"health-good": "green", "health-warn": "amber",
                  "health-crit": "red"}.get(tone)
        text = to_html(body, self._palette)
        if colour and self._palette.get(colour):
            text = f'<span style="color: {self._palette[colour]};">{text}</span>'
        self._label.setText(pad + text)


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
        self._VALIGN = Qt.AlignBottom
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


class HdrRow(_GroupedRow):
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
        self._init_group(lay)

        self._key.setText(to_html((key or "").upper(), self._palette))
        self.set_value(value)

    def set_value(self, text: str, classes: str = "val") -> None:
        self._val.setText(to_html(text, self._palette))
        _apply_classes(self._val, classes)
        self._changed()


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
        self._arrange_now()

    def add_row(self, w: QWidget) -> None:
        self._lay.insertWidget(self._lay.count() - 1, w)
        self._arrange_now()

    def _arrange_now(self) -> None:
        """Place the new rows before they are first drawn: arranged only on
        the next pass, a refresh drew them at the edge and then moved them."""
        if _theme.value_offsets() is None:
            return
        try:
            arrange_rows(self._body)
        except Exception:
            _schedule(self._body)


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
                             self._press(a) if ev.button() == Qt.LeftButton else None)

    def _press(self, action: str) -> None:
        if not self.toggle_fold(action):
            self.row_action(action)

    def toggle_fold(self, action: str) -> bool:
        """Open or close a fold (R.fold); False for any other action."""
        from core.windows import FOLD_ACTION
        if not action.startswith(FOLD_ACTION):
            return False
        folds = self.__dict__.setdefault("_open_folds", set())
        folds ^= {action[len(FOLD_ACTION):]}
        self.refresh_data()
        return True

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
        from core.windows import align_values, cells_text, iter_render, table_text, unfold
        out: list = []
        rows = unfold(rows, self.__dict__.get("_open_folds", set()))
        for kind, row, widths in iter_render(align_values(rows)):
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
            elif kind == "note":
                out.append(NoteRow(row[1], row[2] if len(row) > 2 else "",
                                   row[3] if len(row) > 3 else "dim",
                                   palette=self.palette_map))
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
