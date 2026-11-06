"""
gui/preferences.py — Preferences dialog (Qt).

The Qt counterpart of ``tui/preferences.py``, carrying the same six pages:

  General       — journal folder, UTC, display toggles, inactivity alerts
  Notifications — per-event log levels (0–3)
  Discord       — webhook, user ID, display options
  Appearance    — theme, the interface a plain launch opens, EDCARS alerts,
                  the Helm panel
  Data          — CAPI, EDDN, EDSM, EDAstro, Inara, Raven Colonial
  Display       — window layout (position → window assignment)

The pages are picked from a column down the left, one selector per page, the
components' pages after EDLD's own in alphabetical order. A row of tabs had
grown past the window's width with sixteen of them, and scrolled sideways.
Opened from EDCARS, the column is EDCARS's rail — its pills, in Euro Caps, with
the rail's foot below them — and the window takes its headings, buttons and
scrollbars; opened from the Dashboard, it wears the theme as before.

Changes are collected in a pending dict and written to config.toml on Apply,
using the same ``config_to_toml`` writer and the same ``_RESTART_KEYS`` table
as the TUI, so the two screens produce byte-identical config files for the
same edits.  Settings marked ⚠ require a restart; the dialog restarts the
process via ``core.restart_process()`` when Apply is confirmed.

Components may inject their own page by implementing ``gui_preferences_tab()``,
mirroring the TUI's ``tui_preferences_tab()`` hook.  A component that
implements only the TUI hook simply doesn't appear here, which is the correct
behaviour for one that builds Textual widgets.
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
from gui.theme import FONT_SIZES, stylesheet

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

#: Width of the column of page selectors: the longest label, "Notifications",
#: with room to spare in either skin.
NAV_W = 156

#: Object name the window takes when opened from EDCARS, which its own rules
#: are scoped to.
EDCARS_SKIN = "edcarsOptions"


def _nav_qss(theme: str) -> str:
    """The Dashboard's selectors: a strip in the title colour, the current page
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
    font-size: {FONT_SIZES['body']}pt;
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
    Opened from EDCARS it is one of the console's pills, lamps and all."""

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
    (see the module docstring). Ctrl+PgDown and Ctrl+PgUp, or Ctrl+Tab and
    Ctrl+Shift+Tab, move between pages, as they did between the tabs; the
    arrow keys do the same while a selector has the focus.
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

        for label, build in (("General", self._tab_general),
                             ("Notifications", self._tab_notif),
                             ("Discord", self._tab_discord),
                             ("Appearance", self._tab_appearance),
                             ("Data", self._tab_data),
                             ("Display", self._tab_display)):
            self._add_page(label, build())
        extra = []
        for tab_id, tab_label, builder in self._extra_tabs():
            try:
                # Builders are handed this dialog so their controls can record
                # changes through the same _record() path as every other page.
                # Without it an injected page could draw its settings but never
                # save them, which is why nothing used this hook before.  The
                # bare call is kept for any builder written against the old
                # signature.
                try:
                    widget = builder(self)
                except TypeError:
                    widget = builder()
                if widget is not None:
                    extra.append((str(tab_label), widget))
            except Exception as exc:
                try:
                    from core import debug as _debug
                    _debug.exception(f"preferences tab {tab_id!r} failed", exc)
                except Exception:
                    pass
        # The components' pages in the order a commander reads the column,
        # not the order their modules happen to load in.
        for label, widget in sorted(extra, key=lambda e: e[0].casefold()):
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
        # Under the pages, not the selectors, from EDCARS.
        bottom.setContentsMargins(NAV_W + 10 if self._edcars else 0, 0, 0, 0)
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
        """A picker over a fixed vocabulary.

        Anything with a closed set of valid values should use this rather than
        a text field: a typed setting can be wrong and has to be validated,
        reported and ignored, and the commander finds out by noticing that
        nothing happened.
        """
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

        lay.addWidget(_section("SESSION"))
        form = QFormLayout()
        form.addRow("Journal Folder  ⚠",
                    self._text_edit(s.get("JournalFolder", ""), "Settings",
                                    "JournalFolder"))
        form.addRow("Use UTC Timestamps",
                    self._bool_combo(s.get("UseUTC", False), "Settings", "UseUTC"))
        lay.addLayout(form)

        lay.addWidget(_section("DISPLAY"))
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
        # config.toml), fall back to "default" rather than leaving the combo
        # on an arbitrary entry.
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

        from core import edcars as _edcars
        from core import helm as _helm
        from core import modes as _modes
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
        form.addRow(f"{_edcars.EDCARS_NAME}: new urgent alert", self._choice_pairs(
            _edcars.alert_mode_of(ui), "UI", _edcars.ALERTS_KEY, _edcars.ALERT_MODES))
        form.addRow(f"{_edcars.EDCARS_NAME}: console", self._choice_pairs(
            _edcars.console_of(ui), "UI", _edcars.CONSOLE_KEY, _edcars.console_choices()))
        form.addRow(f"Dashboard: {_helm.HELM_NAME} panel", self._bool_combo(
            _helm.panel_wanted(ui), "UI", "HelmPanel"))
        lay.addWidget(_note(_edcars.console_note()))
        lay.addWidget(_note(
            f"The {_helm.HELM_NAME} panel — the game's controls and EDLD's "
            "automation — runs along the foot of the Dashboard while automation "
            f"is on (Options → Automation). {_edcars.EDCARS_NAME} gives it a "
            "section of its own."))
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
            "Sync colonisation project supply needs and deliveries to "
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

    def _tab_display(self) -> QWidget:
        from core import layout_model as LM
        page, lay = _scroll_page()
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
                lay.addWidget(_section(f"{info['column'].upper()} COLUMN"))
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
        lay.addStretch(1)
        return page

    # ── Component-injected preference tabs ────────────────────────────────────

    def _extra_tabs(self) -> list[tuple[str, str, object]]:
        """Ask loaded components if they want to inject a preferences tab.

        A component may expose ``gui_preferences_tab()`` returning
        ``(tab_id, tab_label, builder)`` where ``builder()`` returns a QWidget.
        Only called for components that implement the method — invisible to
        all other code.
        """
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
        """Read the Display tab's combos into a validated assignment."""
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
