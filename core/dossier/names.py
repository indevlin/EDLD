"""
core/dossier/names.py — journal ids as the dossier prints them.

Mostly a thin layer over the tables EDLD already has (data/modules.py,
data/ships.py, data/engineering.py, data/ranks.py), plus what only the dossier
needs: how a ``Loadout`` slot is labelled and grouped, and on-foot suit and
modification names. Module names come from the shared normaliser, so the
dossier and the dashboard name a module the same way.
"""

from __future__ import annotations

import re

from data.engineering import normalise_eng_name
from data.modules import is_cosmetic_module, normalise_module_name
from data.ranks import (RANK_NAMES, RANK_NAMES_CQC, RANK_NAMES_EMPIRE,
                        RANK_NAMES_EXOBIO, RANK_NAMES_EXPLORE,
                        RANK_NAMES_FEDERATION, RANK_NAMES_SOLDIER,
                        RANK_NAMES_TRADE)


# ── ships ─────────────────────────────────────────────────────────────────────


def ship_type(raw: str, localised: str = "") -> str:
    from data.ships import normalise_ship_name
    if localised and not localised.startswith("$"):
        return localised
    return (normalise_ship_name(raw or "")
            or (raw or "").replace("_", " ").title() or "Unknown")


# ── modules ───────────────────────────────────────────────────────────────────

def module_name(item: str) -> str:
    """A Loadout ``Item`` as the outfitting screen names it."""
    key = (item or "").lower().strip().lstrip("$").removesuffix(";") \
        .removesuffix("_name")
    return str(normalise_module_name(key))


def engineering_name(name: str) -> str:
    return normalise_eng_name(name or "")


# ── slots ─────────────────────────────────────────────────────────────────────

CORE_SLOTS = {
    "Armour": "Bulkheads", "PowerPlant": "Power plant",
    "MainEngines": "Thrusters", "FrameShiftDrive": "Frame shift drive",
    "LifeSupport": "Life support", "PowerDistributor": "Power distributor",
    "Radar": "Sensors", "FuelTank": "Fuel tank",
}
CORE_ORDER = list(CORE_SLOTS)

#: Slots that are part of every hull and carry nothing worth listing.
HIDDEN_SLOTS = {"shipcockpit", "cargohatch"}

_COSMETIC_SLOT = re.compile(
    r"^(paintjob|decal\d*|shipname\d*|shipid\d*|shipkit.*|weaponcolour|"
    r"enginecolour|vesselvoice|bobble\d*|stringlights|cockpitdecal.*|"
    r"enginetrail|holo.*)$", re.I)

#: The order the groups appear in, with their headings.
GROUPS = (
    ("hardpoints", "Hardpoints"),
    ("utility", "Utility mounts"),
    ("core", "Core internals"),
    ("optional", "Optional internals"),
    ("fixed", "Built in"),
    ("cosmetic", "Cosmetics"),
)


def slot_group(slot: str, item: str) -> str:
    low = (slot or "").lower()
    if _COSMETIC_SLOT.match(slot or "") or is_cosmetic_module(item):
        return "cosmetic"
    if low.startswith("tinyhardpoint"):
        return "utility"
    if "hardpoint" in low:
        return "hardpoints"
    if slot in CORE_SLOTS:
        return "core"
    if re.match(r"slot\d+_size\d+$", low) or re.match(
            r"(limpetcontroller|fighterbay|cargo|passenger|military)\d+$", low):
        return "optional"
    return "fixed"


def _split_camel(text: str) -> str:
    words = re.sub(r"(?<=[a-z])(?=[A-Z])|(?<=[A-Za-z])(?=\d)", " ", text).split()
    out = " ".join(w if w.isupper() else w.lower() for w in words)
    out = re.sub(r"\b0+(\d)", r"\1", out)
    return out[:1].upper() + out[1:]


def slot_label(slot: str) -> str:
    if slot in CORE_SLOTS:
        return CORE_SLOTS[slot]
    m = re.match(r"(Tiny|Small|Medium|Large|Huge)(Mining)?Hardpoint(\d+)$", slot or "")
    if m:
        size, mining, n = m.groups()
        if size == "Tiny":
            return f"Utility {n}"
        return f"{size} hardpoint {n}" + (" (mining)" if mining else "")
    m = re.match(r"Slot(\d+)_Size(\d+)$", slot or "")
    if m:
        return f"Optional {int(m.group(1))} · size {m.group(2)}"
    m = re.match(r"Military(\d+)$", slot or "")
    if m:
        return f"Military {int(m.group(1))}"
    return _split_camel(slot or "")


def slot_sort_key(slot: str):
    if slot in CORE_SLOTS:
        return (0, CORE_ORDER.index(slot), 0)
    m = re.match(r"(Tiny|Small|Medium|Large|Huge)(?:Mining)?Hardpoint(\d+)$", slot or "")
    if m:
        order = ["Huge", "Large", "Medium", "Small", "Tiny"].index(m.group(1))
        return (0, order, int(m.group(2)))
    m = re.match(r"Slot(\d+)_Size(\d+)$", slot or "")
    if m:
        return (0, int(m.group(1)), 0)
    nums = re.findall(r"\d+", slot or "")
    return (1, slot or "", int(nums[-1]) if nums else 0)


# ── ranks ─────────────────────────────────────────────────────────────────────

#: (journal key, label, names) in the order the dossier lists them.
RANKS = (
    ("Combat", "Combat", RANK_NAMES),
    ("Trade", "Trade", RANK_NAMES_TRADE),
    ("Explore", "Exploration", RANK_NAMES_EXPLORE),
    ("Soldier", "Mercenary", RANK_NAMES_SOLDIER),
    ("Exobiologist", "Exobiology", RANK_NAMES_EXOBIO),
    ("CQC", "CQC", RANK_NAMES_CQC),
    ("Federation", "Federation", RANK_NAMES_FEDERATION),
    ("Empire", "Empire", RANK_NAMES_EMPIRE),
)


def rank_name(names: list, value) -> str:
    try:
        return names[int(value)]
    except (TypeError, ValueError, IndexError):
        return str(value) if value is not None else ""


# ── on foot ───────────────────────────────────────────────────────────────────

from data.ships import SUIT_NAMES as _SUITS  # noqa: E402 — one table for every suit name

_SUIT_MODS = {
    "suit_backpackcapacity": "Extra Backpack Capacity",
    "suit_increasedammoreserves": "Extra Ammo Capacity",
    "suit_improvedarmourrating": "Damage Resistance",
    "suit_increasedbatterycapacity": "Improved Battery Capacity",
    "suit_increasedmeleedamage": "Added Melee Damage",
    "suit_increasedo2capacity": "Increased Air Reserves",
    "suit_increasedshieldregen": "Faster Shield Regen",
    "suit_increasedsprintduration": "Increased Sprint Duration",
    "suit_improvedjumpassist": "Improved Jump Assist",
    "suit_improvedradar": "Enhanced Tracking",
    "suit_nightvision": "Night Vision",
    "suit_quieterfootsteps": "Quieter Footsteps",
    "suit_reducedtoolbatteryconsumption": "Reduced Tool Battery Consumption",
}

_WEAPON_MODS = {
    "weapon_accuracy": "Improved Hip Fire Accuracy",
    "weapon_backpackreloading": "Stowed Reloading",
    "weapon_clipsize": "Magazine Size",
    "weapon_handling": "Faster Handling",
    "weapon_headshotdamage": "Headshot Damage",
    "weapon_range": "Greater Range",
    "weapon_reloadspeed": "Reload Speed",
    "weapon_scope": "Scope",
    "weapon_stability": "Stability",
    "weapon_suppression_unpressurised": "Noise Suppressor",
}


def suit_name(internal: str) -> tuple[str, int | None]:
    """(name, class) from e.g. ``explorationsuit_class3``."""
    key = (internal or "").lower().strip()
    m = re.match(r"([a-z]+?)(?:_class(\d))?$", key)
    base, cls = (m.group(1), m.group(2)) if m else (key, None)
    name = _SUITS.get(base, base.replace("_", " ").title() or "Suit")
    return name, (int(cls) if cls else None)


def _mod_name(table: dict, mod: str) -> str:
    key = (mod or "").lower()
    if key in table:
        return table[key]
    return re.sub(r"^(suit|weapon)_", "", key).replace("_", " ").title()


def suit_mod(mod: str) -> str:
    return _mod_name(_SUIT_MODS, mod)


def weapon_mod(mod: str) -> str:
    return _mod_name(_WEAPON_MODS, mod)


def weapon_name(internal: str, display: str = "") -> str:
    if display and not display.startswith("$"):
        return display
    key = re.sub(r"^wpn_[a-z]_", "", (internal or "").lower())
    return key.replace("_", " ").title() or "Weapon"


def slot_name_on_foot(slot: str) -> str:
    return {"PrimaryWeapon1": "Primary 1", "PrimaryWeapon2": "Primary 2",
            "SecondaryWeapon": "Secondary"}.get(slot, _split_camel(slot))
