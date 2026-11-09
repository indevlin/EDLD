"""core/edcars.py — the EDCARS style: its name, its sections, and its header strip.

Helm is the panel of controls and automation (core/helm.py), which EDCARS gives
a section of its own.

* the style's name — ``EDCARS_NAME`` is the only place it is spelled. Renaming
  the style is a change to this one constant; the value stored in config.toml
  (as the interface id) and sent to EDAM is ``EDCARS_ID``, which is not shown
  to anyone;
* the sections, in rail order, and which windows and wire panels each holds;
* the header strip — the handful of facts that stay on screen whichever
  section is showing — and how each is worded and colored;
* which alerts are urgent enough to pulse the Alerts pill.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Optional

from core.helm import HELM_NAME, HELM_SECTION

# ── The style ─────────────────────────────────────────────────────────────────

#: The style's display name. The one place it is written: Options, the docs'
#: wording aside, and EDAM all take it from here or from the wire.
EDCARS_NAME = "EDCARS"

#: What config.toml stores and the wire carries. Not a name anyone reads, so a
#: rename of EDCARS_NAME never has to migrate a saved setting.
EDCARS_ID = "edcars"
DASHBOARD_ID = "dashboard"

#: (id, display name) of the two layouts; EDAM is sent these.
STYLES: tuple[tuple[str, str], ...] = ((DASHBOARD_ID, "Dashboard"), (EDCARS_ID, EDCARS_NAME))

#: How a new urgent alert is surfaced: the Alerts pill pulses, or the rail also
#: switches to the Alerts section.
ALERTS_PULSE = "pulse"
ALERTS_SWITCH = "switch"
ALERT_MODES: tuple[tuple[str, str], ...] = (
    (ALERTS_PULSE, "Pulse the Alerts pill"),
    (ALERTS_SWITCH, "Pulse and switch to Alerts"),
)

#: The ``[UI]`` key that holds the choice.
ALERTS_KEY = "EdcarsAlerts"


# ── Consoles ──────────────────────────────────────────────────────────────────
#
# The EDCARS layout — band, strip, rail, framed windows, radio — can be drawn
# in more than one console's dress. EDCARS's own is the first; the other three
# are homages to a galaxy far, far away, each with a theme of the same name
# whose lights and screens match it (core/palette.py). The panels are the
# console's own paint and stay as they are whatever theme is chosen; the
# lights, the screens and the text take the theme's colors. Chosen in Options
# → Appearance as ``[UI] Console``; the interface is still EDCARS.

#: The consoles' display names, each written only here.
ORDER_NAME = "ORDER"      # Imperial fleet console
REBEL_NAME = "REBEL"      # Rebel / New Republic ops board
ROGUE_NAME = "ROGUE"      # independent freighter cockpit

ORDER_ID = "order"
REBEL_ID = "rebel"
ROGUE_ID = "rogue"


@dataclass(frozen=True)
class Console:
    id: str
    name: str
    #: The theme made for it, offered alongside; "" for EDCARS, which suits
    #: them all.
    theme: str
    blurb: str


CONSOLES: tuple[Console, ...] = (
    Console(EDCARS_ID, EDCARS_NAME, "",
            "the band and the elbow, pills down the rail"),
    Console(ORDER_ID, ORDER_NAME, ORDER_ID,
            "an Imperial fleet console: gray steel, indicator lights, "
            "readouts behind chamfered black glass"),
    Console(REBEL_ID, REBEL_NAME, REBEL_ID,
            "a Rebel ops board: cream consoles, orange and yellow lamps, "
            "screens in their bezels"),
    Console(ROGUE_ID, ROGUE_NAME, ROGUE_ID,
            "an independent freighter's cockpit: worn plate, tape labels, "
            "toggle switches, amber CRTs"),
)
CONSOLE_IDS: tuple[str, ...] = tuple(c.id for c in CONSOLES)
CONSOLE_BY_ID: dict[str, Console] = {c.id: c for c in CONSOLES}

#: The ``[UI]`` key that holds the choice.
CONSOLE_KEY = "Console"


def console_of(ui_cfg: Optional[dict]) -> str:
    """The configured console, EDCARS's own for anything unrecognized."""
    raw = str((ui_cfg or {}).get(CONSOLE_KEY, EDCARS_ID) or EDCARS_ID).strip().lower()
    return raw if raw in CONSOLE_BY_ID else EDCARS_ID


def console_choices() -> list[tuple[str, str]]:
    """(id, label) pairs for Options."""
    return [(c.id, c.name) for c in CONSOLES]


def console_note() -> str:
    """What the choice offers, worded once for both front ends' Options."""
    kinds = "; ".join(f"{c.name}, {c.blurb}" for c in CONSOLES)
    return (f"The console is how {EDCARS_NAME}'s band, rail and frames are drawn: "
            f"{kinds}. Each of the last three has a theme of its own name under "
            "Theme, though any theme will do. Used from the next start.")


def style_for_mode(mode_id: str) -> str:
    """The layout the desktop window and EDAM's "follow EDLD" use for the
    interface EDLD is running as: EDCARS for EDCARS, the Dashboard for
    everything else — the Dashboard window itself and both terminal
    interfaces, which draw the Dashboard's windows."""
    return EDCARS_ID if str(mode_id or "").strip().lower() == EDCARS_ID else DASHBOARD_ID


def alert_mode_of(ui_cfg: Optional[dict]) -> str:
    raw = str((ui_cfg or {}).get(ALERTS_KEY, ALERTS_PULSE) or ALERTS_PULSE).strip().lower()
    return raw if raw in dict(ALERT_MODES) else ALERTS_PULSE


# ── Sections ──────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class Part:
    """One framed window in a section.

    ``window`` is a layout-model window name (core.layout_model.BLOCK_DISPLAY),
    or ``"alerts"`` for the Alerts list EDCARS draws itself, or ``"helm"`` for
    the Helm panel (core/helm.py). ``part`` picks a piece of a window that EDCARS
    splits between sections: the Commander window's identity tabs and its fleet
    tabs, and the Crew half of Crew / Alerts. ``column`` and ``weight`` place it:
    parts sharing a column stack, columns sit side by side, and weight is the
    share of the column or row it gets.

    ``groups`` and ``panels`` say which of the section's wire panels EDAM puts in
    this frame, by the same rule as sections (see part_for_panel), so a device
    frames the same windows, in the same places, as the desktop does. ``tabs`` is
    whether the desktop window is tabbed: a device shows a frame's panels as tabs
    when it is, and one under another when it is not. ``header`` is a panel drawn
    as the line above the tabs. ``tools`` puts the Navigation window's forms
    (header "tools") after the frame's panels, as the desktop's tabs follow
    Route.
    """
    window: str
    part: str = ""
    column: int = 0
    weight: int = 1
    title: str = ""
    groups: tuple[str, ...] = ()
    panels: tuple[str, ...] = ()
    tabs: bool = True
    header: str = ""
    tools: bool = False

    @property
    def id(self) -> str:
        return f"{self.window}.{self.part}" if self.part else self.window


@dataclass(frozen=True)
class Section:
    id: str
    label: str
    parts: tuple[Part, ...]
    #: Wire groups whose panels belong here on EDAM.
    groups: tuple[str, ...] = ()
    #: Panel-id prefixes that belong here whatever their group — how the
    #: Commander group's fleet panels reach the Fleet section.
    panels: tuple[str, ...] = ()
    #: Column widths, relative, left to right.
    columns: tuple[int, ...] = (1,)


#: The Commander window's tabs EDCARS moves to the Fleet section.
FLEET_TABS = ("Ships", "Modules", "Carrier", "S. Carrier")

SECTIONS: tuple[Section, ...] = (
    Section(
        "command", "Command",
        parts=(Part("commander", "identity", column=0, weight=3, title="Commander",
                    groups=("commander",)),
               Part("status", "crew", column=0, weight=2, title="Crew / SLF",
                    groups=("crew",), tabs=False),
               Part("ship_info", column=1, weight=1, title="Ship",
                    groups=("ship", "vessel"), header="ship")),
        groups=("commander", "ship", "vessel", "crew"),
        columns=(45, 55),
    ),
    Section(
        HELM_SECTION, HELM_NAME,
        parts=(Part("helm", title=HELM_NAME, groups=("helm",), tabs=False),),
        groups=("helm",),
    ),
    Section(
        "fleet", "Fleet",
        parts=(Part("commander", "fleet", title="Fleet"),),
        panels=("commander.ships", "commander.stored-modules",
                "commander.carrier", "commander.squadron-carrier"),
    ),
    Section(
        "exploration", "Exploration",
        parts=(Part("exploration", column=0, title="Exploration / Exobiology",
                    groups=("exploration",), tabs=False),
               Part("navigation", column=1, title="Navigation",
                    groups=("navigation",), tools=True)),
        groups=("exploration", "navigation"),
        columns=(55, 45),
    ),
    Section(
        "objectives", "Objectives",
        parts=(Part("objectives", title="Objectives"),),
        groups=("missions", "colonisation", "survey"),
    ),
    Section(
        "career", "Career",
        parts=(Part("career", title="Career / Session"),),
        groups=("session", "career"),
    ),
    Section(
        "alerts", "Alerts",
        parts=(Part("alerts", title="Alerts", tabs=False),),
        groups=("alerts",),
    ),
)

ALERTS_SECTION = "alerts"

#: Panels EDLD sends that EDCARS does not draw: hull, shields and fuel are in
#: the Commander window's Info tab and the header strip, and this panel is
#: there for the Dashboard style.
EDCARS_OMITS: tuple[str, ...] = ("status",)


def section(sid: str) -> Optional[Section]:
    return next((s for s in SECTIONS if s.id == sid), None)


def section_for_panel(panel_id: str, group: str) -> Optional[str]:
    """Which section a wire panel belongs to, or None for one EDCARS does not
    place — a device shows those in a section of their own, so a window a
    newer EDLD adds is never lost."""
    for s in SECTIONS:
        if any(panel_id == p or panel_id.startswith(p + ".") or panel_id.startswith(p + "-")
               for p in s.panels):
            return s.id
    for s in SECTIONS:
        if group in s.groups:
            return s.id
    return None


def part_for_panel(sec: Section, panel_id: str, group: str) -> Part:
    """Which frame of ``sec`` a wire panel already placed in it goes in."""
    for p in sec.parts:
        if any(panel_id == x or panel_id.startswith(x + ".") or panel_id.startswith(x + "-")
               for x in p.panels):
            return p
    for p in sec.parts:
        if group in p.groups:
            return p
    return sec.parts[-1]


def section_columns(sec: Section) -> list[int]:
    """Relative column widths, one per column the section's parts use."""
    n = max(p.column for p in sec.parts) + 1
    return list(sec.columns[:n]) + [1] * (n - len(sec.columns))


def wire_sections() -> list[dict]:
    """The sections as EDAM receives them, in rail order.

    ``columns`` and ``parts`` are the desktop window's own layout — the frames,
    their titles, which column each sits in and its share of it — so EDAM draws
    each section as the desktop does.
    """
    return [{"id": s.id, "label": s.label, "groups": list(s.groups),
             "panels": list(s.panels), "columns": section_columns(s),
             "parts": [{"id": p.id, "title": p.title or p.window,
                        "column": p.column, "weight": p.weight, "tabs": p.tabs,
                        "groups": list(p.groups), "panels": list(p.panels),
                        "header": p.header, "tools": p.tools}
                       for p in s.parts]}
            for s in SECTIONS]


# ── Header strip ──────────────────────────────────────────────────────────────

@dataclass
class Field:
    """One fact on the header strip. ``tone`` is "", "good", "warn" or "crit"."""
    key: str
    label: str
    value: str
    tone: str = ""

    @property
    def gives_way(self) -> bool:
        """Whether this fact's value ends in "…" when the strip is too narrow
        (GIVES_WAY), so the short facts after it stay in sight."""
        return self.key in GIVES_WAY

    def wire(self) -> dict:
        out = {"id": self.key, "label": self.label, "value": self.value}
        if self.tone:
            out["tone"] = self.tone
        if self.gives_way:
            out["shrinks"] = True
        return out


#: The strip's long facts. On a narrow window, a tablet or a phone they end in
#: "…" rather than push fuel, hull and mode — what is checked at a glance — off
#: the end.
GIVES_WAY = ("vessel", "location")


def location_text(state) -> str:
    """Where the commander is: the system, and the body or station within it.
    """
    system = str(getattr(state, "pilot_system", "") or "")
    body = str(getattr(state, "pilot_body", "") or "")
    if body and system and body.startswith(system):
        body = body[len(system):].strip()
    if system and body:
        return f"{system} · {body}"
    return system or body


def vessel_text(state) -> str:
    mode = str(getattr(state, "vessel_mode", "ship") or "ship").lower()
    if mode == "on_foot":
        suit = str(getattr(state, "suit_name", "") or "")
        return suit or "On foot"
    if mode == "srv":
        srv = str(getattr(state, "srv_type", "") or "")
        return srv or "SRV"
    if getattr(state, "cmdr_in_slf", False):
        return "Fighter"
    name = str(getattr(state, "ship_name", "") or "")
    ident = str(getattr(state, "ship_ident", "") or "")
    kind = str(getattr(state, "pilot_ship", "") or "")
    named = f"{name} ({ident})" if name and ident else (name or ident)
    if named and kind:
        return f"{named} · {kind}"
    return named or kind


def cargo_text(state) -> str:
    """Used/total for whichever vessel the commander is in."""
    mode = str(getattr(state, "vessel_mode", "ship") or "ship").lower()
    if mode == "on_foot":
        return ""
    if mode == "srv":
        from data.ships import srv_cargo_capacity
        used = int(getattr(state, "srv_cargo_count", 0) or 0)
        cap = srv_cargo_capacity(str(getattr(state, "srv_type", "") or ""))
        return f"{used:,}/{cap:,} t" if cap else f"{used:,} t"
    items = getattr(state, "cargo_items", None) or {}
    used = sum(int((v or {}).get("count", 0) or 0) for v in items.values())
    cap = int(getattr(state, "cargo_capacity", 0) or 0)
    if not cap and not used:
        return ""
    return f"{used:,}/{cap:,} t" if cap else f"{used:,} t"


def _mode(state) -> str:
    return str(getattr(state, "vessel_mode", "ship") or "ship").lower()


def _fuel(state) -> tuple[str, str]:
    """The ship's main tank. Nothing in an SRV or on foot: the journal reports
    no capacity for an SRV's tank, and the ship's is not what is running low."""
    from core.state import FUEL_CRIT_THRESHOLD, FUEL_WARN_THRESHOLD
    if _mode(state) != "ship":
        return "", ""
    cur = getattr(state, "fuel_current", None)
    tank = getattr(state, "fuel_tank_size", None)
    if cur is None or not tank:
        return "", ""
    # More fuel than the tank holds: the tank is not known yet (the default
    # until the replay reaches a Loadout) while Status.json already reports
    # the fuel. Said as nothing rather than as 200%.
    if float(cur) > float(tank) + 0.01:
        return "", ""
    frac = float(cur) / float(tank)
    tone = ("crit" if frac < FUEL_CRIT_THRESHOLD
            else "warn" if frac < FUEL_WARN_THRESHOLD else "good")
    return f"{frac * 100:.0f}%", tone


def _hull(state) -> tuple[str, str]:
    """The hull of whatever the commander is in: the SRV's while driving."""
    mode = _mode(state)
    if mode == "on_foot":
        return "", ""
    if mode == "srv":
        pct = getattr(state, "srv_hull", None)
    else:
        exact = getattr(state, "ship_hull_exact", None)
        pct = (float(exact) * 100) if exact is not None else getattr(state, "ship_hull", None)
    if pct is None:
        return "", ""
    pct = float(pct)
    tone = "good" if pct > 75 else ("warn" if pct >= 25 else "crit")
    return f"{pct:.0f}%", tone


def squadron_text(state) -> str:
    """The squadron and its tag — "Mining and Logistics Ltd [MALL]" — or ""
    when the commander is in none."""
    sq = str(getattr(state, "pilot_squadron_name", "") or "").strip()
    if not sq:
        return ""
    tag = str(getattr(state, "pilot_squadron_tag", "") or "").strip()
    return f"{sq} [{tag.upper()}]" if tag else sq


def title_text(state) -> str:
    """The band's title: the commander, and their squadron when they are in
    one — "CMDR MERRICK CALBRUIN // MINING AND LOGISTICS LTD [MALL]".
    """
    return title_forms(state)[0]


def title_forms(state) -> list[str]:
    """The band's title, longest first, for a band too narrow for the whole
    of it: with the squadron, then with its tag alone, then the commander
    alone — "CMDR MERRICK CALBRUIN // MINING AND LOGISTICS LTD [MALL]",
    "CMDR MERRICK CALBRUIN [MALL]", "CMDR MERRICK CALBRUIN". The first that
    fits is drawn; when none does, the last ends in "…"."""
    name = str(getattr(state, "pilot_name", "") or "").strip() if state is not None else ""
    if not name:
        return ["COMMANDER"]
    sq = squadron_text(state)
    tag = str(getattr(state, "pilot_squadron_tag", "") or "").strip()
    forms = [f"CMDR {name}" + (f" // {sq}" if sq else "")]
    if sq and tag:
        forms.append(f"CMDR {name} [{tag}]")
    forms.append(f"CMDR {name}")
    out: list[str] = []
    for f in forms:
        if f.upper() not in out:
            out.append(f.upper())
    return out


def strip(state) -> list[Field]:
    """The header strip, left to right. Empty values are left out."""
    if state is None:
        return []
    out: list[Field] = []
    name = str(getattr(state, "pilot_name", "") or "")
    if name:
        out.append(Field("cmdr", "CMDR", name))
    # The squadron is in the band's title (title_text), not here.
    v = vessel_text(state)
    if v:
        out.append(Field("vessel", "Vessel", v))
    c = cargo_text(state)
    if c:
        out.append(Field("cargo", "Cargo", c))
    loc = location_text(state)
    if loc:
        out.append(Field("location", "Location", loc))
    fuel, tone = _fuel(state)
    if fuel:
        out.append(Field("fuel", "Fuel", fuel, tone))
    hull, tone = _hull(state)
    if hull:
        out.append(Field("hull", "Hull", hull, tone))
    mode = str(getattr(state, "pilot_mode", "") or "")
    if mode:
        out.append(Field("mode", "Mode", mode))
    return out


def clock_text(now: Optional[datetime] = None) -> str:
    """The local time of day, for the end of the strip."""
    return (now or datetime.now()).strftime("%H:%M")


# ── Alerts ────────────────────────────────────────────────────────────────────

def is_urgent(alert: dict) -> bool:
    """Whether an alert should pulse the Alerts pill."""
    return bool((alert or {}).get("urgent"))
