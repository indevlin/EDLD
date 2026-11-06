"""
tests/test_neutron_supercharge.py — a neutron route is plotted with the ship's
own supercharge.

Every route was sent to Spansh at ×4. The Caspian Explorer's SCO drive Mk II
supercharges ×6 (its +500% against the standard +300%), so its neutron routes
used every boost at two thirds of its length and took more jumps than the
ship needs.
"""
from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.route_view import supercharge_multiplier  # noqa: E402
from core.state import MonitorState  # noqa: E402

MK2 = "int_hyperdrive_overcharge_size8_class5_overchargebooster_mkii"


def _loadout(item):
    from components.commander import CommanderPlugin
    state = MonitorState()
    p = CommanderPlugin.__new__(CommanderPlugin)
    p.core = SimpleNamespace(state=state, gui_queue=None, _plugins={},
                             plugin_call=lambda *a, **k: None,
                             emitter=SimpleNamespace(emit=lambda **k: None))
    p._star_pos_live = False
    p.on_event({"timestamp": "2026-10-20T10:00:00Z", "event": "Loadout",
                "Ship": "explorer_nx", "ShipName": "PICTOR", "ShipIdent": "CE-PIC",
                "MaxJumpRange": 73.179588, "UnladenMass": 600.0,
                "FuelCapacity": {"Main": 128.0, "Reserve": 1.13},
                "Modules": [{"Slot": "FrameShiftDrive", "Item": item}]}, state)
    return state


def test_the_mk2_supercharges_six_times():
    assert _loadout(MK2).ship_fsd_item == MK2
    assert supercharge_multiplier(_loadout(MK2)) == 6


def test_every_other_drive_four_times():
    for item in ("int_hyperdrive_overcharge_size5_class5", "int_hyperdrive_size6_class1"):
        assert supercharge_multiplier(_loadout(item)) == 4
    assert supercharge_multiplier(MonitorState()) == 4


def test_the_neutron_plot_sends_it():
    from components.spansh import SpanshPlugin
    sent = {}
    p = SpanshPlugin.__new__(SpanshPlugin)
    p.core = SimpleNamespace(state=_loadout(MK2))
    p._plot_route = lambda kind, params, store_key=None: sent.update(params) or {}
    p.plot_neutron_route("Sol", "Colonia", 66.9)
    assert sent["supercharge_multiplier"] == 6
