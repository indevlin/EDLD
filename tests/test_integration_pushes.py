"""tests/test_integration_pushes.py — when integrations send, and what Inara and EDDN send."""
from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core import push_triggers  # noqa: E402
from core.state import MonitorState  # noqa: E402


class _Sender:
    def __init__(self):
        self.items, self.flushes = [], 0

    def push(self, item):
        self.items.append(item)

    def enqueue(self, item):
        self.items.append(item)

    def flush(self):
        self.flushes += 1


def test_the_push_triggers():
    yes = ["Docked", "Undocked", "FSDJump", "CarrierJump", "ShipyardSwap", "LaunchSRV",
           "DockSRV", "LaunchFighter", "DockFighter", "Died", "Loadout", "ModuleBuy",
           "ModuleStore", "ModuleRetrieve", "ModuleSwap", "MassModuleStore"]
    assert all(push_triggers.is_push({"event": e}) for e in yes)
    assert push_triggers.is_push({"event": "StartJump", "JumpType": "Hyperspace"})
    assert not push_triggers.is_push({"event": "StartJump", "JumpType": "Supercruise"})
    assert not push_triggers.is_push({"event": "Scan"})


def _inara():
    from components.inara import InaraPlugin
    p = InaraPlugin.__new__(InaraPlugin)
    p.core = SimpleNamespace(state=MonitorState(), gui_queue=None)
    p.storage = SimpleNamespace(read_json=lambda *a: {}, write_json=lambda *a: None,
                                file_path=lambda n: Path("/nonexistent") / n)
    p._enabled, p._reconciled, p._sender = True, True, _Sender()
    p._star_pos, p._ship_type, p._ship_id, p._rank_values = None, "anaconda", 7, {}
    p._cmdr_name = "MERRICK CALBRUIN"
    return p


def _inara_names(p):
    return [i["eventName"] for i in p._sender.items]


def test_inara_travel_events():
    p = _inara()
    st = p.core.state
    st.in_preload = False
    p.on_event({"timestamp": "2026-11-01T07:19:10Z", "event": "CarrierJump", "Docked": True,
                "StationName": "N2Z-N8M", "MarketID": 3715178496, "StarSystem": "Wolf 397",
                "StarPos": [1, 2, 3]}, st)
    p.on_event({"timestamp": "2026-11-01T06:45:32Z", "event": "Location", "Docked": False,
                "StarSystem": "LFT 509", "StarPos": [4, 5, 6]}, st)
    p.on_event({"timestamp": "2026-11-01T06:55:22Z", "event": "FSDJump",
                "StarSystem": "Eurybia", "StarPos": [7, 8, 9], "JumpDist": 12.3}, st)
    names = _inara_names(p)
    assert names[:2] == ["addCommanderTravelCarrierJump", "setCommanderTravelLocation"]
    assert "addCommanderTravelFSDJump" in names
    carrier = p._sender.items[0]["eventData"]
    assert carrier["marketID"] == 3715178496 and "jumpDistance" not in carrier
    # Each of the three is a push trigger: the batch went at once.
    assert p._sender.flushes == 3


def test_inara_flushes_on_a_module_change_it_sends_nothing_for():
    p = _inara()
    st = p.core.state
    st.in_preload = False
    p.on_event({"timestamp": "2026-11-01T07:00:00Z", "event": "ModuleStore", "Slot": "Slot01"}, st)
    assert p._sender.flushes == 1 and p._sender.items == []


def _eddn(tmp_path):
    from components.eddn import EDDNPlugin
    p = EDDNPlugin.__new__(EDDNPlugin)
    p.core = SimpleNamespace(journal_dir=tmp_path, state=MonitorState())
    p._sender = _Sender()
    p._star_system, p._horizons, p._odyssey = "Eurybia", True, True
    p._last_shipyard_hash = p._last_outfitting_hash = p._last_commodity_hash = None
    p._game_version, p._game_build, p._cmdr_name, p._test_mode = "4.3", "r1", "X", True
    return p


def test_eddn_resends_a_carrier_shipyard_after_the_carrier_moves(tmp_path):
    p = _eddn(tmp_path)
    shipyard = {"timestamp": "2026-11-01T07:01:13Z", "event": "Shipyard", "MarketID": 3715178496,
                "StationName": "N2Z-N8M", "StarSystem": "Eurybia",
                "PriceList": [{"ShipType": "anaconda"}, {"ShipType": "type9"}]}
    (tmp_path / "Shipyard.json").write_text(json.dumps(shipyard), encoding="utf-8")
    trigger = {"MarketID": 3715178496, "timestamp": shipyard["timestamp"]}
    p._send_shipyard_json(trigger, True)
    p._send_shipyard_json(trigger, True)                  # same docking, same place
    assert len(p._sender.items) == 1
    shipyard.update(StarSystem="Wolf 397", timestamp="2026-11-01T07:50:19Z")
    (tmp_path / "Shipyard.json").write_text(json.dumps(shipyard), encoding="utf-8")
    p._send_shipyard_json(trigger, True)                  # the carrier jumped
    assert len(p._sender.items) == 2
    assert p._sender.items[1]["message"]["systemName"] == "Wolf 397"
