"""
components/automation.py — auto honk, the next route system after a
supercharge, and the Helm panel's keys.

Everything here presses the game's own keys (core/keys.py) through the
commander's own bindings (core/binds.py), and only while the game has the
focus and nothing has changed under the sequence (core/automation.py). All of
it is off until turned on.

Auto honk       On arriving in a system this commander has never honked or
                mapped, hold the discovery scanner's trigger once the ship is
                in supercruise with no panel open. Not in a fight; not if the
                commander honks first.
Next waypoint   On a route EDLD plotted with stops several jumps apart (a
                neutron route), after a supercharge at a neutron star or white
                dwarf, plot the galaxy map to the next stop.
Helm panel      The buttons every interface draws (core/helm.py): the two
                above on demand, and the game's controls bound to a key or a
                mouse button. From EDLD's own window a press first brings the
                game to the front; from a paired device only when "Allow
                paired devices to press keys" is on as well.
"""
from __future__ import annotations

import threading
import time

from core import callout
from core.plugin_loader import BasePlugin
from core.settings_spec import Action, Heading, Setting, SettingsSpecMixin

#: Seconds after an arrival before honking: the arrival star's scan and the
#: drop from the jump tunnel into supercruise come first.
_HONK_DELAY_S = 4.0
#: Seconds after a supercharge before plotting: the boost's own effects end.
_PLOT_DELAY_S = 3.0


class AutomationPlugin(SettingsSpecMixin, BasePlugin):
    PLUGIN_NAME = "automation"
    PLUGIN_DISPLAY = "Automation"
    PLUGIN_VERSION = "1.0.0"
    PLUGIN_DESCRIPTION = ("Auto honk, plotting the next route stop after a supercharge, "
                          "and the keys the Helm panel presses.")
    SUBSCRIBED_EVENTS = ["FSDJump", "FSSDiscoveryScan", "JetConeBoost", "StartJump",
                         "Shutdown"]

    SETTINGS_SECTION = "Automation"
    SETTINGS_TAB = ("pref-tab-automation", "Automation")
    SETTINGS = (
        Heading("Automation",
                "Presses the game's keys, through your own bindings, only while the game has "
                "the focus. See docs/AUTOMATION.md."),
        Setting("Enabled", "Allow EDLD to press keys", bool, False),
        Setting("AssumeFocus", "Assume the game has the focus (desktops that cannot say)",
                bool, False),
        Setting("BindingsDir", "Bindings folder (empty: found from the journal folder)", str, ""),
        Action("check-binds", "Check bindings"),
        Heading("Auto honk", "Only in systems you have never honked or mapped."),
        Setting("AutoHonk", "Honk on arrival", bool, False),
        Setting("HonkTrigger", "Discovery scanner trigger", "choice", "PrimaryFire",
                choices=(("PrimaryFire", "Primary fire"), ("SecondaryFire", "Secondary fire"))),
        Setting("HonkFireGroup", "Its fire group (1-8; 0: the one selected)", int, 0),
        Heading("Neutron routes"),
        Setting("AutoTarget", "Plot to the next stop after a supercharge", bool, False),
        Setting("PlotScript", "Galaxy-map sequence", str, ""),
        Heading("Helm panel", "Buttons for the game's controls and these automata, "
                "in every interface."),
        Setting("AllowControl", "Allow paired devices to press keys (EDAM's Helm)", bool, False),
    )

    def on_load(self, core) -> None:
        super().on_load(core)
        from core.binds import Bindings
        self.bindings = Bindings()
        self._auto = None
        self._honked_here = False
        self._arrival_seq = 0
        self._binds_loaded_at = 0.0
        #: What the last press from the Helm panel came to, for its status line.
        self.last_result = ""
        self._pressing = False

    # ── the engine ───────────────────────────────────────────────────────────

    def _engine(self):
        from core import automation as A
        from core.keys import keyboard
        cfg = self.settings()
        if time.monotonic() - self._binds_loaded_at > 30 or not self.bindings.folder:
            self.bindings.load(self.core.journal_dir, cfg.get("BindingsDir", ""))
            self._binds_loaded_at = time.monotonic()
        if self._auto is None:
            self._auto = A.Automation(self.core.journal_dir, keyboard(), self.bindings)
        self._auto.assume_focus = bool(cfg.get("AssumeFocus"))
        return self._auto

    def _say(self, text: str, warn: bool = False) -> None:
        callout.say(self.core, "Automation", "🤖", text,
                    sigil="!  AUTO" if warn else "-  AUTO")

    # ── events ───────────────────────────────────────────────────────────────

    def on_event(self, event: dict, state) -> None:
        ev = event.get("event")
        if getattr(state, "in_preload", False):
            return
        cfg = self.settings()
        if not cfg.get("Enabled"):
            return
        if ev == "FSDJump":
            self._honked_here = False
            self._arrival_seq += 1
            if cfg.get("AutoHonk") and self._never_honked(event):
                threading.Thread(target=self._honk_later, args=(self._arrival_seq,),
                                 daemon=True, name="auto-honk").start()
        elif ev == "FSSDiscoveryScan":
            self._honked_here = True
        elif ev == "StartJump":
            self._arrival_seq += 1          # leaving: cancel anything pending
        elif ev == "JetConeBoost" and cfg.get("AutoTarget"):
            threading.Thread(target=self._target_later, args=(self._arrival_seq,),
                             daemon=True, name="auto-target").start()
        elif ev == "Shutdown":
            from core.keys import keyboard
            keyboard().close()

    def _never_honked(self, event: dict) -> bool:
        """Neither honked nor mapped by this commander, by the body database."""
        try:
            from core.bodies_db import get_db
            address = int(event.get("SystemAddress") or 0)
            cid = self.core.plugin_call("explo_sync", "current_commander_id")
            if not address or not cid:
                return False
            db = get_db()
            sid = db.system_id_by_address(address)
            if not sid:
                return True
            row = db._c.execute(
                "SELECT honked, fully_mapped FROM system_status WHERE system_id=? "
                "AND commander_id=?", (sid, cid)).fetchone()
            return not (row and (row["honked"] or row["fully_mapped"]))
        except Exception:
            return False

    def _honk_later(self, seq: int) -> None:
        time.sleep(_HONK_DELAY_S)
        # Up to a minute for the commander to settle in supercruise with
        # nothing open.
        from core import automation as A
        end = time.monotonic() + 60
        eng = self._engine()
        while time.monotonic() < end:
            if seq != self._arrival_seq or self._honked_here:
                return
            st = eng.status()
            flags = int(st.get("Flags") or 0)
            if (flags & A.FLAG_SUPERCRUISE and not flags & (A.FLAG_FSD_CHARGING | A.FLAG_FSD_JUMP)
                    and int(st.get("GuiFocus") or 0) == A.GUI_NONE):
                break
            time.sleep(1.0)
        else:
            return
        cfg = self.settings()
        ok, why = eng.honk(str(cfg.get("HonkTrigger") or "PrimaryFire"),
                           max(0, min(8, int(cfg.get("HonkFireGroup") or 0))))
        if not ok:
            self._say(f"Auto honk skipped: {why}", warn=True)

    def _target_later(self, seq: int) -> None:
        time.sleep(_PLOT_DELAY_S)
        if seq != self._arrival_seq:
            return
        nav = self.core._plugins.get("navigation")
        if nav is None:
            return
        route, source = nav.active_route()
        if source != "edld" or not route:
            return
        # Only where stops are several jumps apart: on a jump-by-jump route
        # the game's own route already goes to the next stop.
        if not any(int((e.get("EDLD") or {}).get("jumps") or 1) > 1 for e in route):
            return
        system, why = nav.next_system()
        if not system:
            return
        from core import automation as A
        if A.read_navroute_end(self.core.journal_dir).strip().lower() == system.lower():
            return
        ok, why = self._plot_to(system)
        self._say(f"Plotted to {system}" if ok else f"Could not plot to {system}: {why}",
                  warn=not ok)

    def _plot_to(self, system: str) -> tuple[bool, str]:
        from core import automation as A
        script = str(self.settings().get("PlotScript") or "").strip() or A.DEFAULT_PLOT_SCRIPT
        return self._engine().plot(system, script)

    def _honk_now(self) -> tuple[bool, str]:
        cfg = self.settings()
        return self._engine().honk(str(cfg.get("HonkTrigger") or "PrimaryFire"),
                                   max(0, min(8, int(cfg.get("HonkFireGroup") or 0))),
                                   anywhere=True)

    def _next_stop_now(self) -> tuple[bool, str]:
        nav = (getattr(self.core, "_plugins", None) or {}).get("navigation")
        if nav is None:
            return False, "the Navigation component is not loaded"
        route, source = nav.active_route()
        if source != "edld" or not route:
            return False, "EDLD has no route plotted (Navigation → Neutron or Exact)"
        system, why = nav.next_system()
        if not system:
            return False, why or "the route has no next stop"
        return self._plot_to(system)

    # ── the Helm panel ───────────────────────────────────────────────────────

    def _bound(self, control) -> bool:
        """Whether a Helm control can be pressed: its binding, or every
        binding its sequence needs, is a key or a mouse button."""
        from core import automation as A
        from core import helm as H
        if control.binding:
            return self.bindings.get(control.binding) is not None
        cfg = self.settings()
        if control.id == H.HONK:
            need = [str(cfg.get("HonkTrigger") or "PrimaryFire")]
            if int(cfg.get("HonkFireGroup") or 0) > 0:
                need.append("CycleFireGroupNext")
        elif control.id == H.NEXT_STOP:
            script = str(cfg.get("PlotScript") or "").strip() or A.DEFAULT_PLOT_SCRIPT
            need = A.script_actions(script)
        else:
            return False
        return all(self.bindings.get(a) is not None for a in need)

    def _why_unbound(self, control) -> str:
        from core import automation as A
        from core import helm as H
        if control.binding:
            return self.bindings.why(control.binding)
        cfg = self.settings()
        if control.id == H.HONK:
            need = [str(cfg.get("HonkTrigger") or "PrimaryFire"), "CycleFireGroupNext"]
        else:
            script = str(cfg.get("PlotScript") or "").strip() or A.DEFAULT_PLOT_SCRIPT
            need = A.script_actions(script)
        missing = [a for a in need if self.bindings.get(a) is None]
        return self.bindings.why(missing[0]) if missing else ""

    def helm_view(self):
        """The Helm panel for EDLD's own interfaces (core/helm.View): every
        control, those that cannot be pressed greyed with the reason."""
        from core import helm as H
        cfg = self.settings()
        enabled = bool(cfg.get("Enabled"))
        if enabled:
            self._engine()
            note = "" if self.bindings.folder else (self.bindings.problem or
                                                     "the game's bindings were not found")
        else:
            note = "Automation is off. Options → Automation turns it on."
        auto = [label for key, label in (("AutoHonk", "auto honk"),
                                         ("AutoTarget", "next stop after a supercharge"))
                if cfg.get(key)]
        status = ("Pressing…" if self._pressing else self.last_result or
                  (("On its own: " + " and ".join(auto) + ".") if enabled and auto else ""))
        return H.build_view(enabled, self._bound, self._why_unbound, note, status)

    def controls(self) -> list[dict]:
        """The controls a paired device may press right now: those allowed
        and bound to a key or a mouse button, in the panel's order."""
        cfg = self.settings()
        if not (cfg.get("Enabled") and cfg.get("AllowControl")):
            return []
        from core import helm as H
        self._engine()
        return [{"id": c.id, "label": c.label, "group": c.group}
                for c in H.CONTROLS if self._bound(c)]

    def controls_note(self) -> str:
        """Why a device has nothing to press, for its Helm section; "" when
        it has."""
        cfg = self.settings()
        if not cfg.get("Enabled"):
            return "Automation is off in EDLD (Options → Automation)."
        if not cfg.get("AllowControl"):
            return ("EDLD does not let paired devices press keys: turn on \"Allow paired "
                    "devices to press keys\" in Options → Automation.")
        if not self.controls():
            return ("None of the game's controls is bound to a key or a mouse button "
                    "EDLD can press (Options → Automation → Check bindings).")
        return ""

    def press_control(self, control_id: str, here: bool = False) -> tuple[bool, str]:
        """Press one Helm control: from a paired device, or ``here`` — a
        button in EDLD's own window — which first brings the game to the
        front, the click having just taken the focus from it."""
        from core import helm as H
        control = H.BY_ID.get(control_id)
        if control is None:
            return False, "not a control"
        cfg = self.settings()
        if not cfg.get("Enabled"):
            return False, "automation is off"
        if not here and not cfg.get("AllowControl"):
            return False, "not available"
        self._engine()
        if not self._bound(control):
            return False, self._why_unbound(control) or "not available"
        if here:
            from core.keys import focus_game
            ok, why = focus_game()
            if not ok:
                return False, why
        if control.id == H.HONK:
            return self._honk_now()
        if control.id == H.NEXT_STOP:
            return self._next_stop_now()
        return self._engine().press(control_id)

    def press_here(self, control_id: str) -> None:
        """A Helm button in EDLD's own window: pressed on a thread of its
        own — a honk holds the trigger for seconds — with the outcome on the
        panel's status line."""
        from core import helm as H
        control = H.BY_ID.get(control_id)
        label = control.label if control else control_id

        def _run():
            try:
                ok, why = self.press_control(control_id, here=True)
            except Exception as exc:
                ok, why = False, f"{type(exc).__name__}: {exc}"
            self._pressing = False
            if ok:
                # A sequence says what it did ("honked", "plotted to Sol").
                self.last_result = (why[:1].upper() + why[1:] + "." if why
                                    else f"Pressed {label}.")
            else:
                self.last_result = f"{label} not pressed: {why}"
            self._refresh_helm()

        self._pressing = True
        self._refresh_helm()
        threading.Thread(target=_run, daemon=True, name="helm-press").start()

    def _refresh_helm(self) -> None:
        gq = getattr(self.core, "gui_queue", None)
        if gq is not None:
            gq.put(("helm_update", None))

    # ── options ──────────────────────────────────────────────────────────────

    def settings_action(self, action_id: str) -> str:
        if action_id != "check-binds":
            return ""
        return self.binding_report()

    def binding_report(self) -> str:
        """What each sequence presses, what it is bound to, and whether EDLD
        can press it — so a binding EDLD cannot use is found here rather
        than halfway through a jump."""
        from core import automation as A
        from core.binds import action_name
        cfg = self.settings()
        if not self.bindings.load(self.core.journal_dir, cfg.get("BindingsDir", "")):
            return self.bindings.problem
        self._binds_loaded_at = time.monotonic()
        from core.keys import keyboard
        ok, why = keyboard().available()
        lines = [f"Read {self.bindings.folder}", "Keys: ready" if ok else f"Keys: {why}"]

        def line(action: str) -> str:
            b = self.bindings.get(action)
            if b is None:
                return f"  ✗ {self.bindings.why(action)}"
            text = f"  ✓ {action_name(action)}: {b.text()}"
            if b.mouse:
                text += " — pressed only while the pointer is over the game"
            return text

        trigger = str(cfg.get("HonkTrigger") or "PrimaryFire")
        lines.append("Auto honk")
        lines.append(line(trigger))
        if int(cfg.get("HonkFireGroup") or 0) > 0:
            lines.append(line("CycleFireGroupNext"))
        else:
            lines.append("  · Cycle Next Fire Group: not needed — honks in the fire group selected")
        script = str(cfg.get("PlotScript") or "").strip() or A.DEFAULT_PLOT_SCRIPT
        lines.append("Next route stop")
        lines += [line(a) for a in A.script_actions(script)]
        rail_ok = [label for action, label, _g in A.CONTROLS.values()
                   if self.bindings.get(action) is not None]
        lines.append(f"Helm panel: {len(rail_ok)} of {len(A.CONTROLS)} controls can be pressed")
        lines += [line(action) for action, _l, _g in A.CONTROLS.values()
                  if self.bindings.get(action) is None]
        return "\n".join(lines)
