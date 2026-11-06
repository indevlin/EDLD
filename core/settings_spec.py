"""
core/settings_spec.py — a component's settings, described once, drawn twice.

Every component that brings settings had to write its Options tab twice — a
Qt form for the desktop window and a Textual one for the terminal dashboard —
and then register its terminal widget ids separately, or they were drawn and
never saved. A component that describes its settings here gets both tabs and
the save bindings from the one description, so the two cannot drift.

    class CalloutsPlugin(SettingsSpecMixin, BasePlugin):
        SETTINGS_SECTION = "Callouts"
        SETTINGS_TAB = ("pref-tab-callouts", "Callouts")
        SETTINGS = (
            Heading("Sounds"),
            Setting("Sounds", "Play sounds", bool, True),
            Setting("Volume", "Volume (%)", int, 70),
            Setting("Mode", "Mode", "choice", "pulse",
                    choices=(("pulse", "Pulse"), ("switch", "Switch"))),
            Action("check-gaps", "Check now"),
        )

``self.settings()`` returns the section with every default filled in.
``Action`` draws a button; the component handles it in
``settings_action(action_id) -> str``, whose answer is shown beside it.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class Heading:
    text: str
    note: str = ""


@dataclass(frozen=True)
class Setting:
    key: str
    label: str
    kind: Any                 # bool, int, float, str, or "choice"
    default: Any
    choices: tuple = ()       # (value, label) pairs, for "choice"
    help: str = ""


@dataclass(frozen=True)
class Action:
    id: str
    label: str
    help: str = ""


def _coerce(kind, raw):
    if kind is bool:
        return raw if isinstance(raw, bool) else str(raw).strip().lower() in ("1", "true", "on", "yes")
    if kind is int:
        return int(float(str(raw).strip() or 0))
    if kind is float:
        return float(str(raw).strip() or 0)
    return str(raw)


class SettingsSpecMixin:
    """Options tabs and bindings from SETTINGS. See the module docstring."""

    SETTINGS_SECTION: str = ""
    SETTINGS_TAB: tuple[str, str] = ("", "")
    SETTINGS: tuple = ()

    # ── Values ────────────────────────────────────────────────────────────────

    @classmethod
    def settings_defaults(cls) -> dict:
        return {s.key: s.default for s in cls.SETTINGS if isinstance(s, Setting)}

    def settings(self) -> dict:
        try:
            got = self.core.load_setting(self.SETTINGS_SECTION, self.settings_defaults(),
                                         warn=False) or {}
        except Exception:
            got = {}
        out = self.settings_defaults()
        for s in self.SETTINGS:
            if isinstance(s, Setting) and s.key in got:
                try:
                    out[s.key] = _coerce(s.kind if s.kind != "choice" else str, got[s.key])
                except (TypeError, ValueError):
                    pass
        return out

    def _wid(self, key: str) -> str:
        return f"{self.SETTINGS_TAB[0]}-{key}".lower()

    def settings_action(self, action_id: str) -> str:   # override
        return ""

    # ── Terminal dashboard ────────────────────────────────────────────────────

    def preferences_bindings(self) -> dict:
        out = {}
        for s in self.SETTINGS:
            if isinstance(s, Setting):
                typ = bool if s.kind is bool else (str if s.kind == "choice" else s.kind)
                out[self._wid(s.key)] = (self.SETTINGS_SECTION, s.key, typ)
        return out

    def preferences_action(self, bid: str, values: dict | None = None) -> str | None:
        for s in self.SETTINGS:
            if isinstance(s, Action) and bid == self._wid(s.id):
                try:
                    return self.settings_action(s.id) or ""
                except Exception as exc:
                    return f"Failed: {exc}"
        return None

    def tui_preferences_tab(self) -> tuple | None:
        if not self.SETTINGS:
            return None
        values = self.settings()

        def _compose():
            from textual.containers import Horizontal
            from textual.widgets import Button, Input, Label, Select
            bool_opts = [("Off", "false"), ("On", "true")]
            for s in self.SETTINGS:
                if isinstance(s, Heading):
                    yield Label(s.text.upper(), classes="pref-section")
                    if s.note:
                        yield Label(s.note, classes="dim")
                elif isinstance(s, Action):
                    with Horizontal(classes="pref-row"):
                        yield Button(s.label, id=self._wid(s.id))
                    # Under the button, the full width: an answer can run to
                    # several lines (Automation's binding check), which beside
                    # the button ran off the screen's edge.
                    yield Label(s.help, id=f"{self._wid(s.id)}-result", classes="dim pref-result")
                elif isinstance(s, Setting):
                    v = values.get(s.key, s.default)
                    with Horizontal(classes="pref-row"):
                        yield Label(s.label, classes="key")
                        if s.kind is bool:
                            yield Select(bool_opts, value="true" if v else "false",
                                         id=self._wid(s.key), classes="pref-bool-sel",
                                         allow_blank=False)
                        elif s.kind == "choice":
                            opts = [(str(lab), str(val)) for val, lab in s.choices]
                            cur = str(v) if any(str(val) == str(v) for val, _ in s.choices) \
                                else str(s.choices[0][0])
                            yield Select(opts, value=cur, id=self._wid(s.key),
                                         classes="pref-bool-sel", allow_blank=False)
                        else:
                            yield Input(value=str(v), id=self._wid(s.key),
                                        classes="pref-input")
                    if s.help:
                        yield Label(f"  {s.help}", classes="dim")

        return (self.SETTINGS_TAB[0], self.SETTINGS_TAB[1], _compose)

    # ── Desktop window ────────────────────────────────────────────────────────

    def gui_preferences_tab(self) -> tuple | None:
        if not self.SETTINGS:
            return None
        values = self.settings()

        def _build(dlg):
            from PySide6.QtWidgets import (QFormLayout, QHBoxLayout, QLabel,
                                           QPushButton, QScrollArea, QVBoxLayout,
                                           QWidget)
            page = QWidget()
            lay = QVBoxLayout(page)
            lay.setContentsMargins(10, 10, 10, 10)
            form = None
            sec = self.SETTINGS_SECTION
            for s in self.SETTINGS:
                if isinstance(s, Heading) or form is None:
                    title = QLabel((s.text if isinstance(s, Heading) else "").upper())
                    title.setProperty("role", "section")
                    lay.addWidget(title)
                    form = QFormLayout()
                    lay.addLayout(form)
                    if isinstance(s, Heading):
                        if s.note:
                            note = QLabel(s.note)
                            note.setWordWrap(True)
                            note.setProperty("role", "dim")
                            form.addRow(note)
                        continue
                if isinstance(s, Action):
                    row = QHBoxLayout()
                    btn = QPushButton(s.label)
                    result = QLabel(s.help)
                    result.setProperty("role", "dim")
                    result.setWordWrap(True)

                    def _run(_c=False, aid=s.id, lab=result):
                        try:
                            lab.setText(self.settings_action(aid) or "")
                        except Exception as exc:
                            lab.setText(f"Failed: {exc}")
                    btn.clicked.connect(_run)
                    from PySide6.QtCore import Qt
                    # Top-aligned: an answer can run to many lines.
                    row.addWidget(btn, 0, Qt.AlignmentFlag.AlignTop)
                    row.addWidget(result, 1, Qt.AlignmentFlag.AlignTop)
                    form.addRow(row)
                    continue
                v = values.get(s.key, s.default)
                if s.kind is bool:
                    w = dlg._bool_combo(bool(v), sec, s.key)
                elif s.kind == "choice":
                    w = dlg._choice_pairs(str(v), sec, s.key, s.choices)
                else:
                    w = dlg._text_edit(v, sec, s.key, s.kind)
                if s.help:
                    w.setToolTip(s.help)
                form.addRow(s.label, w)
                if s.help:
                    hl = QLabel(s.help)
                    hl.setWordWrap(True)
                    hl.setProperty("role", "dim")
                    form.addRow("", hl)
            lay.addStretch(1)
            scroll = QScrollArea()
            scroll.setWidgetResizable(True)
            scroll.setWidget(page)
            return scroll

        return (self.SETTINGS_TAB[0], self.SETTINGS_TAB[1], _build)
