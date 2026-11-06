"""
tests/test_srv_hull_fuel.py — an SRV's hull and fuel are not the ship's.

From a real session, 20261018: driving the SRV Rhino, it rolled and its hull
fell to 20% in a second. The alerts component wrote that to the ship's hull
and announced "Ship hull: 20%" over a ship at 100%; the crew component posted
the same damage to the terminal and Discord a second time; and on the next
start the hull bootstrap read it back as the ship's. Resuming in the SRV,
LoadGame's FuelLevel — the SRV's, 0 — and Status.json's FuelMain — 0 in an
SRV — put the ship's fuel at 0% in red.
"""
from __future__ import annotations

import json
import queue
import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.state import MonitorState  # noqa: E402

SRV_HIT = {"timestamp": "2026-10-18T08:00:09Z", "event": "HullDamage",
           "Health": 0.198991, "PlayerPilot": True}


def _alerts(state):
    import components.alerts as A
    state.in_preload = False
    from collections import deque
    p = A.AlertsPlugin.__new__(A.AlertsPlugin)
    p.alert_queue = deque(maxlen=5)
    p.faults = []
    said = []
    p.core = SimpleNamespace(state=state, gui_queue=None, cfg=None, app_settings={},
                             notify_levels={"HullEvent": 3},
                             emitter=SimpleNamespace(emit=lambda **k: said.append(k)))
    return p, said


def test_srv_damage_is_the_srvs():
    state = MonitorState()
    state.vessel_mode = "srv"
    state.ship_hull = 100
    p, said = _alerts(state)
    p.on_event(dict(SRV_HIT), state)
    assert state.ship_hull == 100
    assert state.srv_hull == 20
    assert p.get_alerts()[0]["text"] == "SRV hull: 20%"
    assert "SRV hull damaged" in said[0]["msg_term"]


def test_ship_damage_is_still_the_ships():
    state = MonitorState()
    state.vessel_mode = "ship"
    p, _ = _alerts(state)
    p.on_event(dict(SRV_HIT), state)
    assert state.ship_hull == 20
    assert p.get_alerts()[0]["text"] == "Ship hull: 20%"


def test_the_crew_component_no_longer_announces_the_commanders_hull():
    import components.crew_slf as C
    cls = next(getattr(C, n) for n in dir(C) if n.endswith("Plugin")
               and isinstance(getattr(C, n), type) and getattr(C, n).__module__ == C.__name__)
    p = cls.__new__(cls)
    said = []
    state = MonitorState()
    state.vessel_mode = "srv"
    p.core = SimpleNamespace(state=state, gui_queue=None, cfg=None, app_settings={},
                             notify_levels={"HullEvent": 3, "FighterDamage": 2},
                             emitter=SimpleNamespace(emit=lambda **k: said.append(k)))
    p.on_event(dict(SRV_HIT), state)
    assert said == [] and state.ship_hull == 100


def _write(jdir, name, events):
    (jdir / name).write_text("\n".join(json.dumps(e) for e in events) + "\n",
                             encoding="utf-8")


def test_the_hull_bootstrap_skips_srv_damage(tmp_path):
    from core.journal import bootstrap_hull
    _write(tmp_path, "Journal.2026-10-17T173002.01.log", [
        {"timestamp": "2026-10-18T07:00:00Z", "event": "HullDamage", "Health": 0.9,
         "PlayerPilot": True},
        {"timestamp": "2026-10-18T07:34:53Z", "event": "LaunchSRV", "SRVType": "mev_rhino"},
        dict(SRV_HIT),
    ])
    state = MonitorState()
    state.vessel_mode = "srv"
    bootstrap_hull(state, tmp_path)
    assert state.ship_hull == 90, "the SRV's 20% was taken for the ship's"


def test_the_hull_bootstrap_after_docking_the_srv(tmp_path):
    from core.journal import bootstrap_hull
    _write(tmp_path, "Journal.2026-10-17T173002.01.log", [
        {"timestamp": "2026-10-18T07:00:00Z", "event": "HullDamage", "Health": 0.8,
         "PlayerPilot": True},
        {"timestamp": "2026-10-18T07:34:53Z", "event": "LaunchSRV"},
        dict(SRV_HIT),
        {"timestamp": "2026-10-18T07:40:00Z", "event": "DockSRV"},
    ])
    state = MonitorState()
    state.vessel_mode = "ship"
    bootstrap_hull(state, tmp_path)
    assert state.ship_hull == 80


def test_status_json_fuel_in_an_srv_is_not_the_ships(tmp_path):
    import importlib.util
    spec = importlib.util.spec_from_file_location("cmdr_fuel", ROOT / "components" / "commander.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    p = mod.CommanderPlugin.__new__(mod.CommanderPlugin)
    state = MonitorState()
    state.fuel_current = 24.0
    core = SimpleNamespace(state=state, journal_dir=str(tmp_path))
    (tmp_path / "Status.json").write_text(json.dumps(
        {"Flags": 0x04000000 | 0x01000000, "Fuel": {"FuelMain": 0.0, "FuelReservoir": 0.4}}))
    p._read_status_json(core)
    assert state.fuel_current == 24.0
    (tmp_path / "Status.json").write_text(json.dumps(
        {"Flags": 0x01000000, "Fuel": {"FuelMain": 20.0, "FuelReservoir": 0.4}}))
    p._read_status_json(core)
    assert state.fuel_current == 20.0


def test_the_status_poller_skips_fuel_in_an_srv():
    src = (ROOT / "core" / "journal.py").read_text(encoding="utf-8")
    poll = src[src.index("def _poll_status_json"):]
    poll = poll[:poll.index("\ndef ")]
    assert "0x04000000" in poll and "Flags2" in poll


def test_loadgame_in_an_srv_leaves_the_ships_fuel():
    """In an SRV LoadGame's fuel is the SRV's, on foot the suit's: only in
    the ship is it the ship's (tests/test_on_foot.py has the suit)."""
    src = (ROOT / "components" / "commander.py").read_text(encoding="utf-8")
    assert 'if lg_fuel is not None and state.vessel_mode == "ship":' in src


def test_session_management_names_the_srv():
    src = (ROOT / "components" / "ksw.py").read_text(encoding="utf-8")
    assert '"SRV hull"' in src
    assert "ending the game session" in src, "a kill must reach the diagnostic log"


def test_a_ship_swap_does_not_keep_the_last_ships_fuel():
    """Swapping from a 128 t Panther to a 32 t Type-11 kept the Panther's
    128 t as the fuel aboard — 400% on the strip and the Info tab — until
    the game wrote Status.json again, and for good once it had shut down.
    The swap gives no fuel level, so the level is unknown until something
    says it."""
    import importlib.util
    spec = importlib.util.spec_from_file_location("cmdr_swap", ROOT / "components" / "commander.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    p = mod.CommanderPlugin.__new__(mod.CommanderPlugin)
    state = MonitorState()
    state.in_preload = True
    p.core = SimpleNamespace(
        state=state, journal_dir="/nonexistent", gui_queue=None,
        active_session=SimpleNamespace(fuel_check_time=0, fuel_check_level=0),
        emitter=SimpleNamespace(emit=lambda **k: None), notify_levels={})
    state.fuel_current, state.fuel_tank_size = 114.0, 128
    p.on_event({"event": "ShipyardSwap", "ShipType": "lakonminer",
                "ShipType_Localised": "Type-11 Prospector"}, state)
    p.on_event({"event": "Loadout", "Ship": "lakonminer", "ShipName": "FOSSOR",
                "FuelCapacity": {"Main": 32.0, "Reserve": 0.6}, "Modules": []}, state)
    assert state.fuel_current is None and state.fuel_tank_size == 32.0
    from core import edcars
    assert "fuel" not in {f.key for f in edcars.strip(state)}

    # A Loadout alone (a ship's tank changed in outfitting) keeps a level that fits.
    state.fuel_current = 30.0
    p.on_event({"event": "Loadout", "Ship": "lakonminer", "ShipName": "FOSSOR",
                "FuelCapacity": {"Main": 32.0, "Reserve": 0.6}, "Modules": []}, state)
    assert state.fuel_current == 30.0
