"""
The Fleet: a fold per ship, with its figures and fitting; the Ship window's
Stats tab; and the pieces they are built from — the Loadout's figures per ship,
StoredShips' locations, Status.json's reservoir and pips.
"""
from __future__ import annotations

import asyncio
import os
from types import SimpleNamespace

import pytest

from components.assets import ship_stats_from
from core import fsd
from core.state import MonitorState
from core.windows import FOLD_ACTION, R, unfold, wire, wire_rows
from core.windows import commander as CW
from core.windows import ship as SW
from tests.test_fsd import SPECULATOR

LOADOUT = dict(SPECULATOR, ShipID=12, ShipIdent="M-SPEC", CargoCapacity=32, HullHealth=0.97,
               Rebuy=4_212_000, HullValue=50_000_000, ModulesValue=34_000_000)
FITTED = [
    {"slot": "FrameShiftDrive", "name_display": "5A Frame Shift Drive (SCO)",
     "engineering": {"BlueprintName": "FSD_LongRange", "Level": 5,
                     "ExperimentalEffect": "special_fsd_heavy"}},
    {"slot": "Armour", "name_display": "Lightweight Alloy",
     "engineering": {"BlueprintName": "Armour_HeavyDuty", "Level": 5,
                     "ExperimentalEffect": "special_armour_chunky"}},
    {"slot": "Slot01_Size6", "name_display": "6A Fuel Scoop", "engineering": {}},
]


class _Assets:
    def __init__(self, stats=None, loadouts=None):
        self.stats, self.loadouts = stats or {}, loadouts or {}

    def ship_stats(self, sid):
        return dict(self.stats.get(sid) or {})

    def loadout_for(self, sid):
        return list(self.loadouts.get(sid) or [])


def _core(**assets):
    s = MonitorState()
    s.ship_drive = fsd.from_loadout(LOADOUT)
    s.ship_max_jump_range = LOADOUT["MaxJumpRange"]
    s.ship_unladen_mass = LOADOUT["UnladenMass"]
    s.fuel_tank_size, s.fuel_current, s.fuel_reservoir = 32, 24.5, 0.41
    s.ship_pips = [4, 8, 0]
    s.cargo_capacity, s.cargo_items = 32, {"gold": {"count": 6}}
    s.assets_current_ship = {"ship_id": 12, "current": True, "name": "Speculator",
                             "ident": "m-spec", "type_display": "Mandalay", "rebuy": 4_212_000}
    s.assets_stored_ships = [
        {"ship_id": 3, "name": "Fossor", "ident": "T11-FO", "type_display": "Type-11 Prospector",
         "system": "Col 285 Sector AB-C d1", "station": "Hutton Orbital", "value": 140_000_000},
        {"ship_id": 5, "name": "", "ident": "", "type_display": "Cobra Mk V", "in_transit": True},
    ]
    return SimpleNamespace(state=s, _plugins={"assets": _Assets(**assets)})


# ── Stats ─────────────────────────────────────────────────────────────────────

def test_stats_are_the_games_figures_and_the_drive_formula():
    core = _core()
    rows = {r[1]: r[2] for r in SW.stats(core).rows if r[0] == "kv"}
    d = core.state.ship_drive
    assert rows["Now"] == f"{fsd.jump_range(d, 24.5, 6):,.2f} ly"
    assert rows["Full tank"] == f"{fsd.jump_range(d, 32, 6):,.2f} ly"
    assert rows["Unladen max"] == "76.76 ly"
    assert rows["Main tank"] == "24.50 t / 32 t"
    assert rows["Reservoir"] == "0.41 t / 0.50 t"
    assert rows["Cargo"] == "6 / 32 t"
    assert rows["Total"] == "325.9 t"
    assert rows["Pips"] == "SYS 2 · ENG 4 · WEP 0"
    assert rows["Rebuy"] == "4.2M cr"


def test_half_pips_and_no_pips():
    assert SW.pips_text([3, 6, 3]) == "SYS 1½ · ENG 3 · WEP 1½"
    assert SW.pips_text(None) == "—"


def test_stats_without_a_loadout_say_so():
    core = SimpleNamespace(state=MonitorState(), _plugins={})
    assert SW.stats(core).rows[0][0] == "text"


def test_the_stats_tab_reaches_the_wire():
    core = _core()
    ids = {p["id"]: p["group"] for p in wire.panels(core)}
    assert ids.get("ship.stats") == "ship"


# ── Fleet ─────────────────────────────────────────────────────────────────────

def test_titles_and_places():
    assert CW.ship_title({"name": "Speculator", "ident": "m-spec", "type_display": "Mandalay"}) \
        == "SPECULATOR [M-SPEC] (Mandalay)"
    assert CW.ship_title({"type_display": "Cobra Mk V"}) == "Cobra Mk V"
    assert CW.ship_title({"ident": "X-1", "type": "anaconda"}) == "[X-1] (anaconda)"
    assert CW.ship_where({"system": "Sol"}, True) == "Current ship"
    assert CW.ship_where({"in_transit": True}, False) == "In transit"
    assert CW.ship_where({"station": "Abraham Lincoln", "system": "Sol"}, False) \
        == "Abraham Lincoln (Sol)"
    assert CW.ship_where({"system": "—"}, False) == "—"


def test_a_fold_per_ship_all_closed():
    core = _core(stats={3: ship_stats_from(dict(LOADOUT, MaxJumpRange=31.2, UnladenMass=812.4,
                                                 CargoCapacity=520))},
                 loadouts={12: FITTED})
    rows = CW.ships(core).rows
    shown = unfold(rows, set())
    assert [r[1] for r in shown] == ["+ SPECULATOR [M-SPEC] (Mandalay)",
                                     "+ FOSSOR [T11-FO] (Type-11 Prospector)",
                                     "+ Cobra Mk V"]
    assert [r[4] for r in shown] == [FOLD_ACTION + "ship-12", FOLD_ACTION + "ship-3",
                                     FOLD_ACTION + "ship-5"]
    assert shown[0][3] == "val highlight"


def test_an_open_fold_shows_figures_and_fitting():
    core = _core(stats={3: ship_stats_from(dict(LOADOUT, MaxJumpRange=31.2, UnladenMass=812.4,
                                                 CargoCapacity=520))},
                 loadouts={12: FITTED})
    rows = unfold(CW.ships(core).rows, {"ship-12", "ship-3"})
    labels = [r[1] for r in rows]
    assert labels[0] == "− SPECULATOR [M-SPEC] (Mandalay)"
    i = labels.index("Fitting")
    assert labels[i + 1:i + 6] == ["5A Frame Shift Drive (SCO)", "G5 Increased Range (Mass Manager)",
                                   "Lightweight Alloy", "G5 Heavy Duty (Deep Plating)",
                                   "6A Fuel Scoop"]
    fossor = {r[1]: r[2] for r in rows[labels.index("− FOSSOR [T11-FO] (Type-11 Prospector)"):]
              if r[0] == "kv"}
    assert fossor["Unladen max jump"] == "31.20 ly"
    assert fossor["Cargo capacity"] == "520 t"
    assert fossor["Hull"] == "97%"
    assert fossor["Value"] == "140.0M cr"
    cobra = rows[labels.index("+ Cobra Mk V") + 1:]
    assert cobra == []


def test_a_ship_never_flown_says_so():
    core = _core()
    rows = unfold(CW.ships(core).rows, {"ship-5"})
    assert rows[-1] == ("text", "Not flown since EDLD's journals begin: no fitting known.", "dim")


def test_folds_on_the_wire():
    core = _core(loadouts={12: FITTED})
    w = wire_rows(CW.ships(core).rows)
    assert w[0] == {"label": "SPECULATOR [M-SPEC] (Mandalay)", "value": "Current ship",
                    "kind": "fold", "fold": "ship-12", "tone": "accent", "ident": "m-spec"}
    inside = [r for r in w if r.get("in") == "ship-12"]
    assert inside and all(r["kind"] != "fold" for r in inside)
    assert [r for r in w if r["kind"] == "fold"][2] == {
        "label": "Cobra Mk V", "value": "In transit", "kind": "fold", "fold": "ship-5"}
    groups = {p["id"]: p["group"] for p in wire.panels(core)}
    assert groups["commander.ships"] == "fleet"
    assert groups["commander.info"] == "commander"


def test_within_wraps_rows():
    assert R.within("k", [R.kv("a", "1"), None]) == [("in", "k", ("kv", "a", "1", "val"))]


# ── What the fleet is built from ─────────────────────────────────────────────

def test_ship_stats_from_a_loadout():
    st = ship_stats_from(LOADOUT)
    assert st == {"max_jump": 76.761124, "unladen": 295.0, "fuel": 32.0, "reserve": 0.5,
                  "cargo": 32, "hull": 0.97, "rebuy": 4_212_000, "value": 84_000_000}


def test_ships_here_are_where_the_event_is():
    from components.assets import AssetsPlugin
    p = AssetsPlugin.__new__(AssetsPlugin)
    p._shiptype_cache = {}
    ships = p._parse_stored_ships({
        "event": "StoredShips", "StationName": "Hutton Orbital", "StarSystem": "Alpha Centauri",
        "ShipsHere": [{"ShipID": 3, "ShipType": "type11", "Name": "Fossor", "Value": 1}],
        "ShipsRemote": [{"ShipID": 4, "ShipType": "cobramkv", "StarSystem": "Sol",
                         "ShipMarketID": 1, "Value": 2},
                        {"ShipID": 5, "ShipType": "mandalay", "InTransit": True, "Value": 3}]})
    by = {s["ship_id"]: s for s in ships}
    assert (by[3]["system"], by[3]["station"]) == ("Alpha Centauri", "Hutton Orbital")
    assert (by[4]["system"], by[4]["station"]) == ("Sol", "")
    assert by[5]["in_transit"] is True


# ── Folds in the interfaces ──────────────────────────────────────────────────

def test_tui_fold_opens_and_closes():
    pytest.importorskip("textual")
    from textual.app import App
    from textual.containers import VerticalScroll
    from tui.block_base import TuiBlock

    core = _core(loadouts={12: FITTED})

    class Fleet(TuiBlock):
        def compose(self):
            yield VerticalScroll(id="rows")

        def refresh_data(self):
            scroll = self.query_one("#rows", VerticalScroll)
            scroll.remove_children()
            scroll.mount(*self.render_rows(CW.ships(core).rows))

    class Host(App):
        def compose(self):
            yield Fleet(core)

    async def run():
        app = Host()
        async with app.run_test() as pilot:
            block = app.query_one(Fleet)
            block.refresh_data()
            await pilot.pause()
            assert len(block.query_one("#rows").children) == 3
            assert block.toggle_fold(FOLD_ACTION + "ship-12")
            await pilot.pause()
            assert len(block.query_one("#rows").children) > 3
            block.toggle_fold(FOLD_ACTION + "ship-12")
            await pilot.pause()
            assert len(block.query_one("#rows").children) == 3
            assert not block.toggle_fold("home")

    asyncio.run(run())


def test_gui_fold_opens_and_closes():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication
    from gui.block_base import GuiBlock

    app = QApplication.instance() or QApplication([])
    core = _core(loadouts={12: FITTED})
    shown = []

    class Fleet(GuiBlock):
        def _build_body(self, layout):
            pass

        def refresh_data(self):
            shown[:] = self.render_rows(CW.ships(core).rows)

    b = Fleet(core)
    b.refresh_data()
    assert len(shown) == 3
    b._press(FOLD_ACTION + "ship-3")
    assert len(shown) > 3
    b._press(FOLD_ACTION + "ship-3")
    assert len(shown) == 3
    app.processEvents()


def test_status_json_gives_the_reservoir_and_pips(tmp_path):
    import json
    from components.commander import CommanderPlugin
    p = CommanderPlugin.__new__(CommanderPlugin)
    state = MonitorState()
    core = SimpleNamespace(state=state, journal_dir=str(tmp_path))
    (tmp_path / "Status.json").write_text(json.dumps(
        {"Flags": 0x01000000, "Pips": [2, 8, 2], "Fuel": {"FuelMain": 20.0, "FuelReservoir": 0.4271}}))
    p._read_status_json(core)
    assert (state.fuel_reservoir, state.ship_pips) == (0.43, [2, 8, 2])
    (tmp_path / "Status.json").write_text(json.dumps(
        {"Flags": 0x04000000, "Pips": [8, 2, 2], "Fuel": {"FuelMain": 0.0, "FuelReservoir": 0.1}}))
    p._read_status_json(core)
    assert (state.fuel_reservoir, state.ship_pips) == (0.43, [2, 8, 2]), "an SRV's are not the ship's"


def test_the_status_poller_reads_the_reservoir_and_pips():
    from pathlib import Path
    src = (Path(__file__).resolve().parents[1] / "core" / "journal.py").read_text(encoding="utf-8")
    poll = src[src.index("def _poll_status_json"):]
    poll = poll[:poll.index("\ndef ")]
    assert "FuelReservoir" in poll and 'data.get("Pips")' in poll
