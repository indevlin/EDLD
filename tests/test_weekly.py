"""tests/test_weekly.py — weekly reset boundary and PowerPlay cycle merits."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core import weekly as W  # noqa: E402


def test_week_start_is_the_latest_thursday_0700_utc():
    assert W.iso(W.week_start("2026-11-07T21:49:07Z")) == "2026-11-05T07:00:00Z"
    assert W.iso(W.week_start("2026-11-05T06:59:59Z")) == "2026-10-29T07:00:00Z"
    assert W.iso(W.week_start("2026-11-05T07:00:00Z")) == "2026-11-05T07:00:00Z"
    assert W.iso(W.week_end("2026-11-07T21:49:07Z")) == "2026-11-12T07:00:00Z"


def test_until_reset():
    assert W.until_reset(W.parse("2026-11-08T21:56:00Z")) == "3d 09h"
    assert W.until_reset(W.parse("2026-11-12T05:00:00Z")) == "2h 00m"
    assert W.until_reset(W.parse("2026-11-12T06:48:00Z")) == "12m"


def _merit(ts, gained, total, power="Nakato Kaine"):
    return {"timestamp": ts, "event": "PowerplayMerits", "Power": power,
            "MeritsGained": gained, "TotalMerits": total}


def test_cycle_merits_from_the_server_total():
    cm = W.CycleMerits.rebuild([
        {"timestamp": "2026-10-30T21:43:46Z", "event": "Powerplay", "Power": "Nakato Kaine",
         "Rank": 153, "Merits": 1199564, "TimePledged": 1},
        _merit("2026-11-01T10:00:00Z", 1248, 1200812),
        _merit("2026-11-06T20:23:39Z", 61, 1200873),
        _merit("2026-11-06T20:23:41Z", 61, 1200873),       # repeat: nothing credited
        _merit("2026-11-06T20:23:44Z", 61, 1200934),
    ])
    assert cm.baseline == 1200812 and cm.total == 1200934
    assert cm.cycle(W.parse("2026-11-07T00:00:00Z")) == 122
    # A reset with nothing since: zero, never the pledge total.
    assert cm.cycle(W.parse("2026-11-12T07:00:01Z")) == 0


def test_a_pledge_boundary_restarts_the_count():
    cm = W.CycleMerits.rebuild([
        _merit("2026-09-01T10:00:00Z", 500, 90000, "Li Yong-Rui"),
        {"timestamp": "2026-09-04T15:00:42Z", "event": "PowerplayLeave", "Power": "Li Yong-Rui"},
        {"timestamp": "2026-09-04T15:00:54Z", "event": "PowerplayJoin", "Power": "Nakato Kaine"},
        _merit("2026-09-05T10:00:00Z", 1000, 1000),
    ])
    assert cm.power == "Nakato Kaine" and cm.cycle(W.parse("2026-09-06T00:00:00Z")) == 1000


def test_defect_carries_the_new_power():
    cm = W.CycleMerits()
    cm.feed({"timestamp": "2026-09-05T10:00:00Z", "event": "PowerplayDefect",
             "FromPower": "Li Yong-Rui", "ToPower": "Nakato Kaine"})
    assert cm.power == "Nakato Kaine" and cm.total == 0


def test_cycle_never_exceeds_the_pledge_total():
    cm = W.CycleMerits.rebuild([_merit("2026-11-06T10:00:00Z", 61, 5000)])
    assert cm.cycle(W.parse("2026-11-06T11:00:00Z")) <= cm.total
