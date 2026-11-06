"""
core/helm.py — the Helm panel: the game's controls and EDLD's automation, in
one place.

What used to be EDAM's control rail, beside EDCARS in landscape and a page of
its own in portrait, is a panel every interface draws: a section of EDCARS's
rail, a strip along the foot of the Dashboard on the desktop and in the
terminal, and on EDAM a section or a page. It presses the game's keys through
the commander's own bindings (core/automation.py, core/binds.py, core/keys.py)
and only while the game has the focus.

Everything the front ends must agree on is here, so they cannot drift:

* the panel's name — ``HELM_NAME``, the only place it is spelled;
* the controls, each in the group it belongs to, in the order they are drawn:
  the two automata EDLD runs itself first, then the game's own controls by
  what they are for — flight, the ship, combat, power and panels;
* what a front end is told to draw (``view``), and what a device is sent
  (``wire_groups``).

A control is either one of the game's bindings, pressed once, or a sequence
EDLD runs: ``honk`` holds the discovery scanner in its fire group, as Auto
honk does on arrival, and ``nextstop`` plots the galaxy map to the next stop
of a route EDLD plotted, as it does after a supercharge.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

#: The panel's display name. The one place it is written: the interfaces, the
#: wire and Options take it from here.
HELM_NAME = "Helm"

#: Its section in EDCARS (core/edcars.py) and on EDAM.
HELM_SECTION = "helm"

#: Sequences EDLD runs, rather than one binding pressed.
HONK = "honk"
NEXT_STOP = "nextstop"


@dataclass(frozen=True)
class Control:
    """One button. ``binding`` is the game's action it presses, "" for a
    sequence; ``tip`` says what it does where the label alone does not."""
    id: str
    label: str
    group: str
    binding: str = ""
    tip: str = ""

    @property
    def sequence(self) -> bool:
        return not self.binding


#: (id, label) of each group, in the order they are drawn.
GROUPS: tuple[tuple[str, str], ...] = (
    ("automation", "Automation"),
    ("flight", "Flight"),
    ("ship", "Ship"),
    ("combat", "Combat"),
    ("power", "Power"),
    ("panels", "Panels"),
)

CONTROLS: tuple[Control, ...] = (
    # EDLD's own sequences: what auto honk and the next stop do on their own,
    # on demand.
    Control(HONK, "Honk", "automation",
            tip="Hold the discovery scanner in its fire group (in flight)"),
    Control(NEXT_STOP, "Next stop", "automation",
            tip="Plot the galaxy map to the next stop of the route EDLD plotted"),
    # Flight: leaving, travelling, and the route.
    Control("supercruise", "Supercruise", "flight", "Supercruise"),
    Control("jump", "Jump", "flight", "HyperSuperCombination"),
    Control("nextroute", "Next system", "flight", "TargetNextRouteSystem",
            tip="Target the next system in the route"),
    Control("boost", "Boost", "flight", "UseBoostJuice"),
    Control("fa", "Flight assist", "flight", "ToggleFlightAssist"),
    # The ship: what opens, closes and lights.
    Control("gear", "Landing gear", "ship", "LandingGearToggle"),
    Control("scoop", "Cargo scoop", "ship", "ToggleCargoScoop"),
    Control("lights", "Lights", "ship", "ShipSpotLightToggle"),
    Control("nightvision", "Night vision", "ship", "NightVisionToggle"),
    # Combat: weapons out, then what keeps the ship alive.
    Control("hardpoints", "Hardpoints", "combat", "DeployHardpointToggle"),
    Control("heatsink", "Heat sink", "combat", "DeployHeatSink"),
    Control("chaff", "Chaff", "combat", "FireChaffLauncher"),
    Control("shieldcell", "Shield cell", "combat", "UseShieldCell"),
    Control("silent", "Silent running", "combat", "ToggleButtonUpInput"),
    # Power: the pips, in the order the game's power distributor shows them.
    Control("pips-sys", "SYS", "power", "IncreaseSystemsPower",
            tip="One pip to systems"),
    Control("pips-eng", "ENG", "power", "IncreaseEnginesPower",
            tip="One pip to engines"),
    Control("pips-wep", "WEP", "power", "IncreaseWeaponsPower",
            tip="One pip to weapons"),
    Control("pips-reset", "Reset pips", "power", "ResetPowerDistribution"),
    # Panels and maps.
    Control("galmap", "Galaxy map", "panels", "GalaxyMapOpen"),
    Control("sysmap", "System map", "panels", "SystemMapOpen"),
    Control("fss", "FSS", "panels", "ExplorationFSSEnter",
            tip="Full Spectrum System scanner"),
    Control("hudmode", "HUD mode", "panels", "PlayerHUDModeToggle",
            tip="Combat and analysis modes"),
)

BY_ID: dict[str, Control] = {c.id: c for c in CONTROLS}


def group_label(gid: str) -> str:
    return dict(GROUPS).get(gid, gid.replace("_", " ").title())


def panel_wanted(ui_cfg: Optional[dict]) -> bool:
    """``[UI] HelmPanel``: whether the Dashboard layouts show the panel while
    automation is on. On unless turned off."""
    raw = (ui_cfg or {}).get("HelmPanel", True)
    if isinstance(raw, str):
        return raw.strip().lower() not in ("false", "0", "no", "off")
    return bool(raw)


# ── What a front end draws ────────────────────────────────────────────────────

@dataclass
class Button:
    id: str
    label: str
    #: Can be pressed now: automation is on and the control is bound to a key
    #: or a mouse button.
    ready: bool
    #: Why not, or what it does — the button's tooltip.
    tip: str = ""


@dataclass
class Group:
    id: str
    label: str
    buttons: list[Button] = field(default_factory=list)


@dataclass
class View:
    """The panel, for a front end to draw as it likes.

    ``note`` is a line above the buttons when nothing can be pressed — why,
    and what to change. ``status`` is the outcome of the last press, or what
    the automation is set to do on its own. ``groups`` are in drawing order,
    each with its buttons in order; a group with no buttons is left out.
    """
    enabled: bool
    note: str = ""
    status: str = ""
    groups: list[Group] = field(default_factory=list)


def build_view(enabled: bool, bound, why_unbound, note: str = "",
               status: str = "") -> View:
    """The panel from what the automation knows: ``bound(control)`` whether
    a control can be pressed, ``why_unbound(control)`` why not."""
    groups: list[Group] = []
    for gid, label in GROUPS:
        g = Group(gid, label)
        for c in CONTROLS:
            if c.group != gid:
                continue
            ok = bool(bound(c))
            tip = c.tip if ok else (why_unbound(c) or c.tip)
            g.buttons.append(Button(c.id, c.label, enabled and ok, tip))
        if g.buttons:
            groups.append(g)
    return View(enabled, note, status, groups)


def columns_for(width: float, min_width: float, groups: int) -> int:
    """How many groups side by side make the best use of ``width``: as many
    as fit at ``min_width`` each, never more than there are groups. The
    desktop window, the terminal and EDAM size the panel the same way."""
    if min_width <= 0:
        return max(1, groups)
    return max(1, min(groups, int(width // min_width)))


def wire_groups() -> list[dict]:
    """The groups as a device is sent them, in drawing order, so EDAM labels
    and orders the buttons it is sent as the desktop does."""
    return [{"id": gid, "label": label} for gid, label in GROUPS]
