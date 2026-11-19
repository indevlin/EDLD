"""tests/test_gui_text_rows.py — the desktop windows' text face and size, row
shading and value placement ([UI] FontFamily, FigureFamily, FontSize,
RowStripes, ValuePlacement), and where Options keeps them.
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


def _settle(app):
    for _ in range(3):
        app.processEvents()


# ── Settings ──────────────────────────────────────────────────────────────────

def test_the_settings_are_read_forgivingly(qt):
    from gui import theme as T
    T.configure({})
    assert T.sizes() == T.FONT_SIZES
    assert T.row_stripes() and not T.values_beside_labels()
    T.configure({"FontSize": "14", "RowStripes": "off", "ValuePlacement": "LABELS",
                 "FigureFamily": "Fira Mono"})
    assert T.sizes()["body"] == 14 and T.sizes()["title"] == 15
    assert not T.row_stripes() and T.values_beside_labels()
    assert T.mono_families().startswith('"Fira Mono", ')
    T.configure({"FontSize": 99, "ValuePlacement": "middle"})
    assert T.sizes()["body"] == T.FONT_SIZE_CHOICES[-1]
    assert not T.values_beside_labels()
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
    for key in ("FontFamily", "FigureFamily", "FontSize", "RowStripes", "ValuePlacement"):
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


def test_values_beside_their_labels_share_one_column(qt):
    from gui import theme as T
    from gui.block_base import KVRow
    T.configure({"ValuePlacement": "labels"})
    pane, rows = _pane(qt, SPEC)
    kv = [r for r in rows if isinstance(r, KVRow)]
    rights = _value_rights(rows)
    assert len(set(rights)) == 1, rights
    widest = max(r._key.sizeHint().width() for r in kv)
    assert rights[0] < widest + max(r._val.sizeHint().width() for r in kv) + 40
    assert rights[0] < pane.viewport().width() / 2
    # A longer value later widens the column for every row.
    kv[0].set_value("123,456,789,000 cr")
    _settle(qt)
    again = _value_rights(rows)
    assert len(set(again)) == 1 and again[0] > rights[0]


def test_rearrange_follows_a_change_of_mind(qt):
    from gui import theme as T
    from gui.block_base import rearrange
    from PySide6.QtWidgets import QTableWidget, QVBoxLayout, QWidget
    T.configure({})
    pane, rows = _pane(qt, SPEC)
    host = QWidget()
    QVBoxLayout(host).addWidget(QTableWidget(2, 2))
    T.configure({"ValuePlacement": "labels", "RowStripes": False})
    rearrange(pane)
    rearrange(host)
    _settle(qt)
    assert _value_rights(rows)[0] < pane.viewport().width() / 2
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
    w._core.cfg.ui_cfg = {**w._core.cfg.ui_cfg, "FontSize": 15, "ValuePlacement": "labels"}
    w._poll_queue()
    assert T.sizes()["body"] == 15 and T.values_beside_labels()
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
