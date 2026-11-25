"""tests/test_inara_documented.py — the Inara uploader sends only events in Inara's API documentation."""
from __future__ import annotations

import re
from pathlib import Path

SRC = Path(__file__).resolve().parent.parent / "components" / "inara.py"

DOCUMENTED = {
    "addCommanderFriend", "delCommanderFriend", "getCommanderProfile", "addCommanderPermit", "setCommanderCredits",
    "setCommanderGameStatistics", "setCommanderRankEngineer", "setCommanderRankPilot", "setCommanderRankPower",
    "setCommanderReputationMajorFaction", "setCommanderReputationMinorFaction", "addCommanderInventoryItem",
    "delCommanderInventoryItem", "resetCommanderInventory", "setCommanderInventory", "setCommanderInventoryItem",
    "addCommanderInventoryCargoItem", "delCommanderInventoryCargoItem", "setCommanderInventoryCargo",
    "setCommanderInventoryCargoItem", "addCommanderInventoryMaterialsItem", "delCommanderInventoryMaterialsItem",
    "setCommanderInventoryMaterials", "setCommanderInventoryMaterialsItem", "setCommanderStorageModules",
    "addCommanderShip", "delCommanderShip", "setCommanderShip", "setCommanderShipLoadout", "setCommanderShipTransfer",
    "delCommanderSuitLoadout", "setCommanderSuitLoadout", "updateCommanderSuitLoadout",
    "addCommanderTravelCarrierJump", "addCommanderTravelDock", "addCommanderTravelFSDJump", "addCommanderTravelLand",
    "setCommanderTravelLocation", "addCommanderMission", "setCommanderMissionAbandoned",
    "setCommanderMissionCompleted", "setCommanderMissionFailed", "addCommanderCombatDeath",
    "addCommanderCombatInterdicted", "addCommanderCombatInterdiction", "addCommanderCombatInterdictionEscape",
    "addCommanderCombatKill", "getCommunityGoalsRecent", "setCommanderCommunityGoalProgress", "setCommunityGoal",
}

UNDOCUMENTED_FIELDS = ("shipInGarage", "shipStarSystem", "shipStation", "shipIsHot", "shipInTransit",
                       "killerShipType", "isPlayerKill", "itemCategory")


def _code() -> str:
    return "\n".join(line for line in SRC.read_text(encoding="utf-8").splitlines()
                     if not line.lstrip().startswith("#"))


def test_only_documented_events():
    names = set(re.findall(r'"((?:add|set|del|reset|update|get)Commander[A-Za-z]*|setCommunityGoal|getCommunityGoalsRecent)"',
                           _code()))
    assert names, "event names found"
    assert names <= DOCUMENTED, sorted(names - DOCUMENTED)


def test_no_undocumented_fields():
    code = _code()
    assert [f for f in UNDOCUMENTED_FIELDS if f'"{f}"' in code] == []
