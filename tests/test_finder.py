"""
tests/test_finder.py — the Navigation window's Nearby and Services tabs.

Spansh's answers are stood in for with records shaped like its systems and
stations searches, and the DSSA list like EDAstro's: services as loose
words, coordinates as strings. A DSSA carrier Spansh also lists appears once,
marked DSSA; a carrier no one may dock at is left out.
"""
from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.state import MonitorState  # noqa: E402
from core.survey import system_status  # noqa: E402


def test_system_status():
    assert system_status({"body_count": 2, "bodies": [{"type": "Star"}, {"type": "Planet"}]}) == "done"
    assert system_status({"body_count": 5, "bodies": [{"type": "Star"}, {"type": "Planet"}]}) == "partial"
    assert system_status({"body_count": 5, "bodies": [{"type": "Star"}]}) == "star"
    assert system_status({}) == "star"


def _finder(spansh):
    from components.finder import FinderPlugin
    import threading
    state = MonitorState()
    state.pilot_system, state.pilot_star_pos = "Here", [0.0, 0.0, 0.0]
    core = SimpleNamespace(state=state, _plugins={"spansh": spansh},
                           plugin_call=lambda *a, **k: None)
    p = FinderPlugin.__new__(FinderPlugin)
    p.core, p._dssa, p._dssa_at, p._lock, p.known_status = core, [], 0.0, threading.Lock(), {}
    return p


def test_nearby_marks_each_system_and_remembers_it_for_targeting():
    spansh = SimpleNamespace(systems_near=lambda coords, radius: [
        {"id64": 1, "name": "Here", "distance": 0, "body_count": 1,
         "bodies": [{"type": "Star", "is_main_star": True, "subtype": "G (White-Yellow) Star"}]},
        {"id64": 2, "name": "Near", "distance": 4.2, "body_count": 6,
         "bodies": [{"type": "Star"}, {"type": "Planet"}], "needs_permit": True},
        {"id64": 3, "name": "Far", "distance": 9.9, "body_count": 3, "bodies": [{"type": "Star"}]},
    ])
    p = _finder(spansh)
    res = p._run_nearby(p.core, {"from": "", "radius": "10", "show": "all"})
    assert "3 reported within 10 ly: 1 done, 1 partly scanned, 1 with only the star" in res.status
    labels = [r[1] for r in res.rows]
    assert labels == ["Here", "Near", "Far"]
    assert "permit" in res.rows[1][2] and "2/6 bodies" in res.rows[1][2]
    assert "G (White-Yellow) Star" in res.rows[0][2]
    assert p.known_status == {1: "done", 2: "partial", 3: "star"}
    todo = p._run_nearby(p.core, {"from": "", "radius": "10", "show": "todo"})
    assert [r[1] for r in todo.rows] == ["Near", "Far"]


def test_services_merges_dssa_carriers():
    stations = [
        {"name": "May Terminal", "type": "Coriolis Starport", "system_name": "A",
         "distance": 30.0, "distance_to_arrival": 558, "has_large_pad": True,
         "updated_at": "2026-10-20T00:00:00Z"},
        {"name": "TFF-34Z", "carrier_name": "DSSA Sleeper Service", "type": "Drake-Class Carrier",
         "system_name": "B", "distance": 12.0, "has_large_pad": True,
         "updated_at": "2026-10-24T00:00:00Z", "carrier_docking_access": "all"},
        {"name": "XYZ-123", "carrier_name": "Private", "type": "Drake-Class Carrier",
         "system_name": "C", "distance": 1.0, "has_large_pad": True,
         "updated_at": "2026-10-24T00:00:00Z", "carrier_docking_access": "none"},
    ]
    spansh = SimpleNamespace(stations_near=lambda coords, service, size=40: stations)
    p = _finder(spansh)
    p._dssa_list = lambda: [
        {"status": "Carrier Operational", "coords": {"x": "3", "y": "4", "z": "0"},
         "callsign": "ABC-DEF", "name": "DSSA Near One", "services": ["Repair", "Universal", "Cartographics"],
         "lastSeenSystem": "D", "lastSeenDate": "2026-10-01 10:00:00"},
        {"status": "Carrier Operational", "coords": {"x": "0", "y": "0", "z": "2000"},
         "callsign": "TFF-34Z", "name": "DSSA Sleeper Service", "services": ["UC"]},
        {"status": "Carrier Decommissioned", "coords": {"x": "1", "y": "0", "z": "0"},
         "callsign": "OLD-001", "name": "Gone", "services": ["UC"]},
        {"status": "Carrier Operational", "coords": {"x": "1", "y": "1", "z": "1"},
         "callsign": "VIS-001", "name": "Vista only", "services": ["Vista", "Genomics"]},
    ]
    res = p._run_services(p.core, {"service": "Universal Cartographics", "from": "",
                                   "carriers": True, "large_pad": False, "max_age": ""})
    names = [r[1] for r in res.rows]
    assert names == ["DSSA Near One (ABC-DEF)", "DSSA Sleeper Service (TFF-34Z)", "May Terminal"]
    assert "5.0 ly" in res.rows[0][2] and "DSSA" in res.rows[0][2]
    assert "DSSA" in res.rows[1][2]
    no_carriers = p._run_services(p.core, {"service": "Universal Cartographics", "from": "",
                                           "carriers": False, "large_pad": False, "max_age": ""})
    assert [r[1] for r in no_carriers.rows] == ["May Terminal"]
