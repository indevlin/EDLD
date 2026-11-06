"""
tests/test_codex_footfall.py — the codex by region, and first footfall from
the scan itself.

Schema v2 keeps each scan's WasFootfalled (unknown for scans from before the
game reported it) and the commander's codex entries by region. A database
from v1 gains both and imports its journals again, which only fills them in.
The Exobiology view marks a genus not yet in the codex for the region; an
empty codex is one not read yet, and marks nothing.
"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.bodies_db import BodyDB  # noqa: E402
from core.body_ingest import INGEST_EVENTS, Ingestor  # noqa: E402

ADDR = 5253281760888            # Oochost MU-O a74-0, Sanguineous Rim (34)


def _db(tmp_path):
    return BodyDB(tmp_path / "explo.db")


def _feed(db, *events):
    ing = Ingestor(db)
    ing.ingest({"event": "LoadGame", "FID": "F1", "Commander": "Test"})
    ing.ingest({"event": "FSDJump", "SystemAddress": ADDR, "StarSystem": "Oochost MU-O a74-0",
                "StarPos": [-1, -2, 3]})
    for e in events:
        ing.ingest(e)
    return ing.commander_id


def test_codex_entries_are_kept_by_region(tmp_path):
    db = _db(tmp_path)
    assert "CodexEntry" in INGEST_EVENTS
    cid = _feed(db, {"event": "CodexEntry", "Name": "$Codex_Ent_Bacterial_04_Ruthenium_Name;",
                     "Name_Localised": "Bacterium Acies - Cobalt", "Region": "$Codex_RegionName_34;",
                     "timestamp": "2026-07-07T02:44:49Z"},
                {"event": "CodexEntry", "Name": "$Codex_Ent_Bacterial_04_Ruthenium_Name;",
                 "Name_Localised": "Bacterium Acies - Cobalt", "Region": "$Codex_RegionName_34;"})
    assert db.codex_size(cid) == 1
    assert db.codex_names(cid, 34) == {"Bacterium Acies - Cobalt"}
    assert db.codex_names(cid, 18) == set()


def test_was_footfalled_is_known_only_when_the_scan_says(tmp_path):
    db = _db(tmp_path)
    cid = _feed(db,
                {"event": "Scan", "SystemAddress": ADDR, "BodyID": 3, "BodyName": "X 1",
                 "PlanetClass": "Icy body", "Landable": True, "WasDiscovered": True,
                 "WasMapped": False, "WasFootfalled": False},
                {"event": "Scan", "SystemAddress": ADDR, "BodyID": 4, "BodyName": "X 2",
                 "PlanetClass": "Icy body", "Landable": True, "WasDiscovered": False,
                 "WasMapped": False})
    sid = db.system_id_by_address(ADDR)
    planets = {p["body_id"]: p for p in db.system_bodies(sid, cid)["planets"]}
    assert planets[3]["was_footfalled"] == 0
    assert planets[4]["was_footfalled"] is None
    from core.explo_view import build_system_view
    view = build_system_view(ADDR, cid, db)
    ff = {b["name"]: b["first_footfall"] for b in view["bodies"]}
    # Discovered before, but no one has walked it: the scan says so.
    assert ff == {"X 1": True, "X 2": True}


def test_a_v1_database_gains_the_columns_and_imports_again(tmp_path):
    path = tmp_path / "explo.db"
    conn = sqlite3.connect(path)
    from core import bodies_db as B
    conn.executescript(B._SCHEMA_V1)
    conn.execute("INSERT INTO meta(key, value) VALUES('schema_version', '1')")
    conn.execute("INSERT INTO journals(name) VALUES('Journal.2026-01-01T000000.01.log')")
    conn.commit()
    conn.close()
    db = BodyDB(path)
    assert db.current_version() == 2
    assert db.imported_journals() == set()
    assert db._column_exists(db._c, "planet_status", "was_footfalled")


def _bio_body(db):
    return _feed(db,
                 {"event": "Scan", "SystemAddress": ADDR, "BodyID": 10, "BodyName": "X 10",
                  "PlanetClass": "Rocky body", "Landable": True, "WasDiscovered": True,
                  "Atmosphere": "thin carbon dioxide atmosphere", "SurfaceGravity": 2.0,
                  "SurfaceTemperature": 180.0},
                 {"event": "SAASignalsFound", "SystemAddress": ADDR, "BodyID": 10,
                  "BodyName": "X 10", "Signals": [{"Type": "$SAA_SignalType_Biological;", "Count": 2}],
                  "Genuses": [{"Genus": "$Codex_Ent_Bacterial_Genus_Name;", "Genus_Localised": "Bacterium"},
                              {"Genus": "$Codex_Ent_Stratum_Genus_Name;", "Genus_Localised": "Stratum"}]})


def test_genera_new_to_the_region_are_marked(tmp_path):
    from core.exobio_view import build_exobio_view
    db = _db(tmp_path)
    cid = _bio_body(db)
    # Nothing in the codex at all: not read yet, so nothing is marked.
    view = build_exobio_view(ADDR, cid, db)
    assert not any(g["codex_new"] for b in view["bodies"] for g in b["genera"])
    db.add_codex(cid, "$Codex_Ent_Bacterial_04_Ruthenium_Name;", "Bacterium Acies - Cobalt", 34)
    db.add_codex(cid, "$Codex_Ent_Stratum_07_M_Name;", "Stratum Tectonicas - Green", 18)
    view = build_exobio_view(ADDR, cid, db)
    marks = {g["genus"]: g["codex_new"] for b in view["bodies"] for g in b["genera"]}
    assert marks == {"Bacterium": False, "Stratum": True}
    assert view["system"]["region"] == "Sanguineous Rim"
