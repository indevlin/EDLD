"""core/surface_survey.py — Joining refine events to a surface position.

Frontier added no journal events for surface mining.  The 4.4.1 feature rides
entirely on events that already existed, and none of them carries a position:
across a full journal corpus the only events with a ``Latitude`` field are
``Liftoff``, ``Touchdown``, ``CodexEntry``, ``Location`` and
``ApproachSettlement``.  ``MiningRefined`` fires in the Rhino exactly as it
does in a ship, and says only what came out.

What this deliberately does not do
----------------------------------
Replayed history gets no position.  At startup EDLD replays the journal to
rebuild session state, and those ``MiningRefined`` events are hours or weeks
old with no Status.json to go with them.  Inventing a position for them — the
commander's current one, the last one seen, the body center — would put
fictional deposits in a database whose entire value is that its coordinates
are real.  They are counted and reported instead, once per session, so the
gap is visible rather than silent.
"""

from __future__ import annotations

import threading
from collections import deque
from datetime import datetime, timezone
from typing import NamedTuple, Optional

#: Status.json flag bits used here.  ``0x200000`` (HasLatLong) and
#: ``0x2000000`` (InFighter) are already consumed by the Status poller; InSRV
#: is the next bit up from InFighter.
FLAG_HAS_LATLONG = 0x200000
FLAG_IN_SRV      = 0x4000000

#: How far apart an event timestamp and a position sample may be and still be
#: considered the same moment.  Journal timestamps have one-second resolution
#: and the poll interval is 500 ms, so anything tighter than two seconds would
#: start discarding good captures.
MATCH_WINDOW_S = 2.0

#: Samples retained.  At two per second this is a little over a minute, which
#: is far more than the join needs and cheap enough not to bother trimming.
RING_SIZE = 256


class Position(NamedTuple):
    """One Status.json observation of where the commander is."""
    ts:        float          # unix epoch seconds
    latitude:  float
    longitude: float
    heading:   Optional[float]
    body_name: str
    radius_m:  Optional[float]
    in_srv:    bool


def parse_journal_ts(raw: str) -> Optional[float]:
    """Parse a journal ``timestamp`` into unix epoch seconds.

    Journals write ``2026-09-13T19:49:48Z``.
    """
    if not raw:
        return None
    try:
        s = raw.strip()
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.timestamp()
    except (ValueError, TypeError, AttributeError):
        return None


class PositionRing:
    """Bounded, time-ordered ring of recent surface positions."""

    def __init__(self, size: int = RING_SIZE) -> None:
        self._ring: deque[Position] = deque(maxlen=size)
        self._lock = threading.Lock()

    def add(self, pos: Position) -> None:
        with self._lock:
            self._ring.append(pos)

    def clear(self) -> None:
        with self._lock:
            self._ring.clear()

    def latest(self) -> Optional[Position]:
        with self._lock:
            return self._ring[-1] if self._ring else None

    def __len__(self) -> int:
        with self._lock:
            return len(self._ring)

    def at(self, ts: float, window_s: float = MATCH_WINDOW_S) -> Optional[Position]:
        """Nearest sample to ``ts``, or None if none falls inside the window."""
        if ts is None:
            return None
        with self._lock:
            best, best_d = None, None
            for p in self._ring:
                d = abs(p.ts - ts)
                if d <= window_s and (best_d is None or d < best_d):
                    best, best_d = p, d
            return best


#: The process-wide ring.  Written by the Status.json poller in
#: :mod:`core.journal`, read by the ``surface_mining`` component.  A module
#: singleton rather than a field on MonitorState because it is a transport
#: between two threads, not game state, and nothing should be persisting it.
POSITIONS = PositionRing()


def position_from_status(data: dict, now: float) -> Optional[Position]:
    """Build a :class:`Position` from a Status.json payload, or None."""
    flags = data.get("Flags", 0) or 0
    if not flags & FLAG_HAS_LATLONG:
        return None
    lat = data.get("Latitude")
    lon = data.get("Longitude")
    if lat is None or lon is None:
        return None
    return Position(
        ts        = now,
        latitude  = float(lat),
        longitude = float(lon),
        heading   = data.get("Heading"),
        body_name = str(data.get("BodyName", "") or ""),
        radius_m  = data.get("PlanetRadius"),
        in_srv    = bool(flags & FLAG_IN_SRV),
    )


def is_surface_refine(position: Optional[Position]) -> bool:
    """Whether a ``MiningRefined`` at this position is a surface deposit.

    The discriminator is the position, not the commodity.  A commodity
    whitelist would have to be maintained against every game update and would
    be wrong the day Frontier adds one; having a live latitude while in an SRV
    is true of surface mining and of nothing else.  Ring mining happens in
    space, where there is no latitude at all.
    """
    return bool(position and position.in_srv)


#: Display names whose letters are not the game's symbol, keyed on the display
#: name as :func:`_squash` leaves it. The game's own name for
#: lowtemperaturediamond is "Low Temp.
_COMMODITY_ALIASES: dict[str, str] = {
    "lowtempdiamonds":         "lowtemperaturediamond",
    "lowtemperaturediamonds":  "lowtemperaturediamond",
    "ltd":                     "lowtemperaturediamond",
    "ltds":                    "lowtemperaturediamond",
    "voidopal":                "opal",
    "voidopals":               "opal",
}
_ALIAS_LOCK = threading.Lock()


def _squash(raw: str) -> str:
    s = (raw or "").strip().lower()
    if s.startswith("$") and s.endswith(";"):
        inner = s[1:-1]
        s = inner[:-5] if inner.endswith("_name") else inner
    # Everything that is not a letter or a digit goes. The journal writes
    # $helium3_name; and a commander typing the same commodity by hand writes
    # "Helium-3"; without this they canonicalize differently and the same rock
    # becomes two deposits — one recorded by hand, one by the first refine.
    return "".join(ch for ch in s if ch.isalnum())


def learn_commodity_name(symbol: str, display: str) -> bool:
    """Teach :func:`canonical_commodity` that ``display`` names ``symbol``.

    Returns whether anything new was learned.
    """
    sym = _squash(symbol)
    alias = _squash(display)
    if not sym or not alias or alias == sym:
        return False
    with _ALIAS_LOCK:
        if _COMMODITY_ALIASES.get(alias) == sym:
            return False
        _COMMODITY_ALIASES[alias] = sym
        return True


def canonical_commodity(raw: str) -> str:
    """The game's symbol for a commodity, from any spelling of it.

    ``$thortveitite_name;`` → ``thortveitite``, ``Helium-3`` → ``helium3``, and
    ``Low Temp.
    """
    s = _squash(raw)
    with _ALIAS_LOCK:
        return _COMMODITY_ALIASES.get(s, s)
