"""tests/test_route_view.py — the route being flown, and the range it is flown at.
"""
from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core import route_view as RV  # noqa: E402
from core.state import MonitorState  # noqa: E402

PICTOR_LOADOUT = {
    "event": "Loadout", "Ship": "explorer_nx", "ShipName": "PICTOR",
    "MaxJumpRange": 66.942406, "UnladenMass": 1459.800049, "CargoCapacity": 75,
    "FuelCapacity": {"Main": 88.0, "Reserve": 1.14},
    "Modules": [{"Slot": "FrameShiftDrive",
                 "Item": "int_hyperdrive_overcharge_size8_class5_overchargebooster_mkii",
                 "Engineering": {"Modifiers": [
                     {"Label": "FSDOptimalMass", "Value": 7528.039551}]}}],
}


def _pictor(fuel=88.0, cargo=0):
    from components.commander import CommanderPlugin
    s = MonitorState()
    p = CommanderPlugin.__new__(CommanderPlugin)
    p.core = SimpleNamespace(state=s, gui_queue=None)
    p.on_event(dict(PICTOR_LOADOUT), s)
    s.fuel_current = fuel
    s.cargo_items = {"x": {"count": cargo}} if cargo else {}
    return s


def test_the_range_the_ship_has_with_a_full_tank():
    # From the drive's own figures (core/fsd.py).
    s = _pictor()
    assert round(RV.plan_range(s), 2) == 63.43
    # Lighter as the tank empties; heavier with cargo.
    assert RV.jump_range(s, fuel=10) > RV.plan_range(s)
    assert round(RV.jump_range(_pictor(cargo=75), fuel=88), 2) == 60.5
    # The best is the game's own figure: one jump's fuel, no cargo.
    assert round(RV.jump_range(s, fuel=s.ship_drive.max_fuel, cargo=0), 3) == 66.942
    # Below one jump's fuel, the fuel limits the jump.
    assert RV.jump_range(s, fuel=2.0) < RV.jump_range(s, fuel=s.ship_drive.max_fuel)
    assert RV.jump_range(s, fuel=0) == 0


def test_a_guardian_booster_is_added_not_scaled():
    assert RV.booster_ly([{"Item": "int_guardianfsdbooster_size5"}]) == 10.5
    from core import fsd
    lo = dict(PICTOR_LOADOUT, MaxJumpRange=66.942406 + 10.5,
              Modules=PICTOR_LOADOUT["Modules"]
              + [{"Slot": "Slot01_Size5", "Item": "int_guardianfsdbooster_size5"}])
    boosted, plain = fsd.from_loadout(lo), fsd.from_loadout(PICTOR_LOADOUT)
    assert boosted.booster == 10.5
    for fuel, cargo in ((88, 0), (40, 75), (3, 0)):
        assert abs(fsd.jump_range(boosted, fuel, cargo)
                   - fsd.jump_range(plain, fuel, cargo) - 10.5) < 1e-9


def test_no_loadout_no_range():
    assert RV.plan_range(MonitorState()) is None
    assert "by hand" in RV.range_hint(MonitorState())


def test_pre_filled_fields_follow_the_game_until_typed_in():
    assert RV.autofill("", None, "Wregoe OJ-I c9-2") == "Wregoe OJ-I c9-2"
    # Still what EDLD put there: follows the commander to the next system.
    assert RV.autofill("HIP 27685", "HIP 27685", "Wregoe OJ-I c9-2") == "Wregoe OJ-I c9-2"
    # Typed by hand: left alone.
    assert RV.autofill("68.95", "63.14", "63.10") is None
    assert RV.autofill("63.14", "63.14", "63.14") is None


SPANSH = {
    "distance": 1457.2, "range": 63.14, "total_jumps": 6,
    "system_jumps": [
        {"system": "HIP 27685", "distance_jumped": 0, "jumps": 0, "neutron_star": True},
        {"system": "HIP 23520", "distance_jumped": 509.09, "jumps": 3, "neutron_star": True},
        {"system": "Wreguia HK-A d10", "distance_jumped": 194.21, "jumps": 1,
         "neutron_star": True},
        {"system": "HD 232819", "distance_jumped": 109.63, "jumps": 2, "neutron_star": False},
    ],
}


def test_a_neutron_route_counts_its_jumps_and_boosts():
    status, rows = RV.plot_summary(SPANSH, neutron=True)
    # 3 + 1 + 2 legs, not the waypoint count; boosts are legs from a neutron
    # star, not every jump.
    assert status.startswith("6 jumps · 1,457 ly · 3 neutron boosts")
    assert "plotted at 63.14 ly" in status
    assert rows[1] == ("2. HIP 23520", "509.1 ly · 3 jumps · [magenta]★ neutron[/magenta]")
    assert rows[3] == ("4. HD 232819", "109.6 ly · 2 jumps")


# ── The route being flown ─────────────────────────────────────────────────────

def _core_with_route(route, here, fuel=88.0):
    from components.navigation import NavigationPlugin
    s = _pictor(fuel=fuel)
    s.pilot_system = here
    nav = NavigationPlugin.__new__(NavigationPlugin)
    nav.core = SimpleNamespace(state=s, journal_dir="/nonexistent", gui_queue=None)
    s.nav_transit_to = ""
    s.nav_follow_enabled = False
    s.nav_follow_status = ""
    nav._edld_route = {"timestamp": "2026-10-24T05:00:00Z", "Route": route}
    nav._dismissed_sig = ""
    return SimpleNamespace(state=s, _plugins={"navigation": nav})


ROUTE = [
    {"StarSystem": "A", "StarPos": [0.5, 0, 0], "StarClass": "K"},
    {"StarSystem": "B", "StarPos": [40.5, 0, 0], "StarClass": "M"},
    {"StarSystem": "C", "StarPos": [110.5, 0, 0], "StarClass": "N"},   # 70 ly: too far
    {"StarSystem": "D", "StarPos": [400.5, 0, 0], "StarClass": "DA",
     "EDLD": {"jumps": 2}},                                            # neutron leg
    {"StarSystem": "E", "StarPos": [420.5, 0, 0], "StarClass": "Y"},
]


def test_where_the_commander_is_and_what_is_ahead():
    v = RV.route_view(_core_with_route(ROUTE, "A"))
    assert v["position"] == 1 and v["waypoints"] == 5 and v["destination"] == "E"
    assert v["jumps_left"] == 1 + 1 + 2 + 1
    assert round(v["distance_left"]) == 420
    by = {leg["system"]: leg for leg in v["ahead"]}
    assert by["B"]["kind"] == "scoopable" and not by["B"]["too_far"]
    assert by["C"]["kind"] == "neutron" and by["C"]["too_far"]
    assert by["D"]["kind"] == "white_dwarf" and not by["D"]["too_far"]
    assert by["E"]["kind"] == "other"
    rows = RV.route_rows(v)
    assert ("kv", "Position", "1 of 5") in rows
    assert any(r[1] == "2. C" and "beyond range" in r[2] for r in rows if r[0] == "kv")


def test_off_the_route_says_so():
    v = RV.route_view(_core_with_route(ROUTE, "Somewhere else"))
    assert not v["on_route"]
    assert ("kv", "Position", "[yellow]not on this route[/yellow]") in RV.route_rows(v)


def test_edam_gets_the_same_facts_in_plain_words():
    from core.windows import wire
    core = _core_with_route(ROUTE, "B")
    route = next(p for p in wire.panels(core) if p["id"] == "navigation.route")
    flat = repr(route)
    assert "Jumps left" in flat and "Ahead" in flat
    assert "[" + "red]" not in flat               # no markup on the wire
    assert "beyond range" in flat and "2 jumps" in flat
    # The markup's color comes across as a tone.
    assert any(r.get("tone") == "crit" for r in route["rows"])


def test_both_front_ends_have_the_route_tab_first():
    for p in ("gui/blocks/navigation.py", "tui/blocks/navigation.py"):
        src = (ROOT / p).read_text(encoding="utf-8")
        assert "route_rows(RV.route_view(self.core))" in src
        assert "RV.autofill(" in src
        # The plot forms are described once, not drawn by hand here.
        assert "plot_fsd_route" not in src and "plot_neutron_route" not in src
    gui = (ROOT / "gui/blocks/navigation.py").read_text(encoding="utf-8")
    assert gui.index('"Route")') < gui.index("for tab in TT.tabs(self.core)")
    tui = (ROOT / "tui/blocks/navigation.py").read_text(encoding="utf-8")
    assert tui.index('TabPane("Route"') < tui.index("for tab in self._tool_tabs.values()")
    plots = (ROOT / "core/plot_tools.py").read_text(encoding="utf-8")
    assert "RV.plot_summary(result, neutron)" in plots


# ── Supercharged legs ─────────────────────────────────────────────────────────

PICTOR_NOW = dict(PICTOR_LOADOUT, MaxJumpRange=81.455025, UnladenMass=1198.5)

# The game's own route (NavRoute.json, 2026-11-11): from Sorbago through the
# white dwarf BPM 890, whose ×3 boost carries the 228.7 ly leg after it.
SORBAGO_ROUTE = [
    {"StarSystem": "Sorbago", "StarPos": [60.96875, -72.09375, 37.40625], "StarClass": "K"},
    {"StarSystem": "BPM 890", "StarPos": [58.31250, -34.68750, 41.50000], "StarClass": "DA"},
    {"StarSystem": "Synuefe YA-M c24-20", "StarPos": [283.31250, -50.59375, 3.62500],
     "StarClass": "M"},
    {"StarSystem": "Synuefe FI-W b49-2", "StarPos": [358.93750, -55.84375, -2.40625],
     "StarClass": "M"},
    {"StarSystem": "Synuefe EW-L c24-17", "StarPos": [431.00000, -68.15625, -22.93750],
     "StarClass": "G"},
]


def _core_now(route, here, fuel=88.0):
    from core import fsd
    core = _core_with_route(route, here, fuel)
    core.state.ship_drive = fsd.from_loadout(PICTOR_NOW)
    return core


def test_the_mk2_drive_boosts_white_dwarfs_x3_and_neutrons_x6():
    from core import fsd
    mk2, std = fsd.from_loadout(PICTOR_NOW), fsd.from_loadout(dict(
        PICTOR_NOW, Modules=[{"Slot": "FrameShiftDrive",
                              "Item": "int_hyperdrive_size8_class5"}]))
    assert (fsd.star_boost(mk2, "DA"), fsd.star_boost(mk2, "N")) == (3.0, 6.0)
    assert (fsd.star_boost(std, "DAB"), fsd.star_boost(std, "N")) == (1.5, 4.0)
    assert fsd.star_boost(mk2, "K") == fsd.star_boost(mk2, "") == 1.0
    # A boosted jump burns what a jump of a third the length would.
    assert fsd.jump_fuel(mk2, 228.7, 88) is None
    assert abs(fsd.jump_fuel(mk2, 228.7, 88, boost=3.0)
               - fsd.jump_fuel(mk2, 228.7 / 3, 88)) < 1e-12
    assert fsd.jump_fuel(mk2, 240.0, 88, boost=3.0) is None


def test_a_leg_from_a_white_dwarf_is_in_range():
    v = RV.route_view(_core_now(SORBAGO_ROUTE, "Sorbago"))
    assert round(v["range_now"], 2) == 76.31
    by = {leg["system"]: leg for leg in v["ahead"]}
    ya = by["Synuefe YA-M c24-20"]
    assert round(ya["leg_ly"], 1) == 228.7 and not ya["too_far"] and ya["boost"] == 3.0
    assert by["BPM 890"]["boost"] == 1.0 and by["Synuefe FI-W b49-2"]["boost"] == 1.0
    # Fuel: no false dry tank, no false dry stretch.
    f = v["fuel"]
    assert f["runs_out_at"] == "" and f["dry"] == []
    assert RV.fuel_lines(v) == []
    rows = RV.route_rows(v)
    assert any(r[1] == "2. Synuefe YA-M c24-20" and "×3 boost" in r[2]
               and "beyond range" not in r[2] for r in rows if r[0] == "kv")
    assert "×3 boost" in RV.leg_text(ya)


def test_a_long_leg_from_an_ordinary_star_is_still_beyond_range():
    r = [dict(e) for e in SORBAGO_ROUTE]
    r[1]["StarClass"] = "M"
    v = RV.route_view(_core_now(r, "Sorbago"))
    ya = next(leg for leg in v["ahead"] if leg["system"] == "Synuefe YA-M c24-20")
    assert ya["too_far"] and ya["boost"] == 1.0
    assert v["fuel"]["runs_out_at"] == "Synuefe YA-M c24-20"


def test_a_boost_taken_counts_and_the_jump_spends_it():
    from components.navigation import NavigationPlugin
    core = _core_now(SORBAGO_ROUTE, "BPM 890")
    nav = core._plugins["navigation"]
    s = core.state
    s.in_preload = True
    NavigationPlugin.on_event(nav, {"event": "JetConeBoost", "BoostValue": 3.0}, s)
    assert s.nav_jet_boost == 3.0
    v = RV.route_view(core)
    assert v["ahead"][0]["boost"] == 3.0 and not v["ahead"][0]["too_far"]
    # Off the route, only the boost taken can carry the first leg.
    nav._edld_route = {"timestamp": "2026-10-24T05:00:00Z", "Route": SORBAGO_ROUTE[2:]}
    s.pilot_system = "BPM 890 (off the route)"
    s.pilot_star_pos = [58.3125, -34.6875, 41.5]
    first = RV.route_view(core)["ahead"][0]
    assert not first["too_far"] and first["boost"] == 3.0
    s.nav_jet_boost = 0.0
    assert RV.route_view(core)["ahead"][0]["too_far"]
    s.nav_jet_boost = 3.0
    NavigationPlugin.on_event(nav, {"event": "FSDJump", "StarSystem": "X",
                                    "StarPos": [0, 0, 0]}, s)
    assert s.nav_jet_boost == 0.0
