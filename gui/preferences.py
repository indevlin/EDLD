"""gui/preferences.py — Preferences dialog (Qt).

The Qt counterpart of ``tui/preferences.py``, carrying the same pages, in the
order core/options_pages.py sets:

  General       — journal folder, UTC (and the Backups component's settings)
  Interface     — the interface a plain launch opens, EDCARS, the Dashboard's
                  Helm panel and window layout
  Appearance    — theme; the desktop windows' text face and size, and rows
  Notifications — per-event log levels (0–3)
  Discord       — webhook, user ID, display options
  Combat        — kill messages, inactivity alerts
  Services      — CAPI, EDDN, EDSM, EDAstro, Inara, Raven Colonial (and the
                  EDSM Log component's settings)

with the components' own pages among them.
"""

from __future__ import annotations

import tomllib
from typing import TYPE_CHECKING

from PySide6.QtCore import Qt
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QButtonGroup,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from core.config import config_to_toml
from core.palette import THEME_CHOICES, list_custom_themes, rgb
from gui.edcars import RailPill
from gui.theme import sizes, stylesheet

if TYPE_CHECKING:
    from core.core_api import CoreAPI

# ── Notification event registry ───────────────────────────────────────────────

_NOTIFY_EVENTS = [
    ("RewardEvent",      "Kill (bounty / combat bond)"),
    ("FighterDamage",    "Fighter hull damage"),
    ("FighterLost",      "Fighter destroyed"),
    ("ShieldEvent",      "Ship shields dropped / raised"),
    ("HullEvent",        "Ship hull damaged"),
    ("Died",             "Ship destroyed"),
    ("CargoLost",        "Cargo stolen"),
    ("LowCargoValue",    "Pirate declined to attack"),
    ("PoliceScan",       "Security vessel scan"),
    ("PoliceAttack",     "Security vessel attack"),
    ("FuelStatus",       "Fuel level (routine)"),
    ("FuelWarning",      "Fuel warning"),
    ("FuelCritical",     "Fuel critical"),
    ("MissionUpdate",    "Mission accepted / completed / redirected"),
    ("AllMissionsReady", "All massacre missions ready to hand in"),
    ("MeritEvent",       "Individual merit gain"),
    ("InactiveAlert",    "Inactivity alert"),
    ("RateAlert",        "Kill rate alert"),
    ("InboundScan",      "Incoming cargo scan"),
    ("RouteWarning",     "Route warnings: wrong target, permit, no scoop, dry stretch, re-plot"),
    ("SurveyArrival",    "Arriving at a survey-route system: what is left to do"),
    ("ExploTarget",      "Targeted system: unreported, unscanned or done"),
    ("FirstsWatch",      "Someone else reported your unsold first discoveries"),
    ("MiningCallout",    "Prospector hits, motherlodes and rings you watch for"),
    ("MiningWarning",    "Limpets forgotten, hold nearly full"),
    ("ExobioCallout",    "Safe to sample; a species new to your codex here"),
    ("ExobioWarning",    "Leaving an unfinished sample run"),
    ("CarrierUpkeep",    "Carrier upkeep running low"),
    ("Automation",       "Auto honk and auto-target reports"),
]

_LEVELS = [
    ("0  Off",       "0"),
    ("1  Terminal",  "1"),
    ("2  + Discord", "2"),
    ("3  + Ping",    "3"),
]

# Restart-required keys per config section.  Kept identical to the TUI's table.
_RESTART_KEYS: dict[str, set[str]] = {
    "Settings": {"JournalFolder"},
    "Discord":  {"WebhookURL", "UserID", "Identity",
                 "ForumChannel", "ThreadCmdrNames", "Timestamp"},
    "UI":       {"Theme"},
    "EDDN":     {"Enabled", "TestMode"},
    "EDSM":     {"Enabled", "ApiKey"},
    "EDAstro":  {"Enabled", "UploadCarrierEvents"},
    "Inara":    {"Enabled", "ApiKey"},
}


# ── Page selectors ────────────────────────────────────────────────────────────

#: Least width of the column of page selectors; it widens to its widest
#: selector, which a console's face and letter spacing can push past this.
NAV_W = 156

#: Object name the window takes when opened from EDCARS, which its own rules
#: are scoped to.
EDCARS_SKIN = "edcarsOptions"


def _nav_qss(theme: str) -> str:
    """The Dashboard's selectors: a strip in the title color, the current page
    in the accent on the page's own background with an accent edge, as the
    tabs were."""
    c = rgb(theme)
    return f"""
QWidget#prefNav {{ background-color: {c['title-bg']}; }}
QPushButton#prefPill {{
    background: transparent;
    color: {c['dim']};
    border: none;
    border-left: 3px solid transparent;
    border-radius: 0px;
    text-align: left;
    padding: 5px 10px 5px 9px;
    font-size: {sizes()['body']}pt;
}}
QPushButton#prefPill:hover {{ color: {c['fg']}; }}
QPushButton#prefPill:checked {{
    color: {c['accent']};
    background-color: {c['block-bg']};
    border-left: 3px solid {c['accent']};
    font-weight: 600;
}}
QStackedWidget#prefPages, QStackedWidget#prefPages > QWidget {{
    background-color: {c['block-bg']};
}}
QStackedWidget#prefPages QLabel {{ background: transparent; }}
"""


def _edcars_qss(theme: str) -> str:
    """The window dressed as the console it was opened from (gui/consoles.py):
    the selectors are the rail's pills, a little shorter so that every one of
    them fits; the headings, the buttons and the scrollbars are the console's
    dress for dialogs."""
    from gui import consoles as C
    from gui.edcars import Ink, thin_scrollbars
    console = C.worn()
    ink = Ink(theme)
    s = f"#{EDCARS_SKIN}"
    tall = 30 if console.painted_pills else 16
    return console.qss(ink, s) + console.dialog_qss(ink, s) + f"""
QDialog{s} {{ background-color: {ink.bg}; }}
{s} QWidget#prefNav {{ background: transparent; }}
{s} QPushButton#edcarsPill {{
    padding-top: 8px;
    padding-bottom: 3px;
    min-height: {tall}px;
    font-size: {console.pt(11)};
}}
{s} QStackedWidget#prefPages, {s} QStackedWidget#prefPages > QWidget {{
    background-color: {ink.block_bg};
}}
""" + thin_scrollbars(ink, s)


class _Pill(RailPill):
    """A page selector. Up and Down open the page above or below and take the
    focus with them, wrapping at either end, as the arrow keys moved between
    tabs; left to Qt, they only move the focus, and only in an active window.
    """

    def __init__(self, text: str, step, ink=None) -> None:
        super().__init__(text, ink)
        self._step = step

    def keyPressEvent(self, event) -> None:
        delta = {Qt.Key_Up: -1, Qt.Key_Down: 1}.get(event.key())
        if delta is None or event.modifiers() not in (Qt.NoModifier, Qt.KeypadModifier):
            super().keyPressEvent(event)
            return
        self._step(delta, focus=True)


def _scroll_page() -> tuple[QScrollArea, QVBoxLayout]:
    area = QScrollArea()
    area.setWidgetResizable(True)
    host = QWidget()
    lay = QVBoxLayout(host)
    lay.setContentsMargins(10, 10, 10, 10)
    lay.setSpacing(6)
    area.setWidget(host)
    return area, lay


def _section(text: str) -> QLabel:
    lbl = QLabel(text)
    lbl.setProperty("role", "section")
    return lbl


def _note(text: str) -> QLabel:
    lbl = QLabel(text)
    lbl.setProperty("role", "dim")
    lbl.setWordWrap(True)
    return lbl


class PreferencesDialog(QDialog):
    """Modal preferences dialog — Ctrl+O to open, Escape to cancel.

    ``edcars`` is whether it was opened from EDCARS, which it then dresses as
    (see the module docstring).
    """

    def __init__(self, core: "CoreAPI", theme: str = "default",
                 parent=None, edcars: bool = False) -> None:
        super().__init__(parent)
        self._core = core
        self._cfg = core.cfg
        self._theme = theme
        self._edcars = bool(edcars)
        self._pending: dict[tuple[str, str], object] = {}
        self._restart_required = False
        self._display_selects: dict[str, QComboBox] = {}
        self._fill = None

        self.setWindowTitle("Options")
        self.setMinimumSize(780, 640)
        if self._edcars:
            self.setObjectName(EDCARS_SKIN)
        self.setWindowFlag(Qt.WindowCloseButtonHint, True)

        lay = QVBoxLayout(self)
        # From EDCARS the selectors run against the window's left edge, as the
        # rail does in the main window.
        lay.setContentsMargins(0 if self._edcars else 10, 10, 10, 10)
        lay.setSpacing(8)

        body = QHBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(10 if self._edcars else 0)
        nav = QWidget()
        nav.setObjectName("prefNav")
        nav.setFixedWidth(NAV_W)
        self._nav_lay = QVBoxLayout(nav)
        self._nav_lay.setContentsMargins(0, 0, 0, 0)
        self._nav_lay.setSpacing(5 if self._edcars else 0)
        self._nav = QButtonGroup(self)
        self._nav.setExclusive(True)
        self._pages = QStackedWidget()
        self._pages.setObjectName("prefPages")
        self._nav.idClicked.connect(self._pages.setCurrentIndex)
        self._labels: list[str] = []

        extra = []
        for entry in self._extra_tabs():
            tab_id, tab_label, builder = entry
            try:
                # Builders are handed this dialog so their controls can record
                # changes through the same _record() path as every other page.
                try:
                    widget = builder(self)
                except TypeError:
                    widget = builder()
                if widget is not None:
                    extra.append((str(tab_id), str(tab_label), widget))
            except Exception as exc:
                try:
                    from core import debug as _debug
                    _debug.exception(f"preferences tab {tab_id!r} failed", exc)
                except Exception:
                    pass
        from core import options_pages as OP
        pages, merged = OP.arrange(extra)
        builders = {
            "pref-tab-general":    self._tab_general,
            "pref-tab-interface":  self._tab_interface,
            "pref-tab-appearance": self._tab_appearance,
            "pref-tab-notif":      self._tab_notif,
            "pref-tab-discord":    self._tab_discord,
            "pref-tab-combat":     self._tab_combat,
            "pref-tab-data":       self._tab_data,
        }
        own = {tid: w for tid, _l, w in extra}
        for pid, label in pages:
            widget = builders[pid]() if pid in builders else own[pid]
            for _tid, _lab, part in merged.get(pid, ()):
                self._merge_into(widget, part)
            self._add_page(label, widget)

        if self._edcars:
            from gui.edcars import Ink, _RailFill
            self._fill = _RailFill(Ink(theme))
            self._nav_lay.addWidget(self._fill, 1)
        else:
            self._nav_lay.addStretch(1)
        self.show_page(0)
        body.addWidget(nav, 0)
        body.addWidget(self._pages, 1)
        lay.addLayout(body, 1)

        for keys, step in (("Ctrl+PgDown", 1), ("Ctrl+PgUp", -1),
                           ("Ctrl+Tab", 1), ("Ctrl+Shift+Tab", -1)):
            QShortcut(QKeySequence(keys), self, lambda d=step: self._step(d))

        bottom = QHBoxLayout()
        self._bottom = bottom
        self._restart_note = QLabel("")
        self._restart_note.setProperty("role", "dim")
        bottom.addWidget(self._restart_note, 1)
        buttons = QDialogButtonBox()
        cancel = buttons.addButton("Cancel", QDialogButtonBox.RejectRole)
        apply_btn = buttons.addButton("Apply && Save", QDialogButtonBox.AcceptRole)
        apply_btn.setProperty("role", "primary")
        cancel.clicked.connect(self.reject)
        apply_btn.clicked.connect(self._apply_changes)
        if self._edcars:
            from gui.edcars import caps_font
            for b in (cancel, apply_btn):
                b.setFont(caps_font(11))
        bottom.addWidget(buttons, 0)
        lay.addLayout(bottom)
        self._navw = nav
        self._restyle(theme)

    # ── Pages ─────────────────────────────────────────────────────────────────

    def _add_page(self, label: str, widget: QWidget) -> None:
        idx = self._pages.addWidget(widget)
        if self._edcars:
            from gui.edcars import Ink
            btn = _Pill(label.upper(), self._step, Ink(self._theme))
            btn.setObjectName("edcarsPill")
        else:
            btn = _Pill(label, self._step)
            btn.setObjectName("prefPill")
        btn.setCheckable(True)
        btn.setCursor(Qt.PointingHandCursor)
        if self._edcars:
            # Kerning off, as on the rail: a style sheet cannot say so.
            from gui.edcars import caps_font
            btn.setFont(caps_font(11))
        self._nav.addButton(btn, idx)
        self._nav_lay.addWidget(btn)
        self._labels.append(label)

    def _merge_into(self, page: QWidget, part: QWidget) -> None:
        """A component's page drawn at the foot of one of EDLD's own."""
        host = page.widget() if isinstance(page, QScrollArea) else page
        lay = host.layout() if host is not None else None
        if lay is None:
            return
        if isinstance(part, QScrollArea):
            part = part.takeWidget() or part
            # Set by the scroll area it came from; the page's own shows here.
            part.setAutoFillBackground(False)
        part.setObjectName("prefMerged")
        part.setStyleSheet("QWidget#prefMerged { background: transparent; }")
        inner = part.layout()
        if inner is not None:
            inner.setContentsMargins(0, 0, 0, 0)
            last = inner.itemAt(inner.count() - 1) if inner.count() else None
            if last is not None and last.spacerItem() is not None:
                inner.takeAt(inner.count() - 1)
        lay.insertWidget(max(lay.count() - 1, 0), part)

    def page_labels(self) -> list[str]:
        """The pages' names, top to bottom."""
        return list(self._labels)

    def show_page(self, which: int | str) -> None:
        """Open a page by its position or its name."""
        idx = self._labels.index(which) if isinstance(which, str) else int(which)
        btn = self._nav.button(idx)
        if btn is not None:
            btn.setChecked(True)
            self._pages.setCurrentIndex(idx)

    def current_page(self) -> str:
        return self._labels[self._pages.currentIndex()]

    def _step(self, delta: int, focus: bool = False) -> None:
        n = self._pages.count()
        if n:
            idx = (self._pages.currentIndex() + delta) % n
            self.show_page(idx)
            if focus:
                self._nav.button(idx).setFocus(Qt.TabFocusReason)

    def _restyle(self, theme: str) -> None:
        css = stylesheet(theme) + _nav_qss(theme)
        if self._edcars:
            css += _edcars_qss(theme)
            from gui.edcars import Ink
            ink = Ink(theme)
            for w in [self._fill] + list(self._nav.buttons()):
                if w is not None:
                    w.ink = ink
                    w.update()
        self.setStyleSheet(css)
        self._fit_nav()

    def _fit_nav(self) -> None:
        """The column as wide as its widest selector, NAV_W at least; from
        EDCARS the buttons below start where the pages do."""
        nav = getattr(self, "_navw", None)
        if nav is None:
            return
        width = NAV_W
        for b in self._nav.buttons():
            b.ensurePolished()
            width = max(width, b.sizeHint().width())
        nav.setFixedWidth(width)
        self._bottom.setContentsMargins(width + 10 if self._edcars else 0, 0, 0, 0)

    # ── Widget factories that record on change ────────────────────────────────

    def _bool_combo(self, current: bool, section: str, key: str) -> QComboBox:
        box = QComboBox()
        box.addItem("Off", "false")
        box.addItem("On", "true")
        box.setCurrentIndex(1 if current else 0)
        box.currentIndexChanged.connect(
            lambda _i, s=section, k=key, b=box:
            self._record(s, k, b.currentData() == "true")
        )
        return box

    def _choice_combo(self, current: str, section: str, key: str,
                      choices: "list[str] | tuple[str, ...]") -> QComboBox:
        """A picker over a fixed vocabulary."""
        box = QComboBox()
        for choice in choices:
            box.addItem(str(choice).title(), str(choice))
        current = str(current)
        idx = next((i for i, c in enumerate(choices) if str(c) == current), 0)
        box.setCurrentIndex(idx)
        box.currentIndexChanged.connect(
            lambda _i, s=section, k=key, b=box: self._record(s, k, b.currentData())
        )
        return box

    def _choice_pairs(self, current: str, section: str, key: str,
                      pairs) -> QComboBox:
        """A picker over (value, label) pairs, recording the value."""
        box = QComboBox()
        for value, label in pairs:
            box.addItem(str(label), str(value))
        idx = box.findData(str(current))
        box.setCurrentIndex(idx if idx >= 0 else 0)
        box.currentIndexChanged.connect(
            lambda _i, s=section, k=key, b=box: self._record(s, k, b.currentData()))
        return box

    def _text_edit(self, value: str, section: str, key: str,
                   typ: type = str, password: bool = False,
                   placeholder: str = "") -> QLineEdit:
        edit = QLineEdit(str(value))
        if password:
            edit.setEchoMode(QLineEdit.Password)
        if placeholder:
            edit.setPlaceholderText(placeholder)

        def _changed(text: str) -> None:
            val = text.strip()
            try:
                coerced = typ(val) if val else (0 if typ is int else "")
            except (ValueError, TypeError):
                return
            self._record(section, key, coerced)

        edit.textChanged.connect(_changed)
        return edit

    # ── Tabs ──────────────────────────────────────────────────────────────────

    def _tab_general(self) -> QWidget:
        s = self._cfg.app_settings
        page, lay = _scroll_page()

        lay.addWidget(_section("JOURNALS"))
        form = QFormLayout()
        form.addRow("Journal Folder  ⚠",
                    self._text_edit(s.get("JournalFolder", ""), "Settings",
                                    "JournalFolder"))
        form.addRow("Use UTC Timestamps",
                    self._bool_combo(s.get("UseUTC", False), "Settings", "UseUTC"))
        lay.addLayout(form)
        lay.addStretch(1)
        return page

    def _tab_combat(self) -> QWidget:
        s = self._cfg.app_settings
        page, lay = _scroll_page()

        lay.addWidget(_section("KILL MESSAGES"))
        form2 = QFormLayout()
        form2.addRow("Truncate Names (chars)",
                     self._text_edit(s.get("TruncateNames", 30), "Settings",
                                     "TruncateNames", int))
        form2.addRow("Show Pirate Names",
                     self._bool_combo(s.get("PirateNames", False), "Settings",
                                      "PirateNames"))
        form2.addRow("Show Credit Value per Kill",
                     self._bool_combo(s.get("BountyValue", False), "Settings",
                                      "BountyValue"))
        form2.addRow("Show Victim Faction per Kill",
                     self._bool_combo(s.get("BountyFaction", False), "Settings",
                                      "BountyFaction"))
        form2.addRow("Extended Kill Stats",
                     self._bool_combo(s.get("ExtendedStats", False), "Settings",
                                      "ExtendedStats"))
        lay.addLayout(form2)

        lay.addWidget(_section("INACTIVITY ALERTS"))
        form3 = QFormLayout()
        form3.addRow("Alert After N Minutes Without Kill",
                     self._text_edit(s.get("WarnNoKills", 20), "Settings",
                                     "WarnNoKills", int))
        form3.addRow("Alert When Kill Rate Below (kills/hr)",
                     self._text_edit(s.get("WarnKillRate", 20), "Settings",
                                     "WarnKillRate", int))
        form3.addRow("Alert Cooldown (minutes)",
                     self._text_edit(s.get("WarnCooldown", 15), "Settings",
                                     "WarnCooldown", int))
        lay.addLayout(form3)
        lay.addStretch(1)
        return page

    def _tab_notif(self) -> QWidget:
        nl = self._cfg.notify_levels
        page, lay = _scroll_page()
        form = QFormLayout()
        for key, description in _NOTIFY_EVENTS:
            current = str(nl.get(key, 2))
            box = QComboBox()
            for label, value in _LEVELS:
                box.addItem(label, value)
            idx = next((i for i, (_l, v) in enumerate(_LEVELS) if v == current), 2)
            box.setCurrentIndex(idx)
            box.currentIndexChanged.connect(
                lambda _i, k=key, b=box:
                self._record("LogLevels", k, int(b.currentData()))
            )
            form.addRow(description, box)
        lay.addLayout(form)
        lay.addStretch(1)
        return page

    def _tab_discord(self) -> QWidget:
        d = self._cfg.discord_cfg
        page, lay = _scroll_page()

        lay.addWidget(_section("CONNECTION  (⚠ restart required)"))
        form = QFormLayout()
        form.addRow("Webhook URL",
                    self._text_edit(d.get("WebhookURL", ""), "Discord",
                                    "WebhookURL", password=True))
        form.addRow("User ID (for @mention)",
                    self._text_edit(d.get("UserID", 0), "Discord", "UserID", int))
        lay.addLayout(form)

        lay.addWidget(_section("OPTIONS"))
        form2 = QFormLayout()
        form2.addRow("Use EDLD name and avatar  ⚠",
                     self._bool_combo(d.get("Identity", False), "Discord",
                                      "Identity"))
        form2.addRow("Prefix messages with CMDR name",
                     self._bool_combo(d.get("PrependCmdrName", False), "Discord",
                                      "PrependCmdrName"))
        form2.addRow("Append timestamp to messages  ⚠",
                     self._bool_combo(d.get("Timestamp", False), "Discord",
                                      "Timestamp"))
        form2.addRow("Forum channel thread mode  ⚠",
                     self._bool_combo(d.get("ForumChannel", False), "Discord",
                                      "ForumChannel"))
        form2.addRow("Use CMDR name as thread title  ⚠",
                     self._bool_combo(d.get("ThreadCmdrNames", False), "Discord",
                                      "ThreadCmdrNames"))
        lay.addLayout(form2)
        lay.addStretch(1)
        return page

    def _tab_appearance(self) -> QWidget:
        ui = self._cfg.ui_cfg
        page, lay = _scroll_page()
        lay.addWidget(_section("THEME  (⚠ restart required to persist)"))
        lay.addWidget(_note(
            "The dashboard restyles immediately when a theme is chosen; the "
            "choice is written to config.toml on Apply."))

        box = QComboBox()
        options = list(THEME_CHOICES)
        for tid, stem in list_custom_themes():
            options.append((f"Custom: {stem}", tid))
        for label, value in options:
            box.addItem(label, value)

        # Guard: if the stored theme value does not exist in the options list
        # (a custom theme file that has been removed, or a typo in
        # config.toml), fall back to "default".
        current = ui.get("Theme", "default")
        valid = {v for _l, v in options}
        sel = current if current in valid else "default"
        box.setCurrentIndex(next(i for i, (_l, v) in enumerate(options) if v == sel))

        def _theme_changed() -> None:
            val = str(box.currentData())
            self._record("UI", "Theme", val)
            # Immediate preview, matching the TUI's live restyle.
            applier = getattr(parent_window(self), "apply_theme", None)
            if callable(applier):
                applier(val)
            self._restyle(val)

        box.currentIndexChanged.connect(lambda _i: _theme_changed())
        lay.addWidget(box)

        from gui import theme as T
        lay.addWidget(_section("TEXT"))
        lay.addWidget(_note(
            "The text in the desktop windows and their dialogs. A console's "
            "own lettering — the band, the rail and the headings — keeps its "
            "face and size. Used on Apply."))
        form = QFormLayout()
        lay.addLayout(form)
        form.addRow("Face", self._family_combo(
            str(ui.get("FontFamily", "") or ""), "FontFamily", fixed=False))
        form.addRow("Figures face (fixed width)", self._family_combo(
            str(ui.get("FigureFamily", "") or ""), "FigureFamily", fixed=True))
        size = QComboBox()
        for n in T.FONT_SIZE_CHOICES:
            size.addItem(str(n), n)
        try:
            at = size.findData(int(float(ui.get("FontSize", T.FONT_SIZES["body"]))))
        except (TypeError, ValueError):
            at = size.findData(T.FONT_SIZES["body"])
        size.setCurrentIndex(at if at >= 0 else 0)
        size.currentIndexChanged.connect(
            lambda _i, b=size: self._record("UI", "FontSize", int(b.currentData())))
        form.addRow("Size (pt)", size)

        lay.addWidget(_section("ROWS"))
        form2 = QFormLayout()
        lay.addLayout(form2)
        placement = str(ui.get("ValuePlacement", T.VALUES_EDGE) or T.VALUES_EDGE).lower()
        values = self._choice_pairs(
            T.VALUES_MANUAL if placement == "labels" else placement,
            "UI", "ValuePlacement", T.VALUE_PLACEMENTS)
        if placement not in dict(T.VALUE_PLACEMENTS):
            # An old or unknown value: written as what the picker shows, so
            # that what Apply saves is what was seen.
            self._record("UI", "ValuePlacement", values.currentData())
        form2.addRow("Values", values)
        offsets = []
        for key, label in (("ValueFromLeft", "From the labels' left"),
                           ("ValueFromRight", "From the right edge")):
            edit = self._offset_edit(str(ui.get(key, "") or ""), key)
            offsets.append(edit)
            form2.addRow(label, edit)

        fit_note = _note("")
        fit_note.setProperty("health", "warn")
        fit_note.setVisible(False)
        self._fit_note = fit_note

        def _check_fit(*_a) -> None:
            # What the typed offsets would do in the windows open now.
            from gui.block_base import fit_advice, fit_report
            text = ""
            if values.currentData() == T.VALUES_MANUAL:
                wanted = tuple(T.parse_offset(e.text()) for e in offsets)
                if wanted != (None, None):
                    text = fit_advice(fit_report(wanted))
            fit_note.setText(text)
            fit_note.setVisible(bool(text))

        def _manual(_i=0) -> None:
            on = values.currentData() == T.VALUES_MANUAL
            for e in offsets:
                e.setEnabled(on)
            _check_fit()
        values.currentIndexChanged.connect(_manual)
        for e in offsets:
            e.textChanged.connect(_check_fit)
        _manual()
        form2.addRow(fit_note)
        form2.addRow("Alternate row shading", self._bool_combo(
            bool(ui.get("RowStripes", True)), "UI", "RowStripes"))
        lay.addWidget(_note(
            "Manual alignment places the value column: from the labels' left, "
            "the values start there, left-aligned, or past the longest label; "
            "from the right edge, they end there, right-aligned; with both, "
            "they run between the two. Give pixels, 320, or a share of the "
            "width, 25% (the % is needed), each window measured on its own. "
            "The right edge is firm: offsets a window is too narrow for are "
            "corrected, and said so above. Leave one blank to set only the "
            "other. Shading stripes every other row, in the windows and in "
            "the tables. The terminal dashboard and EDAM keep their own "
            "layout."))
        lay.addStretch(1)
        return page

    def _offset_edit(self, current: str, key: str) -> QLineEdit:
        """Pixels or a share of the width, recorded when blank or understood."""
        from PySide6.QtCore import QRegularExpression
        from PySide6.QtGui import QRegularExpressionValidator
        from gui import theme as T
        edit = QLineEdit(current)
        edit.setPlaceholderText("blank, 320 or 25%")
        edit.setValidator(QRegularExpressionValidator(
            QRegularExpression(r"^\s*(-?\d{0,4}(\.\d*)?\s*(px|p|%)?)?\s*$"), edit))

        def _changed(text: str) -> None:
            text = text.strip()
            if not text or T.parse_offset(text) is not None:
                self._record("UI", key, text)
        edit.textChanged.connect(_changed)
        return edit

    def _family_combo(self, current: str, key: str, fixed: bool) -> QComboBox:
        """The installed faces, after the default; with ``fixed``, only those
        of a fixed width."""
        from PySide6.QtGui import QFontDatabase
        families = [f for f in QFontDatabase.families()
                    if not QFontDatabase.isPrivateFamily(f)
                    and (not fixed or QFontDatabase.isFixedPitch(f))]
        box = QComboBox()
        box.addItem("Default", "")
        for f in families:
            box.addItem(f, f)
        if current and box.findData(current) < 0:
            box.addItem(f"{current} (not installed)", current)
        idx = box.findData(current)
        box.setCurrentIndex(idx if idx >= 0 else 0)
        box.setMaxVisibleItems(20)
        box.currentIndexChanged.connect(
            lambda _i, b=box: self._record("UI", key, b.currentData()))
        return box

    def _tab_interface(self) -> QWidget:
        from core import edcars as _edcars
        from core import helm as _helm
        from core import modes as _modes
        ui = self._cfg.ui_cfg
        page, lay = _scroll_page()
        lay.addWidget(_section("INTERFACE"))
        lay.addWidget(_note(
            f"What EDLD opens when it is started without an interface flag: the "
            f"one chosen here, or the last one started by its shortcut or flag "
            f"(--dasht and the rest), whichever was more recent. "
            f"{_edcars.EDCARS_NAME} groups the windows into sections on a rail, "
            "with the essentials always in its header; the Dashboard shows every "
            "window at once. Used from the next start; nothing restarts now."))
        form = QFormLayout()
        lay.addLayout(form)
        form.addRow("Interface", self._choice_pairs(
            _modes.normalise(ui.get("Interface")), "UI", "Interface",
            _modes.options_choices()))

        lay.addWidget(_section(_edcars.EDCARS_NAME))
        form = QFormLayout()
        lay.addLayout(form)
        form.addRow("New urgent alert", self._choice_pairs(
            _edcars.alert_mode_of(ui), "UI", _edcars.ALERTS_KEY, _edcars.ALERT_MODES))
        form.addRow("Console", self._choice_pairs(
            _edcars.console_of(ui), "UI", _edcars.CONSOLE_KEY, _edcars.console_choices()))
        lay.addWidget(_note(_edcars.console_note()))

        lay.addWidget(_section("DASHBOARD"))
        form = QFormLayout()
        lay.addLayout(form)
        form.addRow(f"{_helm.HELM_NAME} panel", self._bool_combo(
            _helm.panel_wanted(ui), "UI", "HelmPanel"))
        lay.addWidget(_note(
            f"The {_helm.HELM_NAME} panel — the game's controls and EDLD's "
            "automation — runs along the foot of the Dashboard while automation "
            f"is on (Options → Automation). {_edcars.EDCARS_NAME} gives it a "
            "section of its own."))
        self._window_layout(lay)
        lay.addStretch(1)
        return page

    def _tab_data(self) -> QWidget:
        cfg = self._cfg
        eddn, edsm = cfg.eddn_cfg, cfg.edsm_cfg
        edastro, inara = cfg.edastro_cfg, cfg.inara_cfg
        page, lay = _scroll_page()

        lay.addWidget(_section("FRONTIER CAPI  (Companion API)"))
        lay.addWidget(_note(
            "Provides authoritative fleet data from Frontier. Authenticates "
            "via your Frontier account in a browser window."))
        self._capi_status = QLabel(self._get_capi_status())
        self._capi_status.setProperty("role", "dim")
        lay.addWidget(self._capi_status)
        row = QHBoxLayout()
        connect = QPushButton("Connect")
        connect.setProperty("role", "primary")
        connect.clicked.connect(self._capi_connect)
        disconnect = QPushButton("Disconnect")
        disconnect.clicked.connect(self._capi_disconnect)
        row.addWidget(connect)
        row.addWidget(disconnect)
        row.addStretch(1)
        lay.addLayout(row)

        lay.addWidget(_section("EDDN  (Elite Dangerous Data Network)  ⚠"))
        f1 = QFormLayout()
        f1.addRow("Enable EDDN",
                  self._bool_combo(eddn.get("Enabled", False), "EDDN", "Enabled"))
        f1.addRow("Test Mode",
                  self._bool_combo(eddn.get("TestMode", False), "EDDN", "TestMode"))
        lay.addLayout(f1)

        lay.addWidget(_section("EDSM  (Elite Dangerous Star Map)  ⚠"))
        f2 = QFormLayout()
        f2.addRow("Enable EDSM",
                  self._bool_combo(edsm.get("Enabled", False), "EDSM", "Enabled"))
        f2.addRow("EDSM API Key",
                  self._text_edit(edsm.get("ApiKey", ""), "EDSM", "ApiKey",
                                  password=True))
        lay.addLayout(f2)

        lay.addWidget(_section("EDAstro  ⚠"))
        f3 = QFormLayout()
        f3.addRow("Enable EDAstro",
                  self._bool_combo(edastro.get("Enabled", False), "EDAstro",
                                   "Enabled"))
        f3.addRow("Include Carrier Events",
                  self._bool_combo(edastro.get("UploadCarrierEvents", False),
                                   "EDAstro", "UploadCarrierEvents"))
        lay.addLayout(f3)

        lay.addWidget(_section("Inara  ⚠"))
        f4 = QFormLayout()
        f4.addRow("Enable Inara",
                  self._bool_combo(inara.get("Enabled", False), "Inara", "Enabled"))
        f4.addRow("Inara API Key",
                  self._text_edit(inara.get("ApiKey", ""), "Inara", "ApiKey",
                                  password=True))
        lay.addLayout(f4)

        lay.addWidget(_section("RAVEN COLONIAL"))
        lay.addWidget(_note(
            "Sync colonization project supply needs and deliveries to "
            "ravencolonial.com. Leave blank to disable (local tracking still "
            "works)."))
        f5 = QFormLayout()
        colon_cfg = cfg.colonisation_cfg
        f5.addRow("Raven Colonial API Key",
                  self._text_edit(colon_cfg.get("ApiKey", ""), "Colonisation",
                                  "ApiKey", password=True,
                                  placeholder="optional — from ravencolonial.com"))
        lay.addLayout(f5)
        lay.addStretch(1)
        return page

    def _window_layout(self, lay: QVBoxLayout) -> None:
        """The Dashboard's positions, each with the window it shows."""
        from core import layout_model as LM
        lay.addWidget(_section("DASHBOARD WINDOWS"))
        lay.addWidget(_note(
            "Choose which window appears in each position. Only windows of a "
            "matching size fit a position; choosing one already shown "
            "elsewhere moves it. Layout changes apply on restart."))

        asn = LM.load_assignment()
        avail = set(LM.BLOCK_CLASS)
        last_col = None
        form: QFormLayout | None = None
        for info in LM.summary(asn, avail):
            if info["column"] != last_col:
                lay.addWidget(_note(f"{info['column'].title()} column"))
                form = QFormLayout()
                lay.addLayout(form)
                last_col = info["column"]

            box = QComboBox()
            box.addItem("(empty)", "")
            for b in info["eligible"]:
                box.addItem(LM.block_display(b), b)
            value = info["block"] if (info["block"] and
                                      info["block"] in info["eligible"]) else ""
            idx = box.findData(value)
            box.setCurrentIndex(idx if idx >= 0 else 0)
            self._display_selects[info["slot"]] = box
            if form is not None:
                form.addRow(f"{info['slot']}  ·  {info['class_label']}", box)

    # ── Component-injected preference tabs ────────────────────────────────────

    def _extra_tabs(self) -> list[tuple[str, str, object]]:
        """Ask loaded components if they want to inject a preferences tab."""
        result = []
        for plugin in self._core._plugins.values():
            fn = getattr(plugin, "gui_preferences_tab", None)
            if callable(fn):
                try:
                    entry = fn()
                    if entry:
                        result.append(entry)
                except Exception:
                    pass
        return result

    # ── Change collection ─────────────────────────────────────────────────────

    def _record(self, section: str, key: str, value: object) -> None:
        self._pending[(section, key)] = value
        restart = key in _RESTART_KEYS.get(section, set())
        if restart and not self._restart_required:
            self._restart_required = True
            self._restart_note.setText("⚠  Restart required for some changes")

    # ── CAPI helpers ──────────────────────────────────────────────────────────

    def _capi_provider(self):
        try:
            dp = getattr(self._core, "data", None)
            return dp.capi if dp else None
        except Exception:
            return None

    def _get_capi_status(self) -> str:
        capi = self._capi_provider()
        if capi is None:
            return "CAPI provider not available"
        try:
            status = capi.auth_status()
            connected = status.get("connected", False)
            cmdr = status.get("cmdr", "")
            result = status.get("auth_result", "")
            if result == "auth_running":
                return "Waiting for browser authentication…"
            if connected:
                suffix = f" — {cmdr}" if cmdr else ""
                return f"Connected{suffix}"
            return "Not connected"
        except Exception:
            return "Status unavailable"

    def _capi_connect(self) -> None:
        capi = self._capi_provider()
        if capi is None:
            return
        try:
            capi._auth_result = "auth_running"
            capi.authenticate()
            self._capi_status.setText("Waiting for browser authentication…")
        except Exception:
            pass

    def _capi_disconnect(self) -> None:
        capi = self._capi_provider()
        if capi is None:
            return
        try:
            capi.disconnect()
            self._capi_status.setText("Not connected")
        except Exception:
            pass

    # ── Apply ─────────────────────────────────────────────────────────────────

    def _collect_window_assignment(self):
        """Read the Interface page's window combos into a validated assignment."""
        from core import layout_model as LM
        if not self._display_selects:
            return None
        raw = {}
        for sid in LM.slot_ids():
            box = self._display_selects.get(sid)
            if box is None:
                return None
            v = box.currentData()
            raw[sid] = v if (isinstance(v, str) and v) else None
        return LM.normalize_assignment(raw)

    def _apply_changes(self) -> None:
        from core import layout_model as LM

        new_asn = self._collect_window_assignment()
        windows_changed = new_asn is not None and new_asn != LM.load_assignment()

        if not self._pending and not windows_changed:
            self.reject()
            return

        if self._pending:
            config_path = self._cfg.config_path
            try:
                raw = config_path.read_text(encoding="utf-8")
                config = tomllib.loads(raw)
            except Exception as exc:
                self._show_error(f"Could not read config.toml: {exc}")
                return

            profile = self._cfg.config_profile
            for (section, key), value in self._pending.items():
                if profile:
                    target = config.setdefault(profile, {}).setdefault(section, {})
                else:
                    target = config.setdefault(section, {})
                target[key] = value

            try:
                new_toml = config_to_toml(config)
                config_path.write_text(new_toml, encoding="utf-8")
            except Exception as exc:
                self._show_error(f"Could not write config.toml: {exc}")
                return

        if windows_changed:
            LM.save_assignment(new_asn)

        if self._restart_required or windows_changed:
            self._core.restart_process()
        else:
            try:
                self._cfg.refresh(terminal_print=False)
            except Exception:
                pass
            self.accept()

    def _show_error(self, msg: str) -> None:
        self._restart_note.setText(msg)


def parent_window(widget):
    """Walk up to the top-level window that owns ``widget``."""
    w = widget
    while w is not None:
        parent = w.parent()
        if parent is None:
            return w
        w = parent
    return None
