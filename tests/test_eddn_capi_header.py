"""fcmaterials_capi: CAPI's game version, not the journal's, and only for the
carrier docked at, once per change of its orders."""
from types import SimpleNamespace
from pathlib import Path

from components.eddn import CAPI_MARKET, EDDNPlugin


def _plugin():
    p = EDDNPlugin.__new__(EDDNPlugin)
    core = SimpleNamespace(load_setting=lambda *a, **k: {"Enabled": False},
                           cfg=SimpleNamespace(app_settings={}), journal_dir=None)
    p.storage = SimpleNamespace(file_path=lambda n: Path("/dev/null"))
    p.on_load(core)
    p._enabled = True
    sent: list = []
    p._sender = SimpleNamespace(enqueue=sent.append)
    state = SimpleNamespace(in_preload=False)
    p._on_event({"event": "Fileheader", "gameversion": "4.2.3.0", "build": "r1/r0 "}, state)
    return p, sent, state


MID = 3700000000
ITEMS = {"purchases": [], "sales": []}


def _dock(p, state, mid=MID):
    p._on_event({"timestamp": "2026-11-11T19:00:00Z", "event": "Docked", "MarketID": mid,
                 "StationName": "X9X-99X", "StarSystem": "Sol", "SystemAddress": 1,
                 "StationType": "FleetCarrier"}, state)


def test_fcmaterials_capi_names_the_capi_endpoint():
    p, sent, state = _plugin()
    _dock(p, state)
    sent.clear()
    p.push_fcmaterials_capi(3700000000, "X9X-99X", {"purchases": [], "sales": []},
                            "2026-11-11T19:18:56Z")
    h = sent[0]["header"]
    assert h["gameversion"] == CAPI_MARKET == h["gamebuild"]


def test_journal_messages_keep_the_journal_game_version():
    p, sent, state = _plugin()
    p._system_address, p._star_system, p._star_pos = 1, "Sol", [0, 0, 0]
    p._on_event({"timestamp": "2026-11-11T19:00:00Z", "event": "FSSDiscoveryScan",
                 "Progress": 0.5, "BodyCount": 9, "NonBodyCount": 1,
                 "SystemName": "Sol", "SystemAddress": 1}, state)
    h = sent[0]["header"]
    assert (h["gameversion"], h["gamebuild"]) == ("4.2.3.0", "r1/r0 ")


def _fc(p):
    p.push_fcmaterials_capi(MID, "X9X-99X", ITEMS, "2026-11-11T19:18:56Z")


def test_nothing_is_sent_unless_docked_at_that_carrier():
    p, sent, state = _plugin()
    _fc(p)
    assert sent == []
    _dock(p, state, mid=128000000)
    sent.clear()
    _fc(p)
    assert sent == []


def test_a_restart_while_landed_is_not_docked():
    p, sent, state = _plugin()
    _dock(p, state)
    p._on_event({"timestamp": "2026-11-11T21:51:11Z", "event": "Location", "Docked": False,
                 "StarSystem": "Synuefe NL-N c23-4", "SystemAddress": 1184840454858,
                 "StarPos": [1.0, 2.0, 3.0]}, state)
    sent.clear()
    _fc(p)
    assert sent == []


def test_the_same_orders_are_sent_once():
    p, sent, state = _plugin()
    _dock(p, state)
    sent.clear()
    _fc(p)
    _fc(p)
    assert [e["$schemaRef"].rsplit("/", 2)[-2] for e in sent] == ["fcmaterials_capi"]
