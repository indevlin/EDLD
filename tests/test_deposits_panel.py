"""
tests/test_deposits_panel.py — Objectives › Deposits: model rows, filter,
wire panel, edit by id, body backfill.
"""
from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import core.bodies_db as bodies  # noqa: E402
from core.mining_db import MiningDB  # noqa: E402
from components.surface_mining import SurfaceMiningPlugin  # noqa: E402
from core.windows import objectives as W  # noqa: E402

SYS, BODY = 4923936737651, 21


def _setup(tmp_path, monkeypatch):
    cat = bodies.BodyDB(tmp_path / "explo.db")
    sid = cat.upsert_system(SYS, name="Ega")
    cat.upsert_planet(sid, BODY, name="Ega 3 a", type="Rocky body", gravity=0.0664)
    monkeypatch.setattr(bodies, "get_db", lambda: cat)
    p = SurfaceMiningPlugin.__new__(SurfaceMiningPlugin)
    p._db = MiningDB(tmp_path / "mining.db")
    p.logged = []
    p._log = p.logged.append
    p._db.upsert_body(SYS, BODY, body_name="Ega 3 a")
    silver, _ = p._db.record_deposit(SYS, BODY, "silver", 1.0, 2.0,
                                     commodity_display="Silver", amount="High",
                                     signal_no=3)
    plat, _ = p._db.record_deposit(SYS, BODY, "platinum", 40.0, 50.0,
                                   commodity_display="Platinum", rigs=2)
    p._db.annotate_deposit(plat, notes="steep hillside")
    core = SimpleNamespace(state=SimpleNamespace(), gui_queue=None,
                           _plugins={"surface_mining": p})
    p._core = core
    return p, core, silver, plat


def test_backfill_fills_gravity_and_system_name(tmp_path, monkeypatch):
    p, _core, silver, _ = _setup(tmp_path, monkeypatch)
    assert p._db.deposit(silver)["gravity"] is None
    p._enrich_known_bodies()
    rec = p._db.deposit(silver)
    assert rec["system_name"] == "Ega" and rec["gravity"] == 0.066


def test_rows_carry_edit_actions_and_notes(tmp_path, monkeypatch):
    _p, core, silver, plat = _setup(tmp_path, monkeypatch)
    rows = W.deposits(core).rows
    assert rows[0][0] == "table"
    actions = [r[4] for r in rows if r[0] == "cells"]
    assert sorted(actions) == sorted([f"edit:{silver}", f"edit:{plat}"])
    assert any(r[0] == "text" and "steep hillside" in r[1] for r in rows)


def test_filter_matches_any_column_and_notes(tmp_path, monkeypatch):
    _p, core, silver, plat = _setup(tmp_path, monkeypatch)
    only = [r[4] for r in W.deposits(core, "SILVER").rows if r[0] == "cells"]
    assert only == [f"edit:{silver}"]
    by_note = [r[4] for r in W.deposits(core, "hillside").rows if r[0] == "cells"]
    assert by_note == [f"edit:{plat}"]
    none = W.deposits(core, "osmium").rows
    assert none == [("text", "No deposits match", "dim")]


def test_empty_store_placeholder(tmp_path):
    p = SurfaceMiningPlugin.__new__(SurfaceMiningPlugin)
    p._db = MiningDB(tmp_path / "mining.db")
    p._log = lambda *_: None
    core = SimpleNamespace(_plugins={"surface_mining": p})
    assert W.deposits(core).rows == [("text", "No surface deposits recorded", "dim")]


def test_submit_form_for_edits_by_id_and_keeps_commodity(tmp_path, monkeypatch):
    p, _core, silver, _ = _setup(tmp_path, monkeypatch)
    form, heading = p.form_for(silver)
    assert silver in heading and form["commodity"]
    out = p.submit_form_for(silver, {"commodity": "gold", "rigs": "5"})
    assert out.startswith("updated"), out
    rec = p._db.deposit(silver)
    assert rec["rigs"] == 5 and rec["commodity"] == "silver"
    assert p.submit_form_for(silver, {}) == "nothing to change"
    assert "not in the store" in p.submit_form_for("nope", {"rigs": "1"})


def test_wire_panel_is_filterable(tmp_path, monkeypatch):
    from core.windows.wire import panel
    _p, core, _s, _pl = _setup(tmp_path, monkeypatch)
    out = panel("survey.deposits", "Deposits", "survey", W.deposits(core), 1700, filter=True)
    assert out["filter"] is True and out["group"] == "survey"
    assert any(r.get("action", "").startswith("edit:") for r in out["rows"])


def test_gui_table_filters_and_saves_a_cell(tmp_path, monkeypatch):
    import os
    import pytest
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    from gui.deposits_table import COLUMNS, ID_ROLE, DepositsTable
    p, core, silver, _ = _setup(tmp_path, monkeypatch)
    t = DepositsTable(core)
    t.refresh()
    assert t.table.rowCount() == 2
    t.filter.setText("platinum")
    hidden = [t.table.isRowHidden(r) for r in range(2)]
    assert sorted(hidden) == [False, True]
    t.filter.setText("")
    rigs = next(i for i, c in enumerate(COLUMNS) if c[2] == "rigs")
    row = next(r for r in range(2) if t.table.item(r, 0).data(ID_ROLE) == silver)
    assert t.save_cell(row, rigs, "7")
    assert p._db.deposit(silver)["rigs"] == 7
    app.processEvents()
