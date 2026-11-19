"""tests/test_gui_text_rows.py — the desktop windows' text face and size, row
shading and value placement ([UI] FontFamily, FigureFamily, FontSize,
RowStripes, ValuePlacement, ValueFromLeft, ValueFromRight), and where Options
keeps them.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


@pytest.fixture
def qt():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    from gui import theme as T
    yield app
    T.configure({})
    from gui import block_base as B
    for w in app.topLevelWidgets():
        w.close()
    B._MEASURED.clear()


def _settle(app):
    for _ in range(3):
        app.processEvents()


# ── Settings ──────────────────────────────────────────────────────────────────

def test_the_settings_are_read_forgivingly(qt):
    from gui import theme as T
    T.configure({})
    assert T.sizes() == T.FONT_SIZES
    assert T.row_stripes() and T.value_offsets() is None
    T.configure({"FontSize": "14", "RowStripes": "off", "ValuePlacement": "MANUAL",
                 "ValueFromLeft": "320", "ValueFromRight": "25%",
                 "FigureFamily": "Fira Mono"})
    assert T.sizes()["body"] == 14 and T.sizes()["title"] == 15
    assert not T.row_stripes() and T.value_offsets() == ((320.0, False), (25.0, True))
    assert T.mono_families().startswith('"Fira Mono", ')
    T.configure({"FontSize": 99, "ValuePlacement": "middle"})
    assert T.sizes()["body"] == T.FONT_SIZE_CHOICES[-1]
    assert T.value_offsets() is None
    # The first form of manual alignment, beside the labels, is kept.
    T.configure({"ValuePlacement": "labels"})
    assert T.value_offsets() == ((0.0, False), None)
    # ...but offsets given since are not ignored.
    T.configure({"ValuePlacement": "labels", "ValueFromLeft": "30%", "ValueFromRight": "10%"})
    assert T.value_offsets() == ((30.0, True), (10.0, True))
    T.configure({"FontSize": "big"})
    assert T.sizes()["body"] == T.FONT_SIZES["body"]


def test_the_style_sheet_follows_the_size_and_figures_face(qt):
    from gui import theme as T
    T.configure({"FontSize": 15, "FigureFamily": "Fira Mono"})
    css = T.stylesheet("default")
    assert "font-size: 15pt;" in css and "font-size: 16pt;" in css
    assert 'QLabel[col="value"] {{ font-family: "Fira Mono"'.replace("{{", "{") in css
    assert 'QWidget[kvrow="true"][stripe="true"]' in css


def test_the_face_is_the_applications_and_blank_restores_it(qt):
    from gui import theme as T
    before = qt.font().family()
    T.configure({"FontFamily": "DejaVu Serif"})
    T.apply_app_font(qt)
    assert qt.font().families()[0] == "DejaVu Serif"
    T.configure({})
    T.apply_app_font(qt)
    assert qt.font().family() == before


def test_the_defaults_are_documented():
    from core.config import CFG_DEFAULTS_UI
    for key in ("FontFamily", "FigureFamily", "FontSize", "RowStripes", "ValuePlacement",
                "ValueFromLeft", "ValueFromRight"):
        assert key in CFG_DEFAULTS_UI
    assert CFG_DEFAULTS_UI["ValuePlacement"] == "edge" and CFG_DEFAULTS_UI["RowStripes"] is True


# ── Rows ──────────────────────────────────────────────────────────────────────

def _pane(qt, rows_spec):
    from core.palette import rgb
    from gui.block_base import HRule, KVRow, NoteRow, RowScroll, SecHdr
    pal = rgb("default")
    rows = []
    for kind, *a in rows_spec:
        rows.append({"hdr": lambda t: SecHdr(t, pal),
                     "kv": lambda k, v: KVRow(k, v, palette=pal),
                     "note": lambda t: NoteRow(t, palette=pal),
                     "rule": lambda: HRule()}[kind](*a))
    pane = RowScroll()
    pane.resize(1400, 400)
    pane.show()
    pane.set_rows(rows)
    _settle(qt)
    return pane, rows


SPEC = [("hdr", "Combat"), ("kv", "Kills", "15  6.3 /hr"), ("kv", "Bounties", "4,512,000 cr"),
        ("note", "a note under bounties"), ("kv", "Combat bonds", "0 cr"),
        ("hdr", "Exploration"), ("kv", "Jumps", "10  475 ly"), ("kv", "Bodies scanned", "2")]


def test_every_other_row_is_shaded_counting_from_each_heading(qt):
    from gui import theme as T
    T.configure({"RowStripes": True})
    _pane_, rows = _pane(qt, SPEC)
    got = [bool(r.property("stripe")) for r in rows]
    assert got == [False, False, True, True, False, False, False, True]


def test_no_shading_when_it_is_off(qt):
    from gui import theme as T
    T.configure({"RowStripes": False})
    _pane_, rows = _pane(qt, SPEC)
    assert not any(r.property("stripe") for r in rows)


def _value_rights(rows):
    from gui.block_base import KVRow
    return [r._val.mapTo(r, r._val.rect().topRight()).x() for r in rows if isinstance(r, KVRow)]


def test_values_at_the_edge_by_default(qt):
    from gui import theme as T
    T.configure({})
    pane, rows = _pane(qt, SPEC)
    rights = _value_rights(rows)
    assert len(set(rights)) == 1
    assert rights[0] > pane.viewport().width() - 20


def test_offsets_are_pixels_unless_marked_percent():
    from gui import theme as T
    assert T.parse_offset("320") == (320.0, False)
    assert T.parse_offset(" 320px ") == (320.0, False)
    assert T.parse_offset("25%") == (25.0, True)
    assert T.parse_offset("150%") == (100.0, True)
    assert T.parse_offset("") is None and T.parse_offset("a lot") is None
    assert T.offset_px((25.0, True), 1200) == 300 and T.offset_px((40.0, False), 9) == 40


def _texts(rows):
    """(left, right, aligned left) of each value label, in the row."""
    from PySide6.QtCore import Qt
    from gui.block_base import KVRow
    out = []
    for r in rows:
        if isinstance(r, KVRow):
            g = r._val.geometry()
            out.append((g.left(), g.right(), bool(r._val.alignment() & Qt.AlignLeft)))
    return out


def test_from_the_labels_left_values_start_there_left_aligned(qt):
    from gui import theme as T
    T.configure({"ValuePlacement": "manual", "ValueFromLeft": "300"})
    _pane_, rows = _pane(qt, SPEC)
    got = _texts(rows)
    assert {g[0] for g in got} == {6 + 300} and all(g[2] for g in got), got


def test_a_longer_label_pushes_the_column_past_it(qt):
    from gui import theme as T
    from gui.block_base import KVRow
    T.configure({"ValuePlacement": "manual", "ValueFromLeft": "10"})
    _pane_, rows = _pane(qt, SPEC)
    kw = max(r._key.sizeHint().width() for r in rows if isinstance(r, KVRow))
    assert {g[0] for g in _texts(rows)} == {6 + kw + 8}


def test_from_the_right_edge_values_end_there_right_aligned(qt):
    from gui import theme as T
    T.configure({"ValuePlacement": "manual", "ValueFromRight": "25%"})
    pane, rows = _pane(qt, SPEC)
    width = rows[1].parentWidget().width()
    got = _texts(rows)
    assert {g[1] for g in got} == {rows[1].width() - round(width * 0.25) - 1}
    assert not any(g[2] for g in got)
    # A share of the width follows the width.
    pane.resize(800, 400)
    _settle(qt)
    width = rows[1].parentWidget().width()
    assert {g[1] for g in _texts(rows)} == {rows[1].width() - round(width * 0.25) - 1}


def test_with_both_the_column_runs_between_them(qt):
    from gui import theme as T
    T.configure({"ValuePlacement": "manual", "ValueFromLeft": "300", "ValueFromRight": "400"})
    _pane_, rows = _pane(qt, SPEC)
    got = _texts(rows)
    assert {g[0] for g in got} == {306}
    assert {g[1] for g in got} == {rows[1].width() - 400 - 1}
    assert not any(g[2] for g in got)


@pytest.mark.parametrize("ui", [{"ValueFromLeft": "2000"}, {"ValueFromRight": "1500"},
                                {"ValueFromLeft": "90%", "ValueFromRight": "90%"}])
def test_offsets_give_way_in_a_narrow_pane(qt, ui):
    from gui import theme as T
    T.configure({"ValuePlacement": "manual", **ui})
    pane, rows = _pane(qt, SPEC)
    pane.resize(420, 400)
    _settle(qt)
    assert not pane.horizontalScrollBar().isVisible()
    assert all(r.minimumSizeHint().width() <= pane.viewport().width() for r in rows)


def test_manual_with_nothing_set_is_the_right_edge(qt):
    from gui import theme as T
    T.configure({"ValuePlacement": "manual"})
    pane, rows = _pane(qt, SPEC)
    assert len({g[1] for g in _texts(rows)}) == 1
    assert _value_rights(rows)[0] > pane.viewport().width() - 20


def test_rearrange_follows_a_change_of_mind(qt):
    from gui import theme as T
    from gui.block_base import rearrange
    from PySide6.QtWidgets import QTableWidget, QVBoxLayout, QWidget
    T.configure({})
    pane, rows = _pane(qt, SPEC)
    host = QWidget()
    QVBoxLayout(host).addWidget(QTableWidget(2, 2))
    T.configure({"ValuePlacement": "manual", "ValueFromLeft": "200", "RowStripes": False})
    rearrange(pane)
    rearrange(host)
    _settle(qt)
    assert {g[0] for g in _texts(rows)} == {206}
    assert not any(r.property("stripe") for r in rows)
    assert not host.findChild(QTableWidget).alternatingRowColors()


# ── Options ───────────────────────────────────────────────────────────────────

def _dialog(tmp_path):
    from tests.test_options_pages import _core
    from gui.preferences import PreferencesDialog
    return PreferencesDialog(_core(tmp_path), theme="default")


def _page_texts(dlg, label):
    from PySide6.QtWidgets import QLabel
    dlg.show_page(label)
    page = dlg._pages.currentWidget()
    return [w.text() for w in page.findChildren(QLabel)]


def test_options_appearance_holds_the_text_and_rows(qt, tmp_path):
    from PySide6.QtWidgets import QComboBox
    dlg = _dialog(tmp_path)
    texts = _page_texts(dlg, "Appearance")
    assert {"TEXT", "ROWS"} <= set(texts)
    page = dlg._pages.currentWidget()
    size = next(b for b in page.findChildren(QComboBox) if b.findData(20) >= 0
                and b.findText("20") >= 0)
    size.setCurrentIndex(size.findData(14))
    assert dlg._pending[("UI", "FontSize")] == 14
    faces = [b for b in page.findChildren(QComboBox) if b.itemText(0) == "Default"]
    assert len(faces) == 2


def test_options_interface_holds_the_layout_and_general_the_backups(qt, tmp_path):
    dlg = _dialog(tmp_path)
    iface = _page_texts(dlg, "Interface")
    assert {"INTERFACE", "EDCARS", "DASHBOARD", "DASHBOARD WINDOWS"} <= set(iface)
    assert dlg._display_selects
    general = _page_texts(dlg, "General")
    assert "JOURNALS" in general and "JOURNAL BACKUPS" in general
    services = _page_texts(dlg, "Services")
    assert "EDSM FLIGHT LOG" in services
    combat = _page_texts(dlg, "Combat")
    assert {"KILL MESSAGES", "INACTIVITY ALERTS"} <= set(combat)
    assert "Display" not in dlg.page_labels() and "Data" not in dlg.page_labels()


def test_the_column_order_puts_unknown_pages_last():
    from core.options_pages import arrange
    extra = [("pref-tab-zeta", "Zeta", None), ("pref-tab-server", "Server", None),
             ("pref-tab-alpha", "Alpha", None), ("pref-tab-backups", "Backups", "b")]
    pages, merged = arrange(extra)
    names = [n for _i, n in pages]
    assert names[-3:] == ["Server", "Alpha", "Zeta"]
    assert names[0] == "General" and "Backups" not in names
    assert merged == {"pref-tab-general": [("pref-tab-backups", "Backups", "b")]}


def test_the_terminal_options_leave_the_text_to_the_desktop(tmp_path):
    pytest.importorskip("textual")
    from textual.widgets import Label
    from tests.test_options_pages import _core, _run_tui

    async def steps(app, pilot, seen):
        scr = app.screen
        page = scr.query_one("#pref-tab-appearance")
        seen["ids"] = [w.id for w in page.query("*") if w.id]
        general = scr.query_one("#pref-tab-general")
        seen["general"] = [str(w.render()) for w in general.query(Label)]
        seen["interface"] = bool(scr.query("#pref-tab-interface #disp-L1")) or bool(
            [w for w in scr.query_one("#pref-tab-interface").query("*")
             if (w.id or "").startswith("disp-")])

    seen = _run_tui(_core(tmp_path), steps)
    assert seen["ids"] == ["app-theme"] or all("font" not in i.lower() for i in seen["ids"])
    assert "JOURNAL BACKUPS" in seen["general"]
    assert seen["interface"]


def test_a_hand_edited_config_is_taken_up_on_the_next_poll(qt):
    from tests.test_edcars import _window
    from gui import theme as T
    w, _ = _window()
    w._core.cfg.ui_cfg = {**w._core.cfg.ui_cfg, "FontSize": 15, "ValuePlacement": "manual",
                          "ValueFromRight": "30%"}
    w._poll_queue()
    assert T.sizes()["body"] == 15 and T.value_offsets() == (None, (30.0, True))
    assert "font-size: 15pt;" in w.styleSheet()
    w.close()


def test_the_terminal_combat_page_holds_the_kill_settings(tmp_path):
    pytest.importorskip("textual")
    from tests.test_options_pages import _core, _run_tui

    async def steps(app, pilot, seen):
        page = app.screen.query_one("#pref-tab-combat")
        seen["ids"] = {w.id for w in page.query("*") if w.id}
        seen["general"] = {w.id for w in app.screen.query_one("#pref-tab-general").query("*")
                           if w.id}

    seen = _run_tui(_core(tmp_path), steps)
    assert {"g-trunc", "g-pirate", "g-warn-kills", "g-warn-cd"} <= seen["ids"]
    assert "g-trunc" not in seen["general"] and "g-journal" in seen["general"]


def test_component_notes_wear_the_options_note_style(tmp_path):
    """A component page's notes were drawn as dashboard text: in the text
    color and against the edge, where EDLD's own pages pad and dim them."""
    pytest.importorskip("textual")
    from textual.widgets import Label
    from tests.test_options_pages import _core, _run_tui

    async def steps(app, pilot, seen):
        page = app.screen.query_one("#pref-tab-routes")
        seen["notes"] = [w for w in page.query(Label) if w.has_class("pref-note")]
        seen["dim"] = [w for w in page.query(Label) if w.has_class("dim")
                       and not w.has_class("pref-result")]

    seen = _run_tui(_core(tmp_path), steps)
    assert seen["notes"] and not seen["dim"]


def test_options_take_the_offsets_only_for_manual_alignment(qt, tmp_path):
    from PySide6.QtWidgets import QComboBox, QLineEdit
    dlg = _dialog(tmp_path)
    dlg.show_page("Appearance")
    page = dlg._pages.currentWidget()
    edits = [e for e in page.findChildren(QLineEdit) if e.placeholderText() == "blank, 320 or 25%"]
    assert len(edits) == 2 and not any(e.isEnabled() for e in edits)
    values = next(b for b in page.findChildren(QComboBox) if b.findData("manual") >= 0)
    values.setCurrentIndex(values.findData("manual"))
    assert all(e.isEnabled() for e in edits)
    edits[0].setText("25%")
    edits[1].setText("320")
    assert dlg._pending[("UI", "ValueFromLeft")] == "25%"
    assert dlg._pending[("UI", "ValueFromRight")] == "320"
    edits[1].clear()
    edits[1].insert("lots")
    assert edits[1].text() == "" and dlg._pending[("UI", "ValueFromRight")] == ""


def test_edam_is_sent_route_waypoints_as_before():
    from core.tooltab import wire_rows
    from core.ui_helpers import carrier_route_rows
    rows = carrier_route_rows({"jumps": [
        {"name": "Sol"},
        {"name": "Alpha", "distance": 500, "fuel_used": 12, "fuel_in_tank": 988,
         "has_icy_ring": True},
        {"name": "Beta", "distance": 499.5, "fuel_used": 112, "fuel_in_tank": 876,
         "must_restock": True, "restock_amount": 300, "tritium_in_market": 40}]})
    got = [(r["label"], r["value"]) for r in wire_rows([("kv", lab, val) for lab, val in rows])]
    assert got == [("0. Sol", "start  [0t]"), ("1. Alpha", "500 ly  -12t  [988t]  ·"),
                   ("2. Beta", "500 ly  -112t  [876t]  ⛽300t  mkt 40t")]


def test_options_rewrite_an_old_placement_as_manual(qt, tmp_path):
    """"labels" from the first build showed as Manual alignment; choosing
    Manual changed nothing, so it was never written back."""
    from tests.test_options_pages import _core
    from gui.preferences import PreferencesDialog
    core = _core(tmp_path)
    core.cfg.ui_cfg = {**core.cfg.ui_cfg, "ValuePlacement": "labels"}
    dlg = PreferencesDialog(core, theme="default")
    assert dlg._pending[("UI", "ValuePlacement")] == "manual"


# ── Out of bounds ─────────────────────────────────────────────────────────────

def test_fit_holds_the_right_edge_and_says_what_was_corrected():
    from gui.block_base import fit
    # 600 wide, labels 100, values 150: room for the label column 422.
    f = fit(600, 100, 150, 300, 50)
    assert not f.corrected and f.kmin == 292 and f.margin == 50
    assert f.max_left == 430 and f.max_right == 136
    f = fit(600, 100, 150, 900, None)
    assert f.left_out and not f.right_out and f.kmin == 422
    f = fit(600, 100, 150, 300, 200)
    assert f.right_out and f.margin == 136
    f = fit(600, 100, 150, None, -40)
    assert f.right_out and f.margin == 6
    f = fit(600, 100, 150, -10, None)
    assert f.left_out and f.kmin == 100


def test_negative_offsets_are_read_so_they_can_be_corrected():
    from gui import theme as T
    assert T.parse_offset("-40") == (-40.0, False)
    assert T.parse_offset("-150%") == (-100.0, True)


def test_a_corrected_layout_never_passes_the_right_edge(qt):
    from gui import theme as T
    from gui.block_base import fit_report
    T.configure({"ValuePlacement": "manual", "ValueFromLeft": "90%", "ValueFromRight": "-20"})
    pane, rows = _pane(qt, SPEC)
    width = rows[1].width()
    assert all(g[1] <= width - 6 for g in _texts(rows))
    report = fit_report()
    assert report["corrected"] == 1 and report["windows"] == 1
    assert 0 < report["max_left_pct"] <= 100 and report["max_left_px"] > 0
    # Within the safe range nothing is corrected.
    safe = ((report["max_left_px"] - 1.0, False), (0.0, False))
    assert fit_report(safe)["corrected"] == 0


def test_options_say_when_the_typed_offsets_are_out_of_bounds(qt, tmp_path):
    from PySide6.QtWidgets import QComboBox, QLineEdit
    from gui import theme as T
    T.configure({"ValuePlacement": "manual", "ValueFromLeft": "10"})
    pane, _rows = _pane(qt, SPEC)
    dlg = _dialog(tmp_path)
    dlg.show_page("Appearance")
    page = dlg._pages.currentWidget()
    values = next(b for b in page.findChildren(QComboBox) if b.findData("manual") >= 0)
    values.setCurrentIndex(values.findData("manual"))
    edits = [e for e in page.findChildren(QLineEdit) if e.placeholderText() == "blank, 320 or 25%"]
    edits[0].setText("95%")
    assert dlg._fit_note.isVisibleTo(page) and "Out of bounds in 1 window" in dlg._fit_note.text()
    assert "Safe in every window on screen now" in dlg._fit_note.text()
    edits[0].setText("100")
    assert not dlg._fit_note.isVisibleTo(page) and dlg._fit_note.text() == ""
    edits[1].setText("-20")
    assert "Out of bounds" in dlg._fit_note.text()
    assert "with that left" in dlg._fit_note.text() and "Below 0 counts as 0" in dlg._fit_note.text()
    edits[0].setText("99%")
    edits[1].setText("10")
    assert "with the left blank, less as the left grows" in dlg._fit_note.text()
    pane.close()


def test_alerts_say_so_and_stop_saying_so(qt):
    from tests.test_edcars import _window
    from gui import theme as T

    class Alerts:
        def __init__(self):
            self.notices = {}

        def push_notice(self, key, emoji, text):
            self.notices[key] = text

        def drop_notice(self, key):
            self.notices.pop(key, None)

        def get_alerts(self):
            return []

        def opacity_for(self, _a):
            return 1.0

    alerts = Alerts()
    w, _ = _window(plugins={"alerts": alerts})
    T.configure({"ValuePlacement": "manual", "ValueFromLeft": "10"})
    pane, _rows = _pane(qt, SPEC)
    w._type_sig = T.signature(w._ui_cfg())
    for _ in range(w.FIT_POLLS):
        w._check_fit()
    assert not alerts.notices
    T.configure({"ValuePlacement": "manual", "ValueFromLeft": "99%"})
    from gui.block_base import rearrange
    rearrange(pane)
    _settle(qt)
    w._check_fit()
    assert not alerts.notices                    # one poll is not enough
    for _ in range(w.FIT_POLLS):
        w._check_fit()
    assert "out of bounds" in alerts.notices["value-fit"]
    T.configure({"ValuePlacement": "manual", "ValueFromLeft": "10"})
    rearrange(pane)
    _settle(qt)
    for _ in range(w.FIT_POLLS + 1):
        w._check_fit()
    assert not alerts.notices
    pane.close()
    w.close()
