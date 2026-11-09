"""tests/test_mining_callouts.py — prospector, motherlode, hold and ring
callouts; hotspot hit rates; and yields by ring type.

Yields by ring type are kept across sessions, from live prospecting only —
replaying the journal at startup must not count a rock a second time.
"""
from __future__ import annotations

import importlib.util
import sys
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

spec = importlib.util.spec_from_file_location("comp_mining_c", ROOT / "components" / "mining.py")
mining = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mining)

RING = "Col 285 Sector AB-C d1 3 A Ring"


class Store:
    def __init__(self):
        self.saved = {}

    def read_json(self, purpose=None):
        return dict(self.saved.get(purpose, {}))

    def write_json(self, data, purpose=None):
        import json
        self.saved[purpose] = json.loads(json.dumps(data))


def _plugin(settings=None, store=None):
    said = []
    state = SimpleNamespace(event_time=datetime.now(timezone.utc), pilot_body=RING,
                            cargo_capacity=100, cargo_items={"platinum": {"count": 0}},
                            cargo_mean_prices={}, in_preload=False)
    cfg = {"Sounds": False, "ProspectorMinerals": "Platinum, Low Temperature Diamonds",
           "ProspectorPercent": 20, **(settings or {})}
    callouts = SimpleNamespace(settings=lambda: dict(cfg))
    core = SimpleNamespace(state=state, gui_queue=None, notify_levels={},
                           _plugins={"callouts": callouts},
                           register_session_provider=lambda p: None,
                           emitter=SimpleNamespace(emit=lambda **k: said.append(k["msg_term"])))
    p = mining.ActivityMiningPlugin()
    p.storage = store or Store()
    p.on_load(core)
    return p, state, said


def _ring(p, state, hotspots=(("Platinum", 2),), ring_type="eRingClass_Metalic"):
    p.on_event({"event": "Scan", "BodyName": "Col 285 Sector AB-C d1 3",
                "ReserveLevel": "PristineResources",
                "Rings": [{"Name": RING, "RingClass": ring_type}]}, state)
    p.on_event({"event": "SAASignalsFound", "BodyName": RING,
                "Signals": [{"Type": n, "Count": c} for n, c in hotspots]}, state)


def _rock(p, state, mats, mother="", content="$AsteroidMaterialContent_High;"):
    ev = {"event": "ProspectedAsteroid", "Content": content, "Remaining": 100.0,
          "Materials": [{"Name": n, "Name_Localised": loc, "Proportion": pct}
                        for n, loc, pct in mats]}
    if mother:
        ev["MotherlodeMaterial"] = mother
    p.on_event(ev, state)


def test_watched_minerals_over_the_share_are_called_out():
    p, state, said = _plugin()
    _ring(p, state)
    _rock(p, state, [("platinum", "Platinum", 31.4), ("Osmium", "Osmium", 9.0)])
    _rock(p, state, [("platinum", "Platinum", 12.0)])
    _rock(p, state, [("LowTemperatureDiamond", "Low Temperature Diamonds", 25.0)])
    assert said == ["Platinum 31%", "Low Temperature Diamonds 25%"]


def test_a_motherlode_is_called_out_and_a_repeat_rock_is_not():
    p, state, said = _plugin()
    _ring(p, state)
    _rock(p, state, [("Bauxite", "Bauxite", 10.0)], mother="Monazite")
    _rock(p, state, [("Bauxite", "Bauxite", 10.0)], mother="Monazite")
    assert said == ["Motherlode: Monazite — high content"]


def test_hotspot_hit_rate():
    p, state, said = _plugin()
    _ring(p, state)
    _rock(p, state, [("platinum", "Platinum", 5.0)])
    _rock(p, state, [("Osmium", "Osmium", 5.0)])
    _rock(p, state, [("platinum", "Platinum", 7.0), ("Gold", "Gold", 3.0)])
    _rock(p, state, [("platinum", "Platinum", 7.0), ("Gold", "Gold", 3.0)])   # the same rock
    assert p.hotspot_hits[(RING, "Platinum")] == [3, 2]
    rows = [r for r in p.get_tab_rows() if r["label"].strip() == "Platinum"]
    assert rows and rows[0]["rate"] == "in 2/3 rocks (67%)"


def test_yields_by_ring_type_persist_and_skip_the_replay():
    store = Store()
    p, state, said = _plugin(store=store)
    _ring(p, state)
    _rock(p, state, [("platinum", "Platinum", 30.0)], mother="Monazite")
    _rock(p, state, [("platinum", "Platinum", 10.0), ("Gold", "Gold", 4.0)])
    p.on_unload()
    laser, cores, rocks = p.ring_yields("Metallic")
    assert rocks == 2 and laser[0][0] == "Platinum"
    assert laser[0][1] == 100 and laser[0][2] == 20
    assert cores == [("Monazite", 1)]
    # A new session reads them back; a replayed rock is not counted again.
    q, state2, _ = _plugin(store=store)
    state2.in_preload = True
    _ring(q, state2)
    _rock(q, state2, [("Gold", "Gold", 50.0)])
    assert q.ring_yields("Metallic")[2] == 2


def test_dropping_into_the_ring_describes_it_with_your_yields():
    store = Store()
    p, state, said = _plugin(store=store)
    _ring(p, state)
    _rock(p, state, [("platinum", "Platinum", 30.0)])
    said.clear()
    p.on_event({"event": "SupercruiseExit", "BodyType": "PlanetaryRing", "Body": RING}, state)
    assert said == [f"{RING}: Metallic · Pristine · hotspots Platinum ×2 — your metallic "
                    "rings (1 rocks): Platinum 100% of rocks at 30%"]


def test_the_hold_nearly_full_then_full_once_each():
    p, state, said = _plugin()
    for carried in (80, 89, 90, 95, 99, 100, 100):
        state.cargo_items = {"platinum": {"count": carried - 1}}
        p.on_event({"event": "MiningRefined", "Type": "$platinum_name;"}, state)
    assert said[0].startswith("Hold 90% full")
    assert said[1:] == ["Hold full — 100 t"]
