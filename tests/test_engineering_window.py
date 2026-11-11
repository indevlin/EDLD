"""
The Engineering window: builds read from EDSY, Coriolis, EDOMH and SLEF; what
a ship still needs to reach its build; the materials that takes and the trades
that cover a shortfall; the materials themselves, kept from the journal; and
the Ship window's engineering lines.

EDSY's own tables are not shipped, so the tests read builds against a small
set of tables of their own.
"""
from __future__ import annotations

import base64
import gzip
import json
import zlib
from types import SimpleNamespace

import pytest

from core import builds, eddb, eng_plan as P
from core.state import MonitorState
from core.windows import R, wire, wire_rows
from core.windows import engineering as EW
from core.windows import ship as SW


# ── Tables of our own ─────────────────────────────────────────────────────────

RAW = {
    "version": 1,
    "ship": {
        "7": {"fdname": "TestHull", "name": "Test Hull",
              "slots": {"hardpoint": [2, 1, 1], "utility": [0, 0],
                        "component": [1, 4, 4, 4, 3, 4, 3, 4],
                        "military": [4], "internal": [5, 4, 2]},
              "module": {"40131": {"fdname": "TestHull_Armour_Grade1"}}},
    },
    "module": {
        "100": {"fdname": "Int_PowerPlant_Size4_Class5", "mtype": "cpp", "class": 4,
                "rating": "A", "name": "Power Plant"},
        "101": {"fdname": "Int_Hyperdrive_Size4_Class5", "mtype": "cfsd", "class": 4,
                "rating": "A", "name": "Frame Shift Drive"},
        "102": {"fdname": "Hpt_PulseLaser_Gimbal_Medium", "mtype": "hpl", "class": 2,
                "rating": "F", "name": "Pulse Laser", "mount": "G"},
        "103": {"fdname": "Int_CargoRack_Size4_Class1", "mtype": "icr", "class": 4,
                "rating": "E", "name": "Cargo Rack (Cap: 16)"},
        "104": {"fdname": "Hpt_ShieldBooster_Size0_Class5", "mtype": "usb", "class": 0,
                "rating": "A", "name": "Shield Booster"},
    },
    "blueprint": {
        "cpp_oc": {"fdname": "PowerPlant_Boosted", "name": "Overcharged", "maxgrade": 5,
                   "mats": [{"sul": 1}, {"hecowi": 1, "condco": 1},
                            {"hecowi": 1, "condco": 1, "sel": 1},
                            {"hedipl": 1, "coce": 1, "cad": 1},
                            {"coce": 1, "chma": 1, "tel": 1}]},
        "cfsd_ir": {"fdname": "FSD_LongRange", "name": "Increased Range", "maxgrade": 5,
                    "mats": [{"sul": 1}, {"sul": 1}, {"sul": 1}, {"sul": 1}, {"sul": 1}]},
        "usb_hd": {"fdname": "ShieldBooster_HeavyDuty", "name": "Heavy Duty", "maxgrade": 5,
                   "mats": [{"sul": 1}] * 5},
    },
    "expeffect": {
        "cppx_mo": {"fdname": "special_powerplant_highcharge", "name": "Monstered",
                    "mats": {"sul": 5, "cad": 3}},
        "usbx_sc": {"fdname": "special_shieldbooster_chunky", "name": "Super Capacitors",
                    "mats": {"sul": 2}},
    },
    "mtype": {
        "cpp": {"name": "Power Plant", "blueprints": ["cpp_oc"], "expeffects": ["cppx_mo"]},
        "cfsd": {"name": "FSD", "blueprints": ["cfsd_ir"], "expeffects": []},
        "hpl": {"name": "Pulse Lasers", "blueprints": [], "expeffects": []},
        "icr": {"name": "Cargo Racks", "blueprints": [], "expeffects": []},
        "usb": {"name": "Shield Boosters", "blueprints": ["usb_hd"], "expeffects": ["usbx_sc"]},
        "cbh": {"name": "Bulkheads", "blueprints": [], "expeffects": []},
    },
    "material": {
        "sul": {"fdname": "Sulphur", "name": "Sulphur", "mattype": "raw", "matgrp": 3, "rarity": 1},
        "cad": {"fdname": "Cadmium", "name": "Cadmium", "mattype": "raw", "matgrp": 3, "rarity": 3},
        "sel": {"fdname": "Selenium", "name": "Selenium", "mattype": "raw", "matgrp": 4, "rarity": 4},
        "tel": {"fdname": "Tellurium", "name": "Tellurium", "mattype": "raw", "matgrp": 5, "rarity": 4},
        "hecowi": {"fdname": "HeatConductionWiring", "name": "Heat Conduction Wiring",
                   "mattype": "mfc", "matgrp": 3, "rarity": 1},
        "hedipl": {"fdname": "HeatDispersionPlate", "name": "Heat Dispersion Plate",
                   "mattype": "mfc", "matgrp": 3, "rarity": 2},
        "condco": {"fdname": "ConductiveComponents", "name": "Conductive Components",
                   "mattype": "mfc", "matgrp": 4, "rarity": 2},
        "coce": {"fdname": "ConductiveCeramics", "name": "Conductive Ceramics",
                 "mattype": "mfc", "matgrp": 4, "rarity": 3},
        "chma": {"fdname": "ChemicalManipulators", "name": "Chemical Manipulators",
                 "mattype": "mfc", "matgrp": 1, "rarity": 4},
        "gupoce": {"fdname": "Guardian_PowerCell", "name": "Guardian Power Cell",
                   "mattype": "mfc", "matgrp": 0, "rarity": 1},
    },
}


@pytest.fixture
def db(monkeypatch):
    monkeypatch.setattr(eddb, "OBSERVED", {})
    d = eddb.Eddb(RAW)
    eddb.use(d)
    yield d
    eddb.use(None)


# ── tables ──────────────────────────────────────────────────────────────────────

def test_the_shipped_tables_load_and_hold_what_the_window_needs():
    eddb.use(None)
    try:
        db = eddb.load()
        assert db is not None, eddb.last_error()
        assert db.ship("lakonminer").name == "Type-11 Prospector"
        assert db.module("int_hyperdrive_overcharge_size5_class5").mtype
        bp = db.blueprint("FSD_LongRange")
        assert bp.maxgrade == 5 and all(bp.mats)
        assert db.material("vanadium").kind == "raw"
        assert db.ships[38].modules            # hull-only bulkheads, per hull
    finally:
        eddb.use(None)


def test_a_recipe_the_journal_shows_wins_and_a_disagreement_is_logged(db, monkeypatch):
    logged = []
    monkeypatch.setattr("core.debug.log", lambda msg, **k: logged.append(msg))
    monkeypatch.setattr(eddb, "OBSERVED", {})
    monkeypatch.setattr(eddb, "_reported", set())
    assert eddb.recipe(db, "PowerPlant_Boosted", 2) == {"heatconductionwiring": 1,
                                                         "conductivecomponents": 1}
    craft = {"event": "EngineerCraft", "BlueprintName": "PowerPlant_Boosted", "Level": 2,
             "Module": "int_powerplant_size4_class5",
             "Ingredients": [{"Name": "HeatConductionWiring", "Count": 1},
                             {"Name": "sulphur", "Count": 2}]}
    eddb.observe_craft(craft, db)
    eddb.observe_craft(craft, db)
    assert eddb.recipe(db, "PowerPlant_Boosted", 2) == {"heatconductionwiring": 1, "sulphur": 2}
    assert len(logged) == 1 and "PowerPlant_Boosted".lower() in logged[0]
    eddb.observe_craft({"event": "EngineerCraft", "ApplyExperimentalEffect":
                        "special_powerplant_highcharge", "BlueprintName": "PowerPlant_Boosted",
                        "Level": 2, "Ingredients": [{"Name": "sulphur", "Count": 5},
                                                    {"Name": "cadmium", "Count": 3}]}, db)
    assert len(logged) == 1                 # agrees with the table
    assert eddb.effect_recipe(db, "special_powerplant_highcharge") == {"sulphur": 5,
                                                                      "cadmium": 3}


def test_hull_modules_are_kept_per_hull(db):
    assert db.ships[7].modules[40131].fdname == "TestHull_Armour_Grade1"
    assert 40131 not in db.modules
    assert db.module("testhull_armour_grade1").mtype == "cbh"


def test_journal_slot_names_from_the_hull(db):
    hull = db.ships[7]
    assert [db.slot_name(hull, "hardpoint", n) for n in range(3)] == [
        "MediumHardpoint1", "SmallHardpoint1", "SmallHardpoint2"]
    assert db.slot_name(hull, "utility", 1) == "TinyHardpoint2"
    assert db.slot_name(hull, "component", 3) == "FrameShiftDrive"
    assert db.slot_name(hull, "military", 0) == "Military01"
    assert db.slot_name(hull, "internal", 2) == "Slot03_Size2"


# ── Reading builds ────────────────────────────────────────────────────────────

LOADOUT = {"event": "Loadout", "Ship": "TestHull", "ShipName": "Probe", "ShipIdent": "PR-1",
           "Modules": [
               {"Slot": "PowerPlant", "Item": "Int_PowerPlant_Size4_Class5", "On": True,
                "Priority": 1, "Engineering": {"BlueprintName": "PowerPlant_Boosted",
                                               "Level": 5, "Quality": 0.4,
                                               "ExperimentalEffect": "special_powerplant_highcharge"}},
               {"Slot": "FrameShiftDrive", "Item": "int_hyperdrive_size4_class5", "On": True,
                "Priority": 0}]}


def test_slef_and_loadout_read_alike():
    slef = [{"header": {"appName": "EDSY", "appURL": "https://edsy.org/#/L=x"},
             "data": LOADOUT}]
    a, _ = builds.parse(json.dumps(slef))
    b, _ = builds.parse(json.dumps(LOADOUT))
    assert a["source"] == "EDSY" and a["url"] == "https://edsy.org/#/L=x"
    assert a["modules"] == b["modules"]
    pp = a["modules"][0]
    assert pp["item"] == "int_powerplant_size4_class5" and pp["priority"] == 1
    assert pp["engineering"] == {"BlueprintName": "PowerPlant_Boosted", "Level": 5,
                                 "Quality": 0.4,
                                 "ExperimentalEffect": "special_powerplant_highcharge"}
    assert a["ship"] == "testhull" and a["name"] == "Probe" and a["ident"] == "PR-1"


def test_a_coriolis_link_is_gzipped_slef():
    data = base64.b64encode(gzip.compress(json.dumps(
        [{"header": {"appName": "Inara"}, "data": LOADOUT}]).encode())).decode()
    b, _ = builds.parse(f"https://coriolis.io/import?data={data}")
    assert b["source"] == "Coriolis" and len(b["modules"]) == 2


def test_short_links_are_followed_and_wanted():
    data = base64.b64encode(gzip.compress(json.dumps(LOADOUT).encode())).decode()
    seen = []

    def fetch(url):
        seen.append(url)
        return f"https://coriolis.io/import?data={data}"
    b, _ = builds.parse("https://sh.orbis.zone/abc", fetch=fetch)
    assert seen == ["https://sh.orbis.zone/abc"] and b["ship"] == "testhull"
    with pytest.raises(builds.BuildError, match="network"):
        builds.parse("https://edsy.org/s/abc")


def test_what_is_not_a_build_says_so():
    for text in ("", "hello", "https://example.com/x", "{\"a\": 1}", "[]"):
        with pytest.raises(builds.BuildError):
            builds.parse(text)


_H = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz_-"


def _enc(n: int, width: int) -> str:
    out = ""
    for _ in range(width):
        out = _H[n & 0x3F] + out
        n >>= 6
    return out


def _slot(modid, priority=0, on=True, eng=None):
    bits = priority | (0 if on else 0x8) | (0x10 if eng else 0)
    h = _enc(modid, 3) + _enc(bits, 1) + _enc(0, 1)          # discounts
    if eng:
        bp, grade, fx, roll = eng
        h += _enc((bp << 7) | (grade << 4) | fx, 2) + _enc(int(roll * 4000), 2) + _enc(0, 1)
    return h


def test_an_edsy_link_reads_slots_engineering_and_name(db):
    ship = _enc(7, 1) + _enc(0, 1) + _enc(0, 1) + _enc(0, 2) + _enc(0, 1) + _enc(0, 2)
    hardpoint = _slot(102, priority=2) + _enc(199901, 3) + _slot(102, on=False)
    utility = _slot(104, eng=(1, 5, 1, 1.0))
    component = (_slot(40131) + _slot(100, priority=1, eng=(1, 5, 1, 0.4))
                 + _enc(199901, 3) + _slot(101, eng=(1, 3, 0, 1.0)))
    internal = _slot(103)
    name = "Probe"
    h = _H[20] + ",".join([ship, hardpoint, utility, component, "", internal, name, "PR"])
    b, warnings = builds.parse(f"https://edsy.org/#/L={h}", db=db)
    assert warnings == []
    got = {m["slot"]: m for m in b["modules"]}
    assert b["ship"] == "testhull" and b["name"] == "Probe" and b["ident"] == "PR"
    assert got["MediumHardpoint1"]["priority"] == 2
    assert got["SmallHardpoint2"]["on"] is False and "SmallHardpoint1" not in got
    assert got["Armour"]["item"] == "testhull_armour_grade1"
    assert got["PowerPlant"]["engineering"] == {
        "BlueprintName": "PowerPlant_Boosted", "Level": 5, "Quality": 0.4,
        "ExperimentalEffect": "special_powerplant_highcharge"}
    assert got["FrameShiftDrive"]["engineering"]["Level"] == 3
    assert got["TinyHardpoint1"]["engineering"]["ExperimentalEffect"] == \
        "special_shieldbooster_chunky"
    assert got["Slot01_Size5"]["item"] == "int_cargorack_size4_class1"


def test_an_old_edsy_link_is_refused_and_tables_are_needed(db):
    with pytest.raises(builds.BuildError, match="old version"):
        builds.parse("https://edsy.org/#/L=A123", db=db)
    with pytest.raises(builds.BuildError, match="engineering tables"):
        builds.parse("https://edsy.org/#/L=K0", db=None)


def test_an_edomh_ship_reads_by_name_class_and_rating(db):
    ship = {"event": "ship", "version": 2, "shipConfiguration": {
        "name": "Probe", "shipType": "TEST_HULL",
        "cargoHatch": {"id": "CARGO_HATCH", "powerGroup": 1},
        "coreSlots": [
            {"index": 0, "id": "TESTHULL_ARMOUR_GRADE_1"},
            {"index": 1, "id": "POWER_PLANT_4_A", "powerGroup": 2,
             "modification": [{"type": "OVERCHARGED", "grade": "GRADE_5",
                               "percentComplete": 0.4}],
             "experimentalEffect": [{"type": "MONSTERED"}]}],
        "optionalSlots": [{"index": 0, "id": "CARGO_RACK_4_E"}],
        "hardpointSlots": [{"index": 0, "id": "PULSE_LASER_2_F_G"}],
        "utilitySlots": [{"index": 1, "id": "SHIELD_BOOSTER_0_A",
                          "modification": [{"type": "HEAVY_DUTY", "grade": "GRADE_5"}]}],
    }}
    uri = "edomh://ship/?" + base64.urlsafe_b64encode(
        zlib.compress(json.dumps(ship).encode())).decode().rstrip("=")
    b, warnings = builds.parse(uri, db=db)
    got = {m["slot"]: m for m in b["modules"]}
    assert warnings == []
    assert got["PowerPlant"]["item"] == "int_powerplant_size4_class5"
    assert got["PowerPlant"]["priority"] == 1
    assert got["PowerPlant"]["engineering"] == {
        "BlueprintName": "PowerPlant_Boosted", "Level": 5, "Quality": 0.4,
        "ExperimentalEffect": "special_powerplant_highcharge"}
    assert got["Slot01_Size5"]["item"] == "int_cargorack_size4_class1"
    assert got["MediumHardpoint1"]["item"] == "hpt_pulselaser_gimbal_medium"
    assert got["TinyHardpoint2"]["engineering"]["BlueprintName"] == "ShieldBooster_HeavyDuty"


# ── What a build still needs ─────────────────────────────────────────────────

def _m(slot, item, bp="", level=0, quality=1.0, fx=""):
    m = {"slot": slot, "item": item}
    e = {}
    if bp:
        e.update({"BlueprintName": bp, "Level": level, "Quality": quality})
    if fx:
        e["ExperimentalEffect"] = fx
    if e:
        m["engineering"] = e
    return m


def test_grades_already_rolled_are_not_asked_for_again():
    cur = [_m("PowerPlant", "int_powerplant_size4_class5", "PowerPlant_Boosted", 3)]
    tgt = {"modules": [_m("PowerPlant", "int_powerplant_size4_class5", "PowerPlant_Boosted", 5,
                          fx="special_powerplant_highcharge")]}
    (st,) = P.delta(cur, tgt)
    assert st.grades == [(4, 4), (5, 5)] and st.effect == "special_powerplant_highcharge"
    assert P.grade_span(st.grades) == "G4–G5" and not st.module


def test_a_grade_part_rolled_takes_the_rest_of_its_rolls():
    cur = [_m("PowerPlant", "int_powerplant_size4_class5", "PowerPlant_Boosted", 5, 0.4)]
    tgt = {"modules": [_m("PowerPlant", "int_powerplant_size4_class5", "PowerPlant_Boosted", 5)]}
    (st,) = P.delta(cur, tgt)
    assert st.grades == [(5, 3)]
    tgt40 = {"modules": [_m("PowerPlant", "int_powerplant_size4_class5",
                            "PowerPlant_Boosted", 5, 0.4)]}
    assert P.delta(cur, tgt40) == []


def test_another_blueprint_starts_over_and_a_new_module_is_bought_or_taken_from_storage():
    cur = [_m("PowerPlant", "int_powerplant_size4_class5", "PowerPlant_Armoured", 5),
           _m("FrameShiftDrive", "int_hyperdrive_size4_class2")]
    tgt = {"modules": [_m("PowerPlant", "int_powerplant_size4_class5", "PowerPlant_Boosted", 2),
                       _m("FrameShiftDrive", "int_hyperdrive_size4_class5", "FSD_LongRange", 5),
                       _m("TinyHardpoint1", "hpt_shieldbooster_size0_class5")]}
    stored = [{"name_internal": "int_hyperdrive_size4_class5",
               "engineering": {"BlueprintName": "FSD_LongRange", "Level": 4, "Quality": 1}}]
    steps = {s.slot: s for s in P.delta(cur, tgt, stored)}
    assert steps["PowerPlant"].grades == [(1, 1), (2, 2)]
    assert steps["FrameShiftDrive"].module == "stored"
    assert steps["FrameShiftDrive"].grades == [(5, 5)]
    assert steps["TinyHardpoint1"].module == "purchase"


def test_a_module_the_build_leaves_out_is_to_be_removed():
    cur = [_m("Slot02_Size4", "int_cargorack_size4_class1"), _m("CargoHatch", "modularcargobaydoor")]
    steps = P.delta(cur, {"modules": []})
    assert [(s.slot, s.remove) for s in steps] == [("Slot02_Size4", True)]


def test_the_free_module_a_ship_comes_with_is_the_same_module():
    cur = [_m("Slot05_Size5", "int_buggybay_size4_class3_free")]
    assert P.delta(cur, {"modules": [_m("Slot05_Size5", "int_buggybay_size4_class3")]}) == []


def test_materials_are_rolls_times_the_recipe_plus_the_effect(db):
    cur = [_m("PowerPlant", "int_powerplant_size4_class5", "PowerPlant_Boosted", 3)]
    tgt = {"modules": [_m("PowerPlant", "int_powerplant_size4_class5", "PowerPlant_Boosted", 5,
                          fx="special_powerplant_highcharge")]}
    needs, unknown = P.materials(P.delta(cur, tgt), db)
    assert unknown == []
    got = {n.key: n.need for n in needs.values()}
    # G4 four rolls, G5 five, Monstered once
    assert got == {"heatdispersionplate": 4, "conductiveceramics": 9, "cadmium": 4 + 3,
                   "chemicalmanipulators": 5, "tellurium": 5, "sulphur": 5}
    rows = P.shortfall(needs, {"cadmium": 10, "sulphur": 1})
    by = {n.key: n for n in rows}
    assert by["cadmium"].short == 0 and by["sulphur"].short == 4
    assert [n.kind for n in rows] == sorted((n.kind for n in rows),
                                            key=["raw", "mfc", "enc"].index)


@pytest.mark.parametrize("src,dst,want", [
    (("raw", 3, 1), ("raw", 3, 2), (6, 1)),       # up a grade
    (("raw", 3, 1), ("raw", 3, 3), (36, 1)),      # up two
    (("raw", 3, 3), ("raw", 3, 1), (1, 9)),       # down two
    (("raw", 3, 2), ("raw", 4, 2), (6, 1)),       # another column, same grade
    (("raw", 3, 1), ("raw", 4, 2), (36, 1)),      # another column, up
    (("raw", 3, 3), ("raw", 4, 2), (2, 1)),       # another column, down one
    (("raw", 3, 4), ("raw", 4, 2), (2, 3)),       # another column, down two
])
def test_trade_ratios(src, dst, want):
    a = SimpleNamespace(kind=src[0], group=src[1], grade=src[2])
    b = SimpleNamespace(kind=dst[0], group=dst[1], grade=dst[2])
    assert P.trade_ratio(a, b) == want


def test_trades_spend_within_a_column_before_across_and_never_what_the_build_needs(db):
    needs = {
        "conductiveceramics": P.Need("conductiveceramics", "Conductive Ceramics", "mfc", 3, 4,
                                     need=3),
        "heatdispersionplate": P.Need("heatdispersionplate", "Heat Dispersion Plate", "mfc", 2,
                                      3, need=6),
    }
    held = {"conductivecomponents": 12, "heatdispersionplate": 6, "heatconductionwiring": 0,
            "chemicalmanipulators": 1}
    rows = P.shortfall(needs, held)
    trades, left = P.plan_trades(rows, held, db)
    assert [(t.give_name, t.give_count, t.get_name, t.get_count) for t in trades] == [
        ("Conductive Components", 12, "Conductive Ceramics", 2)]
    assert [(n.name, n.need) for n in left] == [("Conductive Ceramics", 1)]


def test_guardian_materials_cannot_be_traded_for(db):
    needs = {"guardian_powercell": P.Need("guardian_powercell", "Guardian Power Cell", "mfc", 1,
                                          0, need=5)}
    rows = P.shortfall(needs, {"conductivecomponents": 300})
    trades, left = P.plan_trades(rows, {"conductivecomponents": 300}, db)
    assert trades == [] and left[0].need == 5


# ── The materials, from the journal ──────────────────────────────────────────

def _eng_plugin(state=None):
    import components.engineering as CE
    s = state or MonitorState()
    s.materials_raw, s.materials_manufactured, s.materials_encoded = {}, {}, {}
    p = CE.EngineeringPlugin.__new__(CE.EngineeringPlugin)
    p.core = SimpleNamespace(state=s, gui_queue=None, journal_dir=None)
    return p, s


def test_a_trade_counts_both_sides():
    p, s = _eng_plugin()
    p.on_event({"event": "Materials", "Manufactured": [
        {"Name": "configurablecomponents", "Count": 10}]}, s)
    p.on_event({"event": "MaterialTrade", "TraderType": "manufactured",
                "Paid": {"Material": "configurablecomponents", "Category": "Manufactured",
                         "Quantity": 3},
                "Received": {"Material": "mechanicalscrap",
                             "Material_Localised": "Mechanical Scrap",
                             "Category": "Manufactured", "Quantity": 81}}, s)
    assert s.materials_manufactured["configurablecomponents"]["count"] == 7
    assert s.materials_manufactured["mechanicalscrap"] == {"count": 81,
                                                           "name_local": "Mechanical Scrap"}


def test_rewards_contributions_and_research_count():
    p, s = _eng_plugin()
    p.on_event({"event": "Materials", "Raw": [{"Name": "iron", "Count": 20}]}, s)
    p.on_event({"event": "MissionCompleted", "MaterialsReward": [
        {"Name": "iron", "Category": "$MICRORESOURCE_CATEGORY_Raw;", "Count": 3}]}, s)
    p.on_event({"event": "EngineerContribution", "Type": "Materials", "Material": "iron",
                "Quantity": 5}, s)
    p.on_event({"event": "ScientificResearch", "Name": "iron", "Category": "Raw", "Count": 2}, s)
    assert s.materials_raw["iron"]["count"] == 16


def test_materials_come_from_the_journals_before_the_current_one(tmp_path):
    jdir = tmp_path / "journal"
    jdir.mkdir()

    def write(name, events):
        (jdir / name).write_text("\n".join(json.dumps(e) for e in events) + "\n",
                                 encoding="utf-8")
    write("Journal.2026-11-01T100000.01.log", [
        {"timestamp": "2026-11-01T10:00:01Z", "event": "Materials",
         "Raw": [{"Name": "iron", "Count": 50}]},
        {"timestamp": "2026-11-01T10:05:00Z", "event": "MaterialCollected",
         "Category": "Raw", "Name": "iron", "Count": 3}])
    write("Journal.2026-11-02T100000.01.log", [
        {"timestamp": "2026-11-02T10:00:00Z", "event": "Fileheader"},
        {"timestamp": "2026-11-02T10:01:00Z", "event": "MaterialCollected",
         "Category": "Raw", "Name": "iron", "Count": 100}])
    p, s = _eng_plugin()
    p.core.journal_dir = jdir
    p._bootstrap_materials()
    # The newest journal is the preload's to replay.
    assert s.materials_raw["iron"]["count"] == 53


# ── The Ship window's engineering lines ──────────────────────────────────────

def test_an_engineered_module_has_its_engineering_on_the_line_under_it():
    core = SimpleNamespace(state=MonitorState(), _plugins={})
    core.state.ship_modules = [
        {"slot": "FrameShiftDrive", "name_display": "8A Mk II Supercharge Optimized Frame "
         "Shift Drive (SCO)", "priority": 0, "health": 1.0,
         "engineering": {"BlueprintName": "FSD_LongRange", "Level": 5,
                         "ExperimentalEffect": "special_fsd_heavy",
                         "ExperimentalEffect_Localised": "Mass Manager"}},
        {"slot": "Armour", "name_display": "Lightweight Alloy", "priority": 1, "health": 1.0,
         "engineering": {"BlueprintName": "Armour_HeavyDuty", "Level": 3}},
        {"slot": "LifeSupport", "name_display": "5D Life Support", "priority": 2, "health": 1.0},
    ]
    rows = SW.modules(core).rows
    assert rows[0][1] == "1  8A Mk II Supercharge Optimized Frame Shift Drive (SCO)"
    assert rows[1] == ("note", "G5 Increased Range (Mass Manager)", "1  8A ", "dim")
    notes = [r for r in rows if r[0] == "note"]
    assert notes[1][1:3] == ("G3 Heavy Duty", "2  ")
    assert len(notes) == 2
    w = wire_rows(rows)
    assert w[1] == {"label": "G5 Increased Range (Mass Manager)", "value": "", "kind": "note",
                    "indent": "1  8A ", "tone": "dim"}


def test_the_ship_window_no_longer_carries_the_materials():
    core = SimpleNamespace(state=MonitorState(), _plugins={})
    assert [t.id for t in SW.tabs(core)] == ["cargo", "modules"]


def test_ship_health_keeps_the_loadouts_engineering():
    import components.ship_health as SH
    p = SH.ShipHealthPlugin.__new__(SH.ShipHealthPlugin)
    p.core = SimpleNamespace(state=MonitorState(), gui_queue=None)
    p._changed = lambda: None
    p._apply_loadout({"Modules": [
        {"Slot": "FrameShiftDrive", "Item": "int_hyperdrive_size5_class5", "Health": 1.0,
         "Engineering": {"BlueprintName": "FSD_LongRange", "Level": 5, "Quality": 1.0,
                         "ExperimentalEffect": "special_fsd_heavy", "Modifiers": [{}]}},
        {"Slot": "LifeSupport", "Item": "int_lifesupport_size3_class2", "Health": 1.0}]})
    a, b = p.core.state.ship_modules
    assert a["engineering"] == {"BlueprintName": "FSD_LongRange", "Level": 5, "Quality": 1.0,
                                "ExperimentalEffect": "special_fsd_heavy"}
    assert "engineering" not in b


def test_a_craft_updates_the_modules_engineering_until_the_next_loadout():
    import components.ship_health as SH
    p = SH.ShipHealthPlugin.__new__(SH.ShipHealthPlugin)
    p.core = SimpleNamespace(state=MonitorState(), gui_queue=None)
    p._changed = lambda: None
    s = p.core.state
    s.ship_modules = [{"slot": "TinyHardpoint1", "name_display": "0A Shield Booster",
                       "engineering": {"BlueprintName": "ShieldBooster_Thermic", "Level": 5,
                                       "ExperimentalEffect": "special_shieldbooster_chunky"}}]
    p.on_event({"event": "EngineerCraft", "Slot": "TinyHardpoint1",
                "BlueprintName": "ShieldBooster_Resistive", "Level": 2, "Quality": 0.5}, s)
    assert s.ship_modules[0]["engineering"] == {"BlueprintName": "ShieldBooster_Resistive",
                                                "Level": 2, "Quality": 0.5}
    p.on_event({"event": "EngineerCraft", "Slot": "TinyHardpoint1",
                "BlueprintName": "ShieldBooster_Resistive", "Level": 2, "Quality": 1.0,
                "ApplyExperimentalEffect": "special_shieldbooster_chunky"}, s)
    assert s.ship_modules[0]["engineering"]["ExperimentalEffect"] == \
        "special_shieldbooster_chunky"
    assert SW.engineering_line(s.ship_modules[0]["engineering"]) == \
        "G2 Resistance Augmented (Super Capacitors)"


# ── The Fitting view ─────────────────────────────────────────────────────────

class _Store:
    """The engineering component's build store, in memory."""

    def __init__(self, tmp_path):
        import components.engineering as CE
        self.p = CE.EngineeringPlugin.__new__(CE.EngineeringPlugin)
        self.p.core = SimpleNamespace(gui_queue=None)
        self.p._builds_cache = {"targets": {}, "planned": {}, "selected": ""}
        self.p._save_builds = lambda: None


def _fit_core(tmp_path, db):
    store = _Store(tmp_path).p
    s = MonitorState()
    s.materials_raw = {"sulphur": {"count": 2, "name_local": "Sulphur"}}
    s.materials_manufactured, s.materials_encoded = {}, {}
    s.assets_current_ship = {"ship_id": 3, "type": "testhull", "name": "PROBE", "ident": "PR-1",
                             "type_display": "Test Hull"}
    s.assets_stored_ships = [{"ship_id": 5, "type": "otherhull", "name": "OTHER", "ident": ""}]
    s.assets_stored_modules = []
    s.ship_modules = [_m("PowerPlant", "int_powerplant_size4_class5", "PowerPlant_Boosted", 3)]
    s.ship_modules[0]["name_internal"] = s.ship_modules[0].pop("item")
    core = SimpleNamespace(state=s, _plugins={"engineering": store}, gui_queue=None)
    return core, store


def test_the_ship_list_is_owned_ships_then_plans_then_a_new_plan(tmp_path, db):
    core, store = _fit_core(tmp_path, db)
    key = store.add_plan("testhull")
    keys = [k for k, _l in EW.choices(core)]
    assert keys == ["ship:3", "ship:5", key, EW.NEW_PLAN]
    assert dict(EW.choices(core))[key] == "Test Hull (planned)"
    store.add_plan("testhull")
    assert [l for k, l in EW.choices(core) if k.startswith("plan:")] == [
        "Test Hull (planned)", "Test Hull (planned 2)"]


def test_the_fitting_compares_and_prices_what_is_left(tmp_path, db):
    core, store = _fit_core(tmp_path, db)
    store.set_target("ship:3", {"ship": "testhull", "source": "EDSY", "url": "", "modules": [
        _m("PowerPlant", "int_powerplant_size4_class5", "PowerPlant_Boosted", 5,
           fx="special_powerplant_highcharge")]})
    v = EW.fitting(core, "ship:3")
    assert v.key == "ship:3" and v.has_target and not v.planned
    (row,) = v.slots
    assert (row.label, row.state) == ("Power Plant", "eng")
    assert row.current_eng == "G3 Overcharged" and row.target_eng == "G5 Overcharged (Monstered)"
    assert v.short > 0
    cells = {r[1]: r[2] for r in v.needs if r[0] == "cells"}
    assert cells["Sulphur"] == ["G1", "5", "2", "3"]
    labels = [r[1] for r in v.work]
    assert labels[0] == "Power Plant: 4A Power Plant"


def test_a_plan_moves_onto_an_owned_hull_of_its_type(tmp_path, db):
    core, store = _fit_core(tmp_path, db)
    key = store.add_plan("testhull")
    v = EW.fitting(core, key)
    assert v.planned and v.apply_to == [("ship:3", "PROBE (PR-1) · Test Hull")]
    assert not store.apply_plan(key, "ship:3")            # nothing planned yet
    build = {"ship": "testhull", "modules": [], "source": "EDSY", "url": ""}
    store.set_target(key, build)
    assert store.apply_plan(key, "ship:3")
    assert store.target("ship:3") == build and store.selected() == "ship:3"
    assert key not in [k for k, _l in EW.choices(core)]


def test_a_build_for_another_hull_is_refused(db, monkeypatch):
    import components.engineering as CE
    p = CE.EngineeringPlugin.__new__(CE.EngineeringPlugin)
    with pytest.raises(builds.BuildError, match="Test Hull"):
        p.import_build(json.dumps(LOADOUT), "otherhull")
    b, _ = p.import_build(json.dumps(LOADOUT), "testhull")
    assert b["ship"] == "testhull"


def test_the_window_reaches_a_device_as_its_own_section(tmp_path, db):
    from core import edcars as H
    core, store = _fit_core(tmp_path, db)
    core.session_providers, core.app_settings = [], {}
    core.plugin_call = lambda *a, **k: None
    ids = {p["id"]: p for p in wire.panels(core)}
    assert ids["engineering.fitting"]["group"] == "engineering"
    assert H.section_for_panel("engineering.fitting", "engineering") == "engineering"
    assert "ship.engineering" not in ids


def test_note_rows_reach_both_front_ends():
    rows = [R.kv("1  8A Thing", "100%"), R.note("G5 Something", "1  8A ")]
    from core.windows import iter_render
    assert [k for k, _r, _w in iter_render(rows)] == ["kv", "note"]


def _journal(path, events):
    path.write_text("".join(json.dumps(e) + "\n" for e in events), encoding="utf-8")


def test_traders_come_from_the_journals_first_and_spansh_fills_the_rest(tmp_path):
    from core import eng_trade
    mt = ["dock", "materialtrader"]
    _journal(tmp_path / "Journal.2026-10-01T100000.01.log", [
        {"timestamp": "2026-10-01T10:00:00Z", "event": "FSDJump", "StarSystem": "Bolg", "StarPos": [10, 0, 0]},
        {"timestamp": "2026-10-01T10:01:00Z", "event": "Docked", "StarSystem": "Bolg", "StationName": "Moxon's Mojo",
         "MarketID": 1, "DistFromStarLS": 50, "StationServices": mt},
        {"timestamp": "2026-10-01T10:02:00Z", "event": "MaterialTrade", "MarketID": 1, "TraderType": "Raw"},
        {"timestamp": "2026-10-01T10:03:00Z", "event": "FSDJump", "StarSystem": "Far", "StarPos": [90, 0, 0]},
        {"timestamp": "2026-10-01T10:04:00Z", "event": "Docked", "StarSystem": "Far", "StationName": "Untraded",
         "MarketID": 2, "StationServices": mt},
    ])
    found = {t["market_id"]: t for t in eng_trade.journal_traders(tmp_path)}
    assert found[1]["kind"] == "raw" and found[1]["pos"] == [10, 0, 0]
    assert found[2]["kind"] == ""

    class Spansh:
        def stations_near(self, here, service, size):
            return [{"market_id": 1, "material_trader": "Raw", "system_name": "Bolg", "name": "Moxon's Mojo", "distance": 10},
                    {"market_id": 3, "material_trader": "Encoded", "system_name": "Enc", "name": "E", "distance": 20},
                    {"market_id": 4, "economy": "High Tech", "system_name": "Guess", "name": "G", "distance": 5}]

    core = SimpleNamespace(journal_dir=tmp_path, _plugins={"spansh": Spansh()},
                           state=SimpleNamespace(pilot_star_pos=[0, 0, 0]))
    got = eng_trade.nearest_traders(core, ["raw", "enc", "mfc"])
    assert [(t["station"], t["seen"]) for t in got["raw"]] == [("Moxon's Mojo", True)]
    assert [t["station"] for t in got["enc"]] == ["E"]
    assert got["mfc"] == []
