"""
tests/test_survey.py — survey routes: the parameters each Spansh router is
sent, and its answer shaped into a route EDLD follows, with what is left to
do at each stop.

The answers here are small, made-up ones in the shapes Spansh's riches,
exobiology, tourist and trade routers return.
"""
from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core import survey  # noqa: E402


def test_params_fill_from_the_ship_and_check_the_form():
    p = survey.params("elw", {"from": "Sol"}, 40.0, None, None, None)
    assert p["body_types"] == ["Earth-like world"] and p["range"] == 40.0 and p["radius"] == 25
    p = survey.params("riches", {"from": "Sol", "range": "30", "loop": True}, 40.0, None, None, None)
    assert p["range"] == 30 and p["loop"] == 1 and p["use_mapping_value"] == 1
    t = survey.params("tourist", {"from": "Sol", "systems": "A, B; C", "to": "D"}, 40, None, None, None)
    assert t["destination"] == ["A", "B", "C"] and t["final_destination"] == "D"
    tr = survey.params("trade", {}, 20.0, 5_000_000, 256, ("Sol", "Abraham Lincoln"))
    assert (tr["system"], tr["station"], tr["max_cargo"], tr["starting_capital"]) == \
        ("Sol", "Abraham Lincoln", 256, 5_000_000)
    with pytest.raises(ValueError):
        survey.params("trade", {}, 20.0, None, None, None)
    with pytest.raises(ValueError):
        survey.params("riches", {"from": ""}, 20.0, None, None, None)
    with pytest.raises(ValueError):
        survey.params("riches", {"from": "Sol", "range": "abc"}, 20.0, None, None, None)


RICHES = {"result": [
    {"name": "Start", "id64": 1, "x": 0, "y": 0, "z": 0, "jumps": 0, "bodies": []},
    {"name": "Alpha", "id64": 2, "x": 30, "y": 0, "z": 40, "jumps": 2, "bodies": [
        {"name": "Alpha 1", "subtype": "Earth-like world", "distance_to_arrival": 500,
         "estimated_mapping_value": 3_000_000, "estimated_scan_value": 900_000,
         "is_terraformable": False},
        {"name": "Alpha 2", "subtype": "High metal content world", "distance_to_arrival": 900,
         "estimated_mapping_value": 1_500_000, "estimated_scan_value": 300_000,
         "is_terraformable": True}]},
]}


def test_shape_riches():
    r = survey.shape("riches", RICHES, {"range": 40})
    assert [x["system"] for x in r["system_jumps"]] == ["Start", "Alpha"]
    assert r["total_jumps"] == 2 and r["distance"] == 50.0
    assert r["value"] == 5_700_000 and r["survey"] == "riches"


def test_shape_trade_and_tourist():
    trade = {"result": [{"source": {"system": "A", "station": "S1", "market_id": 1, "system_id64": 11},
                         "destination": {"system": "B", "station": "S2", "market_id": 2, "system_id64": 22},
                         "distance": 12.5, "total_profit": 100_000, "cumulative_profit": 100_000,
                         "commodities": [{"name": "Gold", "amount": 100,
                                          "source_commodity": {"buy_price": 9000},
                                          "destination_commodity": {"sell_price": 10000}}]}]}
    r = survey.shape("trade", trade, {"max_hop_distance": 20})
    assert [x["trade"]["station"] for x in r["system_jumps"]] == ["S1", "S2"]
    assert r["profit"] == 100_000
    assert r["system_jumps"][0]["trade"]["buy"][0]["name"] == "Gold"
    tour = {"system_jumps": [{"system": "A", "id64": 1, "jumps": 0, "distance": 0},
                             {"system": "B", "id64": 2, "jumps": 3, "distance": 61.2}]}
    r = survey.shape("tourist", tour, {"range": 30})
    assert r["total_jumps"] == 3 and r["destination_system"] == "B"
    with pytest.raises(ValueError):
        survey.shape("riches", {"result": []}, {})


def test_todo_counts_what_the_journal_says_is_done(monkeypatch):
    stop = survey.shape("riches", RICHES, {})["system_jumps"][1]
    stop["bodies"].append({"name": "Alpha 3", "subtype": "Rocky body", "map_value": 0, "scan_value": 0,
                           "species": [{"genus": "Bacterium", "species": "Bacterium Acies",
                                        "value": 1_000_000}], "bio_value": 1_000_000})

    class DB:
        def system_id_by_address(self, a):
            return 5

        def system_bodies(self, sid, cid):
            return {"planets": [{"id": 1, "name": "Alpha 1", "mapped": 1},
                                {"id": 3, "name": "Alpha 3", "mapped": 0}]}

        def planet_flora(self, pid, cid):
            return [{"species": "Bacterium Acies", "logged": 1}] if pid == 3 else []
    import core.bodies_db as BDB
    monkeypatch.setattr(BDB, "get_db", lambda: DB())
    core = SimpleNamespace(plugin_call=lambda *a, **k: 1)
    t = survey.todo(core, "Alpha", 2, stop)
    assert t["done"] == 2 and [m[0] for m in t["map"]] == ["2"] and t["sample"] == []
    assert survey.todo_text(t).startswith("1 to map (")
