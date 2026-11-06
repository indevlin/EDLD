"""
tests/test_on_foot.py — resuming the game on foot names the suit, not a ship.

From a real session, 20261030: the game was resumed on foot at Gill Point.
LoadGame names the commander's suit as its "Ship" — "ExplorationSuit_Class3"
— and, for a grade 3 Artemis, a Ship_Localised the game never translated:
"$ExplorationSuit_Class1_Name;". EDLD took that for the ship's type, beside
the last ship's name, so the header strip said "PROCURATOR (AN-PRO) ·
$ExplorationSuit_Class1_Name;" and the Ship window the same in capitals, and
the commander was shown aboard a ship while standing on a planet.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.state import MonitorState  # noqa: E402
from data.ships import is_suit, suit_display  # noqa: E402

# The journal's own lines, 20261030, trimmed to what is read.
LOADGAME_ON_FOOT = {
    "timestamp": "2026-10-30T21:43:23Z", "event": "LoadGame", "FID": "F10467336",
    "Commander": "MERRICK CALBRUIN", "Horizons": True, "Odyssey": True,
    "Ship": "ExplorationSuit_Class3", "Ship_Localised": "$ExplorationSuit_Class1_Name;",
    "ShipID": 4293000000, "ShipName": "", "ShipIdent": "", "FuelLevel": 1.0,
    "FuelCapacity": 1.0, "GameMode": "Solo", "Credits": 25225597686, "Loan": 0,
}
SUIT_LOADOUT = {
    "timestamp": "2026-10-30T21:43:46Z", "event": "SuitLoadout",
    "SuitID": 1876016497328208, "SuitName": "explorationsuit_class3",
    "SuitName_Localised": "$ExplorationSuit_Class1_Name;",
    "SuitMods": ["suit_increasedo2capacity"], "LoadoutID": 4293000000,
    "LoadoutName": "ARTEMIS", "Modules": [],
}
LOCATION_ON_FOOT = {
    "timestamp": "2026-10-30T21:43:46Z", "event": "Location", "DistFromStarLS": 314.8,
    "Docked": False, "OnFoot": True, "StarSystem": "Eurybia",
    "SystemAddress": 1458309141194, "StarPos": [51.40625, -54.40625, -30.5],
    "Body": "Makalu", "BodyType": "Planet",
}


def _commander(state):
    spec = importlib.util.spec_from_file_location("cmdr_foot", ROOT / "components" / "commander.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    p = mod.CommanderPlugin.__new__(mod.CommanderPlugin)
    said = []
    p.core = SimpleNamespace(
        state=state, journal_dir="/nonexistent", gui_queue=None, cfg=None,
        active_session=SimpleNamespace(fuel_check_time=0, fuel_check_level=0),
        emitter=SimpleNamespace(emit=lambda **k: said.append(k)), notify_levels={})
    p._close_session_if_over = lambda *a, **k: None
    p._star_pos_live = False
    return p, said


def _aboard_procurator() -> MonitorState:
    state = MonitorState()
    state.in_preload = False
    state.pilot_name = "MERRICK CALBRUIN"
    state.ship_name, state.ship_ident = "PROCURATOR", "AN-PRO"
    state.pilot_ship = "Anaconda Mk II"
    state.fuel_current, state.fuel_tank_size = 60.0, 64.0
    return state


def test_a_suit_is_named_from_its_internal_name():
    assert suit_display("ExplorationSuit_Class3", "$ExplorationSuit_Class1_Name;") == "Artemis Suit G3"
    assert suit_display("explorationsuit_class1", "Artemis Suit") == "Artemis Suit G1"
    assert suit_display("UtilitySuit_Class2") == "Maverick Suit G2"
    assert suit_display("TacticalSuit_Class5") == "Dominator Suit G5"
    assert suit_display("FlightSuit", "Flight Suit") == "Flight Suit"
    # A suit a later game adds: its own name when the game gives one.
    assert suit_display("NewSuit_Class1", "Pathfinder Suit") == "Pathfinder Suit G1"
    assert suit_display("NewSuit_Class1", "$NewSuit_Name;") == "New Suit G1"
    assert is_suit("ExplorationSuit_Class3") and is_suit("FlightSuit")
    assert not is_suit("Explorer_NX") and not is_suit("anacondamkii") and not is_suit("")


def test_resuming_on_foot_keeps_the_ship_and_names_the_suit():
    state = _aboard_procurator()
    p, said = _commander(state)
    p.on_event(dict(LOADGAME_ON_FOOT), state)
    assert state.vessel_mode == "on_foot"
    assert state.suit_name == "Artemis Suit G3"
    assert state.pilot_ship == "Anaconda Mk II"
    assert (state.ship_name, state.ship_ident) == ("PROCURATOR", "AN-PRO")
    # The suit's 1 of 1 is not the ship's tank.
    assert state.fuel_current == 60.0 and state.fuel_tank_size == 64.0
    assert "$" not in said[0]["msg_term"] and "Artemis Suit G3" in said[0]["msg_term"]

    from core import edcars
    strip = {f.key: f.value for f in edcars.strip(state)}
    assert strip["vessel"] == "Artemis Suit G3"
    assert "fuel" not in strip and "cargo" not in strip


def test_the_suit_loadout_that_follows_names_it_the_same_way():
    state = _aboard_procurator()
    p, _ = _commander(state)
    p.on_event(dict(LOADGAME_ON_FOOT), state)
    p.on_event(dict(LOCATION_ON_FOOT), state)
    p.on_event(dict(SUIT_LOADOUT), state)
    assert state.vessel_mode == "on_foot"
    assert state.suit_name == "Artemis Suit G3" and state.suit_loadout == "ARTEMIS"


def test_location_on_foot_says_so_without_a_disembark():
    state = _aboard_procurator()
    state.vessel_mode = "ship"
    p, _ = _commander(state)
    p.on_event(dict(LOCATION_ON_FOOT), state)
    assert state.vessel_mode == "on_foot"


def test_resuming_in_the_ship_is_unchanged():
    state = _aboard_procurator()
    state.vessel_mode = "on_foot"
    state.suit_name = "Artemis Suit G3"
    p, _ = _commander(state)
    p.on_event({"timestamp": "2026-11-01T06:45:19Z", "event": "LoadGame",
                "Commander": "MERRICK CALBRUIN", "Ship": "Explorer_NX",
                "Ship_Localised": "Caspian Explorer", "ShipID": 12, "ShipName": "PICTOR",
                "ShipIdent": "CE-PIC", "FuelLevel": 84.5, "FuelCapacity": 88.0,
                "GameMode": "Solo"}, state)
    assert state.vessel_mode == "ship" and state.suit_name == ""
    assert state.pilot_ship == "Caspian Explorer"
    assert (state.ship_name, state.ship_ident) == ("PICTOR", "CE-PIC")
    assert state.fuel_current == 84.5


def test_the_journal_handler_leaves_the_ship_too():
    """core/journal.py's own LoadGame, for the terminal log, set the ship's
    type from the same field."""
    src = (ROOT / "core" / "journal.py").read_text(encoding="utf-8")
    block = src[src.index('            case "LoadGame":'):]
    block = block[:block.index('            case "Loadout":')]
    assert "is_suit(" in block and "if not _on_foot:" in block
