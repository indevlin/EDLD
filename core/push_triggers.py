"""core/push_triggers.py — journal events that flush the integration queues.
"""
from __future__ import annotations

PUSH_EVENTS = frozenset({
    "Docked", "Undocked",
    "StartJump",                   # Hyperspace only, see is_push
    "FSDJump", "CarrierJump", "Location",
    "ShipyardSwap", "ShipyardNew",
    "LaunchSRV", "DockSRV", "SRVDestroyed",
    "LaunchFighter", "DockFighter", "FighterDestroyed",
    "Died",
    "Loadout",
    "ModuleBuy", "ModuleSell", "ModuleSellRemote", "ModuleStore",
    "ModuleRetrieve", "ModuleSwap", "MassModuleStore",
})


def is_push(event: dict) -> bool:
    name = event.get("event")
    if name == "StartJump":
        return event.get("JumpType") == "Hyperspace"
    return name in PUSH_EVENTS
