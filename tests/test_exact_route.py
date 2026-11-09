"""tests/test_exact_route.py — FSD routes from Spansh's exact plotter, with the
ship's own drive; and plotting from a system no database knows yet.
"""
from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core import fsd  # noqa: E402
from core.state import MonitorState  # noqa: E402
from tests.test_route_view import PICTOR_LOADOUT  # noqa: E402

SOL = {"name": "Sol", "id64": 10477373803, "coords": {"x": 0, "y": 0, "z": 0}}
POLARIS = {"name": "Polaris", "id64": 388367419731,
           "coords": {"x": -22.4, "y": 97.6, "z": -321.6}}

JUMPS = [
    {"name": "Sol", "id64": 10477373803, "x": 0, "y": 0, "z": 0, "distance": 0,
     "distance_to_destination": 336.8, "fuel_in_tank": 88, "fuel_used": 0,
     "has_neutron": False, "is_scoopable": False, "must_refuel": False},
    {"name": "Mid", "id64": 1, "x": -10, "y": 40, "z": -150, "distance": 60.2,
     "distance_to_destination": 180.0, "fuel_in_tank": 81.6, "fuel_used": 6.4,
     "has_neutron": False, "is_scoopable": True, "must_refuel": True},
    {"name": "Polaris", "id64": 388367419731, "x": -22.4, "y": 97.6, "z": -321.6,
     "distance": 61.0, "distance_to_destination": 0, "fuel_in_tank": 75.0,
     "fuel_used": 6.6, "has_neutron": False, "is_scoopable": False,
     "must_refuel": False},
]


def _plugin(known=(SOL, POLARIS), here=None):
    from components.spansh import SpanshPlugin
    s = MonitorState()
    s.ship_drive = fsd.from_loadout(PICTOR_LOADOUT)
    s.fuel_current = 88.0
    if here:
        s.pilot_system, s.pilot_star_pos = here
    p = SpanshPlugin.__new__(SpanshPlugin)
    p.core = SimpleNamespace(state=s)
    names = {k["name"].lower(): k for k in known}
    p._edsm_system = lambda n: names.get(n.lower())
    sent = {}

    def plot(kind, params, store_key=None, method="POST"):
        sent.update(kind=kind, method=method, **params)
        return {"jumps": [dict(j) for j in JUMPS]}
    p._plot_route = plot
    return p, sent


def test_the_ship_is_sent_as_its_drive_and_masses():
    p, sent = _plugin()
    out = p.plot_fsd_route("Sol", "Polaris", 63.43)
    assert sent["kind"] == "exact" and sent["method"] == "GET"
    assert sent["source"] == SOL["id64"] and sent["destination"] == POLARIS["id64"]
    d = p.core.state.ship_drive
    assert sent["fuel_power"] == 2.5025 and sent["max_fuel_per_jump"] == d.max_fuel
    assert sent["tank_size"] == 88.0 and sent["internal_tank_size"] == 1.14
    # Spansh's base mass carries the reservoir; the game's mass is unladen.
    assert sent["base_mass"] == round(1459.800049 + 1.14, 4)
    assert sent["use_supercharge"] == 0 and sent["supercharge_multiplier"] == 6
    assert out["total_jumps"] == 2 and out["refuels"] == 1
    assert out["system_jumps"][1]["fuel_in_tank"] == 81.6
    assert out["system_jumps"][1]["is_scoopable"] is True


def test_a_shorter_range_plots_shorter():
    p, sent = _plugin()
    p.plot_fsd_route("Sol", "Polaris", 63.43)
    full = sent["optimal_mass"]
    p.plot_fsd_route("Sol", "Polaris", 50.0)
    assert sent["optimal_mass"] < full
    d = p.core.state.ship_drive
    shorter = fsd.Drive(**{**d.as_dict(), "optimal_mass": sent["optimal_mass"]})
    assert abs(fsd.jump_range(shorter, d.tank, 0) - 50.0) < 1e-6


def test_without_a_loadout_the_old_search_still_plots():
    p, _ = _plugin()
    p.core.state.ship_drive = None
    called = []
    p._plot_fsd_greedy = lambda *a: called.append(a) or {"system_jumps": []}
    p.plot_fsd_route("Sol", "Polaris", 30.0)
    assert called


def test_a_system_just_discovered_plots_from_the_nearest_known_one():
    here = ("Nowhere AB-C d1-2", [1.0, 2.0, 3.0])
    p, sent = _plugin(here=here)
    near = {"name": "Sol", "id64": SOL["id64"], "coords": {"x": 0, "y": 0, "z": 0}}
    p._edsm_sphere_at = lambda coords, radius: [near]
    out = p.plot_fsd_route(here[0], "Polaris", 63.43)
    assert sent["source"] == SOL["id64"]
    rows = out["system_jumps"]
    assert rows[0]["system"] == here[0] and rows[1]["system"] == "Sol"
    assert rows[1]["jumps"] == 1 and abs(rows[1]["distance_jumped"] - 14 ** 0.5) < 1e-9
    assert out["stand_in"] == "Sol" and out["total_jumps"] == 3


def test_an_unknown_system_that_is_not_here_is_an_error():
    p, _ = _plugin()
    out = p.plot_fsd_route("Nowhere AB-C d1-2", "Polaris", 63.43)
    assert "doesn't know" in out["_error"]


def test_the_summary_says_fuel_and_refuels():
    from core.route_view import plot_summary
    p, _ = _plugin()
    status, rows = plot_summary(p.plot_fsd_route("Sol", "Polaris", 63.43), False)
    assert "1 refuel" in status
    assert "81.6 t left" in rows[1][1] and "refuel" in rows[1][1]
