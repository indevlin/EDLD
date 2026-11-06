"""
tests/test_automation_component.py — when the Automation component acts,
the overlay's auto-hide, and the limpet controllers a Loadout fits.
"""
from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.state import MonitorState  # noqa: E402


def _auto(cfg):
    from components.automation import AutomationPlugin
    from core.binds import Binding, Bindings
    state = MonitorState()
    state.in_preload = False
    core = SimpleNamespace(state=state, journal_dir=Path("/nonexistent"), _plugins={},
                           load_setting=lambda s, d, warn=False: dict(cfg),
                           plugin_call=lambda *a, **k: 1,
                           notify_levels={}, emitter=SimpleNamespace(emit=lambda **k: None))
    p = AutomationPlugin.__new__(AutomationPlugin)
    p.core = core
    p.bindings = Bindings()
    p.bindings._map = {"LandingGearToggle": Binding("Key_L"), "ToggleCargoScoop": None}
    p.bindings._path = Path("/x")
    p._auto, p._honked_here, p._arrival_seq = None, False, 0
    import time
    p._binds_loaded_at = time.monotonic()
    return p, state


def test_no_controls_unless_both_switches_are_on():
    assert _auto({})[0].controls() == []
    assert _auto({"Enabled": True})[0].controls() == []
    assert _auto({"AllowControl": True})[0].controls() == []
    p, _ = _auto({"Enabled": True, "AllowControl": True})
    # Only what is bound to a key.
    assert p.controls() == [{"id": "gear", "label": "Landing gear", "group": "ship"}]
    ok, why = p.press_control("scoop")
    assert not ok and why.startswith("Cargo Scoop is not bound")
    assert p.press_control("nonsense") == (False, "not a control")


def test_nothing_happens_while_off_or_replaying(monkeypatch):
    started = []
    import components.automation as AM
    monkeypatch.setattr(AM.threading, "Thread",
                        lambda **k: SimpleNamespace(start=lambda: started.append(k["name"])))
    p, state = _auto({"AutoHonk": True})
    p._never_honked = lambda ev: True
    p.on_event({"event": "FSDJump", "SystemAddress": 1}, state)
    assert started == []                                  # not enabled
    p, state = _auto({"Enabled": True, "AutoHonk": True, "AutoTarget": True})
    p._never_honked = lambda ev: True
    state.in_preload = True
    p.on_event({"event": "FSDJump", "SystemAddress": 1}, state)
    assert started == []                                  # replaying
    state.in_preload = False
    p.on_event({"event": "FSDJump", "SystemAddress": 1}, state)
    p.on_event({"event": "JetConeBoost", "BoostValue": 4.0}, state)
    assert started == ["auto-honk", "auto-target"]
    p._never_honked = lambda ev: False
    p.on_event({"event": "FSDJump", "SystemAddress": 2}, state)
    assert started == ["auto-honk", "auto-target"]        # honked here before


def test_auto_target_only_on_an_edld_route_of_multi_jump_stops(monkeypatch):
    import components.automation as AM
    monkeypatch.setattr(AM.time, "sleep", lambda s: None)
    p, state = _auto({"Enabled": True, "AutoTarget": True})
    plotted = []
    p._engine = lambda: SimpleNamespace(plot=lambda system, script: plotted.append(system) or (True, ""))
    route = [{"StarSystem": "A", "EDLD": {"jumps": 1}}, {"StarSystem": "B", "EDLD": {"jumps": 5}},
             {"StarSystem": "C", "EDLD": {"jumps": 4}}]
    nav = SimpleNamespace(active_route=lambda: (route, "edld"), next_system=lambda: ("B", ""))
    p.core._plugins["navigation"] = nav
    p._target_later(p._arrival_seq)
    assert plotted == ["B"]
    nav.active_route = lambda: (route, "journal")
    p._target_later(p._arrival_seq)
    nav.active_route = lambda: ([{"StarSystem": "A"}, {"StarSystem": "B"}], "edld")
    p._target_later(p._arrival_seq)
    assert plotted == ["B"]
    nav.active_route = lambda: (route, "edld")
    p._target_later(p._arrival_seq - 1)                   # jumped away since
    assert plotted == ["B"]


def test_overlay_auto_hide():
    from components.overlay import auto_hidden
    s = MonitorState()
    assert auto_hidden({"HideDocked": True}, s) == ""
    s.docked_at = {"station": "Jameson Memorial"}
    assert auto_hidden({}, s) == ""
    assert auto_hidden({"HideDocked": "true"}, s) == "docked"
    s.docked_at, s.on_foot = None, True
    assert auto_hidden({"HideOnFoot": True}, s) == "on foot"


def test_loadout_limpet_controllers_and_refinery():
    from components.commander import CommanderPlugin
    state = MonitorState()
    p = CommanderPlugin.__new__(CommanderPlugin)
    p.core = SimpleNamespace(state=state, gui_queue=None, _plugins={},
                             plugin_call=lambda *a, **k: None,
                             emitter=SimpleNamespace(emit=lambda **k: None))
    p._star_pos_live = False
    p.on_event({"timestamp": "2026-10-20T10:00:00Z", "event": "Loadout", "Ship": "python",
                "ShipID": 3, "MaxJumpRange": 20.0, "UnladenMass": 400.0,
                "FuelCapacity": {"Main": 32.0, "Reserve": 0.8},
                "Modules": [{"Slot": "Slot01", "Item": "int_dronecontrol_prospector_size1_class5"},
                            {"Slot": "Slot02", "Item": "int_multidronecontrol_miningv2_size5_class5"},
                            {"Slot": "Slot03", "Item": "int_dronecontrol_unkvesselresearch"},
                            {"Slot": "Slot04", "Item": "int_refinery_size4_class5"}]}, state)
    assert state.ship_limpet_controllers == ["mining", "prospector", "unkvesselresearch"]
    assert state.ship_has_refinery is True


def test_the_binding_check_says_what_each_sequence_presses(tmp_path, monkeypatch):
    """Options → Automation → Check bindings: every binding a sequence
    needs, what it is bound to, and whether EDLD can press it."""
    import test_automation as TA
    (tmp_path / "StartPreset.4.start").write_text("Pad\nPad\nPad\nPad")
    (tmp_path / "Pad.4.2.binds").write_text(TA.SHIP)
    monkeypatch.setattr("core.keys.Keyboard.available", lambda self: (True, ""))
    p, _ = _auto({"BindingsDir": str(tmp_path), "HonkTrigger": "SecondaryFire",
                  "HonkFireGroup": 2})
    report = p.settings_action("check-binds").splitlines()
    assert "  ✓ Secondary Fire: Mouse 2 — pressed only while the pointer is over the game" in report
    assert any(line.startswith("  ✗ Cycle Next Fire Group is bound only to controller X+RB")
               for line in report)
    assert any(line.startswith("  ✗ Open Galaxy Map is not bound") for line in report)
    rail = next(line for line in report if line.startswith("Helm panel:"))
    assert rail.startswith("Helm panel: 2 of ")         # hardpoints (key), lights (mouse)
    p, _ = _auto({"BindingsDir": str(tmp_path)})
    assert any("not needed" in line for line in p.settings_action("check-binds").splitlines())


def test_a_mouse_bound_control_reaches_the_rail():
    from core.binds import Binding
    p, _ = _auto({"Enabled": True, "AllowControl": True})
    p.bindings._map["ShipSpotLightToggle"] = Binding("Mouse_3", (), "Mouse")
    assert {"id": "lights", "label": "Lights", "group": "ship"} in p.controls()
