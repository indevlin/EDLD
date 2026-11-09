"""Ship display names: CAPI's internal ids never reach the screen."""
import data.ships as ships
from data.ships import (normalise_ship_name, learn_ship_name,
                        learn_ship_names_from_event)


def setup_function(_):
    ships._LEARNED_NAMES.clear()


def test_capi_internal_ids_resolve():
    # CAPI /profile sends name "LakonMiner" with nameLocalized null.
    assert normalise_ship_name("LakonMiner") == "Type-11 Prospector"
    assert normalise_ship_name("MediumTransport01") == "Lynx Highliner"
    assert normalise_ship_name("Type9_Military") == "Type-10 Defender"


def test_learned_name_beats_guess_for_unknown_ship():
    assert normalise_ship_name("NewHull01_NX") == "Newhull01 Nx"
    learn_ship_names_from_event({
        "event": "StoredShips",
        "ShipsRemote": [{"ShipType": "NewHull01_NX",
                         "ShipType_Localised": "Brand New Hull"}],
    })
    assert normalise_ship_name("newhull01_nx") == "Brand New Hull"


def test_echoed_ids_and_keys_are_not_learned():
    learn_ship_name("NewHull02", "NewHull02")
    learn_ship_name("NewHull03", "$NewHull03_Name;")
    assert normalise_ship_name("NewHull02") == "Newhull02"
    assert normalise_ship_name("NewHull03") == "Newhull03"


def test_capi_profile_ships_get_display_names():
    """The Commander > Ships list showed "LakonMiner" for the current ship:
    CAPI's nameLocalized is null and the raw id was used as the name."""
    from types import SimpleNamespace
    from core.data import CAPISource
    from core.state import MonitorState

    src = CAPISource.__new__(CAPISource)
    src._storage = SimpleNamespace(write_json=lambda *a, **k: None)
    state = MonitorState()
    profile = {
        "commander": {"id": 1, "name": "X", "credits": 1},
        "ship": {"id": 3, "name": "LakonMiner", "nameLocalized": None,
                 "health": {"hull": 1000000}, "value": {}},
        "ships": {
            "3": {"id": 3, "name": "LakonMiner", "nameLocalized": None},
            "5": {"id": 5, "name": "MediumTransport01", "nameLocalized": None},
        },
    }
    src._extract_profile(profile, state)
    assert state.assets_current_ship["type_display"] == "Type-11 Prospector"
    assert [s["type_display"] for s in state.assets_stored_ships] == ["Lynx Highliner"]


def test_every_ship_type_in_real_journals_has_a_name():
    """Ids taken from real journals (2026)."""
    assert normalise_ship_name("anacondamkii") == "Anaconda Mk II"
    assert normalise_ship_name("AnacondaMkII") == "Anaconda Mk II"
    assert normalise_ship_name("asp_scout") == "Asp Scout"
    assert normalise_ship_name("diamondback") == "Diamondback Scout"
    assert normalise_ship_name("viper_mkiv") == "Viper Mk IV"
    assert normalise_ship_name("anaconda") == "Anaconda"


def test_sidewinder_and_eagle_are_named_as_the_game_names_them():
    # The game, EDSY and FDevIDs: plain "Sidewinder" and "Eagle".
    assert normalise_ship_name("sidewinder") == "Sidewinder"
    assert normalise_ship_name("SideWinder") == "Sidewinder"
    assert normalise_ship_name("eagle") == "Eagle"
    assert normalise_ship_name("Empire_Eagle") == "Imperial Eagle"
