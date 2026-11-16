"""core/helm.py — the Helm panel: the game's controls and EDLD's automation, in
one place.

* the panel's name — ``HELM_NAME``, the only place it is spelled;
* the controls, each in the group it belongs to, in the order they are drawn:
  the two automata EDLD runs itself first, then the game's own controls by
  what they are for; each for the contexts its binding works in — the ship,
  a ship-launched fighter, an SRV, on foot — and only the current one's
  drawn;
* what a front end is told to draw (``view``), and what a device is sent
  (``wire_groups``).
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


#: Where the commander is, as the panel knows it: (id, label). Each control
#: belongs to the contexts its binding works in; the panel shows only the
#: current one's.
SHIP, FIGHTER, SRV, FOOT = "ship", "fighter", "srv", "foot"
CONTEXTS: tuple[tuple[str, str], ...] = (
    (SHIP, "Ship"), (FIGHTER, "Fighter"), (SRV, "SRV"), (FOOT, "On foot"),
)

_S, _F, _V, _O = (SHIP,), (FIGHTER,), (SRV,), (FOOT,)
_SF = (SHIP, FIGHTER)


@dataclass(frozen=True)
class Control:
    """One button. ``binding`` is the game's action it presses, "" for a
    sequence; ``tip`` says what it does where the label alone does not;
    ``contexts`` are where the binding works."""
    id: str
    label: str
    group: str
    binding: str = ""
    tip: str = ""
    contexts: tuple[str, ...] = _S

    @property
    def sequence(self) -> bool:
        return not self.binding


#: (id, label) of each group, in the order they are drawn.
GROUPS: tuple[tuple[str, str], ...] = (
    ("automation", "Automation"),
    ("flight", "Flight"),
    ("throttle", "Throttle"),
    ("ship", "Ship"),
    ("vehicle", "Vehicle"),
    ("suit", "Suit"),
    ("tools", "Tools"),
    ("weapons", "Weapons"),
    ("grenades", "Grenades"),
    ("targeting", "Targeting"),
    ("combat", "Combat"),
    ("orders", "Fighter orders"),
    ("power", "Power"),
    ("panels", "Panels"),
)

#: A group's name where it differs by context: (group, context) → label.
_GROUP_LABELS = {("ship", FIGHTER): "Fighter", ("orders", FIGHTER): "Orders"}

CONTROLS: tuple[Control, ...] = (
    # EDLD's own sequences: what auto honk and the next stop do on their own,
    # on demand. Both press the ship's bindings.
    Control(HONK, "Honk", "automation",
            tip="Hold the discovery scanner in its fire group (in flight)"),
    Control(NEXT_STOP, "Next stop", "automation",
            tip="Plot the galaxy map to the next stop of the route EDLD plotted"),
    # Flight: leaving, traveling, and the route.
    Control("supercruise", "Supercruise", "flight", "Supercruise"),
    Control("jump", "Jump", "flight", "HyperSuperCombination"),
    Control("hyperspace", "Hyperspace", "flight", "Hyperspace",
            tip="Hyperspace jump only, never supercruise"),
    Control("nextroute", "Next system", "flight", "TargetNextRouteSystem",
            tip="Target the next system in the route"),
    Control("boost", "Boost", "flight", "UseBoostJuice", contexts=_SF),
    Control("fa", "Flight assist", "flight", "ToggleFlightAssist", contexts=_SF),
    Control("rotcorr", "Rotation correction", "flight", "DisableRotationCorrectToggle",
            tip="Rotational correction on or off"),
    # Throttle presets.
    Control("thr-0", "0%", "throttle", "SetSpeedZero", contexts=_SF),
    Control("thr-25", "25%", "throttle", "SetSpeed25", contexts=_SF),
    Control("thr-50", "50%", "throttle", "SetSpeed50", contexts=_SF),
    Control("thr-75", "75%", "throttle", "SetSpeed75", contexts=_SF),
    Control("thr-100", "100%", "throttle", "SetSpeed100", contexts=_SF),
    Control("thr-rev", "Reverse", "throttle", "ToggleReverseThrottleInput", contexts=_SF,
            tip="Throttle to reverse, or back"),
    # The ship: what opens, closes and lights.
    Control("gear", "Landing gear", "ship", "LandingGearToggle"),
    Control("scoop", "Cargo scoop", "ship", "ToggleCargoScoop"),
    Control("lights", "Lights", "ship", "ShipSpotLightToggle", contexts=_SF),
    Control("nightvision", "Night vision", "ship", "NightVisionToggle", contexts=_SF),
    Control("colonise", "Colonisation module", "ship", "TriggerColonisationModule",
            tip="Fire the colonisation module"),
    # The SRV: Scarab, Scorpion, Nomad and Rhino share the SRV's bindings.
    Control("srv-assist", "Drive assist", "vehicle", "ToggleDriveAssist", contexts=_V),
    Control("srv-brake", "Handbrake", "vehicle", "AutoBreakBuggyButton", contexts=_V),
    Control("srv-lights", "Headlights", "vehicle", "HeadlightsBuggyButton", contexts=_V),
    Control("srv-nightvision", "Night vision", "vehicle", "NightVisionToggle", contexts=_V),
    Control("srv-scoop", "Cargo scoop", "vehicle", "ToggleCargoScoop_Buggy", contexts=_V),
    Control("srv-turret", "Turret view", "vehicle", "ToggleBuggyTurretButton", contexts=_V,
            tip="Into the turret, or back to driving"),
    Control("srv-recall", "Recall ship", "vehicle", "RecallDismissShip", contexts=_V,
            tip="Call the ship down, or send it away"),
    # On foot: the suit, then what is in hand.
    Control("foot-light", "Flashlight", "suit", "HumanoidToggleFlashlightButton", contexts=_O),
    Control("foot-nightvision", "Night vision", "suit", "HumanoidToggleNightVisionButton",
            contexts=_O),
    Control("foot-shields", "Shields", "suit", "HumanoidToggleShieldsButton", contexts=_O),
    Control("foot-medkit", "Medkit", "suit", "HumanoidHealthPack", contexts=_O),
    Control("foot-cell", "Energy cell", "suit", "HumanoidBattery", contexts=_O),
    Control("foot-recall", "Recall ship", "suit", "RecallDismissShip", contexts=_O,
            tip="Call the ship down, or send it away"),
    Control("foot-energylink", "Energylink", "tools", "HumanoidSwitchToRechargeTool",
            contexts=_O),
    Control("foot-analyser", "Profile analyser", "tools", "HumanoidSwitchToCompAnalyser",
            contexts=_O),
    Control("foot-suittool", "Suit tool", "tools", "HumanoidSwitchToSuitTool", contexts=_O,
            tip="The suit's own tool: arc cutter or genetic sampler"),
    Control("foot-toolmode", "Tool mode", "tools", "HumanoidToggleToolModeButton",
            contexts=_O, tip="The tool in hand's other mode"),
    Control("foot-primary", "Primary", "weapons", "HumanoidSelectPrimaryWeaponButton",
            contexts=_O),
    Control("foot-secondary", "Secondary", "weapons", "HumanoidSelectSecondaryWeaponButton",
            contexts=_O),
    Control("foot-sidearm", "Sidearm", "weapons", "HumanoidSelectUtilityWeaponButton",
            contexts=_O),
    Control("foot-switch", "Switch weapon", "weapons", "HumanoidSwitchWeapon", contexts=_O),
    Control("foot-holster", "Holster", "weapons", "HumanoidHideWeaponButton", contexts=_O),
    Control("foot-reload", "Reload", "weapons", "HumanoidReloadButton", contexts=_O),
    Control("foot-frag", "Frag", "grenades", "HumanoidSelectFragGrenade", contexts=_O),
    Control("foot-emp", "EMP", "grenades", "HumanoidSelectEMPGrenade", contexts=_O),
    Control("foot-shieldgren", "Shield", "grenades", "HumanoidSelectShieldGrenade",
            contexts=_O, tip="Shield projector"),
    Control("foot-nextgren", "Next grenade", "grenades", "HumanoidSelectNextGrenadeTypeButton",
            contexts=_O),
    Control("foot-throw", "Throw", "grenades", "HumanoidThrowGrenadeButton", contexts=_O),
    # Targeting.
    Control("tgt-ahead", "Target ahead", "targeting", "SelectTarget", contexts=_SF),
    Control("tgt-next", "Next target", "targeting", "CycleNextTarget", contexts=_SF),
    Control("tgt-prev", "Previous target", "targeting", "CyclePreviousTarget", contexts=_SF),
    Control("tgt-threat", "Highest threat", "targeting", "SelectHighestThreat", contexts=_SF),
    Control("tgt-hostile", "Next hostile", "targeting", "CycleNextHostileTarget", contexts=_SF),
    Control("tgt-prevhostile", "Previous hostile", "targeting", "CyclePreviousHostileTarget",
            contexts=_SF),
    Control("tgt-sub", "Next subsystem", "targeting", "CycleNextSubsystem", contexts=_SF),
    Control("tgt-prevsub", "Previous subsystem", "targeting", "CyclePreviousSubsystem",
            contexts=_SF),
    Control("tgt-theirs", "Target's target", "targeting", "SelectTargetsTarget", contexts=_SF),
    Control("tgt-wing1", "Wingman 1", "targeting", "TargetWingman0", contexts=_SF),
    Control("tgt-wing2", "Wingman 2", "targeting", "TargetWingman1", contexts=_SF),
    Control("tgt-wing3", "Wingman 3", "targeting", "TargetWingman2", contexts=_SF),
    Control("tgt-winglock", "Wing nav lock", "targeting", "WingNavLock"),
    Control("srv-target", "Target ahead", "targeting", "SelectTarget_Buggy", contexts=_V),
    # Combat: weapons out, then what keeps the ship alive.
    Control("hardpoints", "Hardpoints", "combat", "DeployHardpointToggle"),
    Control("fg-next", "Next fire group", "combat", "CycleFireGroupNext", contexts=_SF),
    Control("fg-prev", "Previous fire group", "combat", "CycleFireGroupPrevious",
            contexts=_SF),
    Control("heatsink", "Heat sink", "combat", "DeployHeatSink"),
    Control("chaff", "Chaff", "combat", "FireChaffLauncher"),
    Control("shieldcell", "Shield cell", "combat", "UseShieldCell"),
    Control("silent", "Silent running", "combat", "ToggleButtonUpInput"),
    Control("srv-fg-next", "Next fire group", "combat", "BuggyCycleFireGroupNext",
            contexts=_V),
    Control("srv-fg-prev", "Previous fire group", "combat", "BuggyCycleFireGroupPrevious",
            contexts=_V),
    # Orders to a ship-launched fighter's crew; from the fighter, to the ship.
    Control("ord-dock", "Request dock", "orders", "OrderRequestDock", contexts=_SF),
    Control("ord-defend", "Defend", "orders", "OrderDefensiveBehaviour", contexts=_SF),
    Control("ord-engage", "Engage at will", "orders", "OrderAggressiveBehaviour", contexts=_SF),
    Control("ord-attack", "Attack target", "orders", "OrderFocusTarget", contexts=_SF),
    Control("ord-holdfire", "Hold fire", "orders", "OrderHoldFire", contexts=_SF),
    Control("ord-hold", "Hold position", "orders", "OrderHoldPosition", contexts=_SF),
    Control("ord-follow", "Follow", "orders", "OrderFollow", contexts=_SF),
    Control("ord-open", "Orders panel", "orders", "OpenOrders", contexts=_SF),
    # Power: the pips, in the order the game's power distributor shows them.
    Control("pips-sys", "SYS", "power", "IncreaseSystemsPower", contexts=_SF,
            tip="One pip to systems"),
    Control("pips-eng", "ENG", "power", "IncreaseEnginesPower", contexts=_SF,
            tip="One pip to engines"),
    Control("pips-wep", "WEP", "power", "IncreaseWeaponsPower", contexts=_SF,
            tip="One pip to weapons"),
    Control("pips-reset", "Reset pips", "power", "ResetPowerDistribution", contexts=_SF),
    Control("srv-pips-sys", "SYS", "power", "IncreaseSystemsPower_Buggy", contexts=_V,
            tip="One pip to systems"),
    Control("srv-pips-eng", "ENG", "power", "IncreaseEnginesPower_Buggy", contexts=_V,
            tip="One pip to engines"),
    Control("srv-pips-wep", "WEP", "power", "IncreaseWeaponsPower_Buggy", contexts=_V,
            tip="One pip to weapons"),
    Control("srv-pips-reset", "Reset pips", "power", "ResetPowerDistribution_Buggy",
            contexts=_V),
    # Panels and maps.
    Control("galmap", "Galaxy map", "panels", "GalaxyMapOpen"),
    Control("sysmap", "System map", "panels", "SystemMapOpen"),
    Control("fss", "FSS", "panels", "ExplorationFSSEnter",
            tip="Full Spectrum System scanner"),
    Control("hudmode", "HUD mode", "panels", "PlayerHUDModeToggle",
            tip="Combat and analysis modes"),
    Control("pnl-left", "Left panel", "panels", "FocusLeftPanel", contexts=_SF),
    Control("pnl-comms", "Comms", "panels", "FocusCommsPanel", contexts=_SF),
    Control("pnl-role", "Role panel", "panels", "FocusRadarPanel", contexts=_SF),
    Control("pnl-right", "Right panel", "panels", "FocusRightPanel", contexts=_SF),
    Control("codex", "Codex", "panels", "OpenCodexGoToDiscovery"),
    Control("orbits", "Orbit lines", "panels", "OrbitLinesToggle"),
    Control("camera", "Camera suite", "panels", "PhotoCameraToggle", contexts=_SF),
    Control("srv-galmap", "Galaxy map", "panels", "GalaxyMapOpen_Buggy", contexts=_V),
    Control("srv-sysmap", "System map", "panels", "SystemMapOpen_Buggy", contexts=_V),
    Control("srv-hudmode", "HUD mode", "panels", "PlayerHUDModeToggle_Buggy", contexts=_V,
            tip="Combat and analysis modes"),
    Control("srv-left", "Left panel", "panels", "FocusLeftPanel_Buggy", contexts=_V),
    Control("srv-comms", "Comms", "panels", "FocusCommsPanel_Buggy", contexts=_V),
    Control("srv-role", "Role panel", "panels", "FocusRadarPanel_Buggy", contexts=_V),
    Control("srv-right", "Right panel", "panels", "FocusRightPanel_Buggy", contexts=_V),
    Control("srv-codex", "Codex", "panels", "OpenCodexGoToDiscovery_Buggy", contexts=_V),
    Control("srv-camera", "Camera suite", "panels", "PhotoCameraToggle_Buggy", contexts=_V),
    Control("foot-galmap", "Galaxy map", "panels", "GalaxyMapOpen_Humanoid", contexts=_O),
    Control("foot-sysmap", "System map", "panels", "SystemMapOpen_Humanoid", contexts=_O),
    Control("foot-comms", "Comms", "panels", "FocusCommsPanel_Humanoid", contexts=_O),
    Control("foot-help", "Mission help", "panels", "HumanoidToggleMissionHelpPanelButton",
            contexts=_O),
    Control("foot-ping", "Ping", "panels", "HumanoidPing", contexts=_O,
            tip="Mark a place for the team"),
    Control("foot-camera", "Camera suite", "panels", "PhotoCameraToggle_Humanoid",
            contexts=_O),
)

BY_ID: dict[str, Control] = {c.id: c for c in CONTROLS}


def group_label(gid: str, context: str = SHIP) -> str:
    return _GROUP_LABELS.get((gid, context)) or dict(GROUPS).get(
        gid, gid.replace("_", " ").title())


def context_label(context: str) -> str:
    return dict(CONTEXTS).get(context, "Ship")


def context_of(state) -> str:
    """Where the commander is: on foot, in an SRV, flying a ship-launched
    fighter, or in the ship."""
    mode = str(getattr(state, "vessel_mode", "") or "ship")
    if mode == "on_foot":
        return FOOT
    if mode == "srv":
        return SRV
    if getattr(state, "cmdr_in_slf", False):
        return FIGHTER
    return SHIP


def in_context(control: Control, context: str) -> bool:
    return context in control.contexts


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

    ``status`` is the outcome of the last press, or what the automation is
    set to do on its own. ``groups`` are in drawing order, each with its
    buttons in order; a group with no buttons is left out.
    """
    enabled: bool
    note: str = ""
    status: str = ""
    groups: list[Group] = field(default_factory=list)
    context: str = SHIP
    #: Where the panel is for — "On foot", "SRV Nomad" — said above it.
    where: str = ""


def status_line(view: "View") -> str:
    """What the panel's foot says: where it is for, then the last press."""
    return " · ".join(x for x in (view.where, view.status) if x)


def build_view(enabled: bool, bound, why_unbound, note: str = "",
               status: str = "", context: str = SHIP, shown=None,
               where: str = "") -> View:
    """The panel from what the automation knows: ``bound(control)`` whether
    a control can be pressed, ``why_unbound(control)`` why not, ``shown``
    whether a control belongs on the panel at all (default: all). Only the
    controls for ``context`` are drawn."""
    groups: list[Group] = []
    for gid, _label in GROUPS:
        g = Group(gid, group_label(gid, context))
        for c in CONTROLS:
            if c.group != gid or not in_context(c, context):
                continue
            if shown is not None and not shown(c):
                continue
            ok = bool(bound(c))
            tip = c.tip if ok else (why_unbound(c) or c.tip)
            g.buttons.append(Button(c.id, c.label, enabled and ok, tip))
        if g.buttons:
            groups.append(g)
    return View(enabled, note, status, groups, context, where or context_label(context))


def columns_for(width: float, min_width: float, groups: int) -> int:
    """How many groups side by side make the best use of ``width``: as many
    as fit at ``min_width`` each, never more than there are groups. The
    desktop window, the terminal and EDAM size the panel the same way."""
    if min_width <= 0:
        return max(1, groups)
    return max(1, min(groups, int(width // min_width)))


def wire_groups(context: str = SHIP) -> list[dict]:
    """The groups as a device is sent them, in drawing order and named for
    ``context``, so EDAM labels and orders the buttons it is sent as the
    desktop does."""
    return [{"id": gid, "label": group_label(gid, context)} for gid, _l in GROUPS]
