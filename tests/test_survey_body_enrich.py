"""tests/test_survey_body_enrich.py — survey bodies filled from the body catalog.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import core.bodies_db as bodies  # noqa: E402
from core.mining_db import MiningDB  # noqa: E402
from components.surface_mining import SurfaceMiningPlugin  # noqa: E402

SYS, BODY = 671491892681, 15


def _catalogue(tmp_path, **planet):
    db = bodies.BodyDB(tmp_path / "explo.db")
    sid = db.upsert_system(SYS, name="Col 285 Sector NK-R b20-0")
    db.upsert_planet(sid, BODY, name="Col 285 Sector NK-R b20-0 A 2", **planet)
    return db


def _plugin(tmp_path, monkeypatch, cat):
    monkeypatch.setattr(bodies, "get_db", lambda: cat)
    p = SurfaceMiningPlugin.__new__(SurfaceMiningPlugin)
    p._db = MiningDB(tmp_path / "mining.db")
    p.logged = []
    p._log = p.logged.append
    return p


def test_planet_facts_reports_unknowns_as_none(tmp_path):
    cat = _catalogue(tmp_path, type="High metal content body", gravity=1.0428)
    facts = cat.planet_facts(SYS, BODY)
    assert facts == {"system_name": "Col 285 Sector NK-R b20-0",
                     "body_name": "Col 285 Sector NK-R b20-0 A 2",
                     "planet_class": "High metal content body", "atmosphere": None,
                     "volcanism": None, "radius_m": None, "gravity": 1.043}
    assert cat.planet_facts(SYS, BODY + 1) is None


def test_enrich_fills_blanks_without_an_error(tmp_path, monkeypatch):
    cat = _catalogue(tmp_path, type="High metal content body", gravity=1.0428,
                     radius=5852827.0)
    p = _plugin(tmp_path, monkeypatch, cat)
    p._enrich_body(SYS, BODY)
    assert not [m for m in p.logged if "failed" in m], p.logged
    body = p._db.body(SYS, BODY)
    assert body["planet_class"] == "High metal content body"
    assert body["gravity"] == 1.043 and body["radius_m"] == 5852827.0


def test_enrich_leaves_a_live_scan_alone(tmp_path, monkeypatch):
    cat = _catalogue(tmp_path, type="Rocky body", gravity=0.5)
    p = _plugin(tmp_path, monkeypatch, cat)
    p._db.upsert_body(SYS, BODY, planet_class="High metal content body")
    p._enrich_body(SYS, BODY)
    body = p._db.body(SYS, BODY)
    assert body["planet_class"] == "High metal content body"
    assert body["gravity"] == 0.5
