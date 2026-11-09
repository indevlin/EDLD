"""core/automation.py — short key sequences, pressed only while it is safe.

``honk``   hold the discovery scanner's trigger in its fire group.
``plot``   type a system into the galaxy map and plot to it, by a short
           script the commander can change (the map's layout has changed
           between game versions), then check the plotted route really
           ends there.
``press``  one binding, for the Helm panel (core/helm.py).
"""
from __future__ import annotations

import json
import threading
import time
from pathlib import Path

from core.binds import Bindings
from core.keys import Keyboard, game_focused, pointer_in_game, typeable

FLAG_DOCKED = 0x1
FLAG_LANDED = 0x2
FLAG_SUPERCRUISE = 0x10
FLAG_FSD_CHARGING = 0x20000
FLAG_IN_DANGER = 0x400000
FLAG_INTERDICTED = 0x800000
FLAG_FSD_JUMP = 0x40000000
FLAG_IN_MAIN_SHIP = 0x01000000
FLAG_IN_FIGHTER = 0x02000000
FLAG_IN_SRV = 0x04000000
FLAG2_ON_FOOT = 0x1

GUI_NONE, GUI_GALAXY_MAP = 0, 6

#: The galaxy-map sequence: actions (a binding), ``Key_*`` (a raw key),
#: ``Action*1.5`` (held that long), ``wait 1.5``, ``focus 6`` (wait for that
#: GuiFocus), ``type`` (the system name), ``route 8`` (wait for the route to
#: end at the system). Separated by semicolons.
DEFAULT_PLOT_SCRIPT = ("GalaxyMapOpen; focus 6; wait 1.5; UI_Up; UI_Select; wait 0.5; type; "
                       "Key_Enter; wait 2.5; UI_Right; UI_Select*1.5; route 8; GalaxyMapOpen")

#: The bindings the Helm panel may press: id → (binding, label, group), from
#: core/helm.py. Nothing outside it can be pressed from a device or a button.
from core.helm import CONTROLS as _HELM_CONTROLS  # noqa: E402

CONTROLS: dict[str, tuple[str, str, str]] = {
    c.id: (c.binding, c.label, c.group) for c in _HELM_CONTROLS if c.binding
}


def script_actions(script: str) -> list[str]:
    """The bindings a galaxy-map sequence presses, in order, once each."""
    out: list[str] = []
    for step in [x.strip() for x in script.split(";") if x.strip()]:
        word = step.partition(" ")[0]
        if word in ("wait", "focus", "type", "route") or word.startswith("Key_"):
            continue
        action = word.partition("*")[0]
        if action and action not in out:
            out.append(action)
    return out


class Aborted(Exception):
    pass


def read_status(journal_dir) -> dict:
    try:
        raw = (Path(journal_dir) / "Status.json").read_text(encoding="utf-8").strip()
        return json.loads(raw) if raw else {}
    except (OSError, ValueError, TypeError):
        return {}


def read_navroute_end(journal_dir) -> str:
    try:
        doc = json.loads((Path(journal_dir) / "NavRoute.json").read_text(encoding="utf-8"))
        route = doc.get("Route") or []
        return str(route[-1].get("StarSystem") or "") if route else ""
    except (OSError, ValueError, TypeError, AttributeError):
        return ""


class Automation:
    """One sequence at a time, against one keyboard and one set of bindings."""

    def __init__(self, journal_dir, keyboard: Keyboard, bindings: Bindings,
                 assume_focus: bool = False, log=None) -> None:
        self.journal_dir = journal_dir
        self.kb = keyboard
        self.binds = bindings
        self.assume_focus = assume_focus
        self._busy = threading.Lock()
        self._log = log or (lambda m: None)

    # ── checks ───────────────────────────────────────────────────────────────

    def status(self) -> dict:
        return read_status(self.journal_dir)

    def _check(self, *, gui: int | None = GUI_NONE, need_flags: int = 0,
               bad_flags: int = FLAG_IN_DANGER | FLAG_INTERDICTED) -> dict:
        ok, why = game_focused(self.assume_focus)
        if not ok:
            raise Aborted(why)
        st = self.status()
        if not st:
            raise Aborted("the game's Status.json is not readable")
        flags = int(st.get("Flags") or 0)
        if need_flags and (flags & need_flags) != need_flags:
            raise Aborted("the ship is no longer where the sequence began")
        if flags & bad_flags & FLAG_SUPERCRUISE:
            raise Aborted("the ship went into supercruise")
        if flags & bad_flags:
            raise Aborted("the ship is in danger")
        if gui is not None and int(st.get("GuiFocus") or 0) != gui:
            raise Aborted("a panel or map is open")
        return st

    def _press(self, action: str, hold: float = 0.06) -> None:
        b = self.binds.get(action)
        if b is None:
            raise Aborted(self.binds.why(action))
        if b.mouse:
            ok, why = pointer_in_game(self.assume_focus)
            if not ok:
                raise Aborted(why)
        if not self.kb.press(b.key, b.modifiers, hold=hold):
            raise Aborted(f"could not press {b.text()}")

    def _run(self, fn, *args) -> tuple[bool, str]:
        if not self._busy.acquire(blocking=False):
            return False, "another sequence is running"
        try:
            ok, why = self.kb.available()
            if not ok:
                return False, why
            return True, fn(*args) or ""
        except Aborted as exc:
            return False, str(exc)
        except Exception as exc:
            return False, f"{type(exc).__name__}: {exc}"
        finally:
            self._busy.release()

    # ── sequences ────────────────────────────────────────────────────────────

    def press(self, control_id: str) -> tuple[bool, str]:
        if control_id not in CONTROLS:
            return False, "not a control"
        action = CONTROLS[control_id][0]

        def _do():
            self._check(gui=None, bad_flags=0)
            self._press(action)
        return self._run(_do)

    @staticmethod
    def honk_blocked(st: dict, anywhere: bool = False) -> str:
        """Why the discovery scanner cannot be fired now, or "" when it can.

        Auto honk (``anywhere`` False) waits for supercruise, where it always
        is just after a jump.
        """
        if not st:
            return "the game's Status.json is not readable"
        flags = int(st.get("Flags") or 0)
        flags2 = int(st.get("Flags2") or 0)
        if flags2 & FLAG2_ON_FOOT:
            return "you are on foot"
        if flags & FLAG_IN_SRV:
            return "you are in the SRV"
        if flags & FLAG_IN_FIGHTER:
            return "you are in a fighter"
        if not flags & FLAG_IN_MAIN_SHIP:
            return "you are not flying the ship (at the main menu, or in a crew's ship)"
        if flags & FLAG_DOCKED:
            return "the ship is docked"
        if flags & FLAG_LANDED:
            return "the ship is landed"
        if flags & (FLAG_FSD_CHARGING | FLAG_FSD_JUMP):
            return "the frame shift drive is charging or jumping"
        if not anywhere and not flags & FLAG_SUPERCRUISE:
            return "the ship is not in supercruise"
        return ""

    def honk(self, trigger: str = "PrimaryFire", fire_group: int = 0,
             hold: float = 6.5, anywhere: bool = False) -> tuple[bool, str]:
        """Hold ``trigger`` in fire group ``fire_group`` (1-based; 0 = the
        one selected), then put the fire group back.

        ``anywhere``: in normal space as well as supercruise, for a honk
        asked for from the Helm panel.
        """
        def _do():
            st = self._check(gui=None, bad_flags=0)
            why = self.honk_blocked(st, anywhere)
            if why:
                raise Aborted(why)
            self._check()                       # danger, interdiction, a panel open
            in_sc = bool(int(st.get("Flags") or 0) & FLAG_SUPERCRUISE)
            keep = ({"need_flags": FLAG_SUPERCRUISE} if in_sc else
                    {"bad_flags": FLAG_IN_DANGER | FLAG_INTERDICTED | FLAG_SUPERCRUISE})
            start = int(st.get("FireGroup") or 0)
            want = fire_group - 1 if fire_group > 0 else start
            moved = self._select_group(want, start, keep)
            try:
                self._check(**keep)
                self._press(trigger, hold=hold)
            finally:
                if moved:
                    try:
                        self._select_group(start, want, keep)
                    except Aborted:
                        pass
            return "honked"
        return self._run(_do)

    def _select_group(self, want: int, have: int, keep: dict | None = None) -> bool:
        if want == have:
            return False
        keep = keep if keep is not None else {"need_flags": FLAG_SUPERCRUISE}
        for _ in range(8):
            st = self._check(**keep)
            have = int(st.get("FireGroup") or 0)
            if have == want:
                return True
            self._press("CycleFireGroupNext")
            time.sleep(0.6)
        raise Aborted("could not select the discovery scanner's fire group")

    def plot(self, system: str, script: str = DEFAULT_PLOT_SCRIPT) -> tuple[bool, str]:
        if not system or not typeable(system):
            return False, f"cannot type {system!r}"

        def _do():
            self._check()
            in_map = False
            try:
                for step in [s.strip() for s in script.split(";") if s.strip()]:
                    word, _, arg = step.partition(" ")
                    if word == "wait":
                        time.sleep(float(arg or 1))
                        continue
                    if word == "focus":
                        self._wait_focus(int(arg or GUI_GALAXY_MAP))
                        in_map = True
                        continue
                    if word == "type":
                        self._check(gui=GUI_GALAXY_MAP if in_map else None)
                        if not self.kb.type_text(system):
                            raise Aborted("could not type the system")
                        continue
                    if word == "route":
                        if not self._wait_route(system, float(arg or 8)):
                            raise Aborted(f"the route did not end at {system}")
                        continue
                    action, _, held = word.partition("*")
                    self._check(gui=GUI_GALAXY_MAP if in_map else None)
                    if action == "GalaxyMapOpen" and in_map:
                        in_map = False
                    hold = float(held) if held else 0.06
                    if action.startswith("Key_"):
                        if not self.kb.press(action, (), hold=hold):
                            raise Aborted(f"could not press {action}")
                    else:
                        self._press(action, hold=hold)
            except Aborted:
                if in_map:
                    try:
                        self._press("GalaxyMapOpen")
                    except Aborted:
                        pass
                raise
            return f"plotted to {system}"
        return self._run(_do)

    def _wait_focus(self, gui: int, timeout: float = 6.0) -> None:
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            if int(self.status().get("GuiFocus") or 0) == gui:
                return
            time.sleep(0.25)
        raise Aborted("the map did not open")

    def _wait_route(self, system: str, timeout: float) -> bool:
        target = system.strip().lower()
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            dest = (self.status().get("Destination") or {}).get("Name") or ""
            if str(dest).strip().lower() == target or \
                    read_navroute_end(self.journal_dir).strip().lower() == target:
                return True
            time.sleep(0.3)
        return False
