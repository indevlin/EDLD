"""gui/blocks/helm.py — the Helm panel (Qt): the game's controls and EDLD's automation as buttons.

``compact`` picks the strip's sizes.
"""
from __future__ import annotations

from math import ceil

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QFontMetrics
from PySide6.QtWidgets import (
    QGridLayout, QHBoxLayout, QLabel, QPushButton, QSizePolicy, QVBoxLayout, QWidget,
)

from core import helm as H
from gui.block_base import GuiBlock


class _GroupBox(QWidget):
    """One group: its name, and its buttons in a grid."""

    def __init__(self, label: str, compact: bool) -> None:
        super().__init__()
        self.setObjectName("helmGroup")
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

    #: (narrowest button, button height) for the strip along the Dashboard's
    #: foot, and for EDCARS's section. A button is never narrower than the
    #: longest name on the panel needs.
    COMPACT = (84, 24)
    LARGE = (104, 32)
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
        layout.addWidget(self._status)

        self._groups: dict[str, _GroupBox] = {}
        self._buttons: dict[str, QPushButton] = {}
        self._layout: tuple = ()
        self._button_w = self._sizes[0]
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
        _bw, bh = self._sizes
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
        self._measure()
        self._layout = ()
        self._arrange()

    def _measure(self) -> None:
        """The narrowest a button may be: the longest name on the panel,
        whole, with room either side."""
        least = self._sizes[0]
        for btn in self._buttons.values():
            text = QFontMetrics(btn.font()).horizontalAdvance(btn.text())
            least = max(least, text + 18)
        self._button_w = least

    # ── Layout ────────────────────────────────────────────────────────────────

    def _arrange(self) -> None:
        """Lay the groups out in core.helm.plan's lines for this width: a
        line's groups side by side, each as wide as its columns, the buttons
        at their own height and what is left below them."""
        if not getattr(self, "_groups", None):
            return
        c = self._compact
        m = self._lines.contentsMargins()
        width = max(1, self._host.width() - m.left() - m.right())
        counts = [(gid, len(box.buttons)) for gid, box in self._groups.items()]
        lines = H.plan(counts, self._helm_context, width, self._button_w,
                       self.GAP[c], self.GROUP_GAP[c])
        layout = tuple(tuple(line) for line in lines)
        if layout == self._layout:
            return
        self._layout = layout
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
        self._status.setText(H.status_line(v))
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
