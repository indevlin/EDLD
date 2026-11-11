"""fcmaterials_capi carries CAPI's game version, not the journal's."""
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


def test_fcmaterials_capi_names_the_capi_endpoint():
    p, sent, _ = _plugin()
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
