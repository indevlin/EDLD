"""core/route_view.py — the route being flown, and the ship's jump range.

``plan_range`` is the range with a full tank and the cargo now aboard: what
a route should be plotted with, since the tank is filled by scooping on the
way.
"""
from __future__ import annotations

import math
from typing import Any

from core.fsd import GUARDIAN_BOOSTER_LY, booster_ly  # noqa: F401  (re-exported)
from core import fsd as _fsd

#: Star classes a fuel scoop works on: K, G, B, F, O, A and M, giants of
#: those classes included ("K_OrangeGiant", "M_RedSuperGiant", …).
SCOOPABLE = frozenset("KGBFOAM")


SUPERCHARGE_STANDARD = _fsd.SUPERCHARGE_STANDARD
SUPERCHARGE_MK2 = _fsd.SUPERCHARGE_MK2


def supercharge_multiplier(state) -> int:
    """The current ship's neutron supercharge multiplier, from its drive:
    ×6 for the Caspian Explorer's SCO drive Mk II, ×4 for every other."""
    drive = getattr(state, "ship_drive", None)
    if drive is not None:
        return drive.supercharge
    item = str(getattr(state, "ship_fsd_item", "") or "").lower()
    return SUPERCHARGE_MK2 if "overchargebooster_mkii" in item else SUPERCHARGE_STANDARD


def cargo_tons(state) -> int:
    items = getattr(state, "cargo_items", {}) or {}
    total = 0
    for v in items.values():
        try:
            total += int((v or {}).get("count", 0) or 0)
        except (TypeError, ValueError, AttributeError):
            pass
    return total


def jump_range(state, fuel: float | None = None, cargo: float | None = None) -> float | None:
    """The ship's jump range with ``fuel`` tons in the main tank and
    ``cargo`` tons aboard — by default what it carries now. None when no
    Loadout has said what the ship is."""
    drive = getattr(state, "ship_drive", None)
    if drive is not None:
        if fuel is None:
            fuel = getattr(state, "fuel_current", None)
            if fuel is None:
                fuel = drive.tank
        if cargo is None:
            cargo = cargo_tons(state)
        return _fsd.jump_range(drive, fuel, cargo)
    mx = getattr(state, "ship_max_jump_range", None)
    m0 = getattr(state, "ship_unladen_mass", None)
    try:
        mx, m0 = float(mx), float(m0)
    except (TypeError, ValueError):
        return None
    if mx <= 0 or m0 <= 0:
        return None
    if fuel is None:
        fuel = getattr(state, "fuel_current", None)
        if fuel is None:
            fuel = getattr(state, "fuel_tank_size", 0) or 0
    if cargo is None:
        cargo = cargo_tons(state)
    boost = float(getattr(state, "ship_fsd_booster_ly", 0.0) or 0.0)
    base = max(mx - boost, 0.0)
    mass = m0 + max(float(fuel), 0.0) + max(float(cargo), 0.0)
    return base * m0 / mass + boost


def plan_range(state) -> float | None:
    """Range with a full tank and today's cargo — what to plot a route with."""
    return jump_range(state, fuel=getattr(state, "fuel_tank_size", 0) or 0)


def getattr_tank(view: dict) -> float:
    return float(view.get("tank_size") or 0)


def tank_jumps(state) -> tuple[int, float] | None:
    """(jumps, light years) the fuel in the tank now takes the ship at full
    range, with no scooping; None until the drive and the fuel are known."""
    drive = getattr(state, "ship_drive", None)
    fuel = getattr(state, "fuel_current", None)
    if drive is None or fuel is None:
        return None
    return _fsd.jumps_on_tank(drive, fuel, cargo_tons(state))


def tank_text(tj: tuple[int, float] | None) -> str | None:
    if not tj:
        return None
    n, ly = tj
    return f"{n} jump{'s' if n != 1 else ''} · {fmt_ly(ly)}"


def _dist(a, b) -> float | None:
    try:
        if not a or not b or len(a) != 3 or len(b) != 3:
            return None
        if all(float(v) == 0.0 for v in a) or all(float(v) == 0.0 for v in b):
            return None                  # an unknown position, not Sol
        return math.dist([float(v) for v in a], [float(v) for v in b])
    except (TypeError, ValueError):
        return None


def star_kind(star_class: str) -> str:
    """"neutron", "white_dwarf", "scoopable", "other" or "" (unknown)."""
    sc = str(star_class or "").strip()
    if not sc:
        return ""
    if sc == "N":
        return "neutron"
    if sc.startswith("D"):
        return "white_dwarf"
    if sc[0] in SCOOPABLE:
        return "scoopable"
    return "other"


def route_view(core, ahead_max: int = 40) -> dict[str, Any] | None:
    """Everything the Route views show, or None when nothing is loaded.

    ``ahead`` lists the systems still to come, each with its leg length from
    the system before it and how many jumps that leg is.
    """
    s = getattr(core, "state", None)
    plugins = getattr(core, "_plugins", None) or {}
    nav = plugins.get("navigation")
    if s is None or nav is None:
        return None
    try:
        route, source = nav.active_route()
    except Exception:
        route, source = [], ""
    view: dict[str, Any] = {
        "status": getattr(s, "nav_follow_status", "") or "No route",
        "follow": bool(getattr(s, "nav_follow_enabled", False)),
        "source": {"edld": "EDLD", "journal": "In game"}.get(source, source),
        "range_now": jump_range(s),
        "range_plan": plan_range(s),
        "tank": tank_jumps(s),
        "tank_size": getattr(s, "fuel_tank_size", 0) or 0,
        "route": bool(route),
        "ahead": [],
        "more": 0,
    }
    if not route:
        return view

    current = nav.effective_current_system()
    idx = nav._index_of(route, current)
    start = 0 if idx is None else idx + 1
    view["on_route"] = idx is not None
    view["position"] = (idx + 1) if idx is not None else 0
    view["waypoints"] = len(route)
    view["destination"] = route[-1].get("StarSystem") or ""

    rng = view["range_now"]
    prev = route[idx].get("StarPos") if idx is not None else getattr(s, "pilot_star_pos", None)
    # Off the route, the first leg leaves wherever the commander is.
    from core import route_fuel
    origins = [route[idx]] + route[start:-1] if idx is not None else [None] + route[:-1]
    mult = route_fuel.boosts(s, origins)
    jumps_left, dist_left, legs = 0, 0.0, []
    for n, entry in enumerate(route[start:], start=1):
        extra = entry.get("EDLD") or {}
        try:
            leg_jumps = max(int(extra.get("jumps") or 1), 1)
        except (TypeError, ValueError):
            leg_jumps = 1
        leg = _dist(prev, entry.get("StarPos"))
        if leg is None:
            try:
                leg = float(extra.get("distance_jumped")) if extra.get("distance_jumped") else None
            except (TypeError, ValueError):
                leg = None
        prev = entry.get("StarPos")
        jumps_left += leg_jumps
        if leg is not None:
            dist_left += leg
        if n <= ahead_max:
            boost = mult[n - 1] if n - 1 < len(mult) else 1.0
            needs_boost = bool(rng and leg and leg_jumps == 1 and leg > rng + 0.005
                               and boost > 1.0)
            sc = str(entry.get("StarClass") or "")
            todo_line = ""
            if extra.get("bodies") or extra.get("trade"):
                try:
                    from core import survey
                    todo_line = survey.todo_text(survey.todo(
                        core, entry.get("StarSystem") or "", entry.get("SystemAddress"), extra))
                except Exception:
                    todo_line = ""
            legs.append({
                "todo": todo_line,
                "n": n,
                "system": entry.get("StarSystem") or "—",
                "star_class": sc,
                "kind": star_kind(sc),
                "leg_ly": leg,
                "jumps": leg_jumps,
                # Only a one-jump leg can be too long: a neutron waypoint is
                # reached in as many jumps as it takes. A leg from a neutron
                # star or white dwarf has the supercharge's range.
                "boost": boost if needs_boost else 1.0,
                "too_far": bool(rng and leg and leg_jumps == 1 and leg > rng * boost + 0.005),
            })
    view["jumps_left"] = jumps_left
    view["distance_left"] = dist_left if dist_left > 0 else None
    # Time at this session's pace, once there is one.
    try:
        view["time_left"] = nav.time_left(jumps_left)
    except Exception:
        view["time_left"] = None
    # Fuel along the way: where it runs out without scooping, dry stretches.
    try:
        from core import route_fuel
        view["fuel"] = route_fuel.analyse(s, route, start - 1 if start > 0 else 0)
    except Exception:
        view["fuel"] = None
    fa = (view.get("fuel") or {}).get("fuel_after") or []
    for leg in legs:
        i = leg["n"] - 1
        leg["fuel_after"] = fa[i] if i < len(fa) else None
    view["ahead"] = legs
    view["more"] = max(0, len(route) - start - ahead_max)
    view["next"] = legs[0]["system"] if legs else ""
    return view


def leg_text(leg: dict) -> str:
    """Plain words for one Ahead row's value: class, leg length, jumps."""
    parts = []
    if leg.get("star_class"):
        parts.append(leg["star_class"])
    if leg.get("leg_ly") is not None:
        parts.append(f"{leg['leg_ly']:.1f} ly")
    if leg.get("jumps", 1) > 1:
        parts.append(f"{leg['jumps']} jumps")
    if leg.get("too_far"):
        parts.append("beyond range")
    elif leg.get("boost", 1.0) > 1.0:
        parts.append(f"{fmt_boost(leg['boost'])} boost")
    if leg.get("todo"):
        parts.append(leg["todo"])
    return " · ".join(parts)


def fmt_boost(b: float) -> str:
    """×3, ×1.5."""
    return f"×{b:g}"


def fmt_duration_s(sec: float | None) -> str:
    if not sec:
        return "—"
    m = int(sec // 60)
    return f"{m // 60}h {m % 60:02d}m" if m >= 60 else f"{max(m, 1)}m"


def fuel_lines(view: dict) -> list[str]:
    """Plain-words fuel warnings for the Route tab and EDAM."""
    f = view.get("fuel") or {}
    out = []
    if f.get("runs_out_at"):
        out.append(f"Tank runs dry at {f['runs_out_at']} ({f['runs_out_after']} jumps) "
                   f"without scooping")
    for d in f.get("dry") or []:
        out.append(f"{d['jumps']} jumps without a scoopable star after {d['after']}"
                   + (" — more than a full tank" if d["too_long"] else ""))
    return out


def fmt_ly(v) -> str:
    if v is None:
        return "—"
    return f"{v:,.0f} ly" if v >= 1000 else f"{v:,.1f} ly"


# ── Rows for the Navigation window's Route tab ────────────────────────────────

_KIND_TAG = {"scoopable": "green", "neutron": "magenta", "white_dwarf": "cyan",
             "other": "dim"}


def route_rows(view: dict | None) -> list[tuple]:
    """The Route tab, as ("hdr", title) / ("kv", key, value) / ("text", body)
    rows in the markup both front ends draw. Same facts as EDAM's panels."""
    if view is None:
        return [("text", "[dim]Navigation component not loaded.[/dim]")]
    rows: list[tuple] = [("hdr", "Route")]
    rows.append(("kv", "Status", view["status"]))
    rows.append(("kv", "Follow", "On" if view["follow"] else "Off"))
    rn, rp = view.get("range_now"), view.get("range_plan")
    if rn:
        rng = f"{rn:.2f} ly now"
        if rp and abs(rp - rn) >= 0.01:
            rng += f" · {rp:.2f} ly full tank"
        rows.append(("kv", "Jump range", rng))
    if tank_text(view.get("tank")):
        rows.append(("kv", "On this tank", tank_text(view["tank"])))
    if not view["route"]:
        rows.append(("text", "[dim]No route. Plot one in the game or on the "
                             "FSD or Neutron tab.[/dim]"))
        return rows
    rows.append(("kv", "Source", view["source"]))
    rows.append(("kv", "Destination", view["destination"]))
    if view.get("on_route"):
        rows.append(("kv", "Position", f"{view['position']} of {view['waypoints']}"))
    else:
        rows.append(("kv", "Position", "[yellow]not on this route[/yellow]"))
    rows.append(("kv", "Jumps left", str(view["jumps_left"])))
    if view.get("distance_left"):
        rows.append(("kv", "Distance left", fmt_ly(view["distance_left"])))
    if view.get("time_left"):
        rows.append(("kv", "Time left", f"~{fmt_duration_s(view['time_left'])} at this pace"))
    for line in fuel_lines(view):
        rows.append(("text", f"[yellow]⛽ {line}[/yellow]"))

    rows.append(("hdr", "Ahead"))
    if not view["ahead"]:
        rows.append(("text", "[dim]Arrived.[/dim]"))
    for leg in view["ahead"]:
        parts = []
        if leg["star_class"]:
            tag = _KIND_TAG.get(leg["kind"], "dim")
            parts.append(f"[{tag}]{leg['star_class']}[/{tag}]")
        if leg["leg_ly"] is not None:
            ly = f"{leg['leg_ly']:.1f} ly"
            if leg["too_far"]:
                parts.append(f"[red]{ly} — beyond range[/red]")
            elif leg.get("boost", 1.0) > 1.0:
                parts.append(f"{ly} · [cyan]{fmt_boost(leg['boost'])} boost[/cyan]")
            else:
                parts.append(ly)
        if leg["jumps"] > 1:
            parts.append(f"{leg['jumps']} jumps")
        fa = leg.get("fuel_after")
        if fa is not None and getattr_tank(view) and fa < 0.25 * getattr_tank(view):
            parts.append(f"[yellow]{fa:.1f} t left[/yellow]")
        if leg.get("todo"):
            parts.append(f"[cyan]{leg['todo']}[/cyan]")
        rows.append(("kv", f"{leg['n']}. {leg['system']}", " · ".join(parts) or "—"))
    if view["more"]:
        rows.append(("text", f"[dim]… {view['more']} more[/dim]"))
    return rows


# ── Plotted routes (FSD and Neutron tabs) ─────────────────────────────────────

def plot_summary(result: dict, neutron: bool) -> tuple[str, list[tuple[str, str]]]:
    """(status line, [(waypoint label, value)]) for a plotted ship route."""
    wps = result.get("system_jumps") or result.get("jumps") or []
    per_leg = []
    for wp in wps:
        try:
            per_leg.append(max(int(wp.get("jumps") or 0), 0))
        except (TypeError, ValueError):
            per_leg.append(0)
    counted = sum(per_leg)
    total = counted or result.get("total_jumps") or max(len(wps) - 1, 0)
    distance = result.get("distance") or 0
    if not distance:
        try:
            distance = sum(float(wp.get("distance_jumped") or 0) for wp in wps)
        except (TypeError, ValueError):
            distance = 0
    status = f"{total} jumps · {fmt_ly(float(distance or 0))}"
    if neutron:
        boosts = sum(1 for wp in wps[:-1] if wp.get("neutron_star"))
        status += f" · {boosts} neutron boost{'s' if boosts != 1 else ''}"
    refuels = result.get("refuels")
    if refuels:
        status += f" · {refuels} refuel{'s' if refuels != 1 else ''}"
    rng = result.get("range")
    if rng:
        try:
            status += f" · plotted at {float(rng):.2f} ly"
        except (TypeError, ValueError):
            pass
    if result.get("stand_in"):
        status += f" · from {result['stand_in']}, the nearest known system"
    rows = []
    for i, (wp, n) in enumerate(zip(wps, per_leg), start=1):
        name = wp.get("system") or wp.get("name") or "—"
        parts = []
        try:
            d = float(wp.get("distance_jumped") or wp.get("distance") or 0)
        except (TypeError, ValueError):
            d = 0.0
        if i > 1 or d:
            parts.append(fmt_ly(d))
        if n > 1:
            parts.append(f"{n} jumps")
        if wp.get("neutron_star"):
            parts.append("[magenta]★ neutron[/magenta]")
        elif wp.get("must_refuel"):
            parts.append("[yellow]⛽ refuel[/yellow]")
        elif wp.get("is_scoopable"):
            parts.append("[green]scoopable[/green]")
        # The exact plotter says what is left in the tank on arrival.
        left = wp.get("fuel_in_tank")
        if left is not None and i > 1:
            try:
                parts.append(f"{float(left):.1f} t left")
            except (TypeError, ValueError):
                pass
        rows.append((f"{i}. {name}", " · ".join(parts) or "start"))
    return status, rows


def autofill(current: str, last_auto: str | None, value: str | None) -> str | None:
    """The text a pre-filled field should now hold, or None to leave it."""
    if not value:
        return None
    cur = (current or "").strip()
    if not cur or cur == (last_auto or ""):
        return value if cur != value else None
    return None


def range_hint(state) -> str:
    """One line under the plot forms saying where the range came from."""
    plan = plan_range(state)
    if not plan:
        return ("[dim]Range: enter it by hand — no loadout read yet for this "
                "ship.[/dim]")
    tank = getattr(state, "fuel_tank_size", 0) or 0
    cargo = cargo_tons(state)
    now = jump_range(state)
    tail = f"; {now:.2f} ly as loaded now" if now and abs(now - plan) >= 0.01 else ""
    return (f"[dim]Range {plan:.2f} ly: this ship with a full tank ({tank:g} t) "
            f"and {cargo} t of cargo{tail}.[/dim]")
