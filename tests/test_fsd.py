"""
tests/test_fsd.py — the drive model: range at any fuel and cargo, fuel per
jump, and jumps left on the tank.

The ranges were scaled from MaxJumpRange by mass alone, from UnladenMass: a
little short, because the game measures MaxJumpRange with one jump's fuel
aboard, and blind to a nearly empty tank, where the fuel, not the mass,
limits the jump. core/fsd.py uses the drive's own figures. The Loadouts here
are real; with them the model gives back each ship's MaxJumpRange.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core import fsd  # noqa: E402

# A Mandalay, its SCO drive engineered for range.
SPECULATOR = {
    "event": "Loadout", "Ship": "mandalay", "ShipName": "SPECULATOR",
    "MaxJumpRange": 76.761124, "UnladenMass": 295.0,
    "FuelCapacity": {"Main": 32.0, "Reserve": 0.5},
    "Modules": [{"Slot": "FrameShiftDrive", "Item": "int_hyperdrive_overcharge_size5_class5",
                 "Engineering": {"Modifiers": [
                     {"Label": "Mass", "Value": 26.0},
                     {"Label": "FSDOptimalMass", "Value": 1997.5}]}}],
}

# The Caspian Explorer PICTOR, its SCO drive Mk II: stock in August,
# engineered by September.
PICTOR_STOCK = {
    "event": "Loadout", "Ship": "explorer_nx", "ShipName": "PICTOR",
    "MaxJumpRange": 40.864399, "UnladenMass": 1483.599976,
    "FuelCapacity": {"Main": 88.0, "Reserve": 1.14},
    "Modules": [{"Slot": "FrameShiftDrive",
                 "Item": "int_hyperdrive_overcharge_size8_class5_overchargebooster_mkii"}],
}
PICTOR = dict(PICTOR_STOCK, MaxJumpRange=66.942406, UnladenMass=1459.800049,
              Modules=[{"Slot": "FrameShiftDrive",
                        "Item": "int_hyperdrive_overcharge_size8_class5_overchargebooster_mkii",
                        "Engineering": {"Modifiers": [
                            {"Label": "FSDOptimalMass", "Value": 7528.039551}]}}])


def test_the_game_s_own_range_comes_back():
    for lo, source in ((SPECULATOR, "loadout"), (PICTOR, "loadout"),
                       (PICTOR_STOCK, "table")):
        d = fsd.from_loadout(lo)
        assert d.source == source
        assert abs(fsd.jump_range(d, d.max_fuel, 0) - lo["MaxJumpRange"]) < 1e-3


def test_the_mk2_is_its_own_drive():
    d = fsd.from_loadout(PICTOR)
    assert (d.max_fuel, d.fuel_power, d.supercharge) == (6.8, 2.5025, 6)


def test_fuel_limits_the_last_jumps():
    d = fsd.from_loadout(SPECULATOR)
    full = fsd.jump_range(d, d.max_fuel)
    assert fsd.jump_range(d, d.max_fuel / 2) < full
    assert fsd.jump_range(d, 0) == 0
    # More fuel than one jump's worth: heavier, so a little shorter.
    assert fsd.jump_range(d, d.tank) < full


def test_fuel_for_a_jump_is_the_inverse_of_its_range():
    d = fsd.from_loadout(SPECULATOR)
    for fuel, cargo in ((32.0, 0), (20.0, 16), (4.0, 0)):
        reach = fsd.jump_range(d, fuel, cargo)
        assert abs(fsd.jump_fuel(d, reach, fuel, cargo) - min(fuel, d.max_fuel)) < 1e-9
        assert fsd.jump_fuel(d, reach + 0.5, fuel, cargo) is None


def test_jumps_on_a_tank():
    d = fsd.from_loadout(SPECULATOR)
    n, ly = fsd.jumps_on_tank(d, 32.0)
    # 32 t at most 5.2 t a jump: six full jumps and a short seventh.
    assert n == 7
    assert ly > 6 * fsd.jump_range(d, 32.0)
    assert fsd.jumps_on_tank(d, 0) == (0, 0.0)


def test_an_unrecognised_drive_takes_its_figures_from_the_range():
    lo = dict(PICTOR_STOCK, Modules=[{"Slot": "FrameShiftDrive",
                                "Item": "int_hyperdrive_overcharge_size8_class5_futurething"}])
    d = fsd.from_loadout(lo)
    assert d is not None and d.source == "range"
    assert abs(fsd.jump_range(d, d.max_fuel) - lo["MaxJumpRange"]) < 1e-6


def test_a_booster_switched_off_is_left_out():
    lo = dict(SPECULATOR, Modules=SPECULATOR["Modules"]
              + [{"Slot": "Slot01_Size5", "Item": "int_guardianfsdbooster_size5", "On": False}])
    d = fsd.from_loadout(lo)     # MaxJumpRange as the game gave it: no booster in it
    assert d.booster == 0.0


def test_no_drive_no_model():
    assert fsd.from_loadout({"event": "Loadout", "MaxJumpRange": 20, "UnladenMass": 100,
                             "Modules": []}) is None
