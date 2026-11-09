"""tests/test_consoles.py — EDCARS drawn as each of its four consoles."""
from __future__ import annotations

import os
import re
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core import edcars as H  # noqa: E402

NEW = [(H.ORDER_ID, H.ORDER_NAME), (H.REBEL_ID, H.REBEL_NAME),
       (H.ROGUE_ID, H.ROGUE_NAME)]


# ── Core ──────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("cid, name", NEW)
def test_each_console_name_is_written_once(cid, name):
    hits = []
    for path in list(ROOT.glob("core/**/*.py")) + list(ROOT.glob("gui/**/*.py")) \
            + list(ROOT.glob("tui/**/*.py")) + list(ROOT.glob("components/*.py")):
        if path.name == "edcars.py" and path.parent.name == "core":
            continue
        if re.search(rf'["\']{name}["\']', path.read_text(encoding="utf-8")):
            hits.append(str(path.relative_to(ROOT)))
    assert not hits, f"{name} is spelled in {hits}; use core/edcars.py"
    assert cid != name                      # stored ids are not display names


def test_the_consoles_in_order_and_the_fallback():
    assert H.CONSOLE_IDS == (H.EDCARS_ID, H.ORDER_ID, H.REBEL_ID, H.ROGUE_ID)
    assert H.console_of({}) == H.EDCARS_ID
    assert H.console_of({"Console": " ORDER "}) == H.ORDER_ID
    assert H.console_of({"Console": "lcars"}) == H.EDCARS_ID
    assert [c for c, _ in H.console_choices()] == list(H.CONSOLE_IDS)
    note = H.console_note()
    assert all(c.name in note for c in H.CONSOLES)


def test_each_new_console_has_its_theme():
    from core.palette import PALETTES, THEME_CHOICES, rgb
    offered = {tid for _n, tid in THEME_CHOICES}
    for cid, name in NEW:
        assert H.CONSOLE_BY_ID[cid].theme == cid
        assert cid in PALETTES and cid in offered
        assert (name, cid) in THEME_CHOICES
        c = rgb(cid)
        assert {"bg", "fg", "accent", "red", "row-alt"} <= set(c)


def test_the_config_default_and_example():
    from core.config import CFG_DEFAULTS_UI
    assert CFG_DEFAULTS_UI[H.CONSOLE_KEY] == H.EDCARS_ID
    example = (ROOT / "example.config.toml").read_text(encoding="utf-8")
    assert re.search(r'(?m)^Console\s+= "edcars"', example)


def test_the_wire_names_the_console_beside_the_style():
    from core.server.protocol import SnapshotBuilder

    def header(ui):
        core = SimpleNamespace(state=None, cfg=SimpleNamespace(ui_cfg=ui), _plugins={},
                               plugin_call=lambda *a, **k: None, ui_mode="edcars")
        return SnapshotBuilder(core).header()

    h = header({"Console": H.REBEL_ID})
    # A device that knows only EDCARS still draws EDCARS.
    assert h["style"] == {"id": H.EDCARS_ID, "name": H.EDCARS_NAME}
    assert {k: h["console"][k] for k in ("id", "name")} == {"id": H.REBEL_ID, "name": H.REBEL_NAME}
    assert h["console"]["consoles"] == [{"id": c.id, "name": c.name} for c in H.CONSOLES]
    assert header({})["console"]["id"] == H.EDCARS_ID


def test_both_options_offer_the_console():
    tui = (ROOT / "tui" / "preferences.py").read_text(encoding="utf-8")
    gui = (ROOT / "gui" / "preferences.py").read_text(encoding="utf-8")
    for src in (tui, gui):
        assert "console_choices()" in src and "console_note()" in src
    assert "app-edcars-console" in tui and "CONSOLE_KEY" in tui


def test_the_faces_ship_with_their_licences():
    fonts = ROOT / "fonts"
    for face, licence in (("Rajdhani-Bold.ttf", "OFL-Rajdhani.txt"),
                          ("SairaCondensed-Bold.ttf", "OFL-SairaCondensed.txt"),
                          ("VT323-Regular.ttf", "OFL-VT323.txt"),
                          ("PermanentMarker-Regular.ttf", "LICENSE-PermanentMarker.txt")):
        assert (fonts / face).is_file() and (fonts / licence).is_file()
    notices = (ROOT / "THIRD-PARTY-NOTICES.md").read_text(encoding="utf-8")
    for name in ("Rajdhani", "Saira", "VT323", "Permanent Marker"):
        assert name in notices


# ── The window ────────────────────────────────────────────────────────────────

@pytest.fixture
def qt():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    yield app
    from gui import consoles as C
    C.set_active(None)


@pytest.mark.parametrize("cid", list(H.CONSOLE_IDS))
def test_the_window_builds_in_every_console(qt, cid, monkeypatch):
    from PySide6.QtWidgets import QApplication
    import test_edcars
    from gui import consoles as C
    from gui.edcars import EdcarsFrame, RailPill
    real = test_edcars._window

    def patched(*a, **k):
        # The harness's config, with the console set.
        import gui.app as A
        orig = A.EdldWindow.__init__

        def init(self, core, *aa, **kk):
            core.cfg.ui_cfg = {**core.cfg.ui_cfg, "Console": cid}
            orig(self, core, *aa, **kk)
        monkeypatch.setattr(A.EdldWindow, "__init__", init)
        return real(*a, **k)

    w, stub = patched()
    shell = w._edcars
    assert shell is not None and C.active() is C.CONSOLES[cid]
    assert shell.console.id == cid
    assert all(isinstance(p, RailPill) and p.ink is not None for p in shell.rail.pills.values())
    assert len(shell.findChildren(EdcarsFrame)) >= len(H.SECTIONS)
    for s in H.SECTIONS:
        shell.show_section(s.id)
        assert shell.current_section() == s.id
    # Pulsing paints in every console, painted pills included.
    shell.rail.set_pulse(H.ALERTS_SECTION, "on")
    shell.rail.pills[H.ALERTS_SECTION].repaint()
    shell.set_theme(C.CONSOLES[cid].id if cid != H.EDCARS_ID else "default-blue")
    w.grab()
    QApplication.processEvents()
    # Dialogs opened from the window wear the console.
    assert "QDialog QDialogButtonBox QPushButton" in w.styleSheet()
    w.close()


def test_the_dashboard_dresses_no_dialogs(qt):
    from test_edcars import _window as edcars_window
    from gui import consoles as C
    from gui.edcars import dialog_qss
    C.set_active(None)
    w, _ = edcars_window(style="dashboard")
    assert w._edcars is None and C.active() is None
    assert dialog_qss("default") == ""
    assert "QDialog QDialogButtonBox" not in w.styleSheet()
    w.close()


@pytest.mark.parametrize("cid", list(H.CONSOLE_IDS))
def test_each_console_has_its_own_face(qt, cid):
    from gui import consoles as C
    c = C.CONSOLES[cid]
    fam = c.family()
    assert fam and fam != c.face_fallback, f"{c.face_file} did not load"
    if c.label_file:
        assert c.label_family() != c.label_fallback
    css = c.qss(SimpleNamespace(**_ink_fields()), "#x") + \
        c.dialog_qss(SimpleNamespace(**_ink_fields()), "QDialog")
    assert fam in css


@pytest.mark.parametrize("cid", [H.ROGUE_ID])
def test_tape_labels_fit_the_rail(qt, cid):
    from PySide6.QtGui import QFontMetricsF
    from gui import consoles as C
    c = C.CONSOLES[cid]
    for sec in H.SECTIONS:
        f = c.fitting_label_font(sec.label.upper(), 100, 13)
        assert QFontMetricsF(f).horizontalAdvance(sec.label.upper()) <= 100 or f.pointSizeF() <= 8


def test_options_from_a_console_wear_its_pills(qt, tmp_path):
    from gui import consoles as C
    from gui.edcars import RailPill
    from test_options_pages import _dialog
    C.set_active(H.ROGUE_ID)
    dlg = _dialog(tmp_path, edcars=True)
    pills = [b for b in dlg.findChildren(RailPill) if b.objectName() == "edcarsPill"]
    assert pills and all(p.ink is not None for p in pills)
    assert C.CONSOLES[H.ROGUE_ID].label_family() in dlg.styleSheet() or \
        C.CONSOLES[H.ROGUE_ID].family() in dlg.styleSheet()
    dlg.show()
    dlg.grab()
    dlg.close()


def _ink_fields():
    from gui.edcars import Ink
    ink = Ink("default")
    return dict(vars(ink))
