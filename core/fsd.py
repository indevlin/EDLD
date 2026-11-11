"""core/fsd.py — the frame shift drive: how far a jump reaches, and what it burns.

    fuel for a jump of d ly at total mass M
        = fuel_multiplier × ((d − booster) × M / optimal_mass) ^ fuel_power

and its inverse, the longest jump that a given amount of fuel pays for:

    range = optimal_mass / M × (fuel / fuel_multiplier) ^ (1 / fuel_power)
            + booster

* MaxJumpRange is measured with one jump's fuel aboard, not unladen, so
  scaling it from UnladenMass came out a little short;
* with less than one jump's worth in the tank, the fuel, not the mass, limits
  the jump — the last jumps on an empty tank are short ones.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, asdict
from typing import Any

#: Range a Guardian FSD booster adds, by size.
GUARDIAN_BOOSTER_LY = {1: 4.00, 2: 6.00, 3: 7.75, 4: 9.25, 5: 10.50}

#: A neutron star's supercharge multiplies jump range by 4 — by 6 for the
#: Caspian Explorer's SCO drive Mk II (its +500% against the standard +300%).
SUPERCHARGE_STANDARD = 4
SUPERCHARGE_MK2 = 6

#: A white dwarf's supercharge: ×1.5, ×3 for the SCO drive Mk II (+200%).
WHITE_DWARF_STANDARD = 1.5
WHITE_DWARF_MK2 = 3.0

#: How far the table's figures may miss the Loadout's own MaxJumpRange before
#: the optimal mass is worked out from the range instead. The game's figure
#: is the authority; a table can be stale or wrong.
RANGE_TOLERANCE = 0.005

_SIZE = re.compile(r"size(\d)")


@dataclass(frozen=True)
class Drive:
    """A ship's drive and the masses its range depends on."""
    item: str
    optimal_mass: float
    max_fuel: float          # most fuel one jump may burn
    fuel_multiplier: float
    fuel_power: float
    booster: float           # Guardian FSD booster, ly
    unladen: float           # UnladenMass
    tank: float              # main tank
    reserve: float           # reservoir
    max_jump_range: float    # the Loadout's own figure
    supercharge: int
    source: str
    white_dwarf: float = WHITE_DWARF_STANDARD

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def _modifiers(module: dict) -> dict[str, float]:
    out = {}
    for m in (module.get("Engineering") or {}).get("Modifiers") or []:
        v = m.get("Value")
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            out[str(m.get("Label"))] = float(v)
    return out


def booster_ly(modules: list[dict]) -> float:
    """The Guardian FSD booster's addition in a Loadout's module list."""
    for m in modules or []:
        item = str(m.get("Item") or "").lower()
        if "guardianfsdbooster" in item:
            size = _SIZE.search(item)
            if size:
                return GUARDIAN_BOOSTER_LY.get(int(size.group(1)), 0.0)
    return 0.0


def _unboosted(opt: float, max_fuel: float, mul: float, power: float, mass: float) -> float:
    return opt / mass * (max_fuel / mul) ** (1.0 / power)


def from_loadout(event: dict) -> Drive | None:
    """The drive in a Loadout, or None when it lacks what a range needs."""
    try:
        from data.fsd_drives import FSD_DRIVES
    except ImportError:
        FSD_DRIVES = {}
    modules = event.get("Modules") or []
    fsd = next((m for m in modules if m.get("Slot") == "FrameShiftDrive"), None)
    try:
        unladen = float(event.get("UnladenMass") or 0)
        r0 = float(event.get("MaxJumpRange") or 0)
    except (TypeError, ValueError):
        return None
    if fsd is None or unladen <= 0 or r0 <= 0:
        return None
    item = str(fsd.get("Item") or "").lower()
    stock = FSD_DRIVES.get(re.sub(r"_free$", "", item))
    if stock is None:
        # A drive newer than the table: the same size's figures, and the
        # optimal mass from the range below.
        size = _SIZE.search(item)
        kin = [v for k, v in FSD_DRIVES.items()
               if size and f"size{size.group(1)}_class5" in k and "mkii" not in k
               and ("overcharge" in k) == ("overcharge" in item)]
        if not kin:
            return None
        stock = kin[0]
    opt, max_fuel, mul, power = stock
    mods = _modifiers(fsd)
    source = "loadout" if "FSDOptimalMass" in mods else "table"
    opt = mods.get("FSDOptimalMass", opt)
    max_fuel = mods.get("MaxFuelPerJump", max_fuel)
    boost = booster_ly(modules)
    cap = event.get("FuelCapacity") or {}
    tank = float(cap.get("Main") or 0)
    reserve = float(cap.get("Reserve") or 0)

    # The Loadout's MaxJumpRange is the authority: unladen, one jump's fuel.
    # A booster switched off is left out of it by the game; so is it here.
    mass0 = unladen + max_fuel
    predicted = _unboosted(opt, max_fuel, mul, power, mass0)
    if boost and abs(predicted + boost - r0) / r0 > RANGE_TOLERANCE \
            and abs(predicted - r0) / r0 <= RANGE_TOLERANCE:
        boost = 0.0
    if abs(predicted + boost - r0) / r0 > RANGE_TOLERANCE and r0 > boost:
        opt = opt * (r0 - boost) / predicted
        source = "range"
    mk2 = "overchargebooster_mkii" in item
    supercharge = SUPERCHARGE_MK2 if mk2 else SUPERCHARGE_STANDARD
    white_dwarf = WHITE_DWARF_MK2 if mk2 else WHITE_DWARF_STANDARD
    return Drive(item, round(opt, 4), max_fuel, mul, power, boost, unladen,
                 tank, reserve, r0, supercharge, source, white_dwarf)


def star_boost(drive: Drive | None, star_class: str) -> float:
    """The range multiplier a jump leaving a ``star_class`` star can have:
    the drive's neutron or white dwarf supercharge, 1 for any other star."""
    sc = str(star_class or "").strip()
    if sc == "N":
        return float(drive.supercharge if drive else SUPERCHARGE_STANDARD)
    if sc.startswith("D"):
        return float(drive.white_dwarf if drive else WHITE_DWARF_STANDARD)
    return 1.0


def jump_range(drive: Drive, fuel: float, cargo: float = 0.0) -> float:
    """The longest jump with ``fuel`` tons in the main tank and ``cargo``
    aboard: limited by the mass, or by the fuel when there is less than one
    jump's worth."""
    fuel = max(float(fuel), 0.0)
    mass = drive.unladen + fuel + max(float(cargo), 0.0)
    burn = min(fuel, drive.max_fuel)
    if burn <= 0:
        return 0.0
    return _unboosted(drive.optimal_mass, burn, drive.fuel_multiplier,
                      drive.fuel_power, mass) + drive.booster


def jump_fuel(drive: Drive, distance: float, fuel: float, cargo: float = 0.0,
              boost: float = 1.0) -> float | None:
    """Fuel a ``distance`` ly jump burns from ``fuel`` tons in the tank, or
    None when it is out of reach. A supercharged jump reaches ``boost`` times
    as far and burns what a jump of ``distance / boost`` would."""
    boost = max(float(boost or 1.0), 1.0)
    if distance > jump_range(drive, fuel, cargo) * boost + 1e-9:
        return None
    distance /= boost
    mass = drive.unladen + fuel + cargo
    d = max(distance - drive.booster, 0.0)
    return drive.fuel_multiplier * (d * mass / drive.optimal_mass) ** drive.fuel_power


def jumps_on_tank(drive: Drive, fuel: float, cargo: float = 0.0,
                  limit: int = 500) -> tuple[int, float]:
    """(jumps, light years) the fuel in the tank takes the ship, each jump as
    long as it can be, the ship lightening as it burns, until what is left
    will not move it. No scooping on the way."""
    n, ly = 0, 0.0
    fuel = max(float(fuel), 0.0)
    while n < limit:
        reach = jump_range(drive, fuel, cargo)
        burn = min(fuel, drive.max_fuel)
        # A jump on the last dregs is a jump in name only: stop below a tenth
        # of a light year.
        if reach < 0.1 or burn <= 0:
            break
        fuel -= burn
        n += 1
        ly += reach
    return n, ly


def plan_optimal_mass(drive: Drive, range_ly: float, cargo: float = 0.0) -> float:
    """The optimal mass that gives a full-tank range of ``range_ly`` — how a
    route is plotted at a range shorter (or longer) than the ship's own. The
    booster's light years stay as they are; the drive's part scales."""
    full = jump_range(drive, drive.tank, cargo)
    if range_ly <= drive.booster or full <= drive.booster:
        return drive.optimal_mass
    return drive.optimal_mass * (range_ly - drive.booster) / (full - drive.booster)


def spansh_params(drive: Drive, cargo: float = 0.0, range_ly: float | None = None,
                  neutrons: bool = False) -> dict[str, Any]:
    """The ship's figures as Spansh's exact plotter takes them."""
    opt = plan_optimal_mass(drive, range_ly, cargo) if range_ly else drive.optimal_mass
    return {
        "is_supercharged": 0,
        "use_supercharge": 1 if neutrons else 0,
        "use_injections": 0,
        "exclude_secondary": 0,
        "fuel_power": drive.fuel_power,
        "fuel_multiplier": drive.fuel_multiplier,
        "optimal_mass": round(opt, 4),
        "base_mass": round(drive.unladen + drive.reserve, 4),
        "tank_size": drive.tank,
        "internal_tank_size": drive.reserve,
        "max_fuel_per_jump": drive.max_fuel,
        "range_boost": drive.booster,
        "supercharge_multiplier": drive.supercharge,
        "cargo": int(round(max(cargo, 0.0))),
    }
