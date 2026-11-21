"""core/modifiers.py — engineering modifiers from the journal's Loadout, as text.

Each modifier is {Label, Value, OriginalValue, LessIsGood}. Used by the
Modules tab and the commander dossier.
"""

from __future__ import annotations

import re

LABELS = {
    "FSDOptimalMass": "Optimal mass", "MaxFuelPerJump": "Max fuel per jump",
    "PowerDraw": "Power draw", "Mass": "Mass", "Integrity": "Integrity",
    "ShieldGenStrength": "Shield strength", "EngineOptimalMass": "Optimal mass",
    "EngineOptPerformance": "Optimal multiplier", "DamagePerSecond": "DPS",
    "Damage": "Damage", "RateOfFire": "Rate of fire", "Range": "Range",
    "PowerCapacity": "Power capacity", "WeaponsCapacity": "Weapons capacity",
    "WeaponsRecharge": "Weapons recharge", "EnginesCapacity": "Engines capacity",
    "EnginesRecharge": "Engines recharge", "SystemsCapacity": "Systems capacity",
    "SystemsRecharge": "Systems recharge", "CargoCapacity": "Capacity",
    "DefenceModifierHealthMultiplier": "Hull boost",
    "DefenceModifierShieldMultiplier": "Shield boost",
    "ScannerRange": "Scanner range", "SensorTargetScanAngle": "Scan angle",
    "MaxRange": "Max range", "BootTime": "Boot time", "HeatEfficiency": "Heat efficiency",
}

#: The fields kept from each journal modifier.
FIELDS = ("Label", "Value", "OriginalValue", "LessIsGood")


def split_words(text: str) -> str:
    out = re.sub(r"(?<=[a-z])(?=[A-Z])", " ", text or "")
    return out[:1].upper() + out[1:].lower()


def label(name: str) -> str:
    return LABELS.get(name, split_words(name))


def value(v) -> str:
    try:
        v = float(v)
    except (TypeError, ValueError):
        return "—"
    if abs(v) >= 100:
        return f"{v:,.0f}"
    if abs(v) >= 10:
        return f"{v:,.1f}"
    return f"{v:,.3f}".rstrip("0").rstrip(".")


def delta(m: dict) -> tuple[float, bool] | None:
    """(percent change, whether it is an improvement), or None."""
    try:
        v, orig = float(m.get("Value")), float(m.get("OriginalValue"))
    except (TypeError, ValueError):
        return None
    if not orig:
        return None
    pct = 100.0 * (v - orig) / abs(orig)
    return pct, (pct < 0) if m.get("LessIsGood") else (pct > 0)


def change(m: dict) -> str:
    d = delta(m)
    if d is None:
        return ""
    pct, better = d
    if not pct:
        return "0%"
    return f"{'+' if pct > 0 else ''}{pct:.1f}%" + (" ▲" if better else " ▼")


def keep(mods) -> list[dict]:
    """The journal's modifiers cut to FIELDS; ones without a value dropped."""
    out = []
    for m in mods or []:
        if isinstance(m, dict) and m.get("Label") and "Value" in m:
            out.append({k: m[k] for k in FIELDS if k in m})
    return out
