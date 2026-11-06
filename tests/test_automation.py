"""
tests/test_automation.py — bindings, the key table, and the sequences that
press them.

No key reaches a real keyboard here: the sequences run against a recording
keyboard and a Status.json the test writes, and the focus check is stood in
for. What is checked is what each sequence presses, in what order, and that
it stops — releasing the fire group it moved — the moment the game's state
says it should.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core import automation as A  # noqa: E402
from core import binds as BD  # noqa: E402
from core import keys as K  # noqa: E402

BINDS = """<?xml version="1.0" encoding="UTF-8" ?>
<Root PresetName="Mine" MajorVersion="4" MinorVersion="2">
  <PrimaryFire><Primary Device="Mouse" Key="Mouse_1" /><Secondary Device="Keyboard" Key="Key_Space" /></PrimaryFire>
  <CycleFireGroupNext><Primary Device="Keyboard" Key="Key_N" /><Secondary Device="{NoDevice}" Key="" /></CycleFireGroupNext>
  <GalaxyMapOpen><Primary Device="Keyboard" Key="Key_M"><Modifier Device="Keyboard" Key="Key_LeftShift" /></Primary><Secondary Device="{NoDevice}" Key="" /></GalaxyMapOpen>
  <UI_Up><Primary Device="Keyboard" Key="Key_W" /><Secondary Device="{NoDevice}" Key="" /></UI_Up>
  <UI_Right><Primary Device="Keyboard" Key="Key_D" /><Secondary Device="{NoDevice}" Key="" /></UI_Right>
  <UI_Select><Primary Device="Keyboard" Key="Key_Space" /><Secondary Device="{NoDevice}" Key="" /></UI_Select>
  <LandingGearToggle><Primary Device="Keyboard" Key="Key_L" /><Secondary Device="{NoDevice}" Key="" /></LandingGearToggle>
  <ToggleCargoScoop><Primary Device="231D0200" Key="Joy_2" /><Secondary Device="{NoDevice}" Key="" /></ToggleCargoScoop>
</Root>
"""


@pytest.fixture
def game(tmp_path):
    """A Proton-style prefix: journals and bindings under one Windows user."""
    user = tmp_path / "pfx" / "drive_c" / "users" / "steamuser"
    journal = user / "Saved Games" / "Frontier Developments" / "Elite Dangerous"
    bdir = user / "AppData" / "Local" / "Frontier Developments" / "Elite Dangerous" / "Options" / "Bindings"
    journal.mkdir(parents=True)
    bdir.mkdir(parents=True)
    (bdir / "StartPreset.4.start").write_text("Mine\nMine\nMine\nMine")
    (bdir / "Mine.4.0.binds").write_text(BINDS.replace("Key_L", "Key_K"))
    (bdir / "Mine.4.2.binds").write_text(BINDS)
    return journal, bdir


def test_the_bindings_folder_is_found_beside_the_journals(game):
    journal, bdir = game
    assert BD.bindings_dir(journal) == bdir
    b = BD.Bindings()
    assert b.load(journal)
    # The newest version of the preset, a keyboard secondary when the
    # primary is a mouse, modifiers kept, joystick-only bindings unpressable.
    assert b.get("LandingGearToggle") == BD.Binding("Key_L")
    assert b.get("PrimaryFire") == BD.Binding("Key_Space")
    assert b.get("GalaxyMapOpen") == BD.Binding("Key_M", ("Key_LeftShift",))
    assert b.known("ToggleCargoScoop") and b.get("ToggleCargoScoop") is None


def test_a_built_in_preset_is_explained(tmp_path):
    (tmp_path / "StartPreset.4.start").write_text("KeyboardMouseOnly")
    b = BD.Bindings()
    assert not b.load(override=str(tmp_path))
    assert "custom copy" in b.problem


def test_the_key_table():
    assert K.KEYS["Key_A"][:2] == (30, 0x1E)
    assert K.KEYS["Key_0"][:2] == (11, 0x0B)
    assert K.KEYS["Key_F10"][:2] == (68, 0x44)
    assert K.KEYS["Key_UpArrow"] == (103, 0x48, True)
    assert K.typeable("Oochost MU-O a74-0") and not K.typeable("Sol\n")
    # Every code is unique: two names on one code would press the wrong key.
    codes = [v[0] for v in K.KEYS.values()]
    assert len(codes) == len(set(codes))


class Recorder:
    def __init__(self, status_path, on_press=None):
        self.pressed = []
        self.status_path = status_path
        self.on_press = on_press

    def available(self):
        return True, ""

    def press(self, key, modifiers=(), hold=0.06):
        self.pressed.append(("+".join(list(modifiers) + [key]), round(hold, 2)))
        if self.on_press:
            self.on_press(key, hold)
        return True

    def type_text(self, text, gap=0.04):
        self.pressed.append(("type", text))
        return True


def _status(journal, **kw):
    doc = {"Flags": A.FLAG_SUPERCRUISE | A.FLAG_IN_MAIN_SHIP, "GuiFocus": 0, "FireGroup": 0, **kw}
    (journal / "Status.json").write_text(json.dumps(doc))


@pytest.fixture
def auto(game, monkeypatch):
    journal, _ = game
    monkeypatch.setattr(A, "game_focused", lambda assume=False: (True, ""))
    monkeypatch.setattr(A.time, "sleep", lambda s: None)
    b = BD.Bindings()
    b.load(journal)
    _status(journal)
    kb = Recorder(journal / "Status.json")
    return A.Automation(journal, kb, b), kb, journal


def test_a_control_presses_its_binding_and_nothing_else(auto):
    a, kb, _ = auto
    assert a.press("gear") == (True, "")
    assert kb.pressed == [("Key_L", 0.06)]
    assert a.press("scoop")[0] is False          # bound to a joystick only
    assert a.press("rm -rf")[0] is False          # not a control


def test_honk_selects_the_fire_group_and_puts_it_back(auto):
    a, kb, journal = auto
    group = {"g": 0}

    def on_press(key, hold):
        if key == "Key_N":
            group["g"] = (group["g"] + 1) % 3
            _status(journal, FireGroup=group["g"])
    kb.on_press = on_press
    ok, why = a.honk("PrimaryFire", fire_group=2, hold=6.5)
    assert ok, why
    assert kb.pressed == [("Key_N", 0.06), ("Key_Space", 6.5), ("Key_N", 0.06), ("Key_N", 0.06)]
    assert group["g"] == 0


def test_honk_stops_when_a_panel_is_open_or_in_danger(auto):
    a, kb, journal = auto
    _status(journal, GuiFocus=2)
    assert a.honk() == (False, "a panel or map is open")
    _status(journal, Flags=A.FLAG_SUPERCRUISE | A.FLAG_IN_MAIN_SHIP | A.FLAG_IN_DANGER)
    assert a.honk() == (False, "the ship is in danger")
    _status(journal, Flags=0)
    assert a.honk()[0] is False
    assert kb.pressed == []


SHIP = A.FLAG_IN_MAIN_SHIP


@pytest.mark.parametrize("flags, flags2, anywhere, why", [
    (SHIP, 0, False, "the ship is not in supercruise"),       # auto honk waits for it
    (SHIP | A.FLAG_DOCKED, 0, True, "the ship is docked"),
    (SHIP | A.FLAG_LANDED, 0, True, "the ship is landed"),
    (A.FLAG_IN_SRV, 0, True, "you are in the SRV"),
    (0, A.FLAG2_ON_FOOT, True, "you are on foot"),
    (A.FLAG_IN_FIGHTER, 0, True, "you are in a fighter"),
    (0, 0, True, "you are not flying the ship (at the main menu, or in a crew's ship)"),
    (SHIP | A.FLAG_SUPERCRUISE | A.FLAG_FSD_CHARGING, 0, True,
     "the frame shift drive is charging or jumping"),
])
def test_honk_says_why_it_cannot_start(auto, flags, flags2, anywhere, why):
    """From a real press: "the ship is no longer where the sequence began"
    was all a honk outside supercruise ever said, before it had begun."""
    a, kb, journal = auto
    _status(journal, Flags=flags, Flags2=flags2)
    assert a.honk(anywhere=anywhere) == (False, why)
    assert kb.pressed == []


def test_a_honk_from_the_helm_panel_works_in_normal_space(auto):
    a, kb, journal = auto
    _status(journal, Flags=A.FLAG_IN_MAIN_SHIP)
    assert a.honk("PrimaryFire", hold=6.5, anywhere=True) == (True, "honked")
    assert kb.pressed == [("Key_Space", 6.5)]


def test_going_into_supercruise_mid_honk_stops_it(auto):
    a, kb, journal = auto
    _status(journal, Flags=A.FLAG_IN_MAIN_SHIP)

    def on_press(key, hold):
        if key == "Key_N":
            _status(journal, Flags=A.FLAG_IN_MAIN_SHIP | A.FLAG_SUPERCRUISE, FireGroup=1)
    kb.on_press = on_press
    assert a.honk("PrimaryFire", fire_group=2, anywhere=True) == (
        False, "the ship went into supercruise")
    assert ("Key_Space", 6.5) not in kb.pressed


def test_plot_types_the_system_and_checks_the_route(auto):
    a, kb, journal = auto

    def on_press(key, hold):
        if key == "Key_M":                         # the galaxy map opens, or closes
            st = json.loads((journal / "Status.json").read_text())
            _status(journal, GuiFocus=0 if st.get("GuiFocus") == 6 else 6)
        if key == "Key_Space" and hold > 1:        # plot route
            (journal / "NavRoute.json").write_text(json.dumps(
                {"Route": [{"StarSystem": "Here"}, {"StarSystem": "Hypua AA-A h0"}]}))
    kb.on_press = on_press
    ok, why = a.plot("Hypua AA-A h0")
    assert ok, why
    assert ("type", "Hypua AA-A h0") in kb.pressed
    assert kb.pressed[0] == ("Key_LeftShift+Key_M", 0.06)
    assert kb.pressed[-1] == ("Key_LeftShift+Key_M", 0.06)


def test_plot_closes_the_map_when_the_route_does_not_land(auto):
    a, kb, journal = auto

    def on_press(key, hold):
        if key == "Key_M":
            st = json.loads((journal / "Status.json").read_text())
            _status(journal, GuiFocus=0 if st.get("GuiFocus") == 6 else 6)
    kb.on_press = on_press
    ok, why = a.plot("Hypua AA-A h0", script="GalaxyMapOpen; focus 6; type; route 0.01")
    assert not ok and "did not end" in why
    assert kb.pressed[-1] == ("Key_LeftShift+Key_M", 0.06)
    assert json.loads((journal / "Status.json").read_text())["GuiFocus"] == 0


def test_one_sequence_at_a_time(auto):
    a, kb, _ = auto
    a._busy.acquire()
    try:
        assert a.press("gear") == (False, "another sequence is running")
    finally:
        a._busy.release()


def test_focus_is_required(game, monkeypatch):
    monkeypatch.setattr(K, "_active_title", lambda: "Firefox")
    assert K.game_focused()[0] is False
    monkeypatch.setattr(K, "_active_title", lambda: "Elite - Dangerous (CLIENT)")
    assert K.game_focused() == (True, "")
    monkeypatch.setattr(K, "_active_title", lambda: None)
    assert K.game_focused()[0] is False
    assert K.game_focused(assume=True) == (True, "")


# ── Mouse buttons, and saying what an action is bound to ─────────────────────

SHIP = """<?xml version="1.0" encoding="UTF-8" ?>
<Root PresetName="Pad" MajorVersion="4" MinorVersion="2">
  <PrimaryFire><Primary Device="GamePad" Key="GamePad_RTrigger" /><Secondary Device="Mouse" Key="Mouse_1" /></PrimaryFire>
  <SecondaryFire><Primary Device="GamePad" Key="GamePad_LTrigger" /><Secondary Device="Mouse" Key="Mouse_2" /></SecondaryFire>
  <CycleFireGroupNext><Primary Device="GamePad" Key="GamePad_RBumper"><Modifier Device="GamePad" Key="GamePad_X" /></Primary><Secondary Device="{NoDevice}" Key="" /></CycleFireGroupNext>
  <DeployHardpointToggle><Primary Device="GamePad" Key="GamePad_X" /><Secondary Device="Keyboard" Key="Key_U" /></DeployHardpointToggle>
  <UseBoostJuice><Primary Device="GamePad" Key="GamePad_A" /><Secondary Device="231D0200" Key="Joy_4" /></UseBoostJuice>
  <ShipSpotLightToggle><Primary Device="Mouse" Key="Mouse_3"><Modifier Device="Keyboard" Key="Key_LeftAlt" /></Primary><Secondary Device="{NoDevice}" Key="" /></ShipSpotLightToggle>
  <NightVisionToggle><Primary Device="Mouse" Key="Mouse_ZAxisInc" /><Secondary Device="{NoDevice}" Key="" /></NightVisionToggle>
  <Supercruise><Primary Device="{NoDevice}" Key="" /><Secondary Device="{NoDevice}" Key="" /></Supercruise>
</Root>
"""


@pytest.fixture
def pad(tmp_path):
    """The bindings in the commander's screenshot: the triggers on the
    controller and the mouse, cycling fire groups on the controller alone."""
    (tmp_path / "StartPreset.4.start").write_text("Pad\nPad\nPad\nPad")
    (tmp_path / "Pad.4.2.binds").write_text(SHIP)
    b = BD.Bindings()
    assert b.load(override=str(tmp_path))
    return b


def test_mouse_buttons_are_pressable_and_controllers_are_described(pad):
    assert pad.get("PrimaryFire") == BD.Binding("Mouse_1", (), "Mouse")
    assert pad.get("SecondaryFire").text() == "Mouse 2"
    assert pad.get("DeployHardpointToggle") == BD.Binding("Key_U")      # a key beats the pad
    assert pad.get("ShipSpotLightToggle") == BD.Binding("Mouse_3", ("Key_LeftAlt",), "Mouse")
    assert pad.describe("PrimaryFire") == "controller RT · Mouse 1"
    # Not pressable, and saying exactly why and what to change.
    assert pad.get("CycleFireGroupNext") is None
    why = pad.why("CycleFireGroupNext")
    assert "Cycle Next Fire Group is bound only to controller X+RB" in why
    assert "empty column" in why
    assert "replace one of them" in pad.why("UseBoostJuice")
    assert "joystick button 4" in pad.why("UseBoostJuice")
    assert pad.get("NightVisionToggle") is None                       # a wheel cannot be held
    assert "is not bound" in pad.why("Supercruise")
    assert pad.why("PrimaryFire") == ""


@pytest.fixture
def pad_auto(pad, tmp_path, monkeypatch):
    journal = tmp_path / "journal"
    journal.mkdir()
    monkeypatch.setattr(A, "game_focused", lambda assume=False: (True, ""))
    monkeypatch.setattr(A, "pointer_in_game", lambda assume=False: (True, ""))
    monkeypatch.setattr(A.time, "sleep", lambda s: None)
    _status(journal)
    kb = Recorder(journal / "Status.json")
    return A.Automation(journal, kb, pad), kb, journal


def test_honk_on_a_mouse_button(pad_auto):
    a, kb, _ = pad_auto
    assert a.honk("SecondaryFire") == (True, "honked")
    assert kb.pressed == [("Mouse_2", 6.5)]


def test_a_mouse_button_waits_for_the_pointer_to_be_over_the_game(pad_auto, monkeypatch):
    a, kb, _ = pad_auto
    monkeypatch.setattr(A, "pointer_in_game",
                        lambda assume=False: (False, "the mouse pointer is not over the game's window"))
    ok, why = a.honk("PrimaryFire")
    assert not ok and "pointer" in why and kb.pressed == []
    assert a.press("hardpoints") == (True, "")                       # a key needs no pointer
    assert kb.pressed == [("Key_U", 0.06)]


def test_a_fire_group_only_a_controller_can_cycle_says_so(pad_auto):
    a, kb, journal = pad_auto
    ok, why = a.honk("PrimaryFire", fire_group=3)
    assert not ok and "controller X+RB" in why and kb.pressed == []


def test_the_mouse_button_table():
    assert K.MOUSE["Mouse_1"][0] == 0x110 and K.MOUSE["Mouse_2"][0] == 0x111
    assert K.MOUSE["Mouse_4"][3] == 1 and K.MOUSE["Mouse_5"][3] == 2
    assert set(K.MOUSE) == set(BD.MOUSE_KEYS)


class FakeDev:
    def __init__(self, log, name):
        self.log, self.name = log, name

    def key(self, k, down):
        self.log.append((self.name, k, down))

    def button(self, k, down):
        self.log.append((self.name, k, down))

    def close(self):
        pass


def test_a_mouse_button_goes_through_the_mouse(monkeypatch):
    log = []
    kb = K.Keyboard()
    monkeypatch.setattr(K.time, "sleep", lambda s: None)
    kb._dev = FakeDev(log, "keyboard")
    kb._mouse = FakeDev(log, "mouse")
    assert kb.press("Mouse_3", ("Key_LeftAlt",))
    assert log == [("keyboard", "Key_LeftAlt", True), ("mouse", "Mouse_3", True),
                   ("mouse", "Mouse_3", False), ("keyboard", "Key_LeftAlt", False)]
    assert not kb.press("Mouse_ZAxisInc")


def test_the_pointer_must_be_over_the_game(monkeypatch):
    monkeypatch.setattr(K, "game_focused", lambda assume=False: (True, ""))
    monkeypatch.setattr(K, "_pointer_over_active", lambda: False)
    assert K.pointer_in_game()[0] is False
    monkeypatch.setattr(K, "_pointer_over_active", lambda: None)
    assert K.pointer_in_game()[0] is False and K.pointer_in_game(assume=True)[0] is True
    monkeypatch.setattr(K, "_pointer_over_active", lambda: True)
    assert K.pointer_in_game() == (True, "")
    monkeypatch.setattr(K, "game_focused", lambda assume=False: (False, "the game is not the focused window (x)"))
    assert K.pointer_in_game() == (False, "the game is not the focused window (x)")


def test_the_plot_script_names_its_bindings():
    assert A.script_actions(A.DEFAULT_PLOT_SCRIPT) == ["GalaxyMapOpen", "UI_Up", "UI_Select", "UI_Right"]
