"""
tests/test_location.py — the location follows the commander.

Two ways it stayed on the system just left:

* riding a fleet carrier. The game writes CarrierJump, not FSDJump, when the
  commander is aboard; nothing that keeps the location read it. From a real
  journal: aboard N2Z-N8M on 2026-10-20 as it jumped from Col 285 Sector NK-R
  b20-0 to Kitchang Mu, the header went on saying Col 285.
* a journal line read before the game had finished writing it. Both halves
  failed to parse and were skipped, so the event — most often a jump, the
  longest line the game writes — was lost, and the warning went to a terminal
  the dashboards had sent to /dev/null.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from components.commander import CommanderPlugin  # noqa: E402
from core import edcars as H  # noqa: E402
from core.journal import _complete_line  # noqa: E402
from core.state import MonitorState  # noqa: E402


def _cmdr():
    state = MonitorState()
    core = SimpleNamespace(state=state, gui_queue=None,
                           emitter=SimpleNamespace(emit=lambda **k: None))
    p = CommanderPlugin.__new__(CommanderPlugin)
    p.core = core
    p._star_pos_live = False
    return p, state


def _feed(p, state, *events):
    for ev in events:
        assert ev["event"] in p.SUBSCRIBED_EVENTS, ev["event"]
        p.on_event(dict(ev), state)


DOCKED_AT_CARRIER = {"event": "Docked", "StationName": "N2Z-N8M",
                     "StationType": "FleetCarrier",
                     "StarSystem": "Col 285 Sector NK-R b20-0"}
CARRIER_JUMP = {"timestamp": "2026-10-20T16:24:09Z", "event": "CarrierJump",
                "Docked": True, "StationName": "N2Z-N8M",
                "StationType": "FleetCarrier", "StarSystem": "Kitchang Mu",
                "Body": "Kitchang Mu 5", "BodyType": "Planet",
                "StarPos": [77.65625, -16.875, 135.25]}


def test_a_carrier_jump_moves_the_commander_aboard():
    p, state = _cmdr()
    _feed(p, state, DOCKED_AT_CARRIER)
    assert H.location_text(state) == "Col 285 Sector NK-R b20-0 · N2Z-N8M"
    _feed(p, state, CARRIER_JUMP)
    assert state.pilot_system == "Kitchang Mu"
    assert H.location_text(state) == "Kitchang Mu · N2Z-N8M"
    assert state.pilot_star_pos == [77.65625, -16.875, 135.25]


def test_a_carrier_jump_on_foot_aboard_names_the_body():
    p, state = _cmdr()
    _feed(p, state, {**CARRIER_JUMP, "Docked": False, "OnFoot": True})
    assert H.location_text(state) == "Kitchang Mu · 5"


def test_the_body_approached_in_supercruise():
    p, state = _cmdr()
    _feed(p, state, {"event": "FSDJump", "StarSystem": "Cephei Sector BA-A c22"},
          {"event": "ApproachBody", "StarSystem": "Cephei Sector BA-A c22",
           "Body": "Cephei Sector BA-A c22 1"})
    assert H.location_text(state) == "Cephei Sector BA-A c22 · 1"
    _feed(p, state, {"event": "LeaveBody", "StarSystem": "Cephei Sector BA-A c22",
                     "Body": "Cephei Sector BA-A c22 1"})
    assert H.location_text(state) == "Cephei Sector BA-A c22"


# ── Half-written journal lines ────────────────────────────────────────────────

def test_a_line_read_in_pieces_is_joined():
    line = json.dumps({"event": "FSDJump", "StarSystem": "Serda"}) + "\n"
    pending = [""]
    assert _complete_line(pending, line[:20]) is None
    assert _complete_line(pending, line[20:30]) is None
    assert _complete_line(pending, line[30:]) == line
    assert pending == [""]
    assert _complete_line(pending, "x\n") == "x\n"


def test_the_monitor_waits_for_the_rest_of_a_line(tmp_path, monkeypatch):
    """Drive monitor_journal itself: half an FSDJump, a pause, the rest."""
    from core import journal as J

    jfile = tmp_path / "Journal.2026-10-23T120000.01.log"
    jfile.write_text(json.dumps({"event": "Fileheader", "part": 1}) + "\n",
                     encoding="utf-8")
    jump = json.dumps({"timestamp": "2026-10-23T12:00:00Z", "event": "FSDJump",
                       "StarSystem": "Serda", "Factions": [{"Name": "x" * 3000}]}) + "\n"
    seen: list[str] = []
    writes = iter([jump[:1500], jump[1500:], None])

    def handle(line, *a, **k):
        seen.append(json.loads(line)["event"])

    def sleep(_s):
        nxt = next(writes)
        if nxt is None:
            raise KeyboardInterrupt
        with open(jfile, "a", encoding="utf-8") as f:
            f.write(nxt)

    monkeypatch.setattr(J, "handle_event", handle)
    monkeypatch.setattr(J.time, "sleep", sleep)
    monkeypatch.setattr(J, "bootstrap_last_session_end", lambda *a, **k: None)
    monkeypatch.setattr(J, "bootstrap_missions", lambda *a, **k: None)
    monkeypatch.setattr(J, "bootstrap_slf", lambda *a, **k: None)
    monkeypatch.setattr(J, "bootstrap_crew", lambda *a, **k: None)
    monkeypatch.setattr(J, "bootstrap_hull", lambda *a, **k: None)
    monkeypatch.setattr(J, "load_session_state", lambda *a, **k: None)
    monkeypatch.setattr(J, "find_latest_journal", lambda d: jfile)
    state = MonitorState()
    state.in_game = True
    emitter = SimpleNamespace(post_embed=lambda e: None, emit=lambda **k: None)
    cfg = SimpleNamespace(refresh=lambda: None, notify_levels={})
    try:
        J.monitor_journal(jfile, state, None, None, emitter, cfg, None,
                          tmp_path, [jfile], 0.0)
    except KeyboardInterrupt:
        pass
    assert seen == ["Fileheader", "FSDJump"]


def test_a_blank_line_is_not_a_parse_error(capsys):
    from core.journal import handle_event
    handle_event("\n", MonitorState(), None, None, None, None, None, Path("."))
    assert "parsing error" not in capsys.readouterr().out
