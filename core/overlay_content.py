"""core/overlay_content.py — What the overlay says, and when it says nothing.

The rule this file exists to enforce
------------------------------------
The overlay is not a second dashboard.
"""

from __future__ import annotations

from typing import Iterable, Optional

from core.geo import bearing as geo_bearing, surface_distance

#: Deposit marks, colored by how much the site holds when full. Depletion is
#: a date on the deposit, not an amount, so it is not a color here.
_AMOUNT_COLOURS = {
    "High":     "#7ee787",
    "Medium":   "#8fd1ff",
    "Low":      "#e3b341",
    "":         "#8fd1ff",
}

#: Beyond this the bearing is not useful — the commander should be flying, not
#: driving, and a mark on the tape would imply otherwise.
MAX_RANGE_M = 20_000.0


def _fmt_distance(metres: float) -> str:
    if metres < 1000:
        return f"{metres:.0f}m"
    return f"{metres / 1000:.1f}km"


def nearest_deposits(latitude: float, longitude: float, radius_m: float,
                     deposits: Iterable[dict], limit: int = 5,
                     max_range_m: float = MAX_RANGE_M) -> list[dict]:
    """Deposits within range, nearest first, each with distance and bearing.

    Each returned dict is the stored row plus ``distance_m`` and ``bearing``.
    """
    out = []
    for dep in deposits:
        lat, lon = dep.get("latitude"), dep.get("longitude")
        if lat is None or lon is None:
            continue
        d = surface_distance(latitude, longitude, lat, lon, radius_m)
        if d > max_range_m:
            continue
        out.append({**dep, "distance_m": d,
                    "bearing": geo_bearing(latitude, longitude, lat, lon)})
    out.sort(key=lambda r: r["distance_m"])
    return out[:limit]
