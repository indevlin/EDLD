"""tests/test_community_goals.py — community goals: the journal's sign-ups,
the goals open to join from CAPI and Inara, and the Missions tab's section.

The events are the commander's own, from the journals of 22 October to
11 November 2026.
"""
from __future__ import annotations

import json
import queue
import sys
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core import community_goals as CG  # noqa: E402
from core.state import MonitorState  # noqa: E402
from core.windows import objectives as O, wire_rows  # noqa: E402

NOW = datetime(2026, 11, 11, 5, 40, tzinfo=timezone.utc)

SORBAGO = {"CGID": 866, "Title": "Defend Sorbago Mastopolos Mining Inc in Sorbago",
           "SystemName": "Sorbago", "MarketName": "Hencke Orbital",
           "Expiry": "2026-11-19T11:00:00Z", "IsComplete": False,
           "CurrentTotal": 39533231614, "PlayerContribution": 0, "NumContributors": 4875,
           "TopTier": {"Name": "Tier 5", "Bonus": ""}, "TopRankSize": 10,
           "PlayerInTopRank": False, "TierReached": "Tier 2",
           "PlayerPercentileBand": 100, "Bonus": 70000000}
COMBAT = {"CGID": 865, "Title": "Faulcon DeLacy Combat Initiative", "SystemName": "HR 8061",
          "MarketName": "Bowen Dock", "Expiry": "2026-10-29T10:00:00Z", "IsComplete": True,
          "CurrentTotal": 168724760846, "PlayerContribution": 2215309,
          "NumContributors": 10629, "TopTier": {"Name": "Tier 5", "Bonus": ""},
          "TopRankSize": 10, "PlayerInTopRank": False, "TierReached": "Tier 2",
          "PlayerPercentileBand": 75, "Bonus": 140000000}
MINING = {"CGID": 863, "Title": "Faulcon DeLacy Mining Initiative  ", "SystemName": "Reorte",
          "MarketName": "Ising Gateway", "Expiry": "2026-10-29T10:00:00Z", "IsComplete": False,
          "CurrentTotal": 1, "PlayerContribution": 3726, "NumContributors": 5000,
          "TopTier": {"Name": "Tier 6", "Bonus": ""}, "TierReached": "Tier 4",
          "PlayerPercentileBand": 50, "Bonus": 200000000}


def _ev(event, **kw):
    return {"timestamp": "2026-11-11T05:36:47Z", "event": event, **kw}


class _Store:
    def __init__(self, data=None):
        self.data = data or {}

    def read_json(self):
        return self.data

    def write_json(self, data):
        self.data = json.loads(json.dumps(data))


def _plugin(store=None):
    from components.community_goals import CommunityGoalsPlugin
    state = MonitorState()
    p = CommunityGoalsPlugin.__new__(CommunityGoalsPlugin)
    p.core = SimpleNamespace(state=state, gui_queue=queue.Queue())
    p.storage = store or _Store()
    p._restore()
    return p, state


# ── The journal ───────────────────────────────────────────────────────────────

def test_a_journal_goal_reads_as_the_game_wrote_it():
    g = CG.from_journal(COMBAT)
    assert g["id"] == 865 and g["title"] == "Faulcon DeLacy Combat Initiative"
    assert (g["station"], g["system"]) == ("Bowen Dock", "HR 8061")
    assert (g["tier"], g["top_tier"]) == (2, 5)
    assert (g["contribution"], g["percentile"], g["reward"]) == (2215309, 75, 140000000)
    assert g["complete"] and g["joined"] and g["expiry"] == "2026-10-29T10:00:00Z"
    # Trailing spaces in a title, as the game wrote one.
    assert CG.from_journal(MINING)["title"] == "Faulcon DeLacy Mining Initiative"


def test_each_list_replaces_the_last_and_a_reward_removes_its_goal():
    p, s = _plugin()
    p.on_event(_ev("CommunityGoal", CurrentGoals=[MINING, COMBAT]), s)
    assert sorted(s.cg_joined) == [863, 865]
    p.on_event(_ev("CommunityGoalReward", CGID=863, Name=MINING["Title"],
                   System="Reorte", Reward=200000000), s)
    assert sorted(s.cg_joined) == [865]
    # Joined: held at once, filled in by the list that follows.
    p.on_event(_ev("CommunityGoalJoin", CGID=866, Name=SORBAGO["Title"], System="Sorbago"), s)
    assert s.cg_joined[866]["contribution"] == 0 and s.cg_joined[866]["system"] == "Sorbago"
    p.on_event(_ev("CommunityGoal", CurrentGoals=[SORBAGO, COMBAT]), s)
    assert s.cg_joined[866]["station"] == "Hencke Orbital"
    # A goal no longer listed was handed in or lapsed without a reward event.
    p.on_event(_ev("CommunityGoal", CurrentGoals=[SORBAGO]), s)
    assert sorted(s.cg_joined) == [866]
    p.on_event(_ev("CommunityGoalDiscard", CGID=866, Name=SORBAGO["Title"], System="Sorbago"), s)
    assert s.cg_joined == {}
    assert p.core.gui_queue.get_nowait() == ("mission_update", None)


def test_a_new_session_starts_empty_and_the_list_survives_a_restart():
    p, s = _plugin()
    p.on_event(_ev("CommunityGoal", CurrentGoals=[COMBAT]), s)
    # Restored from storage, as when the journal replayed at start-up holds
    # no session of its own.
    p2, s2 = _plugin(_Store(p.storage.data))
    assert list(s2.cg_joined) == [865] and s2.cg_joined[865]["reward"] == 140000000
    # The game writes no list at start-up when there is nothing signed up for.
    p2.on_event(_ev("LoadGame", Commander="MERRICK CALBRUIN"), s2)
    assert s2.cg_joined == {} and p2.storage.data == {"joined": []}


# ── CAPI and Inara ────────────────────────────────────────────────────────────

CAPI = {"activeCommunityGoals": [
    {"id": "866", "title": "Defend Sorbago Mastopolos Mining Inc in Sorbago",
     "expiry": "2026-11-19 11:00:00", "market_name": "Hencke Orbital",
     "starsystem_name": "Sorbago", "activityType": "combat",
     "objective": "Hand in combat bonds at Hencke Orbital",
     "commander_progress": {"currentQty": 39533231614, "numContributors": 4875,
                            "commanderContributionQty": None, "commanderPercentile": 100,
                            "commanderSubscribed": True, "complete": False}},
    {"id": "867", "title": "Shinrarta Dezhra Trade Drive", "expiry": "2026-11-18T10:00:00Z",
     "market_name": "Jameson Memorial", "starsystem_name": "Shinrarta Dezhra",
     "objective": "Deliver gold",
     "commander_progress": {"currentQty": 120, "numContributors": 40,
                            "commanderContributionQty": None, "commanderSubscribed": False,
                            "complete": False}},
    {"id": "860", "title": "Over Already", "expiry": "2026-11-01T10:00:00Z",
     "market_name": "X", "starsystem_name": "Y",
     "commander_progress": {"commanderSubscribed": False, "complete": True}},
]}

INARA = [
    {"communitygoalName": "Shinrarta Dezhra  Trade Drive", "starsystemName": "Shinrarta Dezhra",
     "stationName": "Jameson Memorial", "goalExpiry": "2026-11-18T10:00:00+00:00",
     "tierReached": 1, "tierMax": 8, "contributorsNum": 41, "contributionsTotal": 130,
     "isCompleted": False, "goalObjectiveText": "Deliver gold to Jameson Memorial"},
    {"communitygoalName": "Achenar Exploration Survey", "starsystemName": "Achenar",
     "stationName": "Dawes Hub", "goalExpiry": "2026-11-20T10:00:00+00:00",
     "tierReached": 0, "tierMax": 5, "contributorsNum": 12, "contributionsTotal": 9,
     "isCompleted": False, "goalObjectiveText": "Sell exploration data"},
    {"communitygoalName": "Faulcon DeLacy Combat Initiative", "starsystemName": "HR 8061",
     "stationName": "Bowen Dock", "goalExpiry": "2026-10-29T10:00:00+00:00",
     "tierReached": 2, "tierMax": 5, "isCompleted": True,
     "goalObjectiveText": "Hand in combat bonds"},
]


def test_capi_reads_frontiers_shape():
    goals = CG.from_capi(CAPI)
    assert [g["id"] for g in goals] == [866, 867, 860]
    assert goals[0]["joined"] and goals[0]["station"] == "Hencke Orbital"
    assert goals[0]["expiry"] == "2026-11-19T11:00:00Z"        # no zone: UTC
    assert not goals[1]["joined"] and goals[1]["contribution"] == 0
    assert CG.from_capi({}) == [] and CG.from_capi(None) == []


def test_the_capi_extractor_fills_state():
    from core.data import CAPISource
    s = MonitorState()
    CAPISource._extract_communitygoals(SimpleNamespace(), CAPI, s)
    assert [g["title"] for g in s.capi_community_goals][:2] == [
        "Defend Sorbago Mastopolos Mining Inc in Sorbago", "Shinrarta Dezhra Trade Drive"]


def test_merged_puts_sign_ups_first_then_goals_open_to_join_once_each():
    joined = {866: CG.from_journal(SORBAGO), 865: CG.from_journal(COMBAT)}
    goals = CG.merged(joined, CG.from_capi(CAPI), CG.from_inara(INARA), NOW)
    titles = [g["title"] for g in goals]
    assert titles == ["Defend Sorbago Mastopolos Mining Inc in Sorbago",   # running
                      "Faulcon DeLacy Combat Initiative",                  # to hand in
                      "Shinrarta Dezhra Trade Drive",                      # open, CAPI
                      "Achenar Exploration Survey"]                        # open, Inara
    # The journal's numbers stand; the objective comes from CAPI.
    assert goals[0]["contribution"] == 0 and goals[0]["percentile"] == 100
    assert goals[0]["objective"] == "Hand in combat bonds at Hencke Orbital"
    assert goals[1]["objective"] == "Hand in combat bonds"                # from Inara
    assert not goals[2]["joined"] and not goals[3]["joined"]


def test_a_sign_up_capi_has_seen_first_is_shown_as_signed_up():
    goals = CG.merged({}, CG.from_capi(CAPI), None, NOW)
    assert goals[0]["joined"] and goals[0]["id"] == 866
    assert [g["id"] for g in goals] == [866, 867]


# ── The Missions tab ──────────────────────────────────────────────────────────

def _core(state):
    return SimpleNamespace(state=state)


def test_no_goals_no_section():
    s = MonitorState()
    rows = O.missions(_core(s), NOW).rows
    assert rows == [("text", "No active missions", "dim")]


def test_the_section_under_the_missions():
    p, s = _plugin()
    p.on_event(_ev("CommunityGoal", CurrentGoals=[SORBAGO, COMBAT]), s)
    s.capi_community_goals = CG.from_capi(CAPI)
    rows = O.missions(_core(s), NOW).rows
    assert ("hdr", "Community Goals") in rows
    kv = [(r[1], r[2]) for r in rows if r[0] == "kv"]
    assert ("Ends in", "8d 05h") in kv and ("Tier", "2 of 5") in kv
    assert ("Your contribution", "2,215,309") in kv and ("Your band", "Top 75%") in kv
    assert ("Reward", "140.0M cr") in kv
    assert ("Signed up", "No") in kv
    # Nothing handed in to Sorbago yet: no band, no reward.
    assert ("Reward", "70.0M cr") not in kv and ("Your band", "Top 100%") not in kv
    claim = [r for r in rows if r[0] == "kv" and r[1] == "Status"]
    assert claim == [("kv", "Status", "Finished — hand in to claim", "val health-good")]
    # On EDAM: the heading a sub-heading, the claim in green.
    wire = wire_rows(rows)
    assert {"label": "Community Goals", "value": "", "kind": "sub"} in wire
    assert any(r.get("value") == "Finished — hand in to claim" and r.get("tone") == "good"
               for r in wire)
