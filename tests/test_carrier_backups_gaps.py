"""
tests/test_carrier_backups_gaps.py — the carrier's clocks, journal backups,
and filling gaps in the EDSM flight log.
"""
from __future__ import annotations

import gzip
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core import carrier_time as CT  # noqa: E402


# ── Carrier ───────────────────────────────────────────────────────────────────

def test_upkeep_is_thursday_at_seven_utc():
    wed = datetime(2026, 10, 21, 12, 0, tzinfo=timezone.utc)
    assert CT.next_upkeep(wed) == datetime(2026, 10, 22, 7, 0, tzinfo=timezone.utc)
    thu_after = datetime(2026, 10, 22, 7, 0, 1, tzinfo=timezone.utc)
    assert CT.next_upkeep(thu_after) == datetime(2026, 10, 29, 7, 0, tzinfo=timezone.utc)
    thu_before = datetime(2026, 10, 22, 6, 59, tzinfo=timezone.utc)
    assert CT.next_upkeep(thu_before).day == 22


def test_cooldown_and_shortfall():
    c = {"cooldown_until": 1000.0, "maintenance": 9_000_000, "balance": 4_000_000}
    assert CT.cooldown_left(c, now=800.0) == 200.0
    assert CT.cooldown_left(c, now=1200.0) == 0.0
    assert CT.upkeep_short(c) == 5_000_000
    assert CT.upkeep_short({"balance": 1}) == 0
    assert CT.fmt_left(200) == "3m 20s" and CT.fmt_left(90061) == "1d 1h"


def test_a_completed_jump_starts_the_cooldown_and_the_tab_shows_it():
    from components.assets import AssetsPlugin
    from core.ui_helpers import carrier_display_sections
    state = SimpleNamespace(in_preload=True, assets_carrier={"carrier_id": 7, "name": "X",
                            "callsign": "ABC-123", "system": "A"}, assets_squadron_carrier=None)
    p = AssetsPlugin.__new__(AssetsPlugin)
    p.core = SimpleNamespace(state=state, _plugins={}, gui_queue=None, app_settings={})
    p._pending_jumps = {"7": {"system": "B", "departure": "2026-10-25T10:00:00Z"}}
    p._complete_carrier_jump(7, "B", state, {"event": "CarrierLocation",
                                             "timestamp": "2026-10-25T10:01:00Z"})
    until = state.assets_carrier["cooldown_until"]
    assert until == CT.parse_ts("2026-10-25T10:01:00Z") + 300
    rows = dict(dict(carrier_display_sections(state.assets_carrier))["Location & access"])
    assert rows["Jump"] == "Ready"          # long past
    fin = dict(dict(carrier_display_sections(state.assets_carrier))["Finance"])
    assert fin["Next upkeep"].startswith("Thu 07:00 UTC")


# ── Backups ───────────────────────────────────────────────────────────────────

def test_backups_copy_new_and_grown_journals_only(tmp_path):
    from components.backups import backup_journals
    j, dest = tmp_path / "j", tmp_path / "b"
    j.mkdir()
    (j / "Journal.2026-10-01T100000.01.log").write_text('{"event":"Fileheader"}\n')
    (j / "Journal.2026-10-02T100000.01.log").write_text('{"event":"Fileheader"}\n')
    (j / "Status.json").write_text("{}")
    assert backup_journals(j, dest) == (2, 2)
    assert backup_journals(j, dest) == (0, 2)
    with (j / "Journal.2026-10-02T100000.01.log").open("a") as f:
        f.write('{"event":"FSDJump"}\n')
    assert backup_journals(j, dest) == (1, 2)
    text = gzip.open(dest / "Journal.2026-10-02T100000.01.log.gz", "rt").read()
    assert "FSDJump" in text
    assert not (dest / "Status.json.gz").exists()


# ── EDSM gaps ─────────────────────────────────────────────────────────────────

def _journal(tmp_path):
    lines = [
        {"timestamp": "2026-10-20T10:00:00Z", "event": "Fileheader", "gameversion": "4.2.1", "build": "r1"},
        {"timestamp": "2026-10-20T10:00:01Z", "event": "LoadGame", "Commander": "T", "ShipID": 9,
         "Odyssey": True},
        {"timestamp": "2026-10-20T10:05:00Z", "event": "FSDJump", "StarSystem": "Alpha",
         "SystemAddress": 11, "StarPos": [1, 2, 3]},
        {"timestamp": "2026-10-20T10:07:00Z", "event": "FSDJump", "StarSystem": "Beta",
         "SystemAddress": 22, "StarPos": [4, 5, 6], "_logtime": "x"},
    ]
    (tmp_path / "Journal.2026-10-20T100000.01.log").write_text("\n".join(json.dumps(x) for x in lines))
    return tmp_path


def test_journal_jumps_carry_their_context(tmp_path):
    from components.edsm_gaps import journal_jumps
    jumps = journal_jumps(_journal(tmp_path), datetime(2026, 10, 19, tzinfo=timezone.utc))
    assert [j["event"]["StarSystem"] for j in jumps] == ["Alpha", "Beta"]
    assert jumps[0]["ship_id"] == 9 and jumps[0]["meta"]["gameversion"] == "4.2.1"
    assert jumps[0]["meta"]["odyssey"] is True


def test_only_the_jumps_edsm_lacks_are_sent(tmp_path, monkeypatch):
    import components.edsm_gaps as G
    monkeypatch.setattr(G, "datetime", type("D", (datetime,), {
        "now": staticmethod(lambda tz=None: datetime(2026, 10, 25, tzinfo=timezone.utc))}))
    monkeypatch.setattr(G.time, "sleep", lambda s: None)
    pushed = []
    sender = SimpleNamespace(push=pushed.append, flush=lambda: None)
    edsm = SimpleNamespace(_enabled=True, _key="k", _sender=sender)
    p = G.EDSMGapsPlugin.__new__(G.EDSMGapsPlugin)
    import threading
    p._busy = threading.Lock()
    p.core = SimpleNamespace(state=SimpleNamespace(pilot_name="T"), journal_dir=_journal(tmp_path),
                             _plugins={"edsm": edsm})
    p._get_logs = lambda cmdr, key, start, end: [
        {"system": "Alpha", "systemId64": 11, "date": "2026-10-20 10:05:30"}
    ] if start <= datetime(2026, 10, 20, 10, 5, tzinfo=timezone.utc) < end else []
    text = p.fill_gaps(7)
    assert text == "1 jump since 2026-10-20 sent to EDSM."
    (ev,) = pushed
    assert ev["StarSystem"] == "Beta" and ev["_systemAddress"] == 22
    assert ev["_shipId"] == 9 and ev["gameversion"] == "4.2.1" and "_logtime" not in ev
    assert p.fill_gaps(7).startswith("1 jump")      # still missing until EDSM has it
    edsm._enabled = False
    assert "EDSM uploads are off" in p.fill_gaps(7)
