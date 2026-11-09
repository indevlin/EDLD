"""gui/hotspot_dialog.py — Add or edit a ring hotspot. Fields come from
``core.ring_hotspots.FIELDS``; identity fields are read-only once it exists."""

from __future__ import annotations

from PySide6.QtWidgets import (QComboBox, QDialog, QDialogButtonBox,
                               QFormLayout, QLabel, QLineEdit, QVBoxLayout)

from core.ring_hotspots import FIELDS, IDENTITY


class HotspotDialog(QDialog):
    """``hid`` None: a new hotspot (form_for(None) / submit_form_for(None))."""

    def __init__(self, plugin, parent=None, hid: str | None = None) -> None:
        super().__init__(parent)
        self._plugin = plugin
        self._hid = hid
        values, heading = plugin.form_for(hid)
        self.setWindowTitle("Ring Hotspot")
        lay = QVBoxLayout(self)
        self._heading = QLabel(heading)
        self._heading.setWordWrap(True)
        self._heading.setProperty("role", "dim")
        lay.addWidget(self._heading)

        form = QFormLayout()
        lay.addLayout(form)
        self._widgets: dict = {}
        for f in FIELDS:
            current = str(values.get(f.key, "") or "")
            fixed = bool(hid) and f.key in IDENTITY
            if f.kind == "choice":
                box = QComboBox()
                box.addItem("", "")
                for choice in f.choices:
                    box.addItem(choice, choice)
                if current and box.findData(current) < 0:
                    box.addItem(current, current)
                box.setCurrentIndex(max(0, box.findData(current)))
                box.setEnabled(not fixed)
                if f.hint:
                    box.setToolTip(f.hint)
                widget = box
            elif f.kind == "bool":
                widget = QComboBox()
                widget.addItem("No", "")
                widget.addItem("Yes", "true")
                widget.setCurrentIndex(1 if current else 0)
            else:
                widget = QLineEdit(current)
                widget.setPlaceholderText(f.hint)
                widget.setEnabled(not fixed)
            self._widgets[f.key] = widget
            form.addRow(f.label, widget)

        self._result = QLabel("")
        self._result.setWordWrap(True)
        self._result.setProperty("role", "dim")
        lay.addWidget(self._result)
        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        lay.addWidget(buttons)

    def values(self) -> dict:
        return {k: (w.currentData() or "") if isinstance(w, QComboBox) else w.text()
                for k, w in self._widgets.items()}

    def _save(self) -> None:
        result = self._plugin.submit_form_for(self._hid, self.values())
        if result.startswith(("recorded", "updated")) or result == "nothing to change":
            self.accept()
        else:
            self._result.setText(result)
