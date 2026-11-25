"""tests/test_upload_catchup.py — uploaders catch up on journals EDLD did not see,
and a first run sends Inara the commander's state, not old log entries."""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core import upload_catchup  # noqa: E402
from core.state import MonitorState  # noqa: E402
from core.upload_mark import UploadMark  # noqa: E402

NOW = datetime(2026, 11, 25, 12, 0, 0, tzinfo=timezone.utc)


class _Storage:
    def __init__(self, root: Path, through: str = "") -> None:
        self.root = root
        if through:
            (root / "x.sent.json").write_text(json.dumps({"through": through}))

    @property
    def path(self) -> Path:
        return self.root / "x.json"

    def read_json(self, purpose=None):
        p = self.root / (f"x.{purpose}.json" if purpose else "x.json")
        return json.loads(p.read_text()) if p.exists() else {}

    def write_json(self, data, purpose=None):
        (self.root / (f"x.{purpose}.json" if purpose else "x.json")).write_text(json.dumps(data))

    def file_path(self, name):
        return self.root / f"x.{name}"


class _Sender:
    def __init__(self):
        self.items = []

    def push(self, item):
        self.items.append(item)

    def flush(self):
        pass


def _journal(d: Path, name: str, fid: str | None, events: list[dict], part: int = 1) -> Path:
    lines = [{"timestamp": events[0]["timestamp"], "event": "Fileheader", "part": part, "gameversion": "4.3"}]
    if fid:
        lines.append({"timestamp": events[0]["timestamp"], "event": "Commander", "FID": fid, "Name": "X"})
    p = d / name
    p.write_text("".join(json.dumps(x) + "\n" for x in lines + events))
    return p


class _Up:
    def __init__(self, name, storage):
        self.PLUGIN_NAME, self._enabled, self.storage = name, True, storage
        self._mark, self.sent = UploadMark(storage), []

    def _upload_mark(self):
        return self._mark

    def on_event(self, ev, state):
        if not self._mark.replayed(ev, state):
            self.sent.append(ev.get("BodyName") or ev["event"])
        self._mark.advance(ev, state)


def _dispatch(*ups):
    return {"*": list(ups)}


def _setup(tmp_path):
    jd = tmp_path / "j"
    jd.mkdir()
    _journal(jd, "Journal.2026-11-10T100000.01.log", "F1", [
        {"timestamp": "2026-11-10T10:00:05Z", "event": "Scan", "BodyName": "before the mark"}])
    _journal(jd, "Journal.2026-11-20T100000.01.log", "F1", [
        {"timestamp": "2026-11-20T10:00:05Z", "event": "Scan", "BodyName": "sent last run"},
        {"timestamp": "2026-11-20T11:00:00Z", "event": "Scan", "BodyName": "missed 1"}])
    _journal(jd, "Journal.2026-11-20T120000.02.log", None, [
        {"timestamp": "2026-11-20T12:00:05Z", "event": "Scan", "BodyName": "missed 2"}], part=2)
    _journal(jd, "Journal.2026-11-21T100000.01.log", "F2", [
        {"timestamp": "2026-11-21T10:00:05Z", "event": "Scan", "BodyName": "another commander"}])
    _journal(jd, "Journal.2026-11-22T100000.01.log", "F1", [
        {"timestamp": "2026-11-22T10:00:05Z", "event": "Scan", "BodyName": "missed 3"}])
    cur = _journal(jd, "Journal.2026-11-24T100000.01.log", "F1", [
        {"timestamp": "2026-11-24T10:00:05Z", "event": "Scan", "BodyName": "current journal"}])
    return jd, cur


def test_catches_up_from_the_mark_for_this_commander_only(tmp_path, monkeypatch):
    monkeypatch.setattr(upload_catchup, "_done", False)
    jd, cur = _setup(tmp_path)
    (tmp_path / "s").mkdir()
    up = _Up("edsm", _Storage(tmp_path / "s", "2026-11-20T10:00:05Z"))
    upload_catchup.catch_up(cur, jd, MonitorState(), _dispatch(up), now=NOW)
    sent = [s for s in up.sent if s not in ("Fileheader", "Commander")]
    assert sent == ["missed 1", "missed 2", "missed 3"]
    assert up._mark.through == "2026-11-22T10:00:05Z", "the current journal's replay goes on from here"
    assert upload_catchup.catch_up(cur, jd, MonitorState(), _dispatch(up), now=NOW) == 0, "once per run"


def test_no_mark_no_catch_up(tmp_path, monkeypatch):
    monkeypatch.setattr(upload_catchup, "_done", False)
    jd, cur = _setup(tmp_path)
    (tmp_path / "s").mkdir()
    up = _Up("eddn", _Storage(tmp_path / "s"))
    assert upload_catchup.catch_up(cur, jd, MonitorState(), _dispatch(up), now=NOW) == 0
    assert up.sent == []


def test_at_most_thirty_days(tmp_path, monkeypatch):
    monkeypatch.setattr(upload_catchup, "_done", False)
    jd, cur = _setup(tmp_path)
    (tmp_path / "s").mkdir()
    up = _Up("edastro", _Storage(tmp_path / "s", "2026-01-01T00:00:00Z"))
    upload_catchup.catch_up(cur, jd, MonitorState(), _dispatch(up), now=datetime(2026, 12, 15, tzinfo=timezone.utc))
    sent = [s for s in up.sent if s not in ("Fileheader", "Commander")]
    assert sent == ["sent last run", "missed 1", "missed 2", "missed 3"], "nothing before 15 November"


def _inara(tmp_path, through=""):
    from components.inara import InaraPlugin
    p = InaraPlugin.__new__(InaraPlugin)
    p.core = SimpleNamespace(state=MonitorState(), gui_queue=None)
    (tmp_path / "i").mkdir(exist_ok=True)
    p.storage = _Storage(tmp_path / "i", through)
    p._enabled, p._reconciled, p._sender = True, True, _Sender()
    p._star_pos, p._ship_type, p._ship_id, p._rank_values = None, "anaconda", 7, {}
    p._cmdr_name = "X"
    p._seen_ship_ids, p._seen_ship_types, p._save_seen = set(), {}, lambda: None
    return p


EVENTS = [
    {"timestamp": "2026-11-24T10:00:00Z", "event": "Loadout", "Ship": "anaconda", "ShipID": 7, "Modules": []},
    {"timestamp": "2026-11-24T10:01:00Z", "event": "FSDJump", "StarSystem": "Sol", "StarPos": [0, 0, 0], "JumpDist": 5},
    {"timestamp": "2026-11-24T10:02:00Z", "event": "MissionAccepted", "MissionID": 1, "Name": "m"},
]


def test_inara_first_run_replay_sends_state_only(tmp_path):
    p = _inara(tmp_path)
    st = p.core.state
    st.in_preload = True
    for ev in EVENTS:
        p.on_event(dict(ev), st)
    names = [i["eventName"] for i in p._sender.items]
    assert "setCommanderShip" in names
    assert "addCommanderTravelFSDJump" not in names and "addCommanderMission" not in names
    st.in_preload = False
    p.on_event({"timestamp": "2026-11-24T10:05:00Z", "event": "FSDJump", "StarSystem": "Achenar",
                "StarPos": [1, 1, 1], "JumpDist": 9}, st)
    assert "addCommanderTravelFSDJump" in [i["eventName"] for i in p._sender.items], "live play is sent in full"


def test_inara_with_a_mark_replays_everything_after_it(tmp_path):
    p = _inara(tmp_path, "2026-11-24T09:00:00Z")
    st = p.core.state
    st.in_preload = True
    for ev in EVENTS:
        p.on_event(dict(ev), st)
    names = [i["eventName"] for i in p._sender.items]
    assert "addCommanderTravelFSDJump" in names and "addCommanderMission" in names
