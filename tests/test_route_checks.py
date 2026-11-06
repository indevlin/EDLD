"""
tests/test_route_checks.py — what a route is checked for when it is plotted
and followed: where the fuel runs out, dry stretches, permit-locked stops, a
target that is not the next system, and re-plotting after leaving the route.
"""
from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core import fsd, route_fuel  # noqa: E402
from core.state import MonitorState  # noqa: E402

# A class-5 size-5 drive's constants on a 300 t ship with a 16 t tank:
# about 25 ly a jump on a full tank, five full-range jumps to the tank.
DRIVE = fsd.Drive(item="int_hyperdrive_size5_class5", optimal_mass=1050.0, max_fuel=5.0,
                  fuel_multiplier=0.012, fuel_power=2.45, booster=0.0, unladen=300.0,
                  tank=16.0, reserve=0.6, max_jump_range=0.0, supercharge=4, source="table")


def _route(classes, step=20.0):
    return [{"StarSystem": f"S{i}", "SystemAddress": 100 + i, "StarClass": c,
             "StarPos": [i * step, 0.0, 0.0]} for i, c in enumerate(classes)]


def _state(fuel=16.0, scoop=True):
    s = MonitorState()
    s.in_preload = False
    s.ship_drive, s.fuel_current, s.ship_has_scoop = DRIVE, fuel, scoop
    return s


def test_where_the_fuel_runs_out():
    a = route_fuel.analyse(_state(fuel=6.0), _route("KKKKKKKKKK"))
    assert a["runs_out_at"] and 0 < a["runs_out_after"] < 9
    assert len(a["fuel_after"]) == a["runs_out_after"] - 1
    full = route_fuel.analyse(_state(), _route("KK"))
    assert full["runs_out_at"] == "" and full["fuel_after"][0] < 16


def test_dry_stretches():
    a = route_fuel.analyse(_state(), _route("K" + "LTYLT" + "K"))
    assert a["dry"] == [{"after": "S0", "jumps": 6, "too_long": False}]
    long = route_fuel.analyse(_state(), _route("K" + "LTYLTLTYLTY" + "K", step=24.0))
    assert long["dry"][0]["too_long"] is True
    short = route_fuel.analyse(_state(), _route("KLLK"))
    assert short["dry"] == []


def test_multi_jump_legs_are_not_judged():
    r = _route("KNK")
    r[1]["EDLD"] = {"jumps": 5}
    assert route_fuel.analyse(_state(), r) is None
    assert route_fuel.analyse(MonitorState(), _route("KK")) is None     # no drive known


def _nav(state, spansh=None, cfg=None):
    from components.navigation import NavigationPlugin
    said = []
    core = SimpleNamespace(state=state, gui_queue=None, notify_levels={},
                           journal_dir=Path("/nonexistent"),
                           _plugins={"spansh": spansh} if spansh else {},
                           load_setting=lambda s, d, warn=False: dict(cfg or {}),
                           emitter=SimpleNamespace(emit=lambda **k: said.append(k["msg_term"])))
    p = NavigationPlugin.__new__(NavigationPlugin)
    p.core = core
    state.nav_transit_to = ""          # set by on_load
    p._permits, p._edld_route, p._dismissed_sig = {}, None, None
    p._warned_target, p._replotting, p._replotted_from, p._arrivals = "", False, "", []
    return p, said


def test_permit_locked_stops_are_named():
    spansh = SimpleNamespace(systems_by_id64=lambda ids: {102: {"needs_permit": True}})
    p, said = _nav(_state(), spansh)
    p._check_route_inner({"Route": _route("KKKK")})
    assert said == ["Route passes permit-locked systems: S2"]
    # Spansh out of reach is not "no permits", and asks again next time.
    spansh.systems_by_id64 = lambda ids: None
    p2, said2 = _nav(_state(), spansh)
    p2._check_route_inner({"Route": _route("KKKK")})
    assert said2 == [] and p2._permits == {}


def test_no_scoop_on_a_route_longer_than_the_tank():
    p, said = _nav(_state(fuel=6.0, scoop=False), SimpleNamespace(systems_by_id64=lambda ids: {}))
    p._check_route_inner({"Route": _route("KKKKKKKKKK")})
    assert len(said) == 1 and said[0].startswith("No fuel scoop fitted, and the tank runs dry at S")


def test_a_target_off_the_route(monkeypatch):
    p, said = _nav(_state())
    route = _route("KKKK")
    p.active_route = lambda: (route, "edld")
    p.core.state.pilot_system = "S1"
    p._check_target({"event": "FSDTarget", "Name": "Elsewhere"}, p.core.state)
    p._check_target({"event": "FSDTarget", "Name": "Elsewhere"}, p.core.state)
    p._check_target({"event": "FSDTarget", "Name": "S3"}, p.core.state)     # further along
    p._check_target({"event": "FSDTarget", "Name": "S2"}, p.core.state)
    assert said == ["Targeted Elsewhere; the route's next system is S2"]


def test_leaving_the_route_replots_once_from_where_you_are(monkeypatch):
    p, said = _nav(_state())
    p._edld_route = {"Route": _route("KKK"), "EDLDPlot": {"kind": "fsd", "to": "S2", "range": 25}}
    started = []
    import threading
    monkeypatch.setattr(threading, "Thread",
                        lambda target, args, **k: SimpleNamespace(start=lambda: started.append(args)))
    p.core.state.pilot_system = "Detour"
    p._on_arrival(_route("KKK"), "edld", {"StarSystem": "Detour"})
    p._on_arrival(_route("KKK"), "edld", {"StarSystem": "Detour"})
    assert len(started) == 1 and started[0][1] == "Detour"
    p._replotting = False
    p._on_arrival(_route("KKK"), "journal", {"StarSystem": "Elsewhere"})     # the game's route
    assert len(started) == 1
