"""tests/test_missions_board.py — the Missions tab and the board behind it.
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.state import MonitorState  # noqa: E402
from core.windows import objectives as O  # noqa: E402

NAME = "Mission_Massacre_Legal_Military"
SRC, TGT, SYS = "Alioth Independents", "LHS 2637 Ring", "LHS 2637"


def _ev(ts, event, **kw):
    return {"timestamp": f"2026-11-02T{ts}Z", "event": event, **kw}


def _massacre(ts, mid, kc, reward=500_000):
    return _ev(ts, "MissionAccepted", Faction=SRC, Name=NAME, TargetFaction=TGT,
               KillCount=kc, DestinationSystem=SYS, Reward=reward,
               TargetType="$MissionUtil_FactionTag_Pirate;", MissionID=mid,
               Expiry="2026-11-09T19:57:04Z")


def _redirect(ts, mid, name=NAME):
    return _ev(ts, "MissionRedirected", MissionID=mid, Name=name,
               NewDestinationSystem="Stheno", NewDestinationStation="Arc Station")


def _snapshot(ts, *missions):
    """missions: (id, name, expires-in-seconds[, passenger])."""
    return {"timestamp": f"2026-11-02T{ts}Z", "event": "Missions", "Failed": [], "Complete": [],
            "Active": [{"MissionID": m[0], "Name": m[1], "PassengerMission": bool(m[3:] and m[3]),
                        "Expires": m[2]} for m in missions]}


DELIVERY = _ev("18:00:00", "MissionAccepted", Faction="Eurybia Blue Mafia",
               Name="Mission_DeliveryWing_Boom", LocalisedName="Wing delivery",
               Commodity="$EvacuationShelter_Name;", Commodity_Localised="Evacuation Shelter",
               Count=2890, DestinationSystem="Hyades Sector", DestinationStation="Ochoa City",
               Expiry="2026-11-03T18:00:00Z", Wing=True, Reward=5_000_000, MissionID=7)
COURIER = _ev("18:01:00", "MissionAccepted", Faction="Eurybia Blue Mafia",
              Name="Mission_Courier_Engineer", LocalisedName="Engineer Invitation Contract",
              DestinationSystem="Hyades Sector RE-G b11-3", DestinationStation="Ochoa City",
              Expiry="2026-11-03T18:01:00Z", Wing=False, MissionID=8)


def _depot(ts, mid, delivered, total, collected=None):
    return _ev(ts, "CargoDepot", MissionID=mid, UpdateType="Deliver", Count=1,
               ItemsCollected=delivered if collected is None else collected,
               ItemsDelivered=delivered, TotalItemsToDeliver=total, Progress=0.0)


# ── The component ─────────────────────────────────────────────────────────────

class _Store:
    def __init__(self):
        self.data = {}

    def read_json(self, *_a):
        return json.loads(json.dumps(self.data))

    def write_json(self, d, *_a):
        self.data = json.loads(json.dumps(d))


def _component(journal_dir=None, store=None):
    from components.missions import MissionsPlugin
    said: list[str] = []
    state = MonitorState()
    state.in_preload = False
    core = SimpleNamespace(
        state=state, gui_queue=None, journal_dir=journal_dir,
        notify_levels={"MissionUpdate": 1, "AllMissionsReady": 1},
        app_settings={"FullStackSize": 20},
        emitter=SimpleNamespace(emit=lambda **kw: said.append(kw.get("msg_term", ""))),
        register_block=lambda *a, **k: None)
    p = MissionsPlugin.__new__(MissionsPlugin)
    p.storage = store or _Store()
    p.core = core
    p._restore()
    return p, state, said


def _write(path: Path, events):
    path.write_text("".join(json.dumps(e) + "\n" for e in events), encoding="utf-8")


def test_a_redirect_and_a_turn_in_update_the_stack_live():
    """Both used to be shadowed by the general arm before them."""
    p, state, said = _component()
    p.on_event(_snapshot("19:00:00"), state)
    for e in (_massacre("19:57:04", 1, 2), _massacre("19:57:09", 2, 6), _redirect("20:12:48", 1)):
        p.on_event(e, state)
    assert state.missions_complete == 1 and state.massacre_redirected == {1}
    assert "Mission 1 of 2 complete (1 remaining)" in said
    assert state.all_missions[1]["status"] == "Ready"
    p.on_event(_ev("21:34:43", "MissionCompleted", MissionID=1, Name=NAME + "_name"), state)
    assert state.active_missions == [2] and list(state.mission_detail_map) == [2]
    assert state.stack_value == 500_000 and 1 not in state.all_missions
    assert state.massacre_redirected == set()


def test_the_board_is_rebuilt_from_the_journals_at_login(tmp_path):
    """Every type, accepted in an earlier session, with its progress up to
    the snapshot and not after."""
    _write(tmp_path / "Journal.2026-11-02T170000.01.log",
           [DELIVERY, COURIER, _massacre("18:02:00", 1, 20), _depot("18:30:00", 7, 1120, 2890),
            _redirect("18:40:00", 1)])
    login = _snapshot("19:00:00", (7, "Mission_DeliveryWing_Boom", 82800),
                      (8, "Mission_Courier_Engineer", 82860), (1, NAME, 600000),
                      (9, "Mission_Sightseeing", 3600, True))
    _write(tmp_path / "Journal.2026-11-02T185900.01.log",
           [login, _depot("19:10:00", 7, 1500, 2890)])
    p, state, _said = _component(tmp_path)
    state.in_preload = True
    p.on_event(login, state)
    board = state.all_missions
    assert board[7]["commodity"] == "Evacuation Shelter" and board[7]["wing"]
    assert (board[7]["delivered"], board[7]["total"]) == (1120, 2890)     # not 1500: after
    assert board[8]["dest_station"] == "Ochoa City" and board[8]["category"] == "Courier"
    assert board[1]["status"] == "Ready" and state.massacre_redirected == {1}
    assert state.missions_complete == 1                  # redirected while EDLD was closed
    # Never accepted in the journals: what the snapshot says, as a passenger.
    assert board[9]["category"] == "Passenger"
    assert board[9]["expiry"] == "2026-11-02T20:00:00Z"
    # Then the replay carries it on.
    p.on_event(_depot("19:10:00", 7, 1500, 2890), state)
    assert board[7]["delivered"] == 1500


def test_a_restart_counts_a_redirect_once(tmp_path):
    _write(tmp_path / "Journal.2026-11-02T190000.01.log",
           [_massacre("19:57:04", 1, 2), _massacre("19:57:09", 2, 6)])
    second = [{"timestamp": "2026-11-02T20:14:50Z", "event": "LoadGame"},
              _snapshot("20:15:00", (1, NAME, 600000), (2, NAME, 600000)),
              _redirect("20:16:00", 1)]
    _write(tmp_path / "Journal.2026-11-02T201450.01.log", second)
    store = _Store()
    for _start in range(2):
        p, state, said = _component(tmp_path, store)
        state.in_preload = True
        for e in second:
            if e["event"] == "LoadGame":
                state.reset_missions()
            p.on_event(e, state)
        assert state.missions_complete == 1 and state.massacre_redirected == {1}
        assert not [m for m in said if "complete" in m]          # preload says nothing


def test_a_failed_history_read_is_logged_and_the_snapshot_still_shows(tmp_path, monkeypatch):
    import core.journal_index as ji
    monkeypatch.setattr(ji, "index_for", lambda _d: (_ for _ in ()).throw(OSError("disk")))
    seen = []
    import core.debug as dbg
    monkeypatch.setattr(dbg, "exception", lambda msg, exc=None: seen.append(msg))
    p, state, _said = _component(tmp_path)
    p.on_event(_snapshot("19:00:00", (8, "Mission_Courier_Engineer", 3600)), state)
    assert seen and "mission history" in seen[0]
    assert state.all_missions[8]["category"] == "Courier"


# ── The window ────────────────────────────────────────────────────────────────

NOW = datetime(2026, 11, 2, 19, 0, tzinfo=timezone.utc)


def _rows(state):
    return O.missions(SimpleNamespace(state=state, app_settings={"FullStackSize": 20}), NOW).rows


def _stack_state(done=()):
    s = MonitorState()
    s.mission_detail_map = {
        1: {"faction": "A", "kill_count": 20, "reward": 5_000_000, "target_faction": TGT},
        2: {"faction": "A", "kill_count": 25, "reward": 4_000_000, "target_faction": TGT},
        3: {"faction": "B", "kill_count": 12, "reward": 1_000_000, "target_faction": TGT},
    }
    s.active_missions = [1, 2, 3]
    s.massacre_redirected = set(done)
    s.missions_complete = len(done)
    return s


def test_the_massacre_table_reports_missions_done_of_missions_held():
    rows = _rows(_stack_state(done={3}))
    assert rows[0] == ("table", "MASSACRE SOURCE FACTION",
                       [("KILLS", 5), ("MISSIONS", 8), ("REWARD", 6)])
    cells = {r[1]: (r[2], r[3]) for r in rows if r[0] == "cells"}
    assert cells["A"] == (["45", "00 / 02", "9.0M"], "val")
    assert cells["B"] == (["12", "01 / 01", "1.0M"], "val health-good")
    assert cells["Totals"] == (["45", "01 / 03", "10.0M"], "val")
    # No summary lines above the table: the MISSIONS column says it.
    assert not [r for r in rows if r[0] == "kv"]


def test_every_other_kind_gets_a_table_of_its_own():
    s = MonitorState()
    s.all_missions = {
        7: {"category": "Delivery", "name": "Wing delivery", "commodity": "Evacuation Shelter",
            "count": 2890, "delivered": 1120, "total": 2890, "wing": True,
            "expiry": "2026-11-03T04:10:00Z", "reward": 5_000_000, "status": "Active"},
        6: {"category": "Delivery", "commodity": "Evacuation Shelter", "count": 98,
            "expiry": "2026-11-02T19:45:00Z", "reward": 163_000, "status": "Active"},
        8: {"category": "Courier", "dest_station": "Ochoa City", "dest_system": "Hyades",
            "expiry": "2026-11-09T21:00:00Z", "reward": 0, "status": "Ready"},
        9: {"category": "Donation", "faction": "Eurybia Blue Mafia", "donation": 1_000_000,
            "expiry": "2026-11-01T00:00:00Z", "reward": 0, "status": "Active"},
    }
    rows = _rows(s)
    heads = [(r[1], [c for c, _w in r[2]]) for r in rows if r[0] == "table"]
    assert heads == [("DELIVERY COMMODITY", ["TONS", "EXPIRES", "REWARD"]),
                     ("COURIER DESTINATION", ["EXPIRES", "REWARD"]),
                     ("DONATION FACTION", ["CREDITS", "EXPIRES", "REWARD"])]
    cells = [(r[1], r[2], r[3]) for r in rows if r[0] == "cells"]
    assert cells[0] == ("Evacuation Shelter  (Wing)", ["1120 / 2890", "9h 10m", "5.0M"], "val")
    assert cells[1] == ("Evacuation Shelter", ["00 / 98", "45m", "163k"], "val")
    assert cells[2] == ("Totals", ["1120 / 2988", "", "5.2M"], "val")
    assert cells[3] == ("Ochoa City · Hyades", ["READY", "—"], "val health-good")
    assert cells[4] == ("Eurybia Blue Mafia", ["1.0M", "EXPIRED", "—"], "val")


def test_time_left():
    assert O.time_left("2026-11-09T21:30:00Z", NOW) == "7d 02h"
    assert O.time_left("2026-11-02T21:05:00Z", NOW) == "2h 05m"
    assert O.time_left("2026-11-02T19:07:00Z", NOW) == "7m"
    assert O.time_left("2026-11-02T18:00:00Z", NOW) == "EXPIRED"
    assert O.time_left("", NOW) == "" and O.time_left("soon", NOW) == ""


def test_no_missions():
    s = MonitorState()
    s.capi_community_goals = []
    assert _rows(s) == [("text", "No active missions", "dim")]


# ── EDCARS: Settings on the rail ──────────────────────────────────────────────

def test_settings_is_the_last_pill_and_opens_options_without_leaving_the_section():
    pytest.importorskip("PySide6")
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication([])
    from gui.edcars import EdcarsRail, Ink
    opened = []
    rail = EdcarsRail(Ink("default"), lambda _sid: None, on_settings=lambda: opened.append(1))
    lay = rail.layout()
    widgets = [lay.itemAt(i).widget() for i in range(lay.count())]
    assert widgets.index(rail.settings) == len(rail.pills)       # after every section
    assert rail.settings.text() == "SETTINGS" and not rail.settings.isCheckable()
    rail.select("objectives")
    rail.settings.click()
    assert opened == [1] and rail.pills["objectives"].isChecked()
    assert EdcarsRail(Ink("default"), lambda _sid: None).settings is None


# ── A table's heading row is a heading ────────────────────────────────────────

def test_a_table_heading_is_drawn_as_a_heading_on_the_desktop():
    """It was a dim line; EDAM draws it in the accent, and now so do these."""
    pytest.importorskip("PySide6")
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication([])
    from core.windows import R
    from gui.block_base import GuiBlock, TableHdr
    from core.palette import rgb
    block = GuiBlock.__new__(GuiBlock)
    block.palette_map = rgb("default")
    out = block.render_rows([R.table("Massacre Source Faction",
                                     (("KILLS", 5), ("MISSIONS", 8), ("REWARD", 6)))])
    hdr = out[0]
    assert isinstance(hdr, TableHdr)
    assert hdr._key.property("role") == "section"
    assert "MASSACRE SOURCE FACTION" in hdr._key.text()
    assert hdr._val.property("role") == "highlight" and hdr._val.property("col") == "value"


def test_a_table_heading_is_drawn_as_a_heading_in_the_terminal():
    pytest.importorskip("textual")
    from core.windows import R
    from tui.block_base import TableHdr, TuiBlock
    out = TuiBlock.render_rows(TuiBlock.__new__(TuiBlock),
                               [R.table("Courier Destination", (("EXPIRES", 7), ("REWARD", 6)))])
    assert isinstance(out[0], TableHdr)
    assert out[0]._key_text == "COURIER DESTINATION" and out[0]._val_cls == "val hdr-val"


# ── Mining: ore held in the ship and the own carrier ──────────────────────────

def test_mining_missions_show_the_ore_held_beneath_them():
    s = MonitorState()
    s.all_missions = {
        1: {"category": "Mining", "commodity": "Bromellite", "commodity_key": "bromellite",
            "count": 80, "expiry": "2026-11-14T07:01:29Z", "reward": 5_576_000, "status": "Active"},
        2: {"category": "Mining", "commodity": "Bromellite", "commodity_key": "bromellite",
            "count": 118, "expiry": "2026-11-14T07:01:29Z", "reward": 8_125_800, "status": "Active"},
        3: {"category": "Mining", "commodity": "Samarium", "commodity_key": "samarium",
            "count": 36, "expiry": "2026-11-14T14:06:55Z", "reward": 8_126_733, "status": "Active"},
    }
    s.cargo_items = {"bromellite": {"count": 64}}
    s.assets_carrier_hold = {"bromellite": 150, "samarium": 10}
    s.assets_squadron_carrier_hold = {"samarium": 500}          # not counted
    rows = _rows(s)
    i = next(i for i, r in enumerate(rows) if r[0] == "table" and r[1] == "MINING ORE HELD")
    assert rows[i][2] == [("SHIP", 5), ("CARRIER", 7), ("HELD", 5)]
    held = {r[1]: (r[2], r[3]) for r in rows[i + 1:] if r[0] == "cells"}
    assert held["Bromellite"] == (["64", "150", "214"], "val health-good")      # 198 needed
    assert held["Samarium"] == (["0", "10", "10"], "val")                       # 36 needed


def test_the_mission_board_keys_a_commodity_as_the_hold_does():
    p, state, _said = _component()
    p.on_event(_snapshot("06:00:00"), state)
    p.on_event({"timestamp": "2026-11-07T07:01:40Z", "event": "MissionAccepted",
                "Faction": "Sirius Corporation", "Name": "Mission_Mining_Expansion",
                "Commodity": "$Bromellite_Name;", "Commodity_Localised": "Bromellite",
                "Count": 80, "MissionID": 1070644835}, state)
    entry = state.all_missions[1070644835]
    assert entry["category"] == "Mining" and entry["commodity_key"] == "bromellite"


def test_the_own_carrier_hold_follows_transfers_only_at_the_own_carrier():
    from components.assets import AssetsPlugin
    s = MonitorState()
    s.assets_carrier = {"carrier_id": 3715178496}
    s.assets_carrier_hold = {"bromellite": 100}
    p = AssetsPlugin.__new__(AssetsPlugin)
    p.core = SimpleNamespace(state=s, gui_queue=None)
    xfer = {"event": "CargoTransfer", "Transfers": [
        {"Type": "bromellite", "Count": 40, "Direction": "tocarrier"},
        {"Type": "samarium", "Count": 5, "Direction": "tocarrier"}]}
    p._carrier_hold_event("Docked", {"MarketID": 3713581568}, s)        # someone else's
    p._carrier_hold_event("MarketBuy", {"Type": "bromellite", "Count": 50}, s)
    assert s.assets_carrier_hold == {"bromellite": 100}
    p._carrier_hold_event("Docked", {"MarketID": 3715178496}, s)        # ours
    p._carrier_hold_event("CargoTransfer", xfer, s)
    p._carrier_hold_event("MarketBuy", {"Type": "bromellite", "Count": 30}, s)
    assert s.assets_carrier_hold == {"bromellite": 110, "samarium": 5}
