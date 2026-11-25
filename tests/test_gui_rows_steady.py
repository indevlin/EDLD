"""tests/test_gui_rows_steady.py — with values placed by hand, a refresh's new
rows are drawn where the values already are, not at the edge and then moved."""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


@pytest.fixture()
def qapp():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    QtWidgets = pytest.importorskip("PySide6.QtWidgets")
    from gui import theme
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    theme.configure({"ValuePlacement": "manual", "ValueFromLeft": "15%"})
    yield app
    theme.configure({})


def _rows():
    from core.palette import rgb
    from gui.block_base import KVRow
    pal = rgb("default")
    return [KVRow("Credits", "1,234 cr", palette=pal), KVRow("Rebuy", "56 cr", palette=pal)]


def test_a_refresh_draws_rows_in_place(qapp):
    from gui.block_base import RowScroll
    s = RowScroll()
    s.resize(600, 300)
    s.show()
    s.set_rows(_rows())
    qapp.processEvents()
    placed = [r._placed for r in s._body.findChildren(type(_rows()[0]))]
    assert placed and placed[0][0] > 0, "the values sit 15% in"
    s.set_rows(_rows())
    fresh = [w for w in (s._lay.itemAt(i).widget() for i in range(s._lay.count())) if w is not None]
    assert all(w._placed == placed[0] for w in fresh), "placed before the first paint"
    assert all(w._key.minimumWidth() == placed[0][0] for w in fresh)


def test_at_the_edge_nothing_changes(qapp):
    from gui import theme
    from gui.block_base import RowScroll, _EDGE
    theme.configure({})
    s = RowScroll()
    s.resize(600, 300)
    s.set_rows(_rows())
    fresh = [w for w in (s._lay.itemAt(i).widget() for i in range(s._lay.count())) if w is not None]
    assert all(w._placed == _EDGE for w in fresh)
