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

from math import ceil
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
    ("ship", "Ship"),
    ("throttle", "Throttle"),
    ("vehicle", "Vehicle"),
    ("suit", "Suit"),
    ("tools", "Tools"),
    ("weapons", "Weapons"),
    ("grenades", "Grenades"),
    ("targeting", "Targeting"),
    ("wing", "Wing"),
    ("orders", "Fighter orders"),
    ("systems", "Systems"),
    ("views", "Views"),
    ("combat", "Combat"),
    ("power", "Power"),
)

#: The lines the groups are drawn in, per context: the groups of a line side
#: by side when the width holds them, one under another when not. A group
#: missing from the panel (nothing of it bound) leaves its line to the rest.
ROWS: dict[str, tuple[tuple[str, ...], ...]] = {
    SHIP: (("ship", "throttle"), ("targeting", "wing", "orders"), ("systems", "views"),
           ("combat", "power")),
    FIGHTER: (("ship", "throttle"), ("targeting", "wing", "orders"), ("systems", "views"),
              ("combat", "power")),
    SRV: (("vehicle", "power"), ("targeting", "combat"), ("systems", "views")),
    FOOT: (("suit", "tools"), ("weapons", "grenades"), ("views",)),
}

#: Groups drawn as upright bars side by side, BAR_ROWS rows tall or as tall
#: as their line: the throttle, the cockpit's four panels, the pips.
BARS: frozenset[str] = frozenset({"throttle", "systems", "power"})
BAR_ROWS = 2

#: Groups whose columns come in steps: the orders read in pairs, two or four
#: to a row.
STEPS: dict[str, int] = {"orders": 2}

#: What an EDLD before 20261117 sent for STEPS, kept for the EDAM of then.
COLUMNS: dict[str, int] = {"orders": 2}

#: Controls drawn as one cell, ◀ the first and the second ▶, with the
#: cell's name between: (previous, next, name). Either alone is a button.
PAIRS: tuple[tuple[str, str, str], ...] = (
    ("tgt-prev", "tgt-next", "Target"),
    ("tgt-prevhostile", "tgt-hostile", "Hostile"),
    ("tgt-prevsub", "tgt-sub", "Subsystem"),
    ("fg-prev", "fg-next", "Fire group"),
    ("srv-fg-prev", "srv-fg-next", "Fire group"),
)
_PAIR_OF = {i: p for p in PAIRS for i in p[:2]}

#: A group's name where it differs by context: (group, context) → label.
_GROUP_LABELS = {("ship", FIGHTER): "Fighter", ("orders", FIGHTER): "Orders"}

#: The sequences that also run on their own when Options turns them on: the
#: Options key, for the button's AUTO lamp.
AUTOMATIC = {HONK: "AutoHonk", NEXT_STOP: "AutoTarget"}

CONTROLS: tuple[Control, ...] = (
    # The ship. First EDLD's own sequences: what auto honk and the next stop
    # do on their own, on demand; both press the ship's bindings.
    Control(HONK, "Honk", "ship",
            tip="Hold the discovery scanner in its fire group (in flight)"),
    Control(NEXT_STOP, "Next stop", "ship",
            tip="Plot the galaxy map to the next stop of the route EDLD plotted"),
    # Leaving, traveling, and the route.
    Control("supercruise", "Supercruise", "ship", "Supercruise"),
    Control("jump", "Jump", "ship", "HyperSuperCombination"),
    Control("hyperspace", "Hyperspace", "ship", "Hyperspace",
            tip="Hyperspace jump only, never supercruise"),
    Control("nextroute", "Next system", "ship", "TargetNextRouteSystem",
            tip="Target the next system in the route"),
    Control("boost", "Boost", "ship", "UseBoostJuice", contexts=_SF),
    Control("fa", "Flight assist", "ship", "ToggleFlightAssist", contexts=_SF),
    Control("rotcorr", "Rot. correction", "ship", "DisableRotationCorrectToggle",
            tip="Rotational correction on or off"),
    # Throttle presets, reverse first, then 0% to 100%.
    Control("thr-rev", "Reverse", "throttle", "ToggleReverseThrottleInput", contexts=_SF,
            tip="Throttle to reverse, or back"),
    Control("thr-0", "0%", "throttle", "SetSpeedZero", contexts=_SF),
    Control("thr-25", "25%", "throttle", "SetSpeed25", contexts=_SF),
    Control("thr-50", "50%", "throttle", "SetSpeed50", contexts=_SF),
    Control("thr-75", "75%", "throttle", "SetSpeed75", contexts=_SF),
    Control("thr-100", "100%", "throttle", "SetSpeed100", contexts=_SF),
    # What opens, closes and lights, and the ship's stance.
    Control("gear", "Landing gear", "ship", "LandingGearToggle"),
    Control("scoop", "Cargo scoop", "ship", "ToggleCargoScoop"),
    Control("lights", "Lights", "ship", "ShipSpotLightToggle", contexts=_SF),
    Control("nightvision", "Night vision", "ship", "NightVisionToggle", contexts=_SF),
    Control("hardpoints", "Hardpoints", "ship", "DeployHardpointToggle"),
    Control("silent", "Silent running", "ship", "ToggleButtonUpInput"),
    Control("colonise", "Colonisation", "ship", "TriggerColonisationModule",
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
    # Targeting: what to lock now, then the cycles, each a pair (PAIRS).
    Control("tgt-ahead", "Target ahead", "targeting", "SelectTarget", contexts=_SF),
    Control("tgt-threat", "Highest threat", "targeting", "SelectHighestThreat", contexts=_SF),
    Control("tgt-theirs", "Target's target", "targeting", "SelectTargetsTarget", contexts=_SF),
    Control("tgt-prev", "Prev target", "targeting", "CyclePreviousTarget", contexts=_SF),
    Control("tgt-next", "Next target", "targeting", "CycleNextTarget", contexts=_SF),
    Control("tgt-prevhostile", "Prev hostile", "targeting", "CyclePreviousHostileTarget",
            contexts=_SF),
    Control("tgt-hostile", "Next hostile", "targeting", "CycleNextHostileTarget", contexts=_SF),
    Control("tgt-prevsub", "Prev subsystem", "targeting", "CyclePreviousSubsystem",
            contexts=_SF),
    Control("tgt-sub", "Next subsystem", "targeting", "CycleNextSubsystem", contexts=_SF),
    Control("srv-target", "Target ahead", "targeting", "SelectTarget_Buggy", contexts=_V),
    # The wing.
    Control("tgt-wing1", "Wingman 1", "wing", "TargetWingman0", contexts=_SF),
    Control("tgt-wing2", "Wingman 2", "wing", "TargetWingman1", contexts=_SF),
    Control("tgt-wing3", "Wingman 3", "wing", "TargetWingman2", contexts=_SF),
    Control("tgt-winglock", "Nav lock", "wing", "WingNavLock",
            tip="Wing nav lock: follow the wingman targeted"),
    # Combat: the fire groups, then what keeps the ship alive.
    Control("fg-prev", "Prev fire group", "combat", "CycleFireGroupPrevious",
            contexts=_SF),
    Control("fg-next", "Next fire group", "combat", "CycleFireGroupNext", contexts=_SF),
    Control("heatsink", "Heat sink", "combat", "DeployHeatSink"),
    Control("chaff", "Chaff", "combat", "FireChaffLauncher"),
    Control("shieldcell", "Shield cell", "combat", "UseShieldCell"),
    Control("srv-fg-prev", "Prev fire group", "combat", "BuggyCycleFireGroupPrevious",
            contexts=_V),
    Control("srv-fg-next", "Next fire group", "combat", "BuggyCycleFireGroupNext",
            contexts=_V),
    # Orders to a ship-launched fighter's crew; from the fighter, to the ship.
    # In pairs, two to a line (COLUMNS): stance, target, position, then dock.
    Control("ord-engage", "Engage at will", "orders", "OrderAggressiveBehaviour", contexts=_SF),
    Control("ord-defend", "Defend", "orders", "OrderDefensiveBehaviour", contexts=_SF),
    Control("ord-attack", "Attack target", "orders", "OrderFocusTarget", contexts=_SF),
    Control("ord-holdfire", "Hold fire", "orders", "OrderHoldFire", contexts=_SF),
    Control("ord-follow", "Follow", "orders", "OrderFollow", contexts=_SF),
    Control("ord-hold", "Hold position", "orders", "OrderHoldPosition", contexts=_SF),
    Control("ord-dock", "Request dock", "orders", "OrderRequestDock", contexts=_SF),
    Control("ord-open", "Orders panel", "orders", "OpenOrders", contexts=_SF),
    # Power: the pips, in the order the game's power distributor shows them.
    Control("pips-sys", "SYS", "power", "IncreaseSystemsPower", contexts=_SF,
            tip="One pip to systems"),
    Control("pips-eng", "ENG", "power", "IncreaseEnginesPower", contexts=_SF,
            tip="One pip to engines"),
    Control("pips-wep", "WEP", "power", "IncreaseWeaponsPower", contexts=_SF,
            tip="One pip to weapons"),
    Control("pips-reset", "Reset", "power", "ResetPowerDistribution", contexts=_SF,
            tip="Reset the pips"),
    Control("srv-pips-sys", "SYS", "power", "IncreaseSystemsPower_Buggy", contexts=_V,
            tip="One pip to systems"),
    Control("srv-pips-eng", "ENG", "power", "IncreaseEnginesPower_Buggy", contexts=_V,
            tip="One pip to engines"),
    Control("srv-pips-wep", "WEP", "power", "IncreaseWeaponsPower_Buggy", contexts=_V,
            tip="One pip to weapons"),
    Control("srv-pips-reset", "Reset", "power", "ResetPowerDistribution_Buggy",
            contexts=_V, tip="Reset the pips"),
    # The cockpit's four panels, left to right as they sit: navigation,
    # comms, the role panel (vehicles, crew, disembarking), the ship.
    Control("pnl-left", "Nav", "systems", "FocusLeftPanel", contexts=_SF,
            tip="Navigation panel (left)"),
    Control("pnl-comms", "Comms", "systems", "FocusCommsPanel", contexts=_SF),
    Control("pnl-role", "Deploy", "systems", "FocusRadarPanel", contexts=_SF,
            tip="Role panel (bottom): SRV and fighter bays, crew, disembark"),
    Control("pnl-right", "Ship", "systems", "FocusRightPanel", contexts=_SF,
            tip="Systems panel (right)"),
    Control("srv-left", "Nav", "systems", "FocusLeftPanel_Buggy", contexts=_V,
            tip="Navigation panel (left)"),
    Control("srv-comms", "Comms", "systems", "FocusCommsPanel_Buggy", contexts=_V),
    Control("srv-role", "Deploy", "systems", "FocusRadarPanel_Buggy", contexts=_V,
            tip="Role panel (bottom)"),
    Control("srv-right", "SRV", "systems", "FocusRightPanel_Buggy", contexts=_V,
            tip="Systems panel (right)"),
    # Maps and views.
    Control("galmap", "Galaxy map", "views", "GalaxyMapOpen"),
    Control("sysmap", "System map", "views", "SystemMapOpen"),
    Control("fss", "FSS", "views", "ExplorationFSSEnter",
            tip="Full Spectrum System scanner"),
    Control("orbits", "Orbit lines", "views", "OrbitLinesToggle"),
    Control("hudmode", "HUD mode", "views", "PlayerHUDModeToggle",
            tip="Combat and analysis modes"),
    Control("codex", "Codex", "views", "OpenCodexGoToDiscovery"),
    Control("camera", "Camera suite", "views", "PhotoCameraToggle", contexts=_SF),
    Control("srv-galmap", "Galaxy map", "views", "GalaxyMapOpen_Buggy", contexts=_V),
    Control("srv-sysmap", "System map", "views", "SystemMapOpen_Buggy", contexts=_V),
    Control("srv-hudmode", "HUD mode", "views", "PlayerHUDModeToggle_Buggy", contexts=_V,
            tip="Combat and analysis modes"),
    Control("srv-codex", "Codex", "views", "OpenCodexGoToDiscovery_Buggy", contexts=_V),
    Control("srv-camera", "Camera suite", "views", "PhotoCameraToggle_Buggy", contexts=_V),
    Control("foot-galmap", "Galaxy map", "views", "GalaxyMapOpen_Humanoid", contexts=_O),
    Control("foot-sysmap", "System map", "views", "SystemMapOpen_Humanoid", contexts=_O),
    Control("foot-comms", "Comms", "views", "FocusCommsPanel_Humanoid", contexts=_O),
    Control("foot-help", "Mission help", "views", "HumanoidToggleMissionHelpPanelButton",
            contexts=_O),
    Control("foot-ping", "Ping", "views", "HumanoidPing", contexts=_O,
            tip="Mark a place for the team"),
    Control("foot-camera", "Camera suite", "views", "PhotoCameraToggle_Humanoid",
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


def group_order(context: str = SHIP) -> list[str]:
    """The groups in the order ``context``'s lines take them, then any other."""
    order = [g for row in ROWS.get(context, ()) for g in row]
    return order + [g for g, _l in GROUPS if g not in order]


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
    #: For a sequence that also runs on its own (AUTOMATIC): whether Options
    #: has it on, for the button's AUTO lamp; None for any other.
    auto: Optional[bool] = None


@dataclass
class Group:
    id: str
    label: str
    buttons: list[Button] = field(default_factory=list)

    @property
    def bars(self) -> bool:
        return self.id in BARS

    def cells(self) -> list[tuple[Button, ...]]:
        """The buttons as drawn: one each, or a pair (PAIRS) as one."""
        by_id = {b.id: b for b in self.buttons}
        return [tuple(by_id[i] for i in ids) for ids in cells([b.id for b in self.buttons])]


def cells(ids: list[str]) -> list[tuple[str, ...]]:
    """``ids`` as drawn: (id,) each, or (previous, next) where both of a
    pair are there, in the place of the first of them."""
    have = set(ids)
    out: list[tuple[str, ...]] = []
    done: set[str] = set()
    for i in ids:
        if i in done:
            continue
        p = _PAIR_OF.get(i)
        if p and p[0] in have and p[1] in have:
            out.append((p[0], p[1]))
            done.update(p[:2])
        else:
            out.append((i,))
    return out


def pair_label(ids: tuple[str, ...]) -> str:
    """A pair's name: "Target" for (tgt-prev, tgt-next)."""
    p = _PAIR_OF.get(ids[0])
    return p[2] if p else ""


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
    """What the panel's foot says: what the last press came to, for a while
    after it; nothing otherwise."""
    return view.status


def build_view(enabled: bool, bound, why_unbound, note: str = "",
               status: str = "", context: str = SHIP, shown=None,
               where: str = "", auto=None) -> View:
    """The panel from what the automation knows: ``bound(control)`` whether
    a control can be pressed, ``why_unbound(control)`` why not, ``shown``
    whether a control belongs on the panel at all (default: all),
    ``auto(control)`` whether an AUTOMATIC sequence runs on its own. Only the
    controls for ``context`` are drawn."""
    groups: list[Group] = []
    for gid in group_order(context):
        g = Group(gid, group_label(gid, context))
        for c in CONTROLS:
            if c.group != gid or not in_context(c, context):
                continue
            if shown is not None and not shown(c):
                continue
            ok = bool(bound(c))
            tip = c.tip if ok else (why_unbound(c) or c.tip)
            on = bool(auto(c)) if auto is not None and c.id in AUTOMATIC else None
            g.buttons.append(Button(c.id, c.label, enabled and ok, tip, on))
        if g.buttons:
            groups.append(g)
    return View(enabled, note, status, groups, context, where or context_label(context))


def _balanced(n: int, cols: int) -> int:
    """``cols`` columns for ``n`` buttons, cut to as few as keep the rows they
    make, so the last row is not left with one."""
    cols = max(1, min(n, cols))
    return max(1, ceil(n / ceil(n / cols))) if n else 1


def fit(width: float, button: float, gap: float, k: int, group_gap: float = 0) -> int:
    """Button columns ``k`` groups share in ``width``: buttons at least
    ``button`` wide, ``gap`` between them and ``group_gap`` between groups."""
    return max(k, int((width - group_gap * (k - 1) + gap * k) // (button + gap)))


def bar_columns(n: int, button: float, bar: float, gap: float) -> int:
    """Button columns ``n`` bars at least ``bar`` wide take."""
    return max(1, ceil(n * (bar + gap) / (button + gap)))


def group_rows(gid: str, n: int, cols: int) -> int:
    """Rows a group of ``n`` cells takes in ``cols`` columns; bars BAR_ROWS."""
    return BAR_ROWS if gid in BARS else ceil(n / max(1, cols))


def _side_by_side(row, counts, total, button, bar, gap) -> list[int] | None:
    """Columns for the groups of ``row`` sharing ``total``: bars as narrow as
    they may be, the rest given a column (or a STEPS step) at a time, to
    the group with the most rows to lose, down to the bars' height. None
    when they do not fit."""
    floor = BAR_ROWS if any(g in BARS for g in row) else 1
    cols = []
    for g, n in zip(row, counts):
        if g in BARS:
            cols.append(bar_columns(n, button, bar, gap))
        else:
            cols.append(min(n, STEPS.get(g, 1)))
    if sum(cols) > total:
        return None
    while True:
        free = [i for i, (g, n) in enumerate(zip(row, counts))
                if g not in BARS and ceil(n / cols[i]) > floor and cols[i] < n
                and sum(cols) + STEPS.get(g, 1) <= total]
        if not free:
            break
        i = max(free, key=lambda j: (ceil(counts[j] / cols[j]), counts[j]))
        cols[i] += STEPS.get(row[i], 1)
    return [c if g in BARS else _stepped(n, c, STEPS[g]) if g in STEPS else _balanced(n, c)
            for g, n, c in zip(row, counts, cols)]


def _stepped(n: int, cols: int, step: int) -> int:
    """``cols`` cut to the fewest steps that keep its rows."""
    need = ceil(n / ceil(n / cols))
    return min(cols, ceil(need / step) * step)


def _alone(g: str, n: int, one: int, button: float, bar: float, gap: float) -> int:
    if g in BARS:
        return min(one, bar_columns(n, button, bar, gap))
    step = STEPS.get(g)
    if step:
        c = min(n, one)
        return max(1, c - c % step) if c >= step else c
    return _balanced(n, one)


def _parts(k: int):
    """The ways to cut ``k`` groups into runs, fewest runs first."""
    out = [[]]
    for _ in range(k - 1):
        out = [p + [cut] for p in out for cut in (False, True)]
    out.sort(key=sum)
    for cuts in out:
        runs, start = [], 0
        for i, cut in enumerate(cuts, 1):
            if cut:
                runs.append((start, i))
                start = i
        runs.append((start, k))
        yield runs


def plan(groups, context: str, width: float, button: float, gap: float,
         group_gap: float, bar: float = 0) -> list[list[tuple[str, int]]]:
    """The panel's lines: each a list of (group id, columns), from
    ``groups`` as (id, cells) in ROWS's lines for ``context``. A line is cut
    into the runs that make it shortest, a title counting as a row; on a
    tie, the one whose tallest group is shortest, then the fewest runs. A
    run's groups sit side by side. ``bar`` is the narrowest
    bar (half a button by default). The desktop window, the terminal and
    EDAM lay the panel out by this."""
    bar = bar or button / 2
    count = dict(groups)
    lines = [[g for g in row if count.get(g)] for row in ROWS.get(context, ())]
    placed = {g for row in lines for g in row}
    lines += [[g] for g, n in groups if n and g not in placed]
    one = fit(width, button, gap, 1)
    out: list[list[tuple[str, int]]] = []
    for row in (r for r in lines if r):
        best, cost = None, None
        for runs in _parts(len(row)):
            got, tall, peak = [], 0, 0
            for a, b in runs:
                part = row[a:b]
                counts = [count[g] for g in part]
                if len(part) == 1:
                    cols = [_alone(part[0], counts[0], one, button, bar, gap)]
                else:
                    cols = _side_by_side(part, counts,
                                         fit(width, button, gap, len(part), group_gap),
                                         button, bar, gap)
                    if cols is None:
                        break
                got.append(list(zip(part, cols)))
                rows = [group_rows(g, n, c) for g, n, c in zip(part, counts, cols)
                        if g not in BARS]
                tall += max(rows + [BAR_ROWS if len(rows) < len(part) else 1]) + 1
                peak = max([peak] + rows)
            else:
                if cost is None or (tall, peak) < cost:
                    best, cost = got, (tall, peak)
        out += best
    return out


def line_rows(line: list[tuple[str, int]], count: dict) -> int:
    """Rows of buttons a line of plan() takes."""
    return max(group_rows(g, count[g], c) for g, c in line)


def row_height(avail: float, lines, count: dict, title: float, line_gap: float,
               gap: float, least: float, most: float) -> float:
    """The buttons' height filling ``avail``: between ``least`` and
    ``most``, every row alike."""
    rows = sum(line_rows(line, count) for line in lines)
    if not rows:
        return least
    fixed = len(lines) * title + max(0, len(lines) - 1) * line_gap + (rows - len(lines)) * gap
    return max(least, min(most, (avail - fixed) / rows))


def wire_rows(context: str = SHIP) -> list[list[str]]:
    """ROWS for ``context``, as a device is sent them."""
    return [list(r) for r in ROWS.get(context, ())]


def wire_pairs(context: str = SHIP) -> list[dict]:
    """PAIRS for ``context``, as a device is sent them."""
    return [{"prev": p, "next": n, "label": label} for p, n, label in PAIRS
            if in_context(BY_ID[p], context)]


def wire_groups(context: str = SHIP) -> list[dict]:
    """The groups as a device is sent them, in drawing order and named for
    ``context``, so EDAM labels and orders the buttons it is sent as the
    desktop does."""
    return [{"id": gid, "label": group_label(gid, context)} for gid in group_order(context)]
