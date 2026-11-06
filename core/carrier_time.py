"""
core/carrier_time.py — a fleet carrier's two clocks.

* **Jump cooldown**: a carrier cannot be sent on again until five minutes
  after it arrives. The journal says when it arrived (CarrierJump aboard,
  CarrierLocation otherwise); the cooldown is counted from there.
* **Upkeep**: the week's upkeep comes out of the carrier's balance every
  Thursday at 07:00 UTC, in the weekly server maintenance. Only Frontier's
  companion API reports the weekly amount; when it has, the balance is
  checked against it.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

COOLDOWN_S = 300
UPKEEP_WEEKDAY = 3        # Thursday
UPKEEP_HOUR = 7           # 07:00 UTC


def parse_ts(ts) -> float | None:
    try:
        return datetime.strptime(str(ts), "%Y-%m-%dT%H:%M:%SZ").replace(
            tzinfo=timezone.utc).timestamp()
    except (TypeError, ValueError):
        return None


def next_upkeep(now: datetime | None = None) -> datetime:
    now = now or datetime.now(timezone.utc)
    t = now.replace(hour=UPKEEP_HOUR, minute=0, second=0, microsecond=0)
    t += timedelta(days=(UPKEEP_WEEKDAY - now.weekday()) % 7)
    if t <= now:
        t += timedelta(days=7)
    return t


def fmt_left(seconds: float) -> str:
    s = max(int(seconds), 0)
    d, rem = divmod(s, 86400)
    h, rem = divmod(rem, 3600)
    m, sec = divmod(rem, 60)
    if d:
        return f"{d}d {h}h"
    if h:
        return f"{h}h {m:02d}m"
    if m:
        return f"{m}m {sec:02d}s"
    return f"{sec}s"


def cooldown_left(carrier: dict, now: float | None = None) -> float:
    import time
    until = (carrier or {}).get("cooldown_until")
    if not until:
        return 0.0
    return max(float(until) - (now if now is not None else time.time()), 0.0)


def upkeep_short(carrier: dict) -> int:
    """Credits the balance falls short of the week's upkeep; 0 when it
    covers it or the upkeep is not known."""
    try:
        upkeep = int(carrier.get("maintenance") or 0)
        balance = int(carrier.get("balance") or 0)
    except (TypeError, ValueError):
        return 0
    return max(upkeep - balance, 0) if upkeep else 0
