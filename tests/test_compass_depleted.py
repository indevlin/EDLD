"""tests/test_compass_depleted.py — the survey compass leaves out worked-out sites.
"""
from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import core.mining_db as mdb  # noqa: E402
from components.surface_mining import SurfaceMiningPlugin  # noqa: E402
from core.overlay_panels import PanelContext  # noqa: E402

SYS, BODY = 1234, 7


def _plugin(tmp_path):
    p = SurfaceMiningPlugin.__new__(SurfaceMiningPlugin)
    p._db = mdb.MiningDB(tmp_path / "mining.db")
    p._db.upsert_body(SYS, BODY, radius_m=1_500_000.0)
    p._log = lambda *_: None
    p._core = SimpleNamespace(load_setting=lambda s, d, warn=True: dict(d))
    p._system_address, p._body_id = SYS, BODY
    return p


def _ctx():
    return PanelContext(in_srv=True, has_latlong=True, latitude=10.0, longitude=20.0,
                        body_radius=1_500_000.0)


def test_a_depleted_site_is_not_on_the_compass(tmp_path):
    p = _plugin(tmp_path)
    keep, _ = p._db.record_deposit(SYS, BODY, "platinum", 10.002, 20.0)
    gone, _ = p._db.record_deposit(SYS, BODY, "tritium", 10.001, 20.0)
    p._db.mark_depleted(gone)
    rows = p.overlay_panel("survey_compass", _ctx()).rows
    assert [name for name, _ in rows] == ["platinum"]


def test_nothing_left_means_no_panel(tmp_path):
    p = _plugin(tmp_path)
    gone, _ = p._db.record_deposit(SYS, BODY, "tritium", 10.001, 20.0)
    p._db.mark_depleted(gone)
    assert p.overlay_panel("survey_compass", _ctx()) is None


def test_is_depleted_follows_the_refill_rule(monkeypatch):
    assert mdb.is_depleted("") is False
    monkeypatch.setattr(mdb, "REPLENISH_DAYS", None)
    assert mdb.is_depleted("2026-10-01") is True
    monkeypatch.setattr(mdb, "REPLENISH_DAYS", 7)
    assert mdb.is_depleted("2026-10-01", today="2026-10-05") is True
    assert mdb.is_depleted("2026-10-01", today="2026-10-08") is False
