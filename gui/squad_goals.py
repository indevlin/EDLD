"""gui/squad_goals.py — the Squad Goals window (Qt).

Opened from the Squad Goals menu, which EDLD shows only to a commander signed
in to Frontier and in a squadron (core/windows/squad.access). Two tabs:

    Events        the squadron's events and any you were invited to, with
                  standings (core/windows/squad.events_tab, as on EDAM)
    Run an event  the squadron's verified leader only: make, change, end,
                  finalize or cancel an event, invite, remove a member, and the
                  squadron's Discord webhook

Every call to ED Commanders runs off the window's thread; its answer, or why it
failed, shows in the line under the buttons.
"""
from __future__ import annotations

import threading
import time
from datetime import datetime, timezone

from PySide6.QtCore import QDate, QObject, Qt, QTimer, Signal
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QComboBox, QCompleter, QDateEdit, QDialog,
                               QDialogButtonBox, QFormLayout, QHBoxLayout, QHeaderView, QLabel,
                               QLineEdit, QPushButton, QScrollArea, QSpinBox, QTableWidget, QTableWidgetItem,
                               QTabWidget, QVBoxLayout, QWidget)

from core.windows import squad as W
from core.windows.squad import METRICS, parse_credits, parse_weights
from gui.block_base import GuiBlock, RowScroll

REFRESH_MS = 3000

HELP_INTRO = (
    "Make an event for your squadron. Everyone in the squadron who is signed in to Frontier in EDLD or the EDCMDR "
    "client takes part automatically, and only what Frontier's own journal shows counts. Events run whole days, "
    "UTC: from the start of the first day to the end of the last.")
HELP_POOL = "The credits you will pay out. Leave blank for an event with standings only."
HELP_TIERS = ("Optional. Unlock the pool in steps as the squadron's combined total grows: for example 50% of the "
              "pool at 10,000 t and all of it at 25,000 t. With no tiers the whole pool is paid.")
HELP_PLACES = ("How many shares the top places get, in order: \"50, 30, 20\" pays 1st place 50 shares, 2nd 30 and "
               "3rd 20. Each place can get the same as the place above it or less, never more. Leave blank to "
               "share the pool by amount: whoever brings in twice as much gets twice as much.")
HELP_BANDS = ("Optional. Shares for everyone after the top places, in groups: \"the next 50% of them get 5 shares "
              "each, the rest 2\". A group never gets more than a place above it.")
HELP_FLOOR = ("The least a commander must bring in to share in the prize at all. Everyone still shows in the "
              "standings.")
HELP_WHERE = ("Optional: count only what happens in one star system (its name, or its number if you know it), at "
              "one station, outpost, settlement or carrier in it, and only for the commodities you name. Leave a "
              "field blank for anywhere or anything.")
HELP_AUTO = ("ED Commanders posts to the webhook by itself, whether or not you are online: when you save the "
             "event, when it starts, while it runs (every 6 hours for a one-day event, every 12 for two days, "
             "daily for longer), when it ends, and the final results with rewards.")


class _ListCompleter(QCompleter):
    """Suggests for the name being typed after the last comma, and keeps the ones before it."""

    def splitPath(self, path: str) -> list[str]:
        return [path.split(",")[-1].strip()]

    def pathFromIndex(self, index) -> str:
        done = self.widget().text().rsplit(",", 1)[0] if "," in self.widget().text() else ""
        item = super().pathFromIndex(index)
        return f"{done}, {item}" if done else item


class _Bridge(QObject):
    done = Signal(object, object, object)       # callback, result, error


def _utc_day(d: QDate) -> int:
    return int(datetime(d.year(), d.month(), d.day(), tzinfo=timezone.utc).timestamp())


def _qdate(ts: int) -> QDate:
    t = datetime.fromtimestamp(int(ts), timezone.utc)
    return QDate(t.year, t.month, t.day)


def _today() -> QDate:
    t = datetime.now(timezone.utc)
    return QDate(t.year, t.month, t.day)


class EventsBlock(GuiBlock):
    BLOCK_TITLE = "EVENTS"

    def _build_body(self, layout) -> None:
        self._rows = RowScroll()
        layout.addWidget(self._rows, 1)

    def refresh_data(self) -> None:
        self._rows.set_rows(self.render_rows(W.events_tab(self.core, beta=False).rows))


class _Table(QWidget):
    """Rows of two numbers with Add and Remove: tiers and bands."""

    def __init__(self, heads: tuple[str, str], changed) -> None:
        super().__init__()
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        self.t = QTableWidget(0, 2)
        self.t.setHorizontalHeaderLabels(list(heads))
        self.t.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.t.verticalHeader().setVisible(False)
        self.t.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.t.setMaximumHeight(110)
        self.t.itemChanged.connect(lambda *_: changed())
        row = QHBoxLayout()
        add, rem = QPushButton("Add row"), QPushButton("Remove row")
        add.clicked.connect(lambda: (self.t.insertRow(self.t.rowCount()), changed()))
        rem.clicked.connect(lambda: (self.t.removeRow(max(0, self.t.currentRow() if self.t.currentRow() >= 0
                                                          else self.t.rowCount() - 1)), changed()))
        row.addWidget(add)
        row.addWidget(rem)
        row.addStretch(1)
        lay.addWidget(self.t)
        lay.addLayout(row)

    def rows(self) -> list[tuple[str, str]]:
        out = []
        for r in range(self.t.rowCount()):
            a, b = (self.t.item(r, c) for c in (0, 1))
            a, b = (a.text().strip() if a else ""), (b.text().strip() if b else "")
            if a or b:
                out.append((a, b))
        return out

    def set_rows(self, rows: list[tuple]) -> None:
        self.t.blockSignals(True)
        self.t.setRowCount(0)
        for a, b in rows:
            r = self.t.rowCount()
            self.t.insertRow(r)
            self.t.setItem(r, 0, QTableWidgetItem(str(a)))
            self.t.setItem(r, 1, QTableWidgetItem(str(b)))
        self.t.blockSignals(False)


class _InviteDialog(QDialog):
    def __init__(self, parent) -> None:
        super().__init__(parent)
        self.setWindowTitle("Make an invitation")
        f = QFormLayout(self)
        self.kind = QComboBox()
        self.kind.addItem("Anyone verified who has the code", "general")
        self.kind.addItem("One commander", "personal")
        self.name = QLineEdit()
        self.name.setPlaceholderText("Commander name, for an invitation for one commander")
        self.days = QSpinBox()
        self.days.setRange(0, 62)
        self.days.setSpecialValueText("When the event ends")
        self.uses = QSpinBox()
        self.uses.setRange(0, 10000)
        self.uses.setSpecialValueText("No limit")
        f.addRow("For", self.kind)
        f.addRow("Commander", self.name)
        f.addRow("Expires after (days)", self.days)
        f.addRow("Uses", self.uses)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        f.addRow(bb)

    def body(self) -> dict:
        b: dict = {"kind": self.kind.currentData()}
        if b["kind"] == "personal":
            b["name"] = self.name.text().strip()
        if self.days.value():
            b["expires"] = int(time.time() + self.days.value() * 86400)
        if self.uses.value() and b["kind"] == "general":
            b["max_uses"] = self.uses.value()
        return b


#: Field widths, in pixels: wide enough for what goes in them, so a box's arrow sits beside its text and the
#: form reads down one column at any window size.
W_SHORT, W_DATE, W_MID, W_WIDE, W_TABLE = 170, 190, 320, 520, 520
#: The form goes to two columns of groups from this width; the Events list keeps to EVENTS_MAX.
TWO_COLUMNS, EVENTS_MAX = 1480, 860


class _Wrapped(QLabel):
    """Wrapped text at a set width whose height is measured in the font it is drawn in, at layout time, so a
    form row never cuts off its last line."""

    def __init__(self, text: str = "", width: int = 520) -> None:
        super().__init__(text)
        self.setWordWrap(True)
        self.setFixedWidth(width)

    def _height(self) -> int:
        if not self.text():
            return 0
        from PySide6.QtCore import QRect
        self.ensurePolished()                       # the style sheet's font, not the default one
        m = self.contentsMargins()
        w = self.width() - m.left() - m.right()
        r = self.fontMetrics().boundingRect(QRect(0, 0, w, 100000), int(Qt.TextWordWrap), self.text())
        return r.height() + m.top() + m.bottom() + 2

    def minimumSizeHint(self):
        from PySide6.QtCore import QSize
        return QSize(self.width(), self._height())

    def sizeHint(self):
        return self.minimumSizeHint()

    def hasHeightForWidth(self) -> bool:
        return False

    def setText(self, text: str) -> None:
        super().setText(text)
        self.updateGeometry()


def _sized(w, width: int):
    w.setFixedWidth(width)
    return w


def _group(title: str):
    from PySide6.QtWidgets import QGroupBox
    box = QGroupBox(title)
    form = QFormLayout(box)
    form.setFieldGrowthPolicy(QFormLayout.FieldsStayAtSizeHint)
    form.setLabelAlignment(Qt.AlignRight | Qt.AlignVCenter)
    form.setHorizontalSpacing(14)
    form.setVerticalSpacing(8)
    return box, form


class LeaderForm(QWidget):
    """Create event: the squadron leader's form."""

    def __init__(self, win: "SquadGoalsPanel") -> None:
        super().__init__()
        self.win = win
        self.eid: str | None = None
        self.events: dict = {}
        self.stations_for: str = ""
        self.want_market: int | None = None
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 6, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.NoFrame)
        page = QWidget()
        scroll.setWidget(page)
        outer.addWidget(scroll, 1)
        self._scroll = scroll
        top = QVBoxLayout(page)
        top.setContentsMargins(4, 0, 4, 0)
        top.setSpacing(12)
        intro = QLabel(HELP_INTRO)
        intro.setWordWrap(True)
        intro.setProperty("role", "dim")
        intro.setMaximumWidth(2 * (W_WIDE + 260))
        top.addWidget(intro)
        cols = QHBoxLayout()
        cols.setSpacing(18)
        self._col = [QVBoxLayout(), QVBoxLayout()]
        for c in self._col:
            c.setSpacing(12)
            cols.addLayout(c, 0)
        cols.addStretch(1)
        top.addLayout(cols)
        top.addStretch(1)
        self._groups: list = []
        self._cols = 0

        # The event
        box, f = _group("The event")
        self.pick = _sized(QComboBox(), W_MID)
        self.pick.currentIndexChanged.connect(self._picked)
        f.addRow("Event", self.pick)
        self.title = _sized(QLineEdit(), W_MID)
        self.title.setMaxLength(64)
        self.title.setPlaceholderText("Osmium Rush")
        f.addRow("Title", self.title)
        self.note = _sized(QLineEdit(), W_WIDE)
        self.note.setMaxLength(280)
        self.note.setPlaceholderText("Optional: a line for your squadron")
        f.addRow("Note", self.note)
        self._groups.append(box)

        # When
        box, f = _group("When (UTC, whole days)")
        self.starts, self.ends = QDateEdit(), QDateEdit()
        for d in (self.starts, self.ends):
            d.setCalendarPopup(True)
            d.setDisplayFormat("ddd d MMM yyyy")
            d.setDate(_today())
            d.setFixedWidth(W_DATE)
        self.starts.dateChanged.connect(self._dates)
        self.ends.dateChanged.connect(self._dates)
        f.addRow("First day", self.starts)
        f.addRow("Last day", self.ends)
        self.days = self._hint("")
        f.addRow("", self.days)
        self._groups.append(box)

        # What counts
        box, f = _group("What counts")
        self.measure = _sized(QComboBox(), W_MID)
        for key, (label, _unit) in METRICS.items():
            self.measure.addItem(label, key)
        self.measure.currentIndexChanged.connect(self._units)
        f.addRow("Measure", self.measure)
        f.addRow("", self._hint(HELP_WHERE))
        srow = QHBoxLayout()
        self.system = _sized(QLineEdit(), W_MID)
        self.system.setPlaceholderText("Anywhere, or a system such as Ogmar")
        self.system.editingFinished.connect(self._find)
        find = QPushButton("Find")
        find.clicked.connect(self._find)
        srow.addWidget(self.system)
        srow.addWidget(find)
        srow.addStretch(1)
        f.addRow("Star system", srow)
        self.found = self._hint("")
        f.addRow("", self.found)
        self.station = _sized(QComboBox(), W_WIDE)
        self.station.addItem("Anywhere in the system", None)
        f.addRow("Station", self.station)
        self.commodities = _sized(QLineEdit(), W_WIDE)
        self.commodities.setPlaceholderText("Anything, or names such as Osmium, Low Temperature Diamonds")
        self.commodities.editingFinished.connect(self._check_commodities)
        self.completer = _ListCompleter([], self.commodities)
        self.completer.setCaseSensitivity(Qt.CaseInsensitive)
        self.completer.setFilterMode(Qt.MatchContains)
        self.commodities.setCompleter(self.completer)
        self.names_loaded = False
        f.addRow("Commodities", self.commodities)
        self.commodity_note = self._hint("")
        f.addRow("", self.commodity_note)
        self._groups.append(box)

        # Prize
        box, f = _group("Prize")
        self.pool = _sized(QLineEdit(), W_SHORT)
        self.pool.setPlaceholderText("100M")
        self.pool.textChanged.connect(self._preview)
        f.addRow("Prize pool (credits)", self.pool)
        f.addRow("", self._hint(HELP_POOL))
        self.tiers = _Table(("Squadron total reaches", "Share of the pool paid (%)"), self._preview)
        self.tiers.setFixedWidth(W_TABLE)
        f.addRow("Reward tiers", self.tiers)
        f.addRow("", self._hint(HELP_TIERS))
        self.places = _sized(QLineEdit(), W_MID)
        self.places.setPlaceholderText("50, 30, 20")
        self.places.textChanged.connect(self._preview)
        f.addRow("Shares for the top places", self.places)
        f.addRow("", self._hint(HELP_PLACES))
        self.bands = _Table(("The next … % of the rest", "Shares each"), self._preview)
        self.bands.setFixedWidth(W_TABLE)
        f.addRow("Shares for everyone else", self.bands)
        f.addRow("", self._hint(HELP_BANDS))
        self.floor = _sized(QLineEdit(), W_SHORT)
        self.floor.setPlaceholderText("0")
        self.floor.textChanged.connect(self._preview)
        self.floor_label = QLabel("Participation floor")
        f.addRow(self.floor_label, self.floor)
        f.addRow("", self._hint(HELP_FLOOR))
        self.preview = _Wrapped("", W_WIDE)
        self.preview.setProperty("role", "highlight")
        f.addRow("Example", self.preview)
        self._groups.append(box)

        # Discord
        box, f = _group("Discord")
        self.auto = QCheckBox("Post to Discord automatically")
        self.auto.setToolTip(HELP_AUTO)
        f.addRow("Announcements", self.auto)
        f.addRow("", self._hint(HELP_AUTO))
        hook = QHBoxLayout()
        self.hook = _sized(QLineEdit(), W_WIDE)
        self.hook.setPlaceholderText("https://discord.com/api/webhooks/…")
        hs, hf, ha = QPushButton("Save"), QPushButton("Forget"), QPushButton("Announce now")
        hs.setToolTip("Saved for your squadron and used for every event until you forget it.")
        hf.setToolTip("Forget the squadron's webhook.")
        ha.setToolTip("Post the event to Discord as it stands now: before it starts, when; while it runs, time "
                      "left and standings; after it ends, closing standings; once final, the results with rewards.")
        hs.clicked.connect(self._hook_save)
        hf.clicked.connect(self._hook_forget)
        ha.clicked.connect(lambda: self._act("announce", "Posted to Discord."))
        hook.addWidget(self.hook)
        for b in (hs, hf, ha):
            hook.addWidget(b)
        hook.addStretch(1)
        f.addRow("Webhook", hook)
        self._groups.append(box)

        # Members
        box, f = _group("Members")
        member = QHBoxLayout()
        self.member = _sized(QLineEdit(), W_MID)
        self.member.setPlaceholderText("Commander name")
        rm, rs = QPushButton("Remove from events"), QPushButton("Restore")
        rm.clicked.connect(lambda: self._member("remove"))
        rs.clicked.connect(lambda: self._member("restore"))
        member.addWidget(self.member)
        member.addWidget(rm)
        member.addWidget(rs)
        member.addStretch(1)
        f.addRow("Member", member)
        self._groups.append(box)
        self._place(1)

        # The actions, always in view under the form.
        bar = QHBoxLayout()
        self.b_save = QPushButton("Save event")
        self.b_save.setProperty("role", "primary")
        self.b_end = QPushButton("End now")
        self.b_final = QPushButton("Finalize results")
        self.b_cancel = QPushButton("Cancel event")
        self.b_invite = QPushButton("Make invitation…")
        self.b_final.setToolTip("After the event ends, make the results final now instead of waiting "
                                "the 24 hours late journal days are read for.")
        self.b_save.clicked.connect(self._save)
        self.b_end.clicked.connect(lambda: self._act("close", "Ended now. Late journal days are read for 24 hours, "
                                                     "then the results are final."))
        self.b_final.clicked.connect(lambda: self._act("finalize", "The results are final."))
        self.b_cancel.clicked.connect(lambda: self._act("cancel", "Cancelled."))
        self.b_invite.clicked.connect(self._invite)
        for b in (self.b_save, self.b_end, self.b_final, self.b_cancel, self.b_invite):
            bar.addWidget(b)
        bar.addStretch(1)
        outer.addLayout(bar)
        self.status = QLabel("")
        self.status.setWordWrap(True)
        outer.addWidget(self.status)
        self._units()
        self._dates()
        self._fill_pick([])
        self._buttons()

    # ── layout ──────────────────────────────────────────────────────────────
    #: Which groups go in the left column when there are two: the event, when, and what counts; the prize,
    #: Discord and members on the right.
    LEFT = 3

    def _place(self, cols: int) -> None:
        if cols == self._cols:
            return
        self._cols = cols
        for c in self._col:
            while c.count():
                c.takeAt(0)
        for i, g in enumerate(self._groups):
            self._col[1 if cols == 2 and i >= self.LEFT else 0].addWidget(g)
        for c in self._col:
            c.addStretch(1)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._place(2 if event.size().width() >= TWO_COLUMNS else 1)

    # ── helpers ─────────────────────────────────────────────────────────────
    @staticmethod
    def _hint(text: str) -> QLabel:
        lab = _Wrapped(text, W_WIDE)
        lab.setProperty("role", "dim")
        return lab

    @staticmethod
    def _set(lab: QLabel, text: str) -> None:
        lab.setText(text)

    def say(self, text: str, bad: bool = False) -> None:
        self.status.setText(f"<span style='color:#e06c5a'>{text}</span>" if bad else text)

    def _unit(self) -> str:
        return METRICS.get(self.measure.currentData(), ("", "t"))[1]

    def _units(self) -> None:
        u = "credits" if self._unit() == "cr" else "tons"
        self.floor_label.setText(f"Participation floor ({u})")
        self.tiers.t.setHorizontalHeaderLabels([f"Squadron total reaches ({u})", "Share of the pool paid (%)"])
        self._preview()

    def _dates(self) -> None:
        self.ends.setMinimumDate(self.starts.date())
        self.ends.setMaximumDate(self.starts.date().addDays(61))
        if self.eid is None:
            self.starts.setMinimumDate(_today().addDays(-14))
        n = self.starts.date().daysTo(self.ends.date()) + 1
        self._set(self.days, f"{n} day{'s' if n != 1 else ''}: from 00:00:00 UTC on the first to 23:59:59 UTC on the last.")

    def payout(self) -> dict:
        tiers = [{"target": parse_credits(a), "pct": int(float(b))} for a, b in self.tiers.rows()]
        bands = [{"pct": float(a), "w": float(b)} for a, b in self.bands.rows()]
        return {"pool": parse_credits(self.pool.text()), "places": parse_weights(self.places.text()),
                "bands": bands, "min": parse_credits(self.floor.text()), "tiers": tiers}

    def _preview(self) -> None:
        try:
            self.preview.setText(W.preview(self.payout()))
        except (ValueError, TypeError):
            self.preview.setText("…")


    # ── events in the picker ────────────────────────────────────────────────
    def _fill_pick(self, events: list) -> None:
        mine = [e for e in events if e.get("leader") and e.get("state") in ("upcoming", "open", "settling", "closing")]
        ids = [None] + [e["id"] for e in mine]
        have = [self.pick.itemData(i) for i in range(self.pick.count())]
        self.events = {e["id"]: e for e in mine}
        if ids == have:
            return
        cur = self.eid
        self.pick.blockSignals(True)
        self.pick.clear()
        self.pick.addItem("New event", None)
        for e in mine:
            self.pick.addItem(f"{e['title']} ({e['state']})", e["id"])
        i = self.pick.findData(cur)
        self.pick.setCurrentIndex(i if i >= 0 else 0)
        self.pick.blockSignals(False)
        if i < 0 and cur is not None:
            self._picked()

    def _picked(self) -> None:
        self.eid = self.pick.currentData()
        ev = self.events.get(self.eid) if self.eid else None
        if ev is None:
            self.eid = None
            for w in (self.title, self.note, self.pool, self.places, self.floor, self.system, self.commodities):
                w.clear()
            self.tiers.set_rows([])
            self.bands.set_rows([])
            self.starts.setDate(_today())
            self.ends.setDate(_today())
            self.auto.setChecked(False)
            self._stations([], None)
        else:
            self.title.setText(ev.get("title") or "")
            self.note.setText(ev.get("note") or "")
            self.starts.setMinimumDate(_qdate(ev["starts"]).addDays(-14))
            self.starts.setDate(_qdate(ev["starts"]))
            self.ends.setDate(_qdate(ev["ends"]))
            self.measure.setCurrentIndex(max(0, self.measure.findData(ev.get("metric"))))
            p = ev.get("payout") or {}
            self.pool.setText(f"{int(p.get('pool') or 0):,}" if p.get("pool") else "")
            self.places.setText(", ".join(f"{x:g}" for x in p.get("places") or []))
            self.bands.set_rows([(f"{b['pct']:g}", f"{b['w']:g}") for b in p.get("bands") or []])
            self.tiers.set_rows([(f"{int(t['target']):,}", str(int(t["pct"]))) for t in p.get("tiers") or []])
            self.floor.setText(f"{int(p.get('min') or 0):,}" if p.get("min") else "")
            f = ev.get("filters") or {}
            sysn = (f.get("systems") or [{}])[0].get("name", "")
            self.system.setText(sysn)
            self.commodities.setText(", ".join(f.get("commodity_names") or f.get("commodities") or []))
            self.auto.setChecked(bool(ev.get("auto_announce")))
            markets = f.get("markets") or []
            self.want_market = markets[0] if markets else None
            self.stations_for = ""
            if sysn:
                self._find()
        self._dates()
        self._buttons()
        self._preview()

    def _buttons(self) -> None:
        ev = self.events.get(self.eid) if self.eid else None
        st = ev.get("state") if ev else None
        self.b_save.setText("Save changes" if ev else "Save event")
        self.b_end.setEnabled(st in ("upcoming", "open"))
        self.b_final.setEnabled(st in ("settling", "closing"))
        self.b_cancel.setEnabled(ev is not None)
        self.b_invite.setEnabled(st in ("upcoming", "open"))

    def load_names(self) -> None:
        """Every commodity name, once, for the suggestions."""
        if self.names_loaded:
            return
        self.names_loaded = True

        def done(j, err):
            if err is None:
                from PySide6.QtCore import QStringListModel
                self.completer.setModel(QStringListModel(j.get("all_commodities") or [], self.completer))
            else:
                self.names_loaded = False
        self.win.call(lambda: self.win.plugin().squad_admin("lookup", list=True), done)

    def set_webhook(self, saved: bool) -> None:
        self.hook.setPlaceholderText("A webhook is saved for your squadron (hidden). Forget it, or paste a new one."
                                     if saved else "https://discord.com/api/webhooks/…")

    # ── system, station, commodities ────────────────────────────────────────
    def _stations(self, stations: list, want) -> None:
        self.station.clear()
        self.station.addItem("Anywhere in the system", None)
        for s in stations:
            kind = f" ({s['type']})" if s.get("type") else ""
            self.station.addItem(f"{s['name']}{kind}", s["market_id"])
        i = self.station.findData(want) if want is not None else 0
        self.station.setCurrentIndex(i if i >= 0 else 0)

    def _find(self) -> None:
        text = self.system.text().strip()
        if not text:
            self._set(self.found, "")
            self._stations([], None)
            self.stations_for = ""
            return
        if text == self.stations_for:
            return
        self.stations_for = text
        self._set(self.found, "Looking it up…")
        want = self.want_market if self.want_market is not None else self.station.currentData()

        def done(j, err):
            if err is not None:
                self._set(self.found, str(err))
                return
            if not j.get("system"):
                self._set(self.found, f"No known star system is called {text}. Check the spelling.")
                self._stations([], None)
                return
            sy = j["system"]
            self.system.setText(sy["name"])
            self.stations_for = sy["name"]
            n = len(j.get("stations") or [])
            self._set(self.found, f"{sy['name']} (system address {sy['id64']}): {n} place{'s' if n != 1 else ''} "
                               f"with a market." if n else f"{sy['name']} (system address {sy['id64']}).")
            self._stations(j.get("stations") or [], want)
            self.want_market = None
        self.win.call(lambda: self.win.plugin().squad_admin("lookup", system=text), done)

    def _check_commodities(self, then=None) -> None:
        typed = [x.strip() for x in self.commodities.text().split(",") if x.strip()]
        if not typed:
            self._set(self.commodity_note, "")
            if then:
                then([])
            return

        def done(j, err):
            if err is not None:
                self._set(self.commodity_note, str(err))
                return
            names, bad = [], []
            for c in j.get("commodities") or []:
                if c.get("symbol"):
                    names.append(c["name"])
                else:
                    sug = c.get("suggest") or []
                    bad.append(f"{c['typed']}" + (f" (did you mean {', '.join(sug)}?)" if sug else ""))
            if bad:
                self._set(self.commodity_note, "Not found: " + "; ".join(bad))
                return
            self.commodities.setText(", ".join(names))
            self._set(self.commodity_note, "")
            if then:
                then(names)
        self.win.call(lambda: self.win.plugin().squad_admin("lookup", commodities=typed), done)

    # ── actions ─────────────────────────────────────────────────────────────
    def _body(self, commodities: list) -> dict:
        title = self.title.text().strip()
        if not title:
            raise ValueError("Give the event a title.")
        body = {"title": title, "note": self.note.text().strip() or None, "metric": self.measure.currentData(),
                "starts": _utc_day(self.starts.date()), "ends": _utc_day(self.ends.date()) + 86399,
                "filters": {"systems": [self.system.text().strip()] if self.system.text().strip() else [],
                            "markets": [self.station.currentData()] if self.station.currentData() else [],
                            "commodities": commodities},
                "payout": self.payout(), "auto_announce": self.auto.isChecked()}
        if self.eid:
            body["id"] = self.eid
        return body

    def _save(self) -> None:
        def go(names):
            try:
                body = self._body(names)
            except ValueError as e:
                self.say(str(e), True)
                return

            def done(j, err):
                if err is not None:
                    self.say(str(err), True)
                    return
                ev = j.get("event") or {}
                self.eid = ev.get("id")
                self.events[self.eid] = ev
                self.say(f"Saved {ev.get('title')}. Your squadron sees it now.")
                self.win.refresh(force=True)
            self.say("Saving…")
            self.win.call(lambda: self.win.plugin().squad_admin("save", **body), done)
        self._check_commodities(then=go)

    def _act(self, action: str, ok: str) -> None:
        if not self.eid:
            self.say("Choose the event first.", True)
            return
        eid = self.eid

        def done(j, err):
            self.say(str(err), True) if err is not None else self.say(ok)
            self.win.refresh(force=True)
        self.win.call(lambda: self.win.plugin().squad_admin(action, id=eid), done)

    def _invite(self) -> None:
        dlg = _InviteDialog(self)
        if not dlg.exec():
            return
        body = dict(dlg.body(), id=self.eid)

        def done(j, err):
            if err is not None:
                self.say(str(err), True)
                return
            who = f"CMDR {j['for']} only" if j.get("for") else "anyone verified who has it"
            self.say(f"Invitation code <b>{j['code']}</b> ({who}). They enter it in EDLD under Options › ED "
                     f"Commanders › Invitation code.")
            self.status.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.win.call(lambda: self.win.plugin().squad_admin("invite", **body), done)

    def _member(self, action: str) -> None:
        name = self.member.text().strip()
        if not name:
            self.say("Type the member's commander name.", True)
            return

        def done(j, err):
            if err is not None:
                self.say(str(err), True)
            elif action == "remove":
                self.say(f"CMDR {j.get('removed')} no longer counts in your squadron's events.")
            else:
                self.say(f"CMDR {j.get('restored')} counts in your squadron's events again.")
        self.win.call(lambda: self.win.plugin().squad_admin(action, name=name), done)

    def _hook_save(self) -> None:
        url = self.hook.text().strip()
        if not url:
            self.say("Paste the webhook address from Discord (Server Settings › Integrations › Webhooks).", True)
            return

        def done(j, err):
            if err is not None:
                self.say(str(err), True)
                return
            self.hook.clear()
            self.set_webhook(True)
            self.say("Webhook saved for your squadron" + (", and a test message posted." if j.get("tested")
                                                         else ", but the test message did not go: check it."))
        self.win.call(lambda: self.win.plugin().squad_admin("webhook", url=url, test=True), done)

    def _hook_forget(self) -> None:
        def done(j, err):
            if err is not None:
                self.say(str(err), True)
                return
            self.hook.clear()
            self.set_webhook(False)
            self.say("Webhook forgotten.")
        self.win.call(lambda: self.win.plugin().squad_admin("forget-webhook"), done)


BETA_TEXT = ("BETA · Squad Goals is new and still being tested. Standings, payouts and announcements may "
             "change as it is fixed, so check them before paying anyone. Feedback and bug reports are very welcome "
             "on the Indevlin Discord: discord.indevlin.com")


class SquadGoalsPanel(QWidget):
    """The Squad Goals page: the beta notice, then Events and, for the squadron's leader, Create event. It sits
    in EDCARS's Squad Goals section and in the window the menu opens."""

    REFRESH_MS = REFRESH_MS

    def __init__(self, core, theme: str = "default", parent=None) -> None:
        super().__init__(parent)
        self.core = core
        self._bridge = _Bridge()
        self._bridge.done.connect(lambda cb, res, err: cb(res, err))
        self.setObjectName("squadPanel")
        # Labels and check boxes take their group's background, not the window's.
        self.setStyleSheet("#squadPanel QGroupBox QLabel, #squadPanel QGroupBox QCheckBox "
                           "{ background: transparent; }")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        beta = QLabel(BETA_TEXT)
        beta.setWordWrap(True)
        beta.setProperty("role", "beta")
        beta.setObjectName("squadBeta")
        lay.addWidget(beta)
        self.tabs = QTabWidget()
        lay.addWidget(self.tabs, 1)

        ev = QWidget()
        el = QVBoxLayout(ev)
        el.setContentsMargins(0, 0, 0, 0)
        self.block = EventsBlock(core, theme=theme)
        self.block.setMaximumWidth(EVENTS_MAX)
        el.addWidget(self.block, 1)
        row = QHBoxLayout()
        join, sync = QPushButton("Use invitation…"), QPushButton("Update standings")
        join.clicked.connect(self._join)
        sync.clicked.connect(self._sync)
        self.ev_status = QLabel("")
        row.addWidget(join)
        row.addWidget(sync)
        row.addWidget(self.ev_status, 1)
        el.addLayout(row)
        self.tabs.addTab(ev, "Events")

        self.form = LeaderForm(self)
        self.tabs.addTab(self.form, "Create event")
        self.tabs.setTabVisible(1, False)
        self._timer = QTimer(self)
        self._timer.timeout.connect(self.refresh)
        self._timer.start(self.REFRESH_MS)
        self.refresh(force=True)

    def plugin(self):
        return W.plugin(self.core)

    def call(self, fn, cb) -> None:
        """fn() off this thread; cb(result, error) back on it."""
        def run():
            try:
                res, err = fn(), None
            except Exception as e:              # ProtoError's text is written for the player
                res, err = None, e
            self._bridge.done.emit(cb, res, err)
        threading.Thread(target=run, daemon=True, name="squad-goals-call").start()

    def refresh_data(self) -> None:
        self.refresh()

    def refresh(self, force: bool = False) -> None:
        if not (force or self.isVisible()):
            return
        acc = W.access(self.core)
        lead = bool(acc.get("lead"))
        self.tabs.setTabVisible(1, lead)
        if not lead and self.tabs.currentIndex() == 1:
            self.tabs.setCurrentIndex(0)
        if lead:
            self.form.load_names()
        self.block.refresh_data()
        p = self.plugin()
        view = p.squad_view() if p is not None else {}
        self.form._fill_pick(view.get("events") or [])
        self.form._buttons()
        self.form.set_webhook(bool(view.get("webhook")))

    def _join(self) -> None:
        from PySide6.QtWidgets import QInputDialog
        code, ok = QInputDialog.getText(self, "Squad Goals", "Invitation code:")
        if not ok or not code.strip():
            return

        def done(j, err):
            self.ev_status.setText(str(err) if err is not None else
                                   f"You are in {(j.get('event') or {}).get('title') or 'the event'}.")
            self.refresh(force=True)
        self.call(lambda: self.plugin().squad_join(code), done)

    def _sync(self) -> None:
        self.plugin().squad_sync_now()
        self.ev_status.setText("Reading your events, and your journal from Frontier, now.")


class SquadGoalsWindow(QWidget):
    """The panel in a window of its own: the Squad Goals menu's, in the Dashboard style."""

    def __init__(self, core, theme: str = "default", parent=None) -> None:
        super().__init__(parent, Qt.Window)
        self.setWindowTitle("Squad Goals (beta)")
        self.resize(900, 820)
        lay = QVBoxLayout(self)
        self.panel = SquadGoalsPanel(core, theme=theme)
        lay.addWidget(self.panel)
        self.tabs, self.form = self.panel.tabs, self.panel.form

    def refresh(self, force: bool = False) -> None:
        self.panel.refresh(force=force)
