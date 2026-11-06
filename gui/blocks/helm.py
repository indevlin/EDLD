"""
gui/blocks/helm.py — the Helm panel (Qt): the game's controls and EDLD's
automation as buttons.

What is in it, in which group and in what order is core/helm.py; whether each
button can be pressed, and why not, is the automation component's
``helm_view``. This only lays it out and passes a click on.

The groups sit side by side as many as fit, then wrap, evened out so six
groups that need two rows go three and three rather than five and one; each
group's buttons fill its width in as many columns as fit. So the same panel is one low strip along the foot of
the Dashboard and a block of large buttons in EDCARS's Helm section, without
either being laid out by hand. ``compact`` picks the strip's sizes.

A click takes the focus from the game, so the press brings the game to the
front first (core/keys.focus_game), on a thread of its own; the outcome comes
back on the status line.
"""
from __future__ import annotations

from math import ceil

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QGridLayout, QLabel, QPushButton, QSizePolicy, QVBoxLayout, QWidget,
)

from core import helm as H
from gui.block_base import GuiBlock


def balanced_columns(width: float, min_width: float, n: int) -> int:
    """Groups per row: as many as fit (core.helm.columns_for), then evened
    out over the rows that makes — six groups three and three rather than
    five and one."""
    cols = H.columns_for(width, min_width, n)
    rows = ceil(n / cols) if n else 1
    return max(1, ceil(n / rows)) if n else 1


class _GroupBox(QWidget):
    """One group: its name, and its buttons in a grid."""

    def __init__(self, label: str, compact: bool) -> None:
        super().__init__()
        self.setObjectName("helmGroup")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(3 if compact else 6)
        self.title = QLabel(label.upper())
        self.title.setObjectName("helmGroupTitle")
        lay.addWidget(self.title)
        self.grid = QGridLayout()
        self.grid.setContentsMargins(0, 0, 0, 0)
        self.grid.setHorizontalSpacing(4 if compact else 6)
        self.grid.setVerticalSpacing(4 if compact else 6)
        lay.addLayout(self.grid)
        lay.addStretch(1)
        self.buttons: list[QPushButton] = []
        self._cols = 0

    def place(self, cols: int) -> None:
        if cols == self._cols:
            return
        self._cols = cols
        for b in self.buttons:
            self.grid.removeWidget(b)
        for i, b in enumerate(self.buttons):
            self.grid.addWidget(b, i // cols, i % cols)
        for c in range(max(cols, self.grid.columnCount())):
            self.grid.setColumnStretch(c, 1 if c < cols else 0)


class _Host(QWidget):
    def __init__(self, on_resize) -> None:
        super().__init__()
        self._on_resize = on_resize

    def resizeEvent(self, event) -> None:          # noqa: N802 (Qt naming)
        super().resizeEvent(event)
        self._on_resize()


class HelmBlock(GuiBlock):
    BLOCK_TITLE = "HELM"

    #: (narrowest group, narrowest button, button height) for the strip along
    #: the Dashboard's foot, and for EDCARS's section.
    COMPACT = (190, 92, 26)
    LARGE = (330, 140, 48)
    #: The tallest a button grows to fill EDCARS's section.
    TALLEST = 96

    def __init__(self, core, theme: str = "default", parent=None,
                 compact: bool = False) -> None:
        self._compact = bool(compact)
        super().__init__(core, theme=theme, parent=parent)
        self.setObjectName("helmBlock")

    # ── Construction ──────────────────────────────────────────────────────────

    def _build_body(self, layout) -> None:
        self._sizes = self.COMPACT if self._compact else self.LARGE
        self._note = QLabel("")
        self._note.setObjectName("helmNote")
        self._note.setWordWrap(True)
        self._note.setVisible(False)
        layout.addWidget(self._note)

        # Laid out again whenever the host itself is resized: the block's
        # own resize comes before the host has its new width.
        self._host = _Host(self._arrange)
        self._grid = QGridLayout(self._host)
        m = 4 if self._compact else 8
        self._grid.setContentsMargins(m, m, m, 2)
        self._grid.setHorizontalSpacing(14 if self._compact else 24)
        self._grid.setVerticalSpacing(8 if self._compact else 18)
        # In EDCARS the panel has the section to itself, and its buttons
        # grow to fill the height (up to TALLEST) rather than leave the lower
        # half empty.
        layout.addWidget(self._host, 0 if self._compact else 1)

        self._status = QLabel("")
        self._status.setObjectName("helmStatus")
        self._status.setTextFormat(Qt.PlainText)
        self._status.setContentsMargins(m, 2, m, 2)
        layout.addWidget(self._status)

        self._groups: dict[str, _GroupBox] = {}
        self._buttons: dict[str, QPushButton] = {}
        self._per_row = 0
        self._layout: tuple = ()
        self._button_h = 0
        self._sig: tuple = ()
        self._button_font = None
        self._title_font = None

    def set_fonts(self, button, title) -> None:
        """The caps EDCARS draws in, without kerning (gui/edcars.caps_font):
        a style sheet cannot turn kerning off."""
        self._button_font, self._title_font = button, title
        for btn in self._buttons.values():
            btn.setFont(button)
        for box in self._groups.values():
            box.title.setFont(title)

    def _make_groups(self, view: H.View) -> None:
        sig = tuple((g.id, tuple(b.id for b in g.buttons)) for g in view.groups)
        if sig == self._sig:
            return
        self._sig = sig
        for box in self._groups.values():
            self._grid.removeWidget(box)
            box.setParent(None)
        self._groups.clear()
        self._buttons.clear()
        _w, _bw, bh = self._sizes
        for g in view.groups:
            box = _GroupBox(g.label, self._compact)
            if self._title_font is not None:
                box.title.setFont(self._title_font)
            for b in g.buttons:
                btn = QPushButton(b.label.upper() if self._button_font else b.label)
                if self._button_font is not None:
                    btn.setFont(self._button_font)
                btn.setProperty("role", "helm")
                btn.setFixedHeight(bh)
                btn.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
                btn.setCursor(Qt.PointingHandCursor)
                btn.clicked.connect(lambda _c=False, cid=b.id: self._press(cid))
                box.buttons.append(btn)
                self._buttons[b.id] = btn
            self._groups[g.id] = box
        self._per_row = 0
        self._layout = ()
        self._button_h = 0
        self._arrange()

    # ── Layout ────────────────────────────────────────────────────────────────

    def _arrange(self) -> None:
        if not getattr(self, "_groups", None):
            return
        gw, bw, _bh = self._sizes
        width = max(1, self._host.width())
        boxes = list(self._groups.values())
        n = len(boxes)
        # The strip: every group in one row, two rows of buttons, each group
        # as wide as its buttons need — when the window is wide enough.
        two_rows = [ceil(len(b.buttons) / 2) for b in boxes]
        if self._compact and (sum(two_rows) * bw
                              + self._grid.horizontalSpacing() * (n - 1)) <= width:
            per_row, cols_of, weight = n, two_rows, two_rows
        else:
            per_row = balanced_columns(width, gw, n)
            cols = max(1, int((width / per_row) // bw))
            cols_of = [min(cols, max(1, len(b.buttons))) for b in boxes]
            weight = [1] * n
        layout = (per_row, tuple(cols_of))
        changed = layout != self._layout
        self._layout = layout
        self._per_row = per_row
        for box, cols in zip(boxes, cols_of):
            box.place(cols)
        if changed:
            for i, box in enumerate(boxes):
                self._grid.removeWidget(box)
                self._grid.addWidget(box, i // per_row, i % per_row, Qt.AlignTop)
            stretch = (weight if per_row == n else [1] * per_row)
            for c in range(max(per_row, self._grid.columnCount())):
                self._grid.setColumnStretch(c, stretch[c] if c < per_row else 0)
            # What the buttons leave goes below them, not between the rows.
            rows = ceil(n / per_row)
            for r in range(max(rows + 1, self._grid.rowCount())):
                self._grid.setRowStretch(r, 1 if r == rows else 0)
        self._fit_height(per_row)

    def _fit_height(self, per_row: int) -> None:
        """EDCARS: the buttons as tall as the section allows, so the panel
        fills it rather than the top of it."""
        _gw, _bw, least = self._sizes
        height = least
        if not self._compact:
            boxes = list(self._groups.values())
            rows = [boxes[i:i + per_row] for i in range(0, len(boxes), per_row)]
            button_rows = [max(ceil(len(b.buttons) / max(1, b._cols)) for b in row)
                           for row in rows]
            title = max(b.title.sizeHint().height() for b in boxes)
            m = self._grid.contentsMargins()
            spare = (self._host.height() - m.top() - m.bottom()
                     - self._grid.verticalSpacing() * (len(rows) - 1)
                     - len(rows) * (title + 6)
                     - 6 * sum(n - 1 for n in button_rows))
            height = max(least, min(self.TALLEST, int(spare / max(1, sum(button_rows)))))
        if height != self._button_h:
            self._button_h = height
            for btn in self._buttons.values():
                btn.setFixedHeight(height)

    # ── Refresh ───────────────────────────────────────────────────────────────

    def _plugin(self):
        return (getattr(self.core, "_plugins", None) or {}).get("automation")

    def view(self) -> H.View:
        auto = self._plugin()
        if auto is None or not hasattr(auto, "helm_view"):
            return H.build_view(False, lambda c: False, lambda c: "",
                                "Automation is not available in this EDLD.")
        return auto.helm_view()

    def shown(self) -> bool:
        """Whether the strip along the Dashboard's foot belongs on screen:
        automation on, and the panel not turned off in Options. EDCARS's
        section is always there."""
        if not self._compact:
            return True
        auto = self._plugin()
        if auto is None:
            return False
        try:
            on = bool(auto.settings().get("Enabled"))
        except Exception:
            on = False
        ui = getattr(getattr(self.core, "cfg", None), "ui_cfg", None) or {}
        return on and H.panel_wanted(ui)

    def refresh_data(self) -> None:
        if self._compact:
            want = self.shown()
            if want != self.isVisible() and self.parent() is not None:
                self.setVisible(want)
            if not want:
                return
        v = self.view()
        self._make_groups(v)
        self._note.setText(v.note)
        self._note.setVisible(bool(v.note))
        self._status.setText(v.status)
        for g in v.groups:
            for b in g.buttons:
                btn = self._buttons.get(b.id)
                if btn is None:
                    continue
                if btn.isEnabled() != b.ready:
                    btn.setEnabled(b.ready)
                if btn.toolTip() != b.tip:
                    btn.setToolTip(b.tip)

    # ── Pressing ──────────────────────────────────────────────────────────────

    def _press(self, cid: str) -> None:
        btn = self._buttons.get(cid)
        if btn is not None:
            self._light(btn, True)
            QTimer.singleShot(250, lambda b=btn: self._light(b, False))
        auto = self._plugin()
        if auto is not None and hasattr(auto, "press_here"):
            auto.press_here(cid)

    @staticmethod
    def _light(btn: QPushButton, on: bool) -> None:
        btn.setProperty("lit", "true" if on else "")
        btn.style().unpolish(btn)
        btn.style().polish(btn)
