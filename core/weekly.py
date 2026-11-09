"""core/weekly.py — the weekly reset (Thursday 07:00 UTC) and PowerPlay cycle merits.

week_start(at) is the latest reset at or before `at`; week_end(at) the next.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Iterable, Optional

RESET_WEEKDAY = 3          # Monday 0 … Thursday 3
RESET_HOUR = 7             # UTC

#: Events CycleMerits.feed reads.
PP_EVENTS = ("Powerplay", "PowerplayMerits", "PowerplayJoin",
             "PowerplayLeave", "PowerplayDefect")


def parse(ts) -> Optional[datetime]:
    """Journal timestamp → aware UTC datetime; None if unparseable."""
    if isinstance(ts, datetime):
        return ts if ts.tzinfo else ts.replace(tzinfo=timezone.utc)
    try:
        return datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None


def week_start(at: datetime | str | None = None) -> datetime:
    at = parse(at) if at is not None else datetime.now(timezone.utc)
    at = at or datetime.now(timezone.utc)
    start = at.replace(hour=RESET_HOUR, minute=0, second=0, microsecond=0)
    start -= timedelta(days=(at.weekday() - RESET_WEEKDAY) % 7)
    if start > at:
        start -= timedelta(days=7)
    return start


def week_end(at: datetime | str | None = None) -> datetime:
    return week_start(at) + timedelta(days=7)


def until_reset(now: datetime | None = None) -> str:
    """Time to the next reset: 3d 14h · 5h 02m · 12m."""
    now = now or datetime.now(timezone.utc)
    secs = max(0, int((week_end(now) - now).total_seconds()))
    d, h, m = secs // 86400, secs % 86400 // 3600, secs % 3600 // 60
    if d:
        return f"{d}d {h:02d}h"
    if h:
        return f"{h}h {m:02d}m"
    return f"{m}m"


def iso(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


class CycleMerits:
    """Merits this cycle for the current pledge."""

    def __init__(self) -> None:
        self.power: str = ""
        self.week: Optional[datetime] = None   # week_start of `total`
        self.baseline: int = 0                 # total at the end of the previous week
        self.total: Optional[int] = None       # latest server total

    def reset(self, power: str = "", at=None) -> None:
        """Pledge boundary: totals restart from zero."""
        self.power = power or ""
        self.week = week_start(at) if at is not None else None
        self.baseline = 0
        self.total = 0 if power else None

    def observe(self, total, at) -> None:
        if total is None:
            return
        total = int(total)
        week = week_start(at)
        if self.week is None:
            # First sight of the pledge: no earlier total, so no baseline.
            self.week, self.baseline = week, total
        elif week > self.week:
            self.baseline = self.total if self.total is not None else total
            self.week = week
        self.total = total

    def feed(self, ev: dict) -> None:
        name, at = ev.get("event"), ev.get("timestamp")
        if name == "PowerplayJoin":
            self.reset(ev.get("Power", ""), at)
        elif name == "PowerplayDefect":
            self.reset(ev.get("ToPower", "") or ev.get("Power", ""), at)
        elif name == "PowerplayLeave":
            self.reset("", at)
        elif name == "Powerplay":
            power = ev.get("Power") or ""
            if power != self.power:
                self.reset(power, None)
            self.observe(ev.get("Merits"), at)
        elif name == "PowerplayMerits":
            power = ev.get("Power") or ""
            if power and self.power and power != self.power:
                self.reset(power, None)
            self.power = self.power or power
            self.observe(ev.get("TotalMerits"), at)

    def cycle(self, now: datetime | None = None) -> int:
        """Merits since the latest reset; 0 when none observed since."""
        if self.total is None or self.week is None:
            return 0
        if week_start(now) > self.week:
            return 0
        return max(0, self.total - self.baseline)

    @classmethod
    def rebuild(cls, events: Iterable[dict], until: str = "") -> "CycleMerits":
        """Fed from journal events in order, stopping before `until`."""
        cm = cls()
        for ev in events:
            if until and str(ev.get("timestamp", "")) >= until:
                break
            cm.feed(ev)
        return cm
