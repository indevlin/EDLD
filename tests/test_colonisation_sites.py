"""tests/test_colonisation_sites.py — site tracking: manual clear, inactivity clear, empty text."""
from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.state import MonitorState  # noqa: E402


def _ago(days: float) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")


class _Store:
    def __init__(self, data=None):
        self.data = dict(data or {})

    def read_json(self, *_a):
        return json.loads(json.dumps(self.data))

    def write_json(self, d, *_a):
        self.data = json.loads(json.dumps(d))


def _plugin(store=None, journal_dir=None):
    from components.colonisation import ColonisationPlugin
    state = MonitorState()
    state.colonisation_sites, state.colonisation_docked = [], False
    state.in_preload = False
    core = SimpleNamespace(state=state, gui_queue=None, journal_dir=journal_dir)
    p = ColonisationPlugin.__new__(ColonisationPlugin)
    p.core, p.storage = core, store or _Store()
    p._api_key, p._cmdr_name, p._last_depot = "", "", {}
    p._current_market_id = p._current_system_address = None
    p._own_fc_market_id, p._current_station_type, p._fc_linked = None, "", False
    p._restore()
    return p, state


def _depot(ts, mid=3965534210):
    return {"timestamp": ts, "event": "ColonisationConstructionDepot", "MarketID": mid,
            "ConstructionProgress": 0.1, "ConstructionComplete": False, "ConstructionFailed": False,
            "ResourcesRequired": [{"Name": "$Steel_name;", "Name_Localised": "Steel",
                                   "RequiredAmount": 100, "ProvidedAmount": 0}]}


def _site(mid, **kw):
    return {"market_id": mid, "system": "HIP 73225", "station": "Depot", "progress": 0.0,
            "complete": False, "failed": False, "resources": {}, **kw}


def test_a_site_with_no_contribution_for_seven_days_is_dropped():
    store = _Store({"sites": [_site(1, added=_ago(30)),
                              _site(2, added=_ago(30), last_contribution=_ago(2)),
                              _site(3, added=_ago(1))]})
    _p, state = _plugin(store)
    assert [s["market_id"] for s in state.colonisation_sites] == [2, 3]


def test_a_site_saved_before_timestamps_is_dated_from_the_journals(tmp_path):
    (tmp_path / "Journal.2026-10-09T020000.01.log").write_text(
        json.dumps(_depot("2026-10-09T02:35:12Z")) + "\n", encoding="utf-8")
    store = _Store({"sites": [_site(3965534210)]})
    _p, state = _plugin(store, journal_dir=tmp_path)
    assert state.colonisation_sites == []          # first seen 9 Oct, never contributed


def test_clear_by_hand_holds_until_a_later_depot_visit():
    p, state = _plugin()
    p.on_event(_depot(_ago(0.01)), state)
    assert len(state.colonisation_sites) == 1
    assert p.clear_site(3965534210) and state.colonisation_sites == []
    p.on_event(_depot(_ago(0.02)), state)          # replayed: before the clear
    assert state.colonisation_sites == []
    later = (datetime.now(timezone.utc) + timedelta(minutes=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
    p.on_event(_depot(later), state)               # docked there again
    assert len(state.colonisation_sites) == 1


def test_a_contribution_keeps_a_site_active():
    p, state = _plugin()
    p.on_event(_depot(_ago(0.5)), state)
    now = _ago(0)
    p.on_event({"timestamp": now, "event": "ColonisationContribution", "MarketID": 3965534210,
                "Contributions": [{"Name": "$Steel_name;", "Name_Localised": "Steel", "Amount": 5}]},
               state)
    assert state.colonisation_sites[0]["last_contribution"] == now


def test_the_window_offers_clear_and_says_when_there_is_nothing():
    from core.windows.objectives import colonisation
    from core import panel_actions
    p, state = _plugin()
    core = SimpleNamespace(state=state, _plugins={"colonisation": p})
    assert colonisation(core).rows == [("text", "No recent colonization activity", "dim")]
    p.on_event(_depot(_ago(0.01)), state)
    rows = colonisation(core).rows
    clear = [r for r in rows if r[0] == "kv" and len(r) > 4]
    assert clear and clear[0][4] == "clear:3965534210"
    assert panel_actions.run(core, "colonisation.colonisation", "clear:3965534210")["ok"]
    assert state.colonisation_sites == []
