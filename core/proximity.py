"""core/proximity.py — Noticing that you are standing on something."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Iterable, Optional

#: How close counts as standing on a deposit. Comfortably inside the area the
#: game highlights on the ground, and far tighter than the radius that decides
#: whether two sightings are the same deposit — so an arrival can never be
#: ambiguous between neighbors.
DEFAULT_ENTER_M = 25.0

#: How far away counts as having left.
EXIT_FACTOR = 2.0


@dataclass
class ProximityTracker:
    """Tracks which deposits the commander is currently standing on."""

    enter_m: float = DEFAULT_ENTER_M
    exit_factor: float = EXIT_FACTOR
    _inside: set[str] = field(default_factory=set)

    @property
    def exit_m(self) -> float:
        return self.enter_m * max(1.01, self.exit_factor)

    @property
    def inside(self) -> frozenset[str]:
        return frozenset(self._inside)

    def reset(self) -> None:
        """Forget everything. Called when the commander leaves the body."""
        self._inside.clear()

    def update(self, distances: dict[str, float]) -> list[str]:
        """Feed one sample. Returns the deposits newly arrived at.

        ``distances`` maps deposit id to meters.
        """
        arrived: list[str] = []
        exit_m = self.exit_m

        for dep_id in list(self._inside):
            d = distances.get(dep_id)
            if d is None or d > exit_m:
                self._inside.discard(dep_id)

        for dep_id, d in distances.items():
            if d <= self.enter_m and dep_id not in self._inside:
                self._inside.add(dep_id)
                arrived.append(dep_id)

        return arrived


def distances_to(latitude: float, longitude: float, radius_m: float,
                 deposits: Iterable[dict],
                 measure: Optional[Callable] = None) -> dict[str, float]:
    """Distance from a position to each deposit, keyed by deposit id."""
    if measure is None:
        from core.geo import surface_distance as measure
    out: dict[str, float] = {}
    for dep in deposits:
        dep_id = dep.get("deposit_id")
        lat, lon = dep.get("latitude"), dep.get("longitude")
        if not dep_id or lat is None or lon is None:
            continue
        out[dep_id] = measure(latitude, longitude, lat, lon, radius_m)
    return out
