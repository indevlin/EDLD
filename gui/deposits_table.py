"""gui/deposits_table.py — Objectives → Deposits: the surface survey as a table.

Columns are the shared sheet's dashboard columns (sheets/build_dashboard.py
HEADERS).
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QAbstractItemView, QComboBox, QHBoxLayout,
                               QHeaderView, QLabel, QLineEdit, QPushButton,
                               QStyledItemDelegate, QTableWidget,
                               QTableWidgetItem, QVBoxLayout, QWidget)

from core.deposit_form import AMOUNT_LEVELS, DENSITY_LEVELS

#: (heading, record key or None, form key when editable)
COLUMNS = (
    ("System", "system_name", None),
    ("Body", "body_name", None),
    ("Gravity", "gravity", None),
    ("Mining Site", "signal_no", "signal_no"),
    ("Commodity", "commodity_display", None),
    ("Amount", "amount", "amount"),
    ("Density", "density_observed", "density_observed"),
    ("Rigs", "rigs", "rigs"),
    ("Depleted", "depleted_on", "depleted_on"),
    ("Notes", "notes", "notes"),
)
CHOICES = {"amount": AMOUNT_LEVELS, "density_observed": DENSITY_LEVELS}
ID_ROLE = Qt.UserRole + 1


def cell_text(rec: dict, key: str) -> str:
    v = rec.get(key)
    if key == "commodity_display":
        return v or rec.get("commodity", "") or ""
    if key == "density_observed":
        return v or rec.get("density_claimed", "") or ""
    if key == "gravity":
        return f"{float(v):.2f}" if v not in (None, "") else ""
    if key == "depleted_on":
        return (v or "")[:10]
    if key == "notes":
        return " ".join((v or "").split())
    return "" if v in (None, "") else str(v)


class _Delegate(QStyledItemDelegate):
    """Combo for Amount / Density; line edit otherwise. Commit goes through
    the table's save callback; a refusal leaves the cell unchanged."""

    def __init__(self, table: "DepositsTable") -> None:
        super().__init__(table.table)
        self._t = table

    def createEditor(self, parent, option, index):
        key = COLUMNS[index.column()][2]
        if key in CHOICES:
            box = QComboBox(parent)
            box.addItems(CHOICES[key])
            return box
        return QLineEdit(parent)

    def setEditorData(self, editor, index):
        text = index.data(Qt.DisplayRole) or ""
        if isinstance(editor, QComboBox):
            editor.setCurrentIndex(max(0, editor.findText(text)))
        else:
            editor.setText(text)
            if COLUMNS[index.column()][2] == "depleted_on" and not text:
                editor.setPlaceholderText("YYYY-MM-DD")

    def setModelData(self, editor, model, index):
        value = editor.currentText() if isinstance(editor, QComboBox) else editor.text()
        self._t.save_cell(index.row(), index.column(), value)


class DepositsTable(QWidget):
    """Filter, table, Edit… button and a status line."""

    def __init__(self, core, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.core = core
        lay = QVBoxLayout(self)
        lay.setContentsMargins(4, 4, 4, 4)
        lay.setSpacing(4)

        top = QHBoxLayout()
        self.filter = QLineEdit()
        self.filter.setPlaceholderText("Filter: system, body, commodity, notes…")
        self.filter.setClearButtonEnabled(True)
        self.filter.textChanged.connect(self._apply_filter)
        self.edit_btn = QPushButton("Edit…")
        self.edit_btn.clicked.connect(self.edit_selected)
        top.addWidget(self.filter, 1)
        top.addWidget(self.edit_btn, 0)
        lay.addLayout(top)

        self.table = QTableWidget(0, len(COLUMNS))
        self.table.setHorizontalHeaderLabels([c[0] for c in COLUMNS])
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.DoubleClicked)
        self.table.setItemDelegate(_Delegate(self))
        self.table.verticalHeader().setVisible(False)
        self.table.setAlternatingRowColors(True)
        self.table.setSortingEnabled(True)
        self.table.sortByColumn(0, Qt.AscendingOrder)
        hdr = self.table.horizontalHeader()
        hdr.setSectionResizeMode(QHeaderView.ResizeToContents)
        hdr.setStretchLastSection(True)
        self.table.cellDoubleClicked.connect(self._double_clicked)
        lay.addWidget(self.table, 1)

        self.status = QLabel("")
        self.status.setProperty("role", "dim")
        self.status.setWordWrap(True)
        lay.addWidget(self.status)
        self._records: list[dict] = []

    # ── data ──────────────────────────────────────────────────────────────────

    def _plugin(self):
        return (getattr(self.core, "_plugins", None) or {}).get("surface_mining")

    def refresh(self) -> None:
        """Reload from the store; skipped while a cell is being edited."""
        if self.table.state() == QAbstractItemView.EditingState:
            return
        plugin = self._plugin()
        records = plugin.deposit_records() if plugin is not None else []
        if records == self._records:
            return
        self._records = records
        selected = self.selected_id()
        self.table.setSortingEnabled(False)
        self.table.setRowCount(len(records))
        for r, rec in enumerate(records):
            depleted = bool(rec.get("depleted_on"))
            for c, (_h, key, editable) in enumerate(COLUMNS):
                item = QTableWidgetItem(cell_text(rec, key))
                item.setData(ID_ROLE, rec.get("deposit_id"))
                flags = Qt.ItemIsSelectable | Qt.ItemIsEnabled
                if editable:
                    flags |= Qt.ItemIsEditable
                item.setFlags(flags)
                if key == "notes":
                    item.setToolTip(rec.get("notes") or "")
                if depleted:
                    f = item.font()
                    f.setStrikeOut(True)
                    item.setFont(f)
                if rec.get("is_test"):
                    f = item.font()
                    f.setItalic(True)
                    item.setFont(f)
                self.table.setItem(r, c, item)
        self.table.setSortingEnabled(True)
        self._apply_filter()
        if selected:
            self.select_id(selected)
        if not records:
            self.status.setText("No surface deposits recorded")

    def _record(self, dep_id: str) -> dict | None:
        return next((d for d in self._records if d.get("deposit_id") == dep_id), None)

    def _apply_filter(self) -> None:
        q = self.filter.text().strip().lower()
        for r in range(self.table.rowCount()):
            text = " ".join((self.table.item(r, c).text() if self.table.item(r, c) else "")
                            for c in range(self.table.columnCount())).lower()
            self.table.setRowHidden(r, bool(q) and q not in text)

    # ── selection ─────────────────────────────────────────────────────────────

    def selected_id(self) -> str | None:
        items = self.table.selectedItems()
        return items[0].data(ID_ROLE) if items else None

    def select_id(self, dep_id: str) -> None:
        for r in range(self.table.rowCount()):
            item = self.table.item(r, 0)
            if item is not None and item.data(ID_ROLE) == dep_id:
                self.table.selectRow(r)
                return

    # ── editing ───────────────────────────────────────────────────────────────

    def save_cell(self, row: int, col: int, value: str) -> bool:
        """Write one cell: SurfaceMiningPlugin.submit_form_for(id, {key: value})."""
        item = self.table.item(row, col)
        plugin = self._plugin()
        key = COLUMNS[col][2]
        if item is None or plugin is None or key is None:
            return False
        dep_id = item.data(ID_ROLE)
        if value.strip() == item.text().strip():
            return False
        result = plugin.submit_form_for(dep_id, {key: value})
        if result.startswith("updated"):
            self.status.setText(f"Saved {COLUMNS[col][0].lower()}: {value or '—'}")
            self._records = []                 # force the reload
            self.refresh()
            self.select_id(dep_id)
            return True
        self.status.setText(result if result != "nothing to change"
                            else "Blank leaves the stored value as it is")
        return False

    def _double_clicked(self, row: int, col: int) -> None:
        if COLUMNS[col][2] is None:
            self.edit_selected()

    def edit_selected(self) -> None:
        dep_id = self.selected_id()
        plugin = self._plugin()
        if not dep_id or plugin is None:
            self.status.setText("Select a deposit to edit")
            return
        from gui.deposit_dialog import DepositDialog
        if DepositDialog(plugin, self, dep_id=dep_id).exec():
            self._records = []
            self.refresh()
            self.select_id(dep_id)
