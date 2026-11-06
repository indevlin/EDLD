"""
tests/test_callouts.py — the Callouts component: firsts, the codex, sample
runs, limpets and the targeting cue.

Each callout is checked against the journal events that should raise it and
the ones that should not, through the same path the dashboard uses
(core/callout.say → the emitter), with sounds off.
"""
from __future__ import annotations

import sys
import time
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.state import MonitorState  # noqa: E402


def _plugin(settings=None, plugins=None):
    from components.callouts import CalloutsPlugin
    said = []
    state = MonitorState()
    state.in_preload = False          # live, not replaying the journal
    cfg = {"Sounds": False, **(settings or {})}
    core = SimpleNamespace(
        state=state, gui_queue=None, notify_levels={}, _plugins=dict(plugins or {}),
        load_setting=lambda section, defaults, warn=False: dict(cfg),
        plugin_call=lambda *a, **k: None,
        emitter=SimpleNamespace(emit=lambda **k: said.append(k["msg_term"])))
    p = CalloutsPlugin.__new__(CalloutsPlugin)
    p.core = core
    core._plugins["callouts"] = p
    p.on_load = None
    import threading
    p._lock = threading.Lock()
    p._scans, p._system, p._run, p._run_thread, p._target_seq = {}, "", None, None, 0
    return p, state, said


def test_an_undiscovered_arrival_star_is_called_out():
    p, state, said = _plugin()
    p.on_event({"event": "FSDJump", "StarSystem": "Oochost AB-C d1-2"}, state)
    p.on_event({"event": "Scan", "ScanType": "AutoScan", "BodyName": "Oochost AB-C d1-2",
                "StarType": "K", "DistanceFromArrivalLS": 0.0, "WasDiscovered": False}, state)
    assert said == ["Oochost AB-C d1-2: undiscovered system"]


def test_a_discovered_one_is_not_and_nothing_during_replay():
    p, state, said = _plugin()
    p.on_event({"event": "Scan", "BodyName": "Sol", "StarType": "G",
                "DistanceFromArrivalLS": 0.0, "WasDiscovered": True}, state)
    state.in_preload = True
    p.on_event({"event": "Scan", "BodyName": "X", "StarType": "G",
                "DistanceFromArrivalLS": 0.0, "WasDiscovered": False}, state)
    assert said == []


def test_first_mapping_and_first_footfall():
    p, state, said = _plugin()
    p.on_event({"event": "Scan", "BodyName": "X 1", "PlanetClass": "Icy body",
                "WasDiscovered": False, "WasMapped": False, "WasFootfalled": False,
                "Landable": True}, state)
    p.on_event({"event": "SAAScanComplete", "BodyName": "X 1"}, state)
    p.on_event({"event": "Touchdown", "Body": "X 1", "PlayerControlled": True}, state)
    p.on_event({"event": "Disembark", "Body": "X 1", "OnPlanet": True}, state)
    p.on_event({"event": "Disembark", "Body": "X 1", "OnPlanet": True}, state)
    assert said == ["X 1: first to map it",
                    "X 1: no one has set foot here — step out for first footfall",
                    "X 1: first footfall"]


def test_ground_already_trodden_says_nothing():
    p, state, said = _plugin()
    p.on_event({"event": "Scan", "BodyName": "X 2", "WasDiscovered": True, "WasMapped": True,
                "WasFootfalled": True, "Landable": True}, state)
    p.on_event({"event": "Touchdown", "Body": "X 2", "PlayerControlled": True}, state)
    # A scan from before the game reported footfall says nothing either way.
    p.on_event({"event": "Scan", "BodyName": "X 3", "WasDiscovered": False, "Landable": True}, state)
    p.on_event({"event": "Touchdown", "Body": "X 3", "PlayerControlled": True}, state)
    assert said == []


def test_an_unfinished_run_is_warned_of_before_it_is_lost():
    p, state, said = _plugin({"SafeToSample": False})
    p.on_event({"event": "ScanOrganic", "ScanType": "Log", "Species_Localised": "Bacterium Acies"}, state)
    # Lifting off to fly to the next site is how a run is flown.
    p.on_event({"event": "Liftoff", "PlayerControlled": True}, state)
    assert said == []
    p.on_event({"event": "SupercruiseEntry"}, state)
    assert said == ["Bacterium Acies: 2 samples short — leaving the body loses the run"]
    p.on_event({"event": "LeaveBody"}, state)
    p.on_event({"event": "SupercruiseEntry"}, state)
    assert len(said) == 1


def test_a_finished_run_says_nothing():
    p, state, said = _plugin({"SafeToSample": False})
    for kind in ("Log", "Sample", "Analyse"):
        p.on_event({"event": "ScanOrganic", "ScanType": kind, "Species_Localised": "Tussock Ventus"}, state)
    p.on_event({"event": "SupercruiseEntry"}, state)
    assert said == []


def test_safe_to_sample_is_said_once_clear(monkeypatch):
    import components.callouts as C
    monkeypatch.setattr(C, "_SAMPLE_POLL_S", 0.02)
    p, state, said = _plugin()
    state.planet_radius = 1_000_000.0
    state.surface_latitude, state.surface_longitude = 0.0, 0.0
    p.on_event({"event": "ScanOrganic", "ScanType": "Log", "Species_Localised": "Bacterium Acies"}, state)
    time.sleep(0.1)
    assert said == []
    # Bacterium: 500 m. One degree of longitude here is about 17.5 km.
    state.surface_longitude = 0.1
    deadline = time.time() + 2
    while not said and time.time() < deadline:
        time.sleep(0.02)
    assert said == ["Clear of earlier samples — Bacterium Acies sample 2/3 here"]
    time.sleep(0.1)
    assert len(said) == 1
    p._stop_run()


def test_undocking_with_controllers_and_no_limpets():
    p, state, said = _plugin()
    state.ship_limpet_controllers = ["collection", "prospector"]
    state.cargo_capacity = 64
    state.cargo_items = {}
    p.on_event({"event": "Undocked"}, state)
    assert said == ["No limpets aboard — collector, prospector controllers fitted"]
    p.on_event({"event": "Undocked"}, state)
    assert len(said) == 1                 # once per ship, until it carries limpets again
    state.cargo_items = {"drones": {"count": 20}}
    p.on_event({"event": "Undocked"}, state)
    assert len(said) == 1
    state.cargo_items = {}
    p.on_event({"event": "Undocked"}, state)
    assert len(said) == 2
    # Any type of controller counts — a repair controller on its own too.
    state.ship_limpet_controllers, state.ship_id = ["repair"], 99
    p.on_event({"event": "Undocked"}, state)
    assert said[-1] == "No limpets aboard — repair controller fitted"
    # No controller at all: never reminded.
    state.ship_limpet_controllers, state.ship_id = [], 100
    p.on_event({"event": "Undocked"}, state)
    assert len(said) == 3


def test_each_type_of_controller_has_its_own_switch():
    from components.callouts import LIMPET_TYPES
    p, state, said = _plugin({"LimpetRepair": False, "LimpetProspector": False})
    state.cargo_capacity, state.cargo_items = 64, {}
    state.ship_limpet_controllers, state.ship_id = ["repair"], 1
    p.on_event({"event": "Undocked"}, state)
    assert said == []                              # its only controller is switched off
    state.ship_limpet_controllers, state.ship_id = ["mining", "prospector"], 2
    p.on_event({"event": "Undocked"}, state)
    assert said == ["No limpets aboard — mining multi-limpet controller fitted"]
    p2, state2, said2 = _plugin({"LimpetReminder": False})
    state2.cargo_capacity, state2.cargo_items = 64, {}
    state2.ship_limpet_controllers = ["prospector"]
    p2.on_event({"event": "Undocked"}, state2)
    assert said2 == []                             # the master switch
    # One setting per type, all on by default, each drawn in Options.
    keys = {s.key for s in p.SETTINGS if hasattr(s, "key")}
    assert {key for _t, key, _n in LIMPET_TYPES} <= keys
    assert all(p.settings_defaults()[key] is True for _t, key, _n in LIMPET_TYPES)


def test_target_status_uses_the_nearby_search_then_spansh():
    finder = SimpleNamespace(known_status={5: "done"})
    spansh = SimpleNamespace(systems_by_id64=lambda ids: {7: {"id64": 7, "body_count": 3,
                                                               "bodies": [{"type": "Star"}]}})
    p, _state, _said = _plugin(plugins={"finder": finder, "spansh": spansh})
    assert p.target_status(5) == "done"
    assert p.target_status(7) == "star"
    assert p.target_status(9) == "new"
    spansh.systems_by_id64 = lambda ids: None
    assert p.target_status(9) is None       # offline is not "never reported"


def test_every_controller_in_the_game_has_a_switch():
    """Each limpet controller in the outfitting data, read the way the
    Loadout is read, maps to one of the switches."""
    import re
    from components.callouts import LIMPET_TYPES
    src = (ROOT / "data" / "outfitting.py").read_text(encoding="utf-8")
    kinds = {re.sub(r"v\d+$", "", m) for m in re.findall(r"'int_[a-z]*dronecontrol_([a-z0-9]+)", src)}
    assert kinds and kinds <= {t for t, _k, _n in LIMPET_TYPES}
