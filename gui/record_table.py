"""gui/record_table.py — A filterable, sortable record table with in-place
editing and an Edit button at the end of every row.

Configured by a ``Spec``: columns, the plugin that owns the records, and how to
list, save and open a record.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QAbstractItemView, QComboBox, QHBoxLayout,
                               QHeaderView, QLabel, QLineEdit, QPushButton,
                               QStyledItemDelegate, QTableWidget,
                               QTableWidgetItem, QVBoxLayout, QWidget)

ID_ROLE = Qt.UserRole + 1


@dataclass
class Spec:
    plugin: str                                  # core._plugins key
    id_key: str                                  # record key holding the id
    columns: tuple                               # (heading, record key, form key | None)
    records: Callable                            # plugin -> list[dict]
    save: Callable                               # (plugin, id, form key, value) -> str
    edit: Callable                               # (plugin, parent, id | None) -> bool
    cell_text: Callable                          # (record, key) -> str
    choices: dict = field(default_factory=dict)  # form key -> tuple of choices
    placeholder: str = "Filter"
    empty: str = "Nothing recorded"
    noun: str = "row"
    struck: Callable = lambda rec: False         # strike the row through
    add_label: str = ""                          # footer Add button; "" for none
    stretch: str = ""                            # record key of the column that stretches


class _Delegate(QStyledItemDelegate):
    """Combo for choice columns, line edit otherwise; commits via save_cell."""

    def __init__(self, table: "RecordTable") -> None:
        super().__init__(table.table)
        self._t = table

    def createEditor(self, parent, option, index):
        key = self._t.spec.columns[index.column()][2]
        if key in self._t.spec.choices:
            box = QComboBox(parent)
            box.addItems(("",) + tuple(self._t.spec.choices[key]))
            return box
        return QLineEdit(parent)

    def setEditorData(self, editor, index):
        text = index.data(Qt.DisplayRole) or ""
        if isinstance(editor, QComboBox):
            editor.setCurrentIndex(max(0, editor.findText(text)))
        else:
            editor.setText(text)
            if self._t.spec.columns[index.column()][2] == "depleted_on" and not text:
                editor.setPlaceholderText("YYYY-MM-DD")

    def setModelData(self, editor, model, index):
        value = editor.currentText() if isinstance(editor, QComboBox) else editor.text()
        self._t.save_cell(index.row(), index.column(), value)


class RecordTable(QWidget):
    """Filter box; table whose last column is an Edit button per row; footer
    with a status line and the optional Add button."""

    def __init__(self, core, spec: Spec, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.core = core
        self.spec = spec
        lay = QVBoxLayout(self)
        lay.setContentsMargins(4, 4, 4, 4)
        lay.setSpacing(4)

        self.filter = QLineEdit()
        self.filter.setPlaceholderText(spec.placeholder)
        self.filter.setClearButtonEnabled(True)
        self.filter.textChanged.connect(self._apply_filter)
        lay.addWidget(self.filter)

        n = len(spec.columns)
        self.table = QTableWidget(0, n + 1)
        self.table.setHorizontalHeaderLabels([c[0] for c in spec.columns] + [""])
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
        hdr.setStretchLastSection(False)
        for c, (_h, key, _f) in enumerate(spec.columns):
            if key == spec.stretch:
                hdr.setSectionResizeMode(c, QHeaderView.Stretch)
        hdr.setSectionResizeMode(n, QHeaderView.Fixed)
        self.table.setColumnWidth(n, QPushButton("Edit").sizeHint().width() + 12)
        self.table.cellDoubleClicked.connect(self._double_clicked)
        lay.addWidget(self.table, 1)

        foot = QHBoxLayout()
        self.status = QLabel("")
        self.status.setProperty("role", "dim")
        self.status.setWordWrap(True)
        foot.addWidget(self.status, 1)
        self.add_btn: Optional[QPushButton] = None
        if spec.add_label:
            self.add_btn = QPushButton(spec.add_label)
            self.add_btn.clicked.connect(lambda _c=False: self.open_editor(None))
            foot.addWidget(self.add_btn, 0)
        lay.addLayout(foot)
        self._records: list[dict] | None = None
        self.edit_buttons: dict[str, QPushButton] = {}

    # ── data ──────────────────────────────────────────────────────────────────

    def _plugin(self):
        return (getattr(self.core, "_plugins", None) or {}).get(self.spec.plugin)

    def refresh(self) -> None:
        """Reload from the plugin; skipped while a cell is being edited."""
        if self.table.state() == QAbstractItemView.EditingState:
            return
        plugin = self._plugin()
        records = self.spec.records(plugin) if plugin is not None else []
        if records == self._records:
            return
        self._records = records
        selected = self.selected_id()
        cols = self.spec.columns
        self.table.setSortingEnabled(False)
        self.table.clearContents()
        self.table.setRowCount(len(records))
        self.edit_buttons = {}
        for r, rec in enumerate(records):
            rid = rec.get(self.spec.id_key)
            struck = self.spec.struck(rec)
            for c, (_h, key, editable) in enumerate(cols):
                item = QTableWidgetItem(self.spec.cell_text(rec, key))
                item.setData(ID_ROLE, rid)
                flags = Qt.ItemIsSelectable | Qt.ItemIsEnabled
                if editable:
                    flags |= Qt.ItemIsEditable
                item.setFlags(flags)
                if key == "notes":
                    item.setToolTip(rec.get("notes") or "")
                if struck or rec.get("is_test"):
                    f = item.font()
                    f.setStrikeOut(struck)
                    f.setItalic(bool(rec.get("is_test")))
                    item.setFont(f)
                self.table.setItem(r, c, item)
            spacer = QTableWidgetItem("")
            spacer.setData(ID_ROLE, rid)
            spacer.setFlags(Qt.ItemIsEnabled)
            self.table.setItem(r, len(cols), spacer)
            btn = QPushButton("Edit")
            btn.setProperty("role", "link")
            btn.setCursor(Qt.PointingHandCursor)
            btn.setToolTip(f"Edit this {self.spec.noun}")
            btn.clicked.connect(lambda _c=False, i=rid: self.open_editor(i))
            self.table.setCellWidget(r, len(cols), btn)
            self.edit_buttons[rid] = btn
        self.table.setSortingEnabled(True)
        self._apply_filter()
        if selected:
            self.select_id(selected)
        self.status.setText("" if records else self.spec.empty)

    def _apply_filter(self) -> None:
        q = self.filter.text().strip().lower()
        n = len(self.spec.columns)
        for r in range(self.table.rowCount()):
            text = " ".join((self.table.item(r, c).text() if self.table.item(r, c) else "")
                            for c in range(n)).lower()
            self.table.setRowHidden(r, bool(q) and q not in text)

    # ── selection ─────────────────────────────────────────────────────────────

    def selected_id(self) -> Optional[str]:
        items = self.table.selectedItems()
        return items[0].data(ID_ROLE) if items else None

    def select_id(self, rid: str) -> None:
        for r in range(self.table.rowCount()):
            item = self.table.item(r, 0)
            if item is not None and item.data(ID_ROLE) == rid:
                self.table.selectRow(r)
                return

    def row_of(self, rid: str) -> int:
        for r in range(self.table.rowCount()):
            item = self.table.item(r, 0)
            if item is not None and item.data(ID_ROLE) == rid:
                return r
        return -1

    # ── editing ───────────────────────────────────────────────────────────────

    def save_cell(self, row: int, col: int, value: str) -> bool:
        item = self.table.item(row, col)
        plugin = self._plugin()
        if col >= len(self.spec.columns):
            return False
        heading, _key, form_key = self.spec.columns[col]
        if item is None or plugin is None or form_key is None:
            return False
        rid = item.data(ID_ROLE)
        if value.strip() == item.text().strip():
            return False
        result = self.spec.save(plugin, rid, form_key, value)
        if result.startswith("updated"):
            self.status.setText(f"Saved {heading.lower()}: {value or '—'}")
            self._records = None
            self.refresh()
            self.select_id(rid)
            return True
        self.status.setText(result if result != "nothing to change"
                            else "Blank leaves the stored value as it is")
        return False

    def _double_clicked(self, row: int, col: int) -> None:
        if col < len(self.spec.columns) and self.spec.columns[col][2] is None:
            item = self.table.item(row, col)
            if item is not None:
                self.open_editor(item.data(ID_ROLE))

    def open_editor(self, rid: Optional[str]) -> None:
        plugin = self._plugin()
        if plugin is None:
            self.status.setText("Not available")
            return
        if self.spec.edit(plugin, self, rid):
            self._records = None
            self.refresh()
            if rid:
                self.select_id(rid)
