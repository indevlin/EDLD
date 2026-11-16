"""gui/blocks/helm.py — the Helm panel (Qt): the game's controls and EDLD's automation as buttons.

``compact`` picks the strip's sizes.
"""
from __future__ import annotations

from PySide6.QtCore import QRect, Qt, QTimer
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPalette
from PySide6.QtWidgets import (
    QGridLayout, QHBoxLayout, QLabel, QPushButton, QSizePolicy, QVBoxLayout, QWidget,
)

from core import helm as H
from gui.block_base import GuiBlock

#: Bars and pairs read centered, whatever corner the console puts a label in.
_CENTRED = """
QPushButton[shape="bar"], QPushButton[shape="pair"] {
    text-align: center; padding-left: 2px; padding-right: 2px;
    padding-top: 0px; padding-bottom: 0px;
}
"""

#: The AUTO lamp: on, off.
LAMP = (QColor("#3fb950"), QColor("#d9534f"))

PREV, NEXT = "◀", "▶"


class _Button(QPushButton):
    """A Helm button: one control, or a pair (``ids`` two long) pressed by
    the half clicked; ``auto`` lights the AUTO lamp in its top corner."""

    def __init__(self, text: str, ids: tuple[str, ...]) -> None:
        super().__init__(text)
        self.ids = ids
        self.auto: bool | None = None
        self.side = 1 if len(ids) > 1 else 0

    def mousePressEvent(self, event) -> None:      # noqa: N802 (Qt naming)
        if len(self.ids) > 1:
            self.side = 0 if event.position().x() < self.width() / 2 else 1
        super().mousePressEvent(event)

    def target(self) -> str:
        return self.ids[self.side] if len(self.ids) > 1 else self.ids[0]

    def paintEvent(self, event) -> None:           # noqa: N802 (Qt naming)
        super().paintEvent(event)
        if self.auto is None:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        f = QFont(self.font())
        f.setPointSizeF(max(6.0, f.pointSizeF() * 0.72))
        p.setFont(f)
        fm = QFontMetrics(f)
        side = max(6, fm.capHeight())
        x = self.width() - 5 - side
        y = 5
        p.fillRect(QRect(x, y, side, side), LAMP[0] if self.auto else LAMP[1])
        p.setPen(self.palette().color(QPalette.ButtonText))
        text = "AUTO"
        p.drawText(x - 4 - fm.horizontalAdvance(text), y + side, text)
        p.end()


class _GroupBox(QWidget):
    """One group: its name, and its cells in a grid, or bars side by side."""

    def __init__(self, gid: str, label: str, compact: bool) -> None:
        super().__init__()
        self.setObjectName("helmGroup")
        self.gid = gid
        self.bars = gid in H.BARS
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(2 if compact else 3)
        self.title = QLabel(label.upper())
        self.title.setObjectName("helmGroupTitle")
        lay.addWidget(self.title)
        self.grid = QGridLayout()
        self.grid.setContentsMargins(0, 0, 0, 0)
        self.grid.setHorizontalSpacing(HelmBlock.GAP[compact])
        self.grid.setVerticalSpacing(HelmBlock.GAP[compact])
        lay.addLayout(self.grid)
        lay.addStretch(1)
        self.buttons: list[_Button] = []
        self._cols = 0

    def place(self, cols: int) -> None:
        cols = len(self.buttons) if self.bars else cols
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

    #: (narrowest button, button height) for the strip along the Dashboard's
    #: foot, and for EDCARS's section. A button is never narrower than the
    #: longest name on the panel needs.
    COMPACT = (84, 24)
    LARGE = (104, 32)
    #: How far EDCARS's section grows its buttons to fill its height.
    GROW = 2.0
    #: Between buttons, between groups on a line, and between lines:
    #: [large, compact].
    GAP = (4, 3)
    GROUP_GAP = (16, 12)
    LINE_GAP = (10, 6)

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
        # own resize comes before the host has its new width. Lines of groups
        # (core.helm.plan), packed at the top.
        self._host = _Host(self._arrange)
        self._host.setStyleSheet(_CENTRED)
        self._lines = QVBoxLayout(self._host)
        m = 4 if self._compact else 6
        self._lines.setContentsMargins(m, m, m, 2)
        self._lines.setSpacing(self.LINE_GAP[self._compact])
        self._lines.addStretch(1)
        self._line_widgets: list[QWidget] = []
        layout.addWidget(self._host, 0 if self._compact else 1)

        self._status = QLabel("")
        self._status.setObjectName("helmStatus")
        self._status.setTextFormat(Qt.PlainText)
        self._status.setContentsMargins(m, 2, m, 2)
        self._status.setVisible(False)
        layout.addWidget(self._status)

        self._groups: dict[str, _GroupBox] = {}
        self._buttons: dict[tuple[str, ...], _Button] = {}
        self._layout: tuple = ()
        self._button_w = self._sizes[0]
        self._bar_w = self._sizes[0] / 2
        self._row_h = self._sizes[1]
        self._helm_context = H.SHIP
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
        self._measure()
        self._layout = ()
        self._arrange()

    def _text(self, label: str) -> str:
        return label.upper() if self._button_font else label

    def _make_groups(self, view: H.View) -> None:
        sig = (view.context,) + tuple((g.id, tuple(b.id for b in g.buttons))
                                      for g in view.groups)
        if sig == self._sig:
            return
        self._sig = sig
        self._helm_context = view.context
        for box in self._groups.values():
            box.setParent(None)
            box.deleteLater()
        self._groups.clear()
        self._buttons.clear()
        for g in view.groups:
            box = _GroupBox(g.id, g.label, self._compact)
            if self._title_font is not None:
                box.title.setFont(self._title_font)
            for cell in g.cells():
                ids = tuple(b.id for b in cell)
                if len(cell) > 1:
                    text = f"{PREV}  {self._text(H.pair_label(ids))}  {NEXT}"
                else:
                    text = self._text(cell[0].label)
                btn = _Button(text, ids)
                if self._button_font is not None:
                    btn.setFont(self._button_font)
                btn.setProperty("role", "helm")
                if g.bars:
                    btn.setProperty("shape", "bar")
                elif len(cell) > 1:
                    btn.setProperty("shape", "pair")
                btn.setFixedHeight(self._row_h)
                btn.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
                btn.setCursor(Qt.PointingHandCursor)
                btn.clicked.connect(lambda _c=False, b=btn: self._press(b))
                box.buttons.append(btn)
                self._buttons[ids] = btn
            self._groups[g.id] = box
        self._measure()
        self._layout = ()
        self._arrange()

    def _measure(self) -> None:
        """The narrowest a button may be: the longest name on the panel,
        whole, with room either side, and the AUTO lamp's; a bar, the
        longest bar's name."""
        least, bar = self._sizes[0], 36
        for btn in self._buttons.values():
            fm = QFontMetrics(btn.font())
            text = fm.horizontalAdvance(btn.text())
            if btn.property("shape") == "bar":
                bar = max(bar, text + 8)
                continue
            if btn.auto is not None or btn.ids[0] in H.AUTOMATIC:
                text += 2 * fm.horizontalAdvance("AUTO")
            least = max(least, text + 18)
        self._button_w, self._bar_w = least, bar

    # ── Layout ────────────────────────────────────────────────────────────────

    def _counts(self) -> dict[str, int]:
        return {gid: len(box.buttons) for gid, box in self._groups.items()}

    def _arrange(self) -> None:
        """Lay the groups out in core.helm.plan's lines for this width: a
        line's groups side by side, each as wide as its columns. EDCARS's
        buttons grow to fill the height, every row alike."""
        if not getattr(self, "_groups", None):
            return
        c = self._compact
        m = self._lines.contentsMargins()
        width = max(1, self._host.width() - m.left() - m.right())
        count = self._counts()
        lines = H.plan(list(count.items()), self._helm_context, width, self._button_w,
                       self.GAP[c], self.GROUP_GAP[c], self._bar_w)
        least = self._sizes[1]
        row_h = least
        if not c and lines:
            title = next(iter(self._groups.values())).title.sizeHint().height() + 3
            avail = self._host.height() - m.top() - m.bottom()
            row_h = int(H.row_height(avail, lines, count, title, self.LINE_GAP[c],
                                     self.GAP[c], least, least * self.GROW))
        layout = (tuple(tuple(line) for line in lines), row_h)
        if layout == self._layout:
            return
        self._layout = layout
        self._row_h = row_h
        gap = self.GAP[c]
        for line in lines:
            rows = H.line_rows(line, count)
            for gid, _cols in line:
                box = self._groups[gid]
                h = rows * row_h + (rows - 1) * gap if box.bars else row_h
                for b in box.buttons:
                    b.setFixedHeight(h)
        for box in self._groups.values():
            box.setParent(None)
        for w in self._line_widgets:
            self._lines.removeWidget(w)
            w.deleteLater()
        self._line_widgets = []
        for i, line in enumerate(lines):
            w = QWidget()
            row = QHBoxLayout(w)
            row.setContentsMargins(0, 0, 0, 0)
            row.setSpacing(self.GROUP_GAP[c])
            for gid, cols in line:
                box = self._groups[gid]
                box.place(cols)
                row.addWidget(box, cols, Qt.AlignTop)
                box.show()
            self._lines.insertWidget(i, w)
            self._line_widgets.append(w)

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
        status = H.status_line(v)
        if status != self._status.text():
            self._status.setText(status)
            self._status.setVisible(bool(status))
            if status:
                # Gone again once the outcome has been up long enough.
                wait = getattr(self._plugin(), "RESULT_SECONDS", 8.0)
                QTimer.singleShot(int(wait * 1000) + 100, self.refresh_data)
        for g in v.groups:
            for cell in g.cells():
                btn = self._buttons.get(tuple(b.id for b in cell))
                if btn is None:
                    continue
                ready = any(b.ready for b in cell)
                if len(cell) > 1:
                    tip = f"{PREV} {cell[0].label}  ·  {cell[1].label} {NEXT}"
                elif cell[0].tip:
                    tip = cell[0].tip
                else:
                    tip = ""
                if btn.isEnabled() != ready:
                    btn.setEnabled(ready)
                if btn.toolTip() != tip:
                    btn.setToolTip(tip)
                auto = cell[0].auto
                if btn.auto != auto:
                    btn.auto = auto
                    btn.update()

    # ── Pressing ──────────────────────────────────────────────────────────────

    def _press(self, btn: _Button) -> None:
        cid = btn.target()
        # One button lit, the one just pressed, for a quarter second.
        were = getattr(self, "_lit", None)
        if were is not None and were is not btn:
            self._light(were, False)
        self._lit = btn
        self._light(btn, True)
        QTimer.singleShot(250, lambda b=btn: self._unlight(b))
        auto = self._plugin()
        if auto is not None and hasattr(auto, "press_here"):
            auto.press_here(cid)

    def _unlight(self, btn: _Button) -> None:
        if getattr(self, "_lit", None) is btn:
            self._lit = None
        try:
            self._light(btn, False)
        except RuntimeError:                       # rebuilt meanwhile
            return
        # The press brought the game to the front: the pointer left this
        # window without its leaving being told, and the button would keep
        # its hover look until the pointer came back to it.
        if not btn.window().isActiveWindow():
            btn.setAttribute(Qt.WA_UnderMouse, False)
            btn.update()

    @staticmethod
    def _light(btn: QPushButton, on: bool) -> None:
        btn.setProperty("lit", "true" if on else "")
        btn.style().unpolish(btn)
        btn.style().polish(btn)
        btn.update()
