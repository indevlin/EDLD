"""
tests/test_discoveries.py — unsold first discoveries, the rescan list a
death leaves, someone else scanning them on Spansh, and the commander's
firsts.
"""
from __future__ import annotations

import json
import sys
import threading
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from components.discoveries import Ledger, check_others, rebuild  # noqa: E402

JUMP = {"event": "FSDJump", "StarSystem": "Eol Prou AB-C d1-2", "SystemAddress": 77}


def _scan(body, found=False, ts="2026-10-01T10:00:00Z", star=False):
    ev = {"event": "Scan", "timestamp": ts, "BodyName": body, "SystemAddress": 77,
          "WasDiscovered": found, "ScanType": "Detailed"}
    ev["StarType" if star else "PlanetClass"] = "K" if star else "Icy body"
    return ev


def test_undiscovered_bodies_are_kept_until_sold():
    led = Ledger()
    led.apply(JUMP)
    assert led.apply(_scan("Eol Prou AB-C d1-2 A", star=True))
    assert led.apply(_scan("Eol Prou AB-C d1-2 1"))
    assert not led.apply(_scan("Eol Prou AB-C d1-2 2", found=True))
    assert not led.apply(_scan("Eol Prou AB-C d1-2 1"))           # the same body again
    led.apply({"event": "SAAScanComplete", "BodyName": "Eol Prou AB-C d1-2 1", "SystemAddress": 77})
    rec = led.unsold["77"]
    assert rec["name"] == "Eol Prou AB-C d1-2" and len(rec["bodies"]) == 2
    assert rec["bodies"]["Eol Prou AB-C d1-2 1"]["mapped"] is True
    assert led.apply({"event": "MultiSellExplorationData",
                      "Discovered": [{"SystemName": "Eol Prou AB-C d1-2", "NumBodies": 2}]})
    assert led.unsold == {}


def test_a_death_moves_them_to_the_rescan_list_and_a_rescan_takes_them_off():
    led = Ledger()
    led.apply(JUMP)
    led.apply(_scan("Eol Prou AB-C d1-2 1"))
    led.apply(_scan("Eol Prou AB-C d1-2 2"))
    assert led.apply({"event": "Died", "timestamp": "2026-10-02T00:00:00Z"})
    assert led.unsold == {} and led.lost_bodies() == 2
    assert led.lost["77"]["lost_at"] == "2026-10-02T00:00:00Z"
    led.apply(_scan("Eol Prou AB-C d1-2 1"))
    assert led.lost_bodies() == 1 and led.unsold_bodies() == 1
    led.apply(_scan("Eol Prou AB-C d1-2 2"))
    assert led.lost == {}
    # The old sale event names systems in a plain list.
    assert led.apply({"event": "SellExplorationData", "Systems": ["Eol Prou AB-C d1-2"]})
    assert led.unsold == {}


def test_rebuild_reads_every_journal(tmp_path):
    lines = [JUMP, _scan("Eol Prou AB-C d1-2 1"), {"event": "Music"},
             {"event": "FSDJump", "StarSystem": "Other", "SystemAddress": 88},
             dict(_scan("Other 1"), SystemAddress=88)]
    (tmp_path / "Journal.2026-10-01T100000.01.log").write_text("\n".join(json.dumps(x) for x in lines[:3]))
    (tmp_path / "Journal.2026-10-02T100000.01.log").write_text("\n".join(json.dumps(x) for x in lines[3:]))
    led = rebuild(tmp_path)
    assert sorted(r["name"] for r in led.unsold.values()) == ["Eol Prou AB-C d1-2", "Other"]


def test_someone_else_scanning_them_is_found_on_spansh():
    led = Ledger()
    led.apply(JUMP)
    led.apply(_scan("Eol Prou AB-C d1-2 1", ts="2026-10-01T10:00:00Z"))
    led.apply(_scan("Eol Prou AB-C d1-2 2", ts="2026-10-01T10:05:00Z"))
    dumps = {77: {"system": {"bodies": [
        # The commander's own upload, minutes later: not someone else.
        {"name": "Eol Prou AB-C d1-2 1", "updateTime": "2026-10-01 10:03:00+00"},
        {"name": "Eol Prou AB-C d1-2 2", "updateTime": "2026-10-03 18:00:00+00"}]}}}
    found = check_others(led, lambda i: dumps.get(i, {}))
    assert found["77"]["bodies"] == ["Eol Prou AB-C d1-2 2"]
    assert check_others(led, lambda i: None) == {}            # Spansh out of reach


def _plugin(tmp_path, ledger):
    from components.discoveries import DiscoveriesPlugin
    said = []
    p = DiscoveriesPlugin.__new__(DiscoveriesPlugin)
    p.core = SimpleNamespace(state=SimpleNamespace(in_preload=False), notify_levels={}, _plugins={},
                             plugin_call=lambda *a, **k: None,
                             emitter=SimpleNamespace(emit=lambda **k: said.append(k["msg_term"])))
    saved = {}
    p.storage = SimpleNamespace(write_json=lambda d, purpose=None: saved.update({purpose: d}),
                                read_json=lambda purpose=None: saved.get(purpose, {}))
    p._lock, p._ready, p._pending, p._checked_at, p.ledger = threading.Lock(), True, [], 0.0, ledger
    return p, said, saved


def test_the_tab_and_the_edam_summary(tmp_path):
    led = Ledger()
    led.apply(JUMP)
    led.apply(_scan("Eol Prou AB-C d1-2 1"))
    p, said, saved = _plugin(tmp_path, led)
    tab = p.navigation_tool_tabs()[0]
    res = tab.run(p.core, {"kind": "unsold", "check": False})
    assert "1 systems, 1 bodies: unsold first discoveries" in res.status
    assert res.rows == [("kv", "Eol Prou AB-C d1-2", "1 body")]
    p.on_event({"event": "Died", "timestamp": "2026-10-02T00:00:00Z"}, p.core.state)
    assert said == ["Unsold data lost: 1 systems are on the rescan list"]
    assert saved["ledger"]["lost"]["77"]["name"] == "Eol Prou AB-C d1-2"
    res = tab.run(p.core, {"kind": "rescan"})
    assert res.rows[0][2] == "1 body · lost 2026-10-02"
    assert ("To rescan", "1 systems") in p.summary_rows()


def test_replayed_events_are_not_counted_again(tmp_path):
    p, said, saved = _plugin(tmp_path, Ledger())
    p.core.state.in_preload = True
    p.on_event(JUMP, p.core.state)
    p.on_event(_scan("Eol Prou AB-C d1-2 1"), p.core.state)
    assert p.ledger.unsold == {} and p.ledger._system[1] == "Eol Prou AB-C d1-2"
    p.core.state.in_preload = False
    p._ready = False
    p.on_event(_scan("Eol Prou AB-C d1-2 2"), p.core.state)      # while the rebuild runs
    assert len(p._pending) == 1
