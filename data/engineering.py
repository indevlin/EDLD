"""data/engineering.py — Engineering blueprint and experimental effect display names.

Keys are lowercase internal names as emitted in journal events (BlueprintName,
ExperimentalEffect).
"""
from __future__ import annotations
import re as _re

BLUEPRINT_NAMES: dict[str, str] = {
    # ── Weapons ───────────────────────────────────────────────────────────────
    "weapon_doubleshot":                    "Double Shot",
    "weapon_efficient":                     "Efficient",
    "weapon_focused":                       "Focused",
    "weapon_highcapacity":                  "High Capacity",
    "weapon_lightweight":                   "Lightweight",
    "weapon_longrange":                     "Long Range",
    "weapon_overcharged":                   "Overcharged",
    "weapon_rapidfire":                     "Rapid Fire",
    "weapon_shortrange":                    "Short Range",
    "weapon_sturdy":                        "Sturdy",
    # ── Thrusters ─────────────────────────────────────────────────────────────
    "engine_dirty":                         "Dirty Drive Tuning",
    "engine_reinforced":                    "Drive Strengthening",
    "engine_tuned":                         "Clean Drive Tuning",
    # ── Frame shift drive and interdictor ─────────────────────────────────────
    "fsd_fastboot":                         "Faster Boot Sequence",
    "fsd_longrange":                        "Increased Range",
    "fsd_shielded":                         "Shielded",
    "fsdinterdictor_expanded":              "Expanded Capture Arc",
    "fsdinterdictor_longrange":             "Long Range",
    # ── Shield generator ──────────────────────────────────────────────────────
    "shieldgenerator_kinetic":              "Kinetic Resistant",
    "shieldgenerator_optimised":            "Enhanced Low Power",
    "shieldgenerator_reinforced":           "Reinforced",
    "shieldgenerator_thermic":              "Thermal Resistant",
    # ── Shield booster and cell bank ──────────────────────────────────────────
    "shieldbooster_explosive":              "Blast Resistant",
    "shieldbooster_heavyduty":              "Heavy Duty",
    "shieldbooster_kinetic":                "Kinetic Resistant",
    "shieldbooster_resistive":              "Resistance Augmented",
    "shieldbooster_thermic":                "Thermal Resistant",
    "shieldcellbank_rapid":                 "Rapid Charge",
    "shieldcellbank_specialised":           "Specialised",
    # ── Power plant ───────────────────────────────────────────────────────────
    "powerplant_armoured":                  "Armoured",
    "powerplant_boosted":                   "Overcharged",
    "powerplant_stealth":                   "Low Emissions",
    # ── Power distributor ─────────────────────────────────────────────────────
    "powerdistributor_highcapacity":        "High Charge Capacity",
    "powerdistributor_highfrequency":       "Charge Enhanced",
    "powerdistributor_priorityengines":     "Engine Focused",
    "powerdistributor_prioritysystems":     "System Focused",
    "powerdistributor_priorityweapons":     "Weapon Focused",
    "powerdistributor_shielded":            "Shielded",
    # ── Bulkheads and hull reinforcement ──────────────────────────────────────
    "armour_advanced":                      "Lightweight",
    "armour_explosive":                     "Blast Resistant",
    "armour_heavyduty":                     "Heavy Duty",
    "armour_kinetic":                       "Kinetic Resistant",
    "armour_thermic":                       "Thermal Resistant",
    "hullreinforcement_advanced":           "Lightweight",
    "hullreinforcement_explosive":          "Blast Resistant",
    "hullreinforcement_heavyduty":          "Heavy Duty",
    "hullreinforcement_kinetic":            "Kinetic Resistant",
    "hullreinforcement_thermic":            "Thermal Resistant",
    # ── Sensors and scanners ──────────────────────────────────────────────────
    "sensor_expanded":                      "Expanded Radius",
    "sensor_fastscan":                      "Fast Scan",
    "sensor_lightweight":                   "Lightweight",
    "sensor_longrange":                     "Long Range",
    "sensor_wideangle":                     "Wide Angle",
    # ── Utility and miscellaneous ─────────────────────────────────────────────
    "misc_chaffcapacity":                   "Ammo Capacity",
    "misc_heatsinkcapacity":                "Ammo Capacity",
    "misc_lightweight":                     "Lightweight",
    "misc_pointdefensecapacity":            "Ammo Capacity",
    "misc_reinforced":                      "Reinforced",
    "misc_shielded":                        "Shielded",
    "cargorack_increasedcapacity":          "Increased Capacity",
}

# Fallback only: Loadout carries ExperimentalEffect_Localised, which wins.
EXP_EFFECT_NAMES: dict[str, str] = {
    # ── Weapons ───────────────────────────────────────────────────────────────
    "special_auto_loader":                  "Auto Loader",
    "special_blinding_shell":               "Dazzle Shell",
    "special_concordant_sequence":          "Concordant Sequence",
    "special_corrosive_shell":              "Corrosive Shell",
    "special_deep_cut_payload":             "Deep-Cut Payload",
    "special_dispersal_field":              "Dispersal Field",
    "special_drag_munitions":               "Drag Munitions",
    "special_emissive_munitions":           "Emissive Munitions",
    "special_feedback_cascade":             "Feedback Cascade",
    "special_force_shell":                  "Force Shell",
    "special_high_yield_shell":             "High Yield Shell",
    "special_incendiary_rounds":            "Incendiary Rounds",
    "special_inertial_impact":              "Inertial Impact",
    "special_ion_disruptor":                "Ion Disruption",
    "special_lock_breaker":                 "Target Lock Breaker",
    "special_mass_lock":                    "Mass Lock Munition",
    "special_overload_munitions":           "Overload Munitions",
    "special_penetrator_munitions":         "Penetrator Munitions",
    "special_phasing_sequence":             "Phasing Sequence",
    "special_plasma_slug":                  "Plasma Slug",
    "special_radiant_canister":             "Radiant Canister",
    "special_regeneration_sequence":        "Regeneration Sequence",
    "special_reverberating_cascade":        "Reverberating Cascade",
    "special_scramble_spectrum":            "Scramble Spectrum",
    "special_screening_shell":              "Screening Shell",
    "special_shiftlock_canister":           "Shift-Lock Canister",
    "special_smart_rounds":                 "Smart Rounds",
    "special_super_penetrator":             "Super Penetrator",
    "special_thermal_cascade":              "Thermal Cascade",
    "special_thermal_conduit":              "Thermal Conduit",
    "special_thermal_vent":                 "Thermal Vent",
    "special_thermalshock":                 "Thermal Shock",
    "special_weapon_damage":                "Oversized",
    "special_weapon_efficient":             "Flow Control",
    "special_weapon_lightweight":           "Stripped Down",
    "special_weapon_rateoffire":            "Multi-Servos",
    "special_weapon_toughened":             "Double Braced",
    # ── Thrusters ─────────────────────────────────────────────────────────────
    "special_engine_cooled":                "Thermal Spread",
    "special_engine_haulage":               "Drive Distributors",
    "special_engine_lightweight":           "Stripped Down",
    "special_engine_overloaded":            "Drag Drives",
    "special_engine_toughened":             "Double Braced",
    # ── Frame shift drive ─────────────────────────────────────────────────────
    "special_fsd_cooled":                   "Thermal Spread",
    "special_fsd_fuelcapacity":             "Deep Charge",
    "special_fsd_heavy":                    "Mass Manager",
    "special_fsd_lightweight":              "Stripped Down",
    "special_fsd_toughened":                "Double Braced",
    # ── Shield generator ──────────────────────────────────────────────────────
    "special_shield_efficient":             "Lo-Draw",
    "special_shield_health":                "Hi-Cap",
    "special_shield_kinetic":               "Force Block",
    "special_shield_lightweight":           "Stripped Down",
    "special_shield_regenerative":          "Fast Charge",
    "special_shield_resistive":             "Multi-Weave",
    "special_shield_thermic":               "Thermo Block",
    "special_shield_toughened":             "Double Braced",
    # ── Shield booster and cell bank ──────────────────────────────────────────
    "special_shieldbooster_chunky":         "Super Capacitors",
    "special_shieldbooster_efficient":      "Flow Control",
    "special_shieldbooster_explosive":      "Blast Block",
    "special_shieldbooster_kinetic":        "Force Block",
    "special_shieldbooster_thermic":        "Thermo Block",
    "special_shieldbooster_toughened":      "Double Braced",
    "special_shieldcell_efficient":         "Flow Control",
    "special_shieldcell_gradual":           "Recycling Cell",
    "special_shieldcell_lightweight":       "Stripped Down",
    "special_shieldcell_oversized":         "Boss Cells",
    "special_shieldcell_toughened":         "Double Braced",
    # ── Power plant and distributor ───────────────────────────────────────────
    "special_powerplant_cooled":            "Thermal Spread",
    "special_powerplant_highcharge":        "Monstered",
    "special_powerplant_lightweight":       "Stripped Down",
    "special_powerplant_toughened":         "Double Braced",
    "special_powerdistributor_capacity":    "Cluster Capacitors",
    "special_powerdistributor_efficient":   "Flow Control",
    "special_powerdistributor_fast":        "Super Conduits",
    "special_powerdistributor_lightweight": "Stripped Down",
    "special_powerdistributor_toughened":   "Double Braced",
    # ── Bulkheads and hull reinforcement ──────────────────────────────────────
    "special_armour_chunky":                "Deep Plating",
    "special_armour_explosive":             "Reflective Plating",
    "special_armour_kinetic":               "Angled Plating",
    "special_armour_thermic":               "Layered Plating",
    "special_hullreinforcement_chunky":     "Deep Plating",
    "special_hullreinforcement_explosive":  "Reflective Plating",
    "special_hullreinforcement_kinetic":    "Angled Plating",
    "special_hullreinforcement_thermic":    "Layered Plating",
}


def normalise_eng_name(name: str) -> str:
    """Convert a BlueprintName or ExperimentalEffect to a readable form."""
    if not name:
        return ""
    key = name.lower().strip()
    if key in EXP_EFFECT_NAMES:
        return EXP_EFFECT_NAMES[key]
    if key in BLUEPRINT_NAMES:
        return BLUEPRINT_NAMES[key]
    name = name.strip()
    cleaned = (name[len("special_"):] if key.startswith("special_")
               else _re.sub(r"^[A-Za-z]+_", "", name))
    cleaned = _re.sub(r"(?<=[a-z])(?=[A-Z])", " ", cleaned)
    return " ".join(w[:1].upper() + w[1:] for w in cleaned.replace("_", " ").split())
