"""
core/binds.py — the commander's keybindings, from the game's own files.

The game keeps bindings in ``Options/Bindings`` under its local application
data: ``StartPreset.4.start`` (or ``StartPreset.start`` before Odyssey) names
the preset in use — one line per category, general, ship, SRV and on foot,
usually all the same — and ``<preset>.4.2.binds`` (the highest version
present) is that preset's XML:

    <HyperSuperCombination>
        <Primary Device="Keyboard" Key="Key_J">
            <Modifier Device="Keyboard" Key="Key_LeftShift" />
        </Primary>
        <Secondary Device="{NoDevice}" Key="" />
    </HyperSuperCombination>

Keyboard bindings are pressed as keys and mouse buttons (Mouse 1–5) as
mouse buttons; a keyboard binding is preferred where an action has both. An
action bound only to a controller or joystick cannot be pressed — the game
names a particular device, which a stand-in could not pass for — so every
slot is kept, to say exactly what it is bound to and what to change: the
Primary and Secondary columns of the game's Controls page. A built-in preset (Keyboard + Mouse, a stock
controller) has no file here: the game ships those in its install folder,
and saving a custom copy of it in Options → Controls makes one.

The folder is found from the journal folder when it is the game's own
Saved Games folder — in a Wine/Proton prefix too, where both live under the
same ``users/<name>``; otherwise it is a setting.
"""
from __future__ import annotations

import os
import re
import sys
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path

_REL = Path("Frontier Developments") / "Elite Dangerous" / "Options" / "Bindings"


#: The mouse buttons EDLD can press, as the game names them.
MOUSE_KEYS = ("Mouse_1", "Mouse_2", "Mouse_3", "Mouse_4", "Mouse_5")

#: A controller's buttons, as the .binds files name them after the device
#: prefix (``GamePad_RBumper``, ``Pad_RBumper``), as the Controls page shows them.
_PAD = {"A": "A", "B": "B", "X": "X", "Y": "Y", "LBumper": "LB", "RBumper": "RB",
        "LTrigger": "LT", "RTrigger": "RT", "LThumb": "LS", "RThumb": "RS",
        "Back": "Back", "Start": "Start", "DPadUp": "D-pad up", "DPadDown": "D-pad down",
        "DPadLeft": "D-pad left", "DPadRight": "D-pad right"}


def key_text(device: str, key: str) -> str:
    """One key as the game's Controls page shows it, near enough."""
    if device == "Keyboard":
        return key.replace("Key_", "")
    if device == "Mouse":
        if key in MOUSE_KEYS:
            return key.replace("_", " ")
        return {"Mouse_ZAxisInc": "wheel up", "Mouse_ZAxisDec": "wheel down"}.get(
            key, key.replace("Mouse_", "mouse "))
    pad = re.sub(r"^(GamePad|Pad)_", "", key)
    if pad != key and pad in _PAD:
        return _PAD[pad]
    m = re.fullmatch(r"Joy_(\d+)", key)
    if m:
        return f"button {m.group(1)}"
    return re.sub(r"^(Pad|Joy|GamePad)_", "", key)


def device_text(device: str, key: str) -> str:
    if device == "Keyboard":
        return "keyboard"
    if device == "Mouse":
        return "mouse"
    if key.startswith(("Pad_", "GamePad_")) or "pad" in device.lower():
        return "controller"
    return "joystick"


@dataclass(frozen=True)
class Binding:
    """What EDLD presses for an action: a keyboard key, or a mouse button,
    with any keyboard keys held with it."""
    key: str
    modifiers: tuple[str, ...] = ()
    device: str = "Keyboard"

    @property
    def mouse(self) -> bool:
        return self.device == "Mouse"

    def text(self) -> str:
        names = [m.replace("Key_", "") for m in self.modifiers] + [key_text(self.device, self.key)]
        return "+".join(names)


@dataclass(frozen=True)
class Slot:
    """One column of an action on the game's Controls page: the device, the
    key or button, and what is held with it, each as (device, key)."""
    device: str
    key: str
    modifiers: tuple[tuple[str, str], ...] = ()

    def binding(self) -> Binding | None:
        """What EDLD would press for this slot, or None when it cannot."""
        if any(d != "Keyboard" for d, _ in self.modifiers):
            return None          # a modifier held on a controller cannot be pressed
        mods = tuple(k for _, k in self.modifiers)
        if self.device == "Keyboard":
            return Binding(self.key, mods)
        if self.device == "Mouse" and self.key in MOUSE_KEYS:
            return Binding(self.key, mods, "Mouse")
        return None

    def text(self) -> str:
        names = [key_text(d, k) for d, k in self.modifiers] + [key_text(self.device, self.key)]
        where = device_text(self.device, self.key)
        joined = "+".join(names)
        return joined if where in ("keyboard", "mouse") else f"{where} {joined}"


def bindings_dir(journal_dir=None, override: str = "") -> Path | None:
    """Where the game keeps its bindings, or None when it cannot be found."""
    if override:
        p = Path(override).expanduser()
        return p if p.is_dir() else None
    cands: list[Path] = []
    if sys.platform == "win32" and os.environ.get("LOCALAPPDATA"):
        cands.append(Path(os.environ["LOCALAPPDATA"]) / _REL)
    if journal_dir:
        # .../users/<name>/Saved Games/Frontier Developments/Elite Dangerous
        parts = Path(journal_dir).resolve().parts
        for i in range(len(parts) - 1, 0, -1):
            if parts[i].lower() == "saved games":
                user = Path(*parts[:i])
                cands += [user / "AppData" / "Local" / _REL,
                          user / "Local Settings" / "Application Data" / _REL]
                break
    home = Path.home()
    cands += [home / ".local/share/Steam/steamapps/compatdata/359320/pfx/drive_c/users/steamuser"
              / "AppData/Local" / _REL,
              home / ".steam/steam/steamapps/compatdata/359320/pfx/drive_c/users/steamuser"
              / "AppData/Local" / _REL]
    for c in cands:
        if c.is_dir():
            return c
    return None


def preset_names(folder: Path) -> list[str]:
    for name in ("StartPreset.4.start", "StartPreset.start"):
        p = folder / name
        try:
            lines = [ln.strip() for ln in p.read_text(encoding="utf-8-sig").splitlines()]
        except OSError:
            continue
        return [ln for ln in lines if ln]
    return []


def _version_key(path: Path) -> tuple:
    nums = re.findall(r"\.(\d+)", path.name[: -len(".binds")])
    return tuple(int(n) for n in nums)


def binds_file(folder: Path, preset: str) -> Path | None:
    files = [p for p in folder.glob(f"{glob_escape(preset)}*.binds")
             if p.name == f"{preset}.binds" or re.fullmatch(
                 re.escape(preset) + r"(\.\d+)+\.binds", p.name)]
    return max(files, key=_version_key) if files else None


def glob_escape(s: str) -> str:
    return re.sub(r"([*?\[])", r"[\1]", s)


def parse_slots(path: Path) -> dict[str, tuple[Slot, ...]]:
    """Every action in a .binds file, with its Primary and Secondary as set
    — an empty column left out."""
    out: dict[str, tuple[Slot, ...]] = {}
    root = ET.parse(path).getroot()
    for el in root:
        if el.find("Primary") is None and el.find("Secondary") is None:
            continue
        slots = []
        for name in ("Primary", "Secondary"):
            b = el.find(name)
            if b is None or not b.get("Key") or b.get("Device") in (None, "", "{NoDevice}"):
                continue
            mods = tuple((m.get("Device") or "", m.get("Key") or "")
                         for m in b.findall("Modifier") if m.get("Key"))
            slots.append(Slot(b.get("Device"), b.get("Key"), mods))
        out[el.tag] = tuple(slots)
    return out


def choose(slots) -> Binding | None:
    """What to press for an action: a keyboard binding in either column
    first, then a mouse button."""
    pressable = [b for b in (s.binding() for s in slots) if b is not None]
    return next((b for b in pressable if not b.mouse), None) or \
        next((b for b in pressable if b.mouse), None)


def parse(path: Path) -> dict[str, Binding | None]:
    """Every action in a .binds file: what EDLD would press, or None when
    it is bound only to a controller (or not at all)."""
    return {k: choose(v) for k, v in parse_slots(path).items()}


#: The actions EDLD presses, as the game's Controls page names them, so a
#: commander can find them there.
ACTION_NAMES = {
    "PrimaryFire": "Primary Fire", "SecondaryFire": "Secondary Fire",
    "CycleFireGroupNext": "Cycle Next Fire Group",
    "CycleFireGroupPrevious": "Cycle Previous Fire Group",
    "DeployHardpointToggle": "Deploy Hardpoints",
    "GalaxyMapOpen": "Open Galaxy Map", "SystemMapOpen": "Open System Map",
    "UI_Up": "UI Panel Up", "UI_Down": "UI Panel Down", "UI_Left": "UI Panel Left",
    "UI_Right": "UI Panel Right", "UI_Select": "UI Panel Select", "UI_Back": "UI Back",
    "LandingGearToggle": "Landing Gear", "ToggleCargoScoop": "Cargo Scoop",
    "ShipSpotLightToggle": "Ship Lights", "NightVisionToggle": "Night Vision",
    "ToggleButtonUpInput": "Silent Running", "DeployHeatSink": "Deploy Heat Sink",
    "FireChaffLauncher": "Deploy Chaff", "UseShieldCell": "Use Shield Cell",
    "ToggleFlightAssist": "Flight Assist", "UseBoostJuice": "Engine Boost",
    "Supercruise": "Supercruise", "HyperSuperCombination": "Frame Shift Drive",
    "TargetNextRouteSystem": "Target Next System in Route",
    "ResetPowerDistribution": "Reset Power Distribution",
    "IncreaseSystemsPower": "Divert Power to Systems",
    "IncreaseEnginesPower": "Divert Power to Engines",
    "IncreaseWeaponsPower": "Divert Power to Weapons",
    "ExplorationFSSEnter": "Enter FSS Mode", "PlayerHUDModeToggle": "Switch HUD Mode",
}


def action_name(action: str) -> str:
    """CycleFireGroupNext → Cycle Next Fire Group: the game's name where
    EDLD knows it, the binding's split into words otherwise."""
    if action in ACTION_NAMES:
        return ACTION_NAMES[action]
    return re.sub(r"(?<=[a-z])(?=[A-Z])", " ", action).replace("_", " ").strip()


def explain(action: str, slots) -> str:
    """Why an action cannot be pressed, and what would fix it."""
    name = action_name(action)
    if not slots:
        return f"{name} is not bound — give it a key or mouse button in the game's Controls"
    shown = " and ".join(s.text() for s in slots)
    if len(slots) < 2:
        return (f"{name} is bound only to {shown} — give it a key or mouse button in "
                "its empty column in the game's Controls")
    return (f"{name} is bound only to {shown} — replace one of them with a key or "
            "mouse button in the game's Controls")


class Bindings:
    """The bindings in use, re-read when the file changes."""

    def __init__(self) -> None:
        self._path: Path | None = None
        self._mtime = 0.0
        self._map: dict[str, Binding | None] = {}
        self._slots: dict[str, tuple[Slot, ...]] = {}
        self.problem = ""

    def load(self, journal_dir=None, override: str = "") -> bool:
        folder = bindings_dir(journal_dir, override)
        if folder is None:
            self.problem = "the game's Bindings folder was not found — set it under Automation"
            return False
        presets = preset_names(folder)
        if not presets:
            self.problem = f"no StartPreset file in {folder}"
            return False
        merged: dict[str, tuple[Slot, ...]] = {}
        missing = []
        newest = 0.0
        # One preset per category; the ship's (the second line) is the one
        # that matters, so it is read last and its bindings win.
        ship = presets[1] if len(presets) > 1 else presets[0]
        order = [p for p in dict.fromkeys(presets) if p != ship] + [ship]
        for name in order:
            f = binds_file(folder, name)
            if f is None:
                missing.append(name)
                continue
            newest = max(newest, f.stat().st_mtime)
            # The ship's preset wins where it can be pressed; otherwise a
            # category whose binding can be pressed is kept, and failing that
            # whichever says what the action is bound to.
            for k, v in parse_slots(f).items():
                old = merged.get(k)
                if old is None or choose(v) is not None or (choose(old) is None and v):
                    merged[k] = v
        if not merged:
            self.problem = (f"preset {', '.join(missing)} is one of the game's own — save a "
                            "custom copy in Options → Controls so EDLD can read it")
            return False
        self._slots = merged
        self._map = {k: choose(v) for k, v in merged.items()}
        self._mtime, self._path, self.problem = newest, folder, ""
        return True

    def get(self, action: str) -> Binding | None:
        return self._map.get(action)

    def known(self, action: str) -> bool:
        return action in self._map

    def slots(self, action: str) -> tuple[Slot, ...]:
        """What the action is bound to, column by column."""
        return self._slots.get(action, ())

    def describe(self, action: str) -> str:
        """What it is bound to, as the Controls page shows it."""
        return " · ".join(s.text() for s in self.slots(action)) or "not bound"

    def why(self, action: str) -> str:
        """Why an action cannot be pressed — or "" when it can."""
        if self.get(action) is not None:
            return ""
        if not self._slots and self.problem:
            return self.problem
        return explain(action, self.slots(action))

    @property
    def folder(self) -> Path | None:
        return self._path
