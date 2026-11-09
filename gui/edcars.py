"""gui/edcars.py — the desktop window in the EDCARS style.

The windows themselves are the dashboard's own blocks, unchanged, framed.

Shapes are painted, colors come from the theme's palette — custom themes
included.
"""
from __future__ import annotations

import time
from typing import Callable, Optional

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QFont, QKeySequence, QPainter, QShortcut
from PySide6.QtWidgets import (
    QHBoxLayout, QLabel, QPushButton, QSizePolicy, QStackedWidget, QVBoxLayout,
    QWidget,
)

from core import edcars as H
from core.palette import _blend, rgb
from gui import consoles as C
from gui.blocks.status import RadioPanel

# ── Geometry ──────────────────────────────────────────────────────────────────

RAIL_W = 176          # the elbow and the rail
BAND_H = 54           # the header band
STRIP_H = 30          # the strip of facts under the band
ELBOW_R = 44          # outer radius of the elbow
FILLET_R = 22         # the concave curve where band and elbow meet
CAP_W = 44            # the rounded cap closing the band on the right
GAP = 5               # between pills, and between band and cap


# ── Font ──────────────────────────────────────────────────────────────────────

def caps_family() -> str:
    """The face the worn console sets its chrome in: Euro Caps for EDCARS,
    bundled beside the code or in the frozen bundle. A build without it draws
    the headings in a fallback face rather than failing."""
    return C.worn().family()


def caps_font(pt: float, bold: bool = True) -> QFont:
    """The worn console's chrome face — the band's title and clock, the strip's
    labels and the rail's pills.
    """
    return C.worn().font(pt, bold)


# ── Colors ───────────────────────────────────────────────────────────────────

class Ink:
    """The theme's palette, plus the mixes EDCARS draws with."""

    def __init__(self, theme: str) -> None:
        c = rgb(theme)
        self.c = c
        self.bg = c["bg"]
        self.fg = c["fg"]
        self.dim = c["dim"]
        self.accent = c["accent"]
        self.block_bg = c["block-bg"]
        self.border = c["border"]
        self.pill = _blend(c["bg"], c["accent"], 0.58)
        self.pill_hover = _blend(c["bg"], c["accent"], 0.82)
        self.fill = _blend(c["bg"], c["accent"], 0.35)
        self.cap = _blend(c["bg"], c["accent"], 0.60)
        self.title_bg = c["title-bg"]
        self.green = c["green"]
        self.amber = c["amber"]
        self.red = c["red"]
        self.red_dim = _blend(c["bg"], c["red"], 0.45)
        self.tone = {"good": c["green"], "warn": c["amber"], "crit": c["red"]}


def _qss(ink: Ink) -> str:
    # The scrollbars are EDCARS's own thin ones, a 3 px thumb in the cap color
    # with no track, as EDAM draws them (ui/Scrollbars.kt); the Dashboard
    # layout keeps the theme's. The pills, the band's text, the frames' titles
    # and the Helm panel's buttons are the worn console's.
    return f"""
#edcars {{ background-color: {ink.bg}; }}
#edcars QWidget#edcarsBand, #edcars QWidget#edcarsStrip {{ background: transparent; }}
#edcars QLabel#edcarsVal {{ color: {ink.fg}; background: transparent; }}
#edcars QLabel#edcarsVal[tone="good"] {{ color: {ink.tone['good']}; }}
#edcars QLabel#edcarsVal[tone="warn"] {{ color: {ink.tone['warn']}; }}
#edcars QLabel#edcarsVal[tone="crit"] {{ color: {ink.tone['crit']}; }}
#edcars QLabel#edcarsAlert {{ color: {ink.red}; background: transparent; font-weight: 600; }}
#edcars QWidget#edcarsRadio QLabel {{ background: transparent; }}
#edcars QLabel#edcarsRadioNow {{ color: {ink.fg}; }}
#edcars QLabel#helmStatus {{ color: {ink.dim}; background: transparent; }}
""" + C.worn().qss(ink, "#edcars") + thin_scrollbars(ink, "#edcars")


def dialog_qss(theme: str) -> str:
    """The worn console's dress for dialogs, scoped to every QDialog (message
    boxes included), or "" when the window is the Dashboard. Appended to the
    window's style sheet, which dialogs inherit, and to those dialogs that set
    a style sheet of their own."""
    console = C.active()
    if console is None:
        return ""
    ink = Ink(theme)
    return console.dialog_qss(ink, "QDialog") + thin_scrollbars(ink, "QDialog")


def thin_scrollbars(ink: Ink, scope: str) -> str:
    """The thin scrollbars for everything under ``scope``: a 3 px thumb in the
    cap color with no track. Shared with the Options window when it is opened
    from EDCARS (gui/preferences.py)."""
    s = scope
    return f"""
{s} QScrollBar:vertical {{ width: 5px; background: transparent; border: none; }}
{s} QScrollBar:horizontal {{ height: 5px; background: transparent; border: none; }}
{s} QScrollBar::handle {{ background: {ink.cap}; border-radius: 1px; margin: 1px; }}
{s} QScrollBar::handle:vertical {{ min-height: 18px; }}
{s} QScrollBar::handle:horizontal {{ min-width: 18px; }}
{s} QScrollBar::add-line, {s} QScrollBar::sub-line {{ width: 0; height: 0; }}
{s} QScrollBar::add-page, {s} QScrollBar::sub-page {{ background: none; }}
"""


# ── Header ────────────────────────────────────────────────────────────────────

class _ElidedLabel(QLabel):
    """A label that ends in "…" when it does not fit."""

    def minimumSizeHint(self):
        hint = super().minimumSizeHint()
        hint.setWidth(0)
        return hint

    #: Shorter forms of the text, tried in turn before ending in "…"
    #: (core.edcars.title_forms).
    forms: tuple[str, ...] = ()

    def set_forms(self, forms) -> None:
        forms = tuple(forms) or ("",)
        if forms != self.forms:
            self.forms = forms
            self.setText(forms[0])
            self.update()

    def shown_text(self) -> str:
        """What fits: the first form that does, else the last one cut short."""
        width = self.contentsRect().width()
        fm = self.fontMetrics()
        text = self.text()
        for form in self.forms[1:]:
            if fm.horizontalAdvance(text) <= width:
                break
            text = form
        return fm.elidedText(text, Qt.ElideRight, width)

    def paintEvent(self, event):
        from PySide6.QtGui import QPainter
        p = QPainter(self)
        r = self.contentsRect()
        text = self.shown_text()
        self.style().drawItemText(p, r, int(self.alignment()), self.palette(), self.isEnabled(),
                                  text, self.foregroundRole())


class EdcarsHeader(QWidget):
    """The band, the elbow, and the strip of facts."""

    def __init__(self, ink: Ink, parent=None) -> None:
        super().__init__(parent)
        self.ink = ink
        self.setFixedHeight(BAND_H + STRIP_H)
        outer = QVBoxLayout(self)
        left, right = C.worn().header_margins()
        outer.setContentsMargins(left, 0, right, 0)
        outer.setSpacing(0)

        band = QWidget()
        band.setObjectName("edcarsBand")
        band.setFixedHeight(BAND_H)
        bl = QHBoxLayout(band)
        bl.setContentsMargins(4, 0, 0, 7)
        bl.setSpacing(16)
        self.cmdr = _ElidedLabel("")
        self.cmdr.setObjectName("edcarsCmdr")
        self.cmdr.setFont(caps_font(19))
        self.cmdr.setAlignment(Qt.AlignLeft | Qt.AlignBottom)
        self.clock = QLabel("")
        self.clock.setObjectName("edcarsClock")
        self.clock.setFont(caps_font(19))
        self.clock.setAlignment(Qt.AlignRight | Qt.AlignBottom)
        bl.addWidget(self.cmdr, 1)
        bl.addWidget(self.clock, 0)
        outer.addWidget(band)

        strip = QWidget()
        strip.setObjectName("edcarsStrip")
        strip.setFixedHeight(STRIP_H)
        self._strip = QHBoxLayout(strip)
        self._strip.setContentsMargins(4, 4, 0, 0)
        self._strip.setSpacing(6)
        self._fields: dict[str, tuple[QLabel, QLabel]] = {}
        self._order: list[str] = []
        self.alert = QLabel("")
        self.alert.setObjectName("edcarsAlert")
        self.alert.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.alert.setVisible(False)
        self._strip.addStretch(1)
        self._strip.addWidget(self.alert, 0)
        outer.addWidget(strip)

    # Labels are made once per key and reused, so the strip does not flicker
    # being torn down and rebuilt on every tick.
    def _pair(self, key: str, label: str) -> tuple[QLabel, QLabel]:
        pair = self._fields.get(key)
        if pair is None:
            k = QLabel(label.upper())
            k.setObjectName("edcarsKey")
            k.setFont(caps_font(9))
            # The long facts end in "…" on a narrow window, rather than hold
            # it wider than the screen with fuel and hull off the end.
            v = _ElidedLabel("") if key in H.GIVES_WAY else QLabel("")
            v.setObjectName("edcarsVal")
            v.setTextFormat(Qt.PlainText)
            pair = (k, v)
            self._fields[key] = pair
        return pair

    def set_strip(self, fields: list[H.Field]) -> None:
        shown = [f for f in fields if f.key != "cmdr"]
        keys = [f.key for f in shown]
        if keys != self._order:
            # Reorder only when the set of facts changes — entering an SRV
            # adds none and removes none, so this is rare.
            for k, v in self._fields.values():
                self._strip.removeWidget(k)
                self._strip.removeWidget(v)
                k.setParent(None)
                v.setParent(None)
            at = 0
            for f in shown:
                k, v = self._pair(f.key, f.label)
                if at:
                    k.setContentsMargins(14, 0, 0, 0)
                else:
                    k.setContentsMargins(0, 0, 0, 0)
                self._strip.insertWidget(at, k, 0)
                self._strip.insertWidget(at + 1, v, 0)
                at += 2
            self._order = keys
        for f in shown:
            k, v = self._pair(f.key, f.label)
            if v.text() != f.value:
                v.setText(f.value)
            if (v.property("tone") or "") != f.tone:
                v.setProperty("tone", f.tone)
                v.style().unpolish(v)
                v.style().polish(v)

    def set_title(self, forms) -> None:
        """The title, longest form first (core.edcars.title_forms); a bare
        string is the one form."""
        self.cmdr.set_forms([forms] if isinstance(forms, str) else forms)

    def set_alert(self, text: str) -> None:
        self.alert.setText(text)
        self.alert.setVisible(bool(text))

    def set_clock(self, text: str) -> None:
        if self.clock.text() != text:
            self.clock.setText(text)

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        C.worn().paint_header(p, self.width(), self.height(), self.ink)
        p.end()


# ── Rail ──────────────────────────────────────────────────────────────────────

class _RailFill(QWidget):
    """The rail below the pills, ending in a rounded foot."""

    def __init__(self, ink: Ink) -> None:
        super().__init__()
        self.ink = ink
        self.setMinimumHeight(40)
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Expanding)

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        C.worn().paint_fill(p, self.width(), self.height(), self.ink)
        p.end()


class RailPill(QPushButton):
    """A pill on the rail, or a page selector in a dialog dressed as one.

    ``ink`` is None for a plain button.
    """

    def __init__(self, text: str, ink: Optional["Ink"] = None) -> None:
        super().__init__(text)
        self.ink = ink

    def paintEvent(self, event) -> None:
        console = C.worn()
        if self.ink is not None and console.painted_pills:
            p = QPainter(self)
            console.paint_pill(p, self, self.ink)
            p.end()
            return
        super().paintEvent(event)
        if self.ink is not None:
            p = QPainter(self)
            console.paint_pill(p, self, self.ink)
            p.end()


class EdcarsRail(QWidget):
    """The section pills, then Settings — the last pill, as on EDAM's rail —
    then the rail running on down to its foot.
    """

    def __init__(self, ink: Ink, on_pick: Callable[[str], None],
                 on_settings: Optional[Callable[[], None]] = None) -> None:
        super().__init__()
        self.setFixedWidth(RAIL_W)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, GAP, 0, 0)
        lay.setSpacing(GAP)
        self.pills: dict[str, QPushButton] = {}
        for i, sec in enumerate(H.SECTIONS):
            b = RailPill(sec.label.upper(), ink)
            b.setObjectName("edcarsPill")
            b.setFont(caps_font(12))
            b.setCheckable(True)
            b.setAutoExclusive(True)
            b.setToolTip(f"{sec.label}  (Ctrl+{i + 1})")
            b.setCursor(Qt.PointingHandCursor)
            b.clicked.connect(lambda _c=False, sid=sec.id: on_pick(sid))
            lay.addWidget(b)
            self.pills[sec.id] = b
        self.settings: Optional[RailPill] = None
        if on_settings is not None:
            b = RailPill("SETTINGS", ink)
            b.setObjectName("edcarsPill")
            b.setFont(caps_font(12))
            b.setToolTip("Options  (Ctrl+O)")
            b.setCursor(Qt.PointingHandCursor)
            b.clicked.connect(lambda _c=False: on_settings())
            lay.addWidget(b)
            self.settings = b
        self.fill = _RailFill(ink)
        lay.addWidget(self.fill, 1)

    def select(self, sid: str) -> None:
        pill = self.pills.get(sid)
        if pill is not None and not pill.isChecked():
            pill.setChecked(True)

    def set_pulse(self, sid: str, state: str) -> None:
        pill = self.pills.get(sid)
        if pill is None or (pill.property("pulse") or "") == state:
            return
        pill.setProperty("pulse", state)
        pill.style().unpolish(pill)
        pill.style().polish(pill)
        pill.update()


# ── Frames ────────────────────────────────────────────────────────────────────

class EdcarsFrame(QWidget):
    """A window in a section: a heading with a bar to its right, and the
    window's body beside a thin accent rule.

    The block's own title row is hidden — the heading replaces it.
    """

    def __init__(self, ink: Ink, title: str, body: QWidget) -> None:
        super().__init__()
        self.ink = ink
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(4)
        self.title = QLabel(title.upper())
        self._body_lay = lay
        self.title.setObjectName("edcarsFrameTitle")
        self.title.setFixedHeight(22)
        self.title.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Fixed)
        head = QHBoxLayout()
        head.setContentsMargins(0, 0, 0, 0)
        head.addWidget(self.title, 0)
        head.addStretch(1)
        lay.addLayout(head)
        holder = QWidget()
        holder.setObjectName("edcarsFrameBody")
        hl = QVBoxLayout(holder)
        hl.setContentsMargins(*C.worn().holder_margins)
        hl.setSpacing(0)
        hl.addWidget(body, 1)
        row = QHBoxLayout()
        row.setContentsMargins(C.worn().frame_indent, 0, 0, 0)   # EDCARS: the accent rule
        row.setSpacing(0)
        row.addWidget(holder, 1)
        lay.addLayout(row, 1)
        old_title = getattr(body, "_title", None)
        if isinstance(old_title, QLabel):
            old_title.setVisible(False)

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        C.worn().paint_frame(p, self, self.ink)
        p.end()


# ── Alerts ────────────────────────────────────────────────────────────────────

class EdcarsAlerts(QWidget):
    """Every alert the alerts component holds, newest first, urgent ones in
    the alert color. The dashboard's Crew / Alerts window shows five; with a
    section to itself there is room for all of them."""

    def __init__(self, core, ink: Ink, on_clear: Callable[[], None]) -> None:
        super().__init__()
        self.core = core
        self.ink = ink
        lay = QVBoxLayout(self)
        lay.setContentsMargins(4, 4, 4, 4)
        lay.setSpacing(2)
        top = QHBoxLayout()
        self.count = QLabel("")
        self.count.setObjectName("edcarsKey")
        self.count.setFont(caps_font(9))
        clear = QPushButton("Clear alerts")
        clear.setProperty("role", "link")
        clear.setToolTip("Clear all alerts  (Ctrl+L)")
        clear.clicked.connect(on_clear)
        top.addWidget(self.count, 1)
        top.addWidget(clear, 0)
        lay.addLayout(top)
        self._rows_host = QVBoxLayout()
        self._rows_host.setSpacing(3)
        lay.addLayout(self._rows_host)
        lay.addStretch(1)
        self._labels: list[QLabel] = []

    def refresh_data(self) -> None:
        alerts = self.core.plugin_call("alerts", "get_alerts") or []
        while len(self._labels) < len(alerts):
            lbl = QLabel("")
            lbl.setTextFormat(Qt.PlainText)
            lbl.setWordWrap(True)
            self._rows_host.addWidget(lbl)
            self._labels.append(lbl)
        now = time.monotonic()
        for i, lbl in enumerate(self._labels):
            if i >= len(alerts):
                lbl.setVisible(False)
                continue
            a = alerts[i]
            age = ""
            if a.get("mono_time") is not None:
                secs = int(now - float(a["mono_time"]))
                age = (f"{secs}s" if secs < 60 else f"{secs // 60}m" if secs < 3600
                       else f"{secs // 3600}h")
                age = f"   {age} ago"
            lbl.setText(f"{a.get('emoji', '')}  {a.get('text', '')}{age}")
            urgent = H.is_urgent(a)
            opacity = self.core.plugin_call("alerts", "opacity_for", a) or 1.0
            colour = (self.ink.red if urgent and opacity >= 0.7
                      else self.ink.dim if opacity < 0.7 else self.ink.fg)
            lbl.setStyleSheet(f"color: {colour}; background: transparent;"
                              + (" font-weight: 600;" if urgent else ""))
            lbl.setVisible(True)
        n = len(alerts)
        self.count.setText("NO ALERTS" if not n else f"{n} ALERT{'S' if n != 1 else ''}")


# ── Radio strip ───────────────────────────────────────────────────────────────

class EdcarsRadio(RadioPanel):
    """The radio as a strip along the foot of the window."""

    def __init__(self, core) -> None:  # noqa: D401 — not RadioPanel.__init__
        QWidget.__init__(self)
        from core.radio import RadioController
        self.setObjectName("edcarsRadio")
        # A QWidget subclass paints a style sheet's background only when asked.
        self.setAttribute(Qt.WA_StyledBackground, True)
        self._block = None
        self._ctl = RadioController(core)
        self._shown_options = []
        self._shown_problems = None

        row = QHBoxLayout(self)
        row.setContentsMargins(RAIL_W + 10, 4, 12, 4)
        row.setSpacing(8)
        label = QLabel("RADIO")
        label.setObjectName("edcarsRadioState")
        row.addWidget(label, 0)
        from PySide6.QtWidgets import QComboBox
        self._combo = QComboBox()
        self._combo.setMinimumWidth(200)
        self._combo.currentIndexChanged.connect(self._on_station_changed)
        row.addWidget(self._combo, 0)
        self._add_btn = self._button("+", self._open_add)
        self._edit_btn = self._button("✎", self._open_edit)
        self._del_btn = self._button("−", self._open_delete)
        self._add_btn.setToolTip("Add a station")
        self._edit_btn.setToolTip("Edit the selected station")
        self._del_btn.setToolTip("Delete the selected station")
        for b in (self._add_btn, self._edit_btn, self._del_btn):
            row.addWidget(b, 0)
        self._play_btn = self._button("▶ Play", self._ctl.toggle_play)
        self._down_btn = self._button("Vol −", self._ctl.volume_down)
        self._up_btn = self._button("Vol +", self._ctl.volume_up)
        self._mute_btn = self._button("Mute", self._ctl.toggle_mute)
        for b in (self._play_btn, self._down_btn, self._up_btn, self._mute_btn):
            row.addWidget(b, 0)
        self._state = QLabel("")
        self._state.setObjectName("edcarsRadioState")
        row.addWidget(self._state, 0)
        self._now = QLabel("")
        self._now.setObjectName("edcarsRadioNow")
        self._now.setTextFormat(Qt.PlainText)
        self._now.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        row.addWidget(self._now, 1)

        self._sync_options()
        self._redraw()
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._poll)
        self._timer.start(self.POLL_MS)

    def _redraw(self) -> None:
        v = self._ctl.view()
        self._del_btn.setEnabled(v["can_delete"])
        self._edit_btn.setEnabled(v["can_edit"])
        self._play_btn.setText(v["play_label"])
        self._play_btn.setEnabled(v["can_play"])
        self._mute_btn.setText(v["mute_label"])
        self._state.setText(f"{v['status']}   {v['volume']}".upper())
        now = v["now"] if v["now"] not in ("", "—") else ""
        on_air = v["on_air"] if v["on_air"] not in ("", "—") else ""
        self._now.setText("  ·  ".join(x for x in (on_air, now) if x))
        tip = "\n".join(v["problems"]) if v["problems"] else ""
        self._combo.setToolTip(tip)


# ── The shell ─────────────────────────────────────────────────────────────────

class _Group:
    """Several widgets refreshed under one dashboard block id."""

    def __init__(self, *members) -> None:
        self.members = [m for m in members if m is not None]

    def refresh_data(self) -> None:
        for m in self.members:
            m.refresh_data()


class EdcarsShell(QWidget):
    """Header, rail, sections and radio strip."""

    #: Pulse half-period, and how long a pulse runs before it settles to a
    #: steady red: long enough to be noticed from the other side of a room,
    #: not so long it nags.
    PULSE_MS = 550

    def __init__(self, core, theme: str, block_classes: dict, block_ids: dict,
                 on_clear_alerts: Callable[[], None], console: str = H.EDCARS_ID,
                 on_options: Optional[Callable[[], None]] = None) -> None:
        super().__init__()
        self.setObjectName("edcars")
        # Worn before anything is built: sizes, margins and faces come from it.
        self.console = C.set_active(console if console in C.CONSOLES else H.EDCARS_ID)
        self.core = core
        self.theme = theme
        self.ink = Ink(theme)
        self.setStyleSheet(_qss(self.ink))
        self.blocks: dict[str, object] = {}
        self._pages: dict[str, int] = {}
        self._current = H.SECTIONS[0].id
        self._seen_urgent: set = set()
        self._unacked: Optional[dict] = None
        self._pulse_on = False

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        self.header = EdcarsHeader(self.ink)
        outer.addWidget(self.header)

        body = QHBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(0)
        self.rail = EdcarsRail(self.ink, self.show_section, on_settings=on_options)
        body.addWidget(self.rail, 0)
        self.stack = QStackedWidget()
        content = QWidget()
        cl = QVBoxLayout(content)
        cl.setContentsMargins(16, 10, 12, 8)
        cl.addWidget(self.stack, 1)
        body.addWidget(content, 1)
        outer.addLayout(body, 1)

        self.radio = EdcarsRadio(core)
        outer.addWidget(self.radio, 0)

        self._build_sections(block_classes, block_ids, on_clear_alerts)

        for i, sec in enumerate(H.SECTIONS[:9]):
            sc = QShortcut(QKeySequence(f"Ctrl+{i + 1}"), self)
            sc.activated.connect(lambda sid=sec.id: self.show_section(sid))

        self._pulse = QTimer(self)
        self._pulse.timeout.connect(self._tick_pulse)
        self._clock = QTimer(self)
        self._clock.timeout.connect(self._tick_clock)
        self._clock.start(1000)
        self._tick_clock()
        self.refresh_header()
        self.show_section(self._current)

    # ── Construction ──────────────────────────────────────────────────────────

    def _make(self, window: str, part: str, classes: dict, ids: dict, clear):
        """The widget for one part, registering whatever must be refreshed."""
        if window == "alerts":
            w = EdcarsAlerts(self.core, self.ink, clear)
            self._alerts_view = w
            self._register("block-status", w)
            return w
        cls = classes.get(window)
        if cls is None:
            return None
        bid = ids[window]
        if window == "commander":
            block = self.blocks.get(bid)
            if block is None:
                block = cls(self.core, theme=self.theme, split_fleet=True)
                self.blocks[bid] = block
            elif isinstance(block, _Group):
                block = block.members[0]
            return block.fleet_tabs if part == "fleet" else block
        if window == "status":
            block = cls(self.core, theme=self.theme, crew_only=True)
            self._register(bid, block)
            return block
        if window == "helm":
            # The Helm panel, at EDCARS's size, in its caps.
            block = cls(self.core, theme=self.theme, compact=False)
            block.set_fonts(caps_font(11), caps_font(10))
            self._register(bid, block)
            return block
        block = cls(self.core, theme=self.theme)
        self._register(bid, block)
        return block

    def _register(self, bid: str, widget) -> None:
        have = self.blocks.get(bid)
        if have is None:
            self.blocks[bid] = widget
        elif isinstance(have, _Group):
            have.members.append(widget)
        else:
            self.blocks[bid] = _Group(have, widget)

    def _build_sections(self, classes: dict, ids: dict, clear) -> None:
        for sec in H.SECTIONS:
            page = QWidget()
            row = QHBoxLayout(page)
            row.setContentsMargins(0, 0, 0, 0)
            row.setSpacing(18)
            widths = H.section_columns(sec)
            ncols = len(widths)
            for c in range(ncols):
                col = QVBoxLayout()
                col.setSpacing(14)
                for part in (p for p in sec.parts if p.column == c):
                    w = self._make(part.window, part.part, classes, ids, clear)
                    if w is None:
                        continue
                    col.addWidget(EdcarsFrame(self.ink, part.title or part.window, w),
                                  part.weight * 100)
                row.addLayout(col, widths[c] * 100)
            self._pages[sec.id] = self.stack.addWidget(page)

    # ── Sections ──────────────────────────────────────────────────────────────

    def show_section(self, sid: str) -> None:
        if sid not in self._pages:
            return
        self._current = sid
        self.stack.setCurrentIndex(self._pages[sid])
        self.rail.select(sid)
        if sid == H.ALERTS_SECTION:
            self.acknowledge()

    def current_section(self) -> str:
        return self._current

    # ── Header ────────────────────────────────────────────────────────────────

    def refresh_header(self) -> None:
        state = getattr(self.core, "state", None)
        try:
            self.header.set_strip(H.strip(state))
            self.header.set_title(H.title_forms(state))
        except Exception as exc:
            from core.ui_helpers import report_block_fault
            faults = self.__dict__.setdefault("_faults", set())
            report_block_fault(self.core, "edcars-header", exc, faults)

    def _tick_clock(self) -> None:
        self.header.set_clock(H.clock_text())

    # ── Alerts ────────────────────────────────────────────────────────────────

    def note_alerts(self) -> None:
        """Look for urgent alerts not seen before; pulse, and maybe switch.

        Called whenever the alerts may have changed.
        """
        alerts = self.core.plugin_call("alerts", "get_alerts") or []
        fresh = []
        for a in alerts:
            if not H.is_urgent(a):
                continue
            key = (a.get("mono_time"), a.get("text"))
            if key not in self._seen_urgent:
                self._seen_urgent.add(key)
                fresh.append(a)
        if len(self._seen_urgent) > 256:
            live = {(a.get("mono_time"), a.get("text")) for a in alerts}
            self._seen_urgent &= live
        if not fresh:
            if not alerts:
                self.acknowledge()
            return
        newest = fresh[0]
        cfg = getattr(getattr(self.core, "cfg", None), "ui_cfg", None) or {}
        if H.alert_mode_of(cfg) == H.ALERTS_SWITCH:
            self._unacked = newest
            self.show_section(H.ALERTS_SECTION)
            self._set_unacked(newest)          # the pulse still marks it
            return
        if self._current == H.ALERTS_SECTION:
            return
        self._set_unacked(newest)

    def _set_unacked(self, alert: dict) -> None:
        self._unacked = alert
        self.header.set_alert(f"{alert.get('emoji', '')}  {alert.get('text', '')}".strip())
        if not self._pulse.isActive():
            self._pulse_started = time.monotonic()
            self._pulse.start(self.PULSE_MS)
        self._pulse_started = time.monotonic()

    def acknowledge(self) -> None:
        """The alerts have been seen: stop pulsing and clear the header."""
        self._unacked = None
        self._pulse.stop()
        self._pulse_on = False
        self.rail.set_pulse(H.ALERTS_SECTION, "")
        self.header.set_alert("")

    def _tick_pulse(self) -> None:
        if self._unacked is None:
            self.acknowledge()
            return
        # After ten seconds the pill stops flashing and stays red until the
        # section is opened: noticed by then, or not looking.
        if time.monotonic() - getattr(self, "_pulse_started", 0) > 10:
            self._pulse.stop()
            self.rail.set_pulse(H.ALERTS_SECTION, "on")
            return
        self._pulse_on = not self._pulse_on
        self.rail.set_pulse(H.ALERTS_SECTION, "on" if self._pulse_on else "dim")
        if self._current == H.ALERTS_SECTION and self._pulse_on is False:
            # Switched there by the setting: one flash is enough.
            self.acknowledge()

    # ── Theme preview ─────────────────────────────────────────────────────────

    def set_theme(self, theme: str) -> None:
        self.theme = theme
        ink = Ink(theme)
        self.ink = ink
        for w in [self.header, self.rail.fill] + self.findChildren(EdcarsFrame) \
                + self.findChildren(EdcarsAlerts) + list(self.rail.pills.values()) \
                + ([self.rail.settings] if self.rail.settings is not None else []):
            w.ink = ink
        self.setStyleSheet(_qss(ink))
        self.update()
        for w in self.findChildren(QWidget):
            w.update()
