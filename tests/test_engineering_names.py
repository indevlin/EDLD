"""tests/test_engineering_names.py — blueprint and experimental labels match the game."""

import pytest

from data.engineering import BLUEPRINT_NAMES, EXP_EFFECT_NAMES, normalise_eng_name


@pytest.mark.parametrize("journal, label", [
    ("PowerDistributor_PriorityEngines", "Engine Focused"),
    ("PowerDistributor_HighFrequency", "Charge Enhanced"),
    ("PowerDistributor_PriorityWeapons", "Weapon Focused"),
    ("Engine_Dirty", "Dirty Drive Tuning"),
    ("Engine_Tuned", "Clean Drive Tuning"),
    ("ShieldGenerator_Optimised", "Enhanced Low Power"),
    ("Armour_Advanced", "Lightweight"),
    ("PowerPlant_Boosted", "Overcharged"),
    ("Weapon_ShortRange", "Short Range"),
])
def test_blueprint_labels(journal, label):
    assert normalise_eng_name(journal) == label


# BlueprintName values seen in Loadout events across a commander's journals.
SEEN_BLUEPRINTS = [
    "Armour_Advanced", "Armour_HeavyDuty", "CargoRack_IncreasedCapacity",
    "Engine_Dirty", "FSD_LongRange", "Misc_HeatSinkCapacity", "Misc_LightWeight",
    "Misc_PointDefenseCapacity", "PowerDistributor_HighFrequency",
    "PowerDistributor_PriorityEngines", "PowerDistributor_PriorityWeapons",
    "PowerPlant_Armoured", "PowerPlant_Boosted", "Sensor_Expanded",
    "Sensor_LightWeight", "Sensor_LongRange", "ShieldBooster_HeavyDuty",
    "ShieldBooster_Resistive", "ShieldBooster_Thermic", "ShieldGenerator_Optimised",
    "ShieldGenerator_Reinforced", "ShieldGenerator_Thermic", "Weapon_Efficient",
    "Weapon_HighCapacity", "Weapon_LongRange",
]


@pytest.mark.parametrize("journal", SEEN_BLUEPRINTS)
def test_seen_blueprints_are_named(journal):
    assert journal.lower() in BLUEPRINT_NAMES


# ExperimentalEffect → ExperimentalEffect_Localised pairs from the same journals.
SEEN_EFFECTS = {
    "special_armour_chunky": "Deep Plating",
    "special_engine_lightweight": "Stripped Down",
    "special_engine_overloaded": "Drag Drives",
    "special_fsd_heavy": "Mass Manager",
    "special_powerdistributor_fast": "Super Conduits",
    "special_powerdistributor_lightweight": "Stripped Down",
    "special_powerplant_highcharge": "Monstered",
    "special_powerplant_lightweight": "Stripped Down",
    "special_scramble_spectrum": "Scramble Spectrum",
    "special_shield_health": "Hi-Cap",
    "special_shield_lightweight": "Stripped Down",
    "special_shield_regenerative": "Fast Charge",
    "special_shieldbooster_chunky": "Super Capacitors",
    "special_weapon_damage": "Oversized",
    "special_weapon_lightweight": "Stripped Down",
}


@pytest.mark.parametrize("journal, localised", sorted(SEEN_EFFECTS.items()))
def test_effect_fallback_matches_localised(journal, localised):
    assert EXP_EFFECT_NAMES[journal] == localised


def test_unknown_names_read_as_words():
    assert normalise_eng_name("Foo_SomeNewThing") == "Some New Thing"
    assert normalise_eng_name("special_new_effect") == "New Effect"
    assert normalise_eng_name("") == ""
