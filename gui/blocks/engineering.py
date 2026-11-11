"""gui/blocks/engineering.py — Engineering window (Qt): Fitting and Materials.

Fitting draws core/windows/engineering.py's view: the ship list, the slots
fitted and planned side by side, the work left and the materials it takes.
"""
from __future__ import annotations

from PySide6.QtCore import QEvent, Qt
from PySide6.QtWidgets import (
    QComboBox, QGridLayout, QHBoxLayout, QLabel, QMessageBox, QPushButton,
    QScrollArea, QSizePolicy, QTabWidget, QVBoxLayout, QWidget,
)

from core.windows import engineering as EW
from gui.block_base import GuiBlock, RowScroll
from gui.markup import to_html

#: Slot states → how the target cell is colored.
_STATE_TONE = {"module": "red", "added": "red", "eng": "amber"}

#: Space between the two halves, above and below.
_GAP = 12


class EngineeringBlock(GuiBlock):
    BLOCK_TITLE = "ENGINEERING"

    def _build_body(self, layout) -> None:
        self._key = ""
        self._filling = False
        self._tabs = QTabWidget()
        self._tabs.setDocumentMode(True)

        # ── Fitting ──────────────────────────────────────────────────────────
        fit = QWidget()
        self._fit = fit
        fit.installEventFilter(self)
        fl = QVBoxLayout(fit)
        fl.setContentsMargins(0, 4, 0, 0)
        fl.setSpacing(4)

        bar = QHBoxLayout()
        bar.setContentsMargins(6, 0, 6, 0)
        bar.setSpacing(6)
        self._ships = QComboBox()
        self._ships.setMinimumWidth(240)
        self._ships.setSizeAdjustPolicy(QComboBox.AdjustToContents)
        self._ships.activated.connect(self._on_ship)
        bar.addWidget(self._ships, 0)
        self._target_btn = self._button("Target…", self._on_target,
                                        "Add or replace the build planned for this ship")
        self._clear_btn = self._button("Clear", self._on_clear, "Forget the target build")
        self._apply_lbl = QLabel("Apply to")
        self._apply_lbl.setProperty("role", "dim")
        self._apply = QComboBox()
        self._apply_btn = self._button("Apply", self._on_apply,
                                       "Make this the chosen ship's target and drop the plan")
        self._delete_btn = self._button("Delete plan", self._on_delete, "Forget this planned build")
        for w in (self._target_btn, self._clear_btn, self._apply_lbl, self._apply,
                  self._apply_btn, self._delete_btn):
            bar.addWidget(w, 0)
        bar.addStretch(1)
        self._shop_btn = self._button("Shopping list…", self._on_shop,
                                      "Trades that cover what is short, and the nearest traders")
        bar.addWidget(self._shop_btn, 0)
        fl.addLayout(bar)

        self._status = QLabel("")
        self._status.setProperty("role", "dim")
        self._status.setWordWrap(True)
        self._status.setTextFormat(Qt.RichText)
        self._status.setOpenExternalLinks(True)
        self._status.setContentsMargins(6, 0, 6, 0)
        fl.addWidget(self._status)

        # The slots, fitted and planned, side by side.
        self._grid_host = QWidget()
        self._grid = QGridLayout(self._grid_host)
        self._grid.setContentsMargins(6, 2, 6, 2)
        self._grid.setHorizontalSpacing(_GAP)
        self._grid.setVerticalSpacing(2)
        self._grid_host.installEventFilter(self)
        grid_scroll = QScrollArea()
        grid_scroll.setWidgetResizable(True)
        grid_scroll.setWidget(self._grid_host)
        fl.addWidget(grid_scroll, 3)

        # The work left, and what it takes: two equal halves.
        lower = QHBoxLayout()
        lower.setSpacing(_GAP)
        self._work = RowScroll()
        self._mats = RowScroll()
        for title, scroll in (("Work left", self._work), ("Materials", self._mats)):
            half = QWidget()
            half.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
            col = QVBoxLayout(half)
            col.setContentsMargins(0, 0, 0, 0)
            col.addWidget(self.hdr(title))
            col.addWidget(scroll, 1)
            lower.addWidget(half, 1)
        self._lower = lower
        fl.addLayout(lower, 2)
        self._tabs.addTab(fit, "Fitting")

        # ── Materials ────────────────────────────────────────────────────────
        self._mat_tabs = QTabWidget()
        self._mat_tabs.setDocumentMode(True)
        self._scrolls: dict[str, RowScroll] = {}
        for key, label in EW.GRADES:
            scroll = RowScroll()
            self._scrolls[key] = scroll
            self._mat_tabs.addTab(scroll, label)
        self._tabs.addTab(self._mat_tabs, "Materials")

        layout.addWidget(self._tabs, 1)

    def _button(self, text: str, slot, tip: str = "") -> QPushButton:
        b = QPushButton(text)
        b.setProperty("role", "link")
        b.setCursor(Qt.PointingHandCursor)
        if tip:
            b.setToolTip(tip)
        b.clicked.connect(lambda _c=False: slot())
        return b

    def _plugin(self):
        return self.core._plugins.get("engineering")

    # ── Refresh ───────────────────────────────────────────────────────────────

    def refresh_data(self) -> None:
        for page in EW.materials(self.core).pages:
            scroll = self._scrolls.get(page.id)
            if scroll is not None:
                scroll.set_rows(self.render_rows(page.rows))
        self._refresh_fitting()

    def _refresh_fitting(self) -> None:
        v = EW.fitting(self.core)
        self._key = v.key
        self._fill_ships(v.key)
        planned = v.planned
        self._target_btn.setText("Build…" if planned else "Target…")
        self._target_btn.setEnabled(bool(v.key))
        self._clear_btn.setVisible(v.has_target and not planned)
        for w in (self._apply_lbl, self._apply, self._apply_btn, self._delete_btn):
            w.setVisible(planned)
        self._apply.clear()
        for key, label in v.apply_to:
            self._apply.addItem(label, key)
        self._apply_btn.setEnabled(bool(v.apply_to) and v.has_target)
        self._apply.setEnabled(bool(v.apply_to))
        if planned and not v.apply_to:
            self._apply.addItem("no ship of this type")
        self._shop_btn.setEnabled(v.short > 0)

        parts = []
        if v.has_target:
            src = v.target_source or "build"
            if v.target_url.startswith("http"):
                src = f'<a href="{v.target_url}">{src}</a>'
            parts.append(f"Target from {src}")
        if v.status:
            parts.append(to_html(v.status, self.palette_map))
        self._status.setText("  ·  ".join(parts))
        self._status.setVisible(bool(parts))

        self._fill_grid(v)
        self._work.set_rows(self.render_rows(v.work if v.has_target else []))
        self._mats.set_rows(self.render_rows(v.needs))

    def _fill_ships(self, key: str) -> None:
        self._filling = True
        try:
            self._ships.clear()
            for k, label in EW.choices(self.core):
                self._ships.addItem(label, k)
            i = self._ships.findData(key)
            if i >= 0:
                self._ships.setCurrentIndex(i)
        finally:
            self._filling = False

    def _cell(self, name: str, eng: str, tone: str = "", eng_tone: str = "") -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(0, 2, 0, 2)
        lay.setSpacing(0)
        top = QLabel()
        top.setTextFormat(Qt.RichText)
        text = to_html(name or "—", self.palette_map)
        if tone and self.palette_map.get(tone):
            text = f'<span style="color: {self.palette_map[tone]};">{text}</span>'
        top.setText(text)
        top.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        lay.addWidget(top)
        if eng:
            sub = QLabel()
            sub.setTextFormat(Qt.RichText)
            colour = self.palette_map.get(eng_tone) or self.palette_map.get("dim", "")
            sub.setText(f'<span style="color: {colour};">'
                        f'{to_html(eng, self.palette_map)}</span>')
            sub.setContentsMargins(14, 0, 0, 0)
            sub.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
            lay.addWidget(sub)
        return w

    def _fill_grid(self, v) -> None:
        while self._grid.count():
            w = self._grid.takeAt(0).widget()
            if w is not None:
                w.setParent(None)
                w.deleteLater()
        heads = ["Slot", "Fitted", "Target"] if not v.planned else ["Slot", "Build"]
        for col, h in enumerate(heads):
            lbl = QLabel(h.upper())
            lbl.setProperty("role", "section")
            self._grid.addWidget(lbl, 0, col)
        for r, s in enumerate(v.slots, start=1):
            slot = QLabel(s.label)
            slot.setProperty("role", "key")
            slot.setAlignment(Qt.AlignLeft | Qt.AlignTop)
            self._grid.addWidget(slot, r, 0, Qt.AlignTop)
            tone = _STATE_TONE.get(s.state, "")
            if v.planned:
                self._grid.addWidget(self._cell(s.target, s.target_eng), r, 1, Qt.AlignTop)
                continue
            self._grid.addWidget(self._cell(s.current, s.current_eng,
                                            "dim" if s.state == "removed" else ""),
                                 r, 1, Qt.AlignTop)
            if v.has_target:
                self._grid.addWidget(self._cell(
                    s.target if s.state != "removed" else "—", s.target_eng,
                    tone if s.state in ("module", "added") else "",
                    "amber" if s.state in ("eng", "module", "added") else ""), r, 2, Qt.AlignTop)
        self._grid.setColumnStretch(0, 0)
        self._grid.setColumnStretch(1, 0)
        self._grid.setColumnStretch(2, 1)
        self._grid.setRowStretch(len(v.slots) + 1, 1)
        self._sync_halves()

    def eventFilter(self, obj, event) -> bool:
        if event.type() == QEvent.Resize and obj in (self._fit, self._grid_host):
            self._sync_halves()
        return super().eventFilter(obj, event)

    def _sync_halves(self) -> None:
        """Slot and Fitted fill the left half, Target the right, with the
        right half starting where Materials does below."""
        g = self._grid
        if not g.count():
            return
        lead = max((item.widget().sizeHint().width() for i in range(g.rowCount())
                    if (item := g.itemAtPosition(i, 0)) is not None and item.widget()),
                   default=0)
        half = (self._fit.width() - _GAP) // 2
        right = half + _GAP - self._grid_host.mapTo(self._fit, self._grid_host.rect().topLeft()).x()
        left_margin = g.contentsMargins().left()
        g.setColumnMinimumWidth(0, lead)
        g.setColumnMinimumWidth(1, max(0, right - left_margin - lead - 2 * _GAP))

    # ── Actions ───────────────────────────────────────────────────────────────

    def _on_ship(self, index: int) -> None:
        if self._filling:
            return
        key = self._ships.itemData(index)
        eng = self._plugin()
        if eng is None or not key:
            return
        if key == EW.NEW_PLAN:
            self._new_plan()
            return
        eng.select(key)
        self._refresh_fitting()

    def _new_plan(self) -> None:
        from gui.eng_dialogs import NewPlanDialog
        eng = self._plugin()
        dlg = NewPlanDialog(self.window(), EW.ship_types(self.core), theme=self.theme)

        def chosen(ship_type: str) -> None:
            eng.add_plan(ship_type)
            self._refresh_fitting()
            self._on_target()
        dlg.chosen.connect(chosen)
        dlg.exec()
        self._refresh_fitting()

    def _on_target(self) -> None:
        from gui.eng_dialogs import TargetDialog
        eng = self._plugin()
        v = EW.fitting(self.core, self._key)
        if eng is None or not v.key:
            return
        ship_type = v.ship_type

        def read(text):
            return eng.import_build(text, ship_type)

        title = f"Build for {v.label}" if v.planned else f"Target build for {v.label}"
        dlg = TargetDialog(self.window(), title, read, theme=self.theme,
                           current=v.target_url)
        dlg.imported.connect(lambda build: (eng.set_target(v.key, build),
                                            self._refresh_fitting()))
        dlg.exec()

    def _on_clear(self) -> None:
        eng = self._plugin()
        if eng is not None and self._key:
            eng.set_target(self._key, None)
            self._refresh_fitting()

    def _on_apply(self) -> None:
        eng = self._plugin()
        ship = self._apply.currentData()
        if eng is None or not ship:
            return
        if eng.target(ship):
            ok = QMessageBox.question(
                self.window(), "Replace target",
                f"{self._apply.currentText()} already has a target build. Replace it?")
            if ok != QMessageBox.Yes:
                return
        if eng.apply_plan(self._key, ship):
            self._refresh_fitting()

    def _on_delete(self) -> None:
        eng = self._plugin()
        if eng is None:
            return
        ok = QMessageBox.question(self.window(), "Delete plan",
                                  f"Forget {self._ships.currentText()}?")
        if ok == QMessageBox.Yes:
            eng.delete_plan(self._key)
            self._refresh_fitting()

    def _on_shop(self) -> None:
        from gui.eng_dialogs import ShoppingDialog
        eng = self._plugin()
        kinds = EW.trade_kinds(self.core, self._key)
        find = (lambda ks: eng.nearest_traders(ks)) if eng is not None else None
        ShoppingDialog(self.window(), self, self._key, kinds, find, theme=self.theme).exec()
