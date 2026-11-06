"""
tests/test_gui_combo_arrow.py — drop-downs in the desktop window have an arrow.

The style sheet styled ``QComboBox::drop-down``, which stops Qt drawing the
platform's arrow, and gave it no image, so every drop-down read as a text box.
"""
from __future__ import annotations

import os
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def test_every_theme_gets_an_arrow_image_in_its_own_colour(tmp_path, monkeypatch):
    import core.state as state
    monkeypatch.setattr(state, "EDLD_DATA_DIR", tmp_path)
    from core.palette import PALETTES, rgb
    from gui.theme import stylesheet
    for name in PALETTES:
        qss = stylesheet(name)
        m = re.search(r'QComboBox::down-arrow \{ image: url\("([^"]+)"\)', qss)
        assert m, f"{name}: no down-arrow image"
        png = Path(m.group(1))
        assert png.exists() and png.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"
        assert rgb(name)["dim"].lstrip("#").lower() in png.name


def test_the_arrow_is_drawn(tmp_path, monkeypatch):
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    pytest.importorskip("PySide6")
    import core.state as state
    monkeypatch.setattr(state, "EDLD_DATA_DIR", tmp_path)
    from PySide6.QtGui import QColor, QImage
    from PySide6.QtWidgets import QApplication, QComboBox
    from core.palette import rgb
    from gui.theme import stylesheet
    QApplication.instance() or QApplication([])
    box = QComboBox()
    box.addItems(["Off", "On"])
    box.setStyleSheet(stylesheet("default"))
    box.resize(200, 28)
    img = box.grab().toImage()
    want = QColor(rgb("default")["dim"])
    near = 0
    for x in range(170, 200):
        for y in range(4, 24):
            c = img.pixelColor(x, y)
            if abs(c.red() - want.red()) + abs(c.green() - want.green()) \
                    + abs(c.blue() - want.blue()) < 40:
                near += 1
    assert near >= 6, "no arrow-coloured pixels at the right of the box"
