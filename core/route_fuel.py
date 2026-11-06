"""
core/route_fuel.py — where a route's fuel runs out, and its dry stretches.

For any route being followed — the game's own plotted route as much as one
EDLD plotted — each leg is flown with the drive model (core/fsd.py) from the
fuel in the tank now:

* **runs out**: the first leg the tank cannot pay for if the commander never
  scoops on the way;
* **dry stretches**: runs of stars no scoop works on, and whether a full tank
  covers one, measured from the last scoopable star before it.

The game's NavRoute.json gives each star's class, so this works for a route
plotted in the galaxy map with nothing from Spansh.
"""
from __future__ import annotations

import math
from typing import Any

#: A run of non-scoopable stars this long is worth a mention even when the
#: tank covers it.
DRY_MENTION = 4


def _scoopable(entry: dict) -> bool:
    from core.route_view import star_kind
    sc = str(entry.get("StarClass") or "")
    if not sc:
        extra = entry.get("EDLD") or {}
        return bool(extra.get("is_scoopable"))
    return star_kind(sc) == "scoopable"


def _legs(route: list) -> list[float | None]:
    out: list[float | None] = []
    for a, b in zip(route, route[1:]):
        try:
            out.append(math.dist([float(v) for v in a.get("StarPos")],
                                 [float(v) for v in b.get("StarPos")]))
        except (TypeError, ValueError):
            extra = b.get("EDLD") or {}
            try:
                out.append(float(extra.get("distance_jumped")) if extra.get("distance_jumped") else None)
            except (TypeError, ValueError):
                out.append(None)
    return out


def analyse(state, route: list, start: int = 0) -> dict[str, Any] | None:
    """Fuel along ``route`` from entry ``start`` (where the commander is).
    None without a drive model or for a route of waypoints several jumps
    apart (a neutron route), where legs are not single jumps."""
    from core import fsd
    from core.route_view import cargo_tons
    drive = getattr(state, "ship_drive", None)
    if drive is None or len(route) - start < 2:
        return None
    if any(int((e.get("EDLD") or {}).get("jumps") or 1) > 1 for e in route[start + 1:]):
        return None
    cargo = cargo_tons(state)
    fuel = getattr(state, "fuel_current", None)
    if fuel is None:
        fuel = drive.tank
    legs = _legs(route)[start:]
    out: dict[str, Any] = {"fuel_after": [], "dry": [], "runs_out_at": "", "runs_out_after": 0}

    # Never scooping, from the fuel aboard now.
    f = float(fuel)
    for i, d in enumerate(legs, start=1):
        if d is None:
            out["fuel_after"].append(None)
            continue
        burn = fsd.jump_fuel(drive, d, f, cargo)
        if burn is None:
            out["runs_out_at"] = route[start + i].get("StarSystem") or ""
            out["runs_out_after"] = i
            break
        f -= burn
        out["fuel_after"].append(f)

    # Dry stretches, from a full tank at the last scoopable star.
    run: list[float] = []
    after = route[start].get("StarSystem") or ""
    for i, d in enumerate(legs, start=1):
        entry = route[start + i]
        if d is not None:
            run.append(d)
        if _scoopable(entry) or i == len(legs):
            if len(run) >= DRY_MENTION or _too_long(drive, run, cargo):
                out["dry"].append({"after": after, "jumps": len(run),
                                   "too_long": _too_long(drive, run, cargo)})
            run = []
            after = entry.get("StarSystem") or ""
    # The last stop need not be scoopable: only a run that ends at a
    # scoopable star, or overruns the tank, is a stretch to cross.
    return out


def _too_long(drive, run: list[float], cargo: float) -> bool:
    from core import fsd
    f = drive.tank
    for d in run:
        burn = fsd.jump_fuel(drive, d, f, cargo)
        if burn is None:
            return True
        f -= burn
    return False
