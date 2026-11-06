"""
tests/test_disk_queue.py — queued uploads survive being re-sent, and Inara's
"slow down" is obeyed rather than argued with.
"""
from __future__ import annotations

import io
import json
import time
from pathlib import Path

import pytest

from core import disk_queue


def _queue(path: Path, msgs) -> None:
    with open(path, "w", encoding="utf-8") as f:
        for m in msgs:
            f.write(json.dumps({"queued_at": 1.0, "msg": m}) + "\n")


def _msgs(path: Path) -> list:
    if not path.exists():
        return []
    return [json.loads(l)["msg"] for l in path.read_text().splitlines() if l.strip()]


def _failing_sender(qf: Path, fail: set):
    """An uploader's _send_batch: whatever fails is appended to the queue."""
    sent = []

    def send(batch):
        for ev in batch:
            if ev["n"] in fail:
                with open(qf, "a", encoding="utf-8") as f:
                    f.write(json.dumps({"queued_at": 2.0, "msg": ev}) + "\n")
            else:
                sent.append(ev["n"])
    return send, sent


def test_a_batch_that_fails_again_is_kept(tmp_path):
    """The bug: drain sent the file, failures were appended to it, and then
    the file was deleted — failures and all."""
    qf = tmp_path / "x.queue.jsonl"
    _queue(qf, [{"n": i} for i in range(5)])
    send, sent = _failing_sender(qf, fail={1, 3})
    assert disk_queue.drain(qf, 2, send, "T") == 5
    assert sent == [0, 2, 4]
    assert [m["n"] for m in _msgs(qf)] == [1, 3]
    assert not qf.with_name(qf.name + ".draining").exists()


def test_a_drain_cut_short_is_picked_up_next_time(tmp_path):
    qf = tmp_path / "x.queue.jsonl"
    staging = qf.with_name(qf.name + ".draining")
    _queue(staging, [{"n": 7}, {"n": 8}])          # left by a stopped drain
    _queue(qf, [{"n": 9}])
    send, sent = _failing_sender(qf, fail=set())
    disk_queue.drain(qf, 10, send, "T")
    assert sent == [7, 8, 9]
    assert not qf.exists() and not staging.exists()


def test_the_batch_in_flight_is_still_on_disk(tmp_path):
    qf = tmp_path / "x.queue.jsonl"
    staging = qf.with_name(qf.name + ".draining")
    _queue(qf, [{"n": i} for i in range(4)])
    seen = []

    def send(batch):
        seen.append([m["n"] for m in _msgs(staging)])
    disk_queue.drain(qf, 2, send, "T")
    # While the first batch is sent all four are still recorded; while the
    # second is, the last two.
    assert seen == [[0, 1, 2, 3], [2, 3]]


def test_prepare_can_put_everything_back(tmp_path):
    qf = tmp_path / "x.queue.jsonl"
    _queue(qf, [{"n": 1}, {"n": 2}])
    send, sent = _failing_sender(qf, fail=set())
    assert disk_queue.drain(qf, 10, send, "T", prepare=lambda evs: None) == 0
    assert sent == [] and [m["n"] for m in _msgs(qf)] == [1, 2]


@pytest.mark.parametrize("name", ["inara", "edsm", "edastro"])
def test_the_uploaders_drain_through_it(name):
    src = (Path(__file__).resolve().parent.parent / "components" / f"{name}.py") \
        .read_text(encoding="utf-8")
    body = src[src.index("    def _drain_disk(self)"):]
    body = body[:body.index("\n    def ", 10)]
    assert "disk_queue import drain" in body and "unlink" not in body


# ── Inara ─────────────────────────────────────────────────────────────────────

class _Resp(io.BytesIO):
    status = 200

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


TOO_MUCH = {"header": {"eventStatus": 400, "eventStatusText":
            "Too much requests, slow down, cowboy. ;) ... The access to API was "
            "temporarily revoked (1 hour)."}}


def _inara_sender(tmp_path):
    from components import inara
    s = inara._Sender(lambda: "CMDR", "key", tmp_path / "inara.queue.jsonl")
    return inara, s


def test_inara_throttle_keeps_events_and_stops_asking(tmp_path, monkeypatch):
    inara, s = _inara_sender(tmp_path)
    calls = []

    def urlopen(req, timeout=None):
        calls.append(req)
        return _Resp(json.dumps(TOO_MUCH).encode())
    monkeypatch.setattr(inara.urllib.request, "urlopen", urlopen)
    s._send_batch([{"eventName": "addCommanderTravelDock", "n": 1}])
    assert len(calls) == 1
    assert s.gate.blocked()
    # Kept, not dropped as a "bad request".
    assert _msgs(s._queue_file) == [{"eventName": "addCommanderTravelDock", "n": 1}]
    # The next batch is kept without asking Inara at all.
    s._send_batch([{"eventName": "setCommanderCredits", "n": 2}])
    assert len(calls) == 1
    assert len(_msgs(s._queue_file)) == 2


def test_inara_pause_survives_a_restart(tmp_path):
    inara, s = _inara_sender(tmp_path)
    s.gate.block(600)
    _, again = _inara_sender(tmp_path)
    assert again.gate.blocked()
    assert again.gate.take_turn() is False


def test_a_plain_bad_request_is_still_dropped(tmp_path, monkeypatch):
    inara, s = _inara_sender(tmp_path)
    bad = {"header": {"eventStatus": 400, "eventStatusText": "Invalid API key."}}
    monkeypatch.setattr(inara.urllib.request, "urlopen",
                        lambda req, timeout=None: _Resp(json.dumps(bad).encode()))
    s._send_batch([{"eventName": "x"}])
    assert not s.gate.blocked()
    assert _msgs(s._queue_file) == []


def test_uploads_and_goal_fetches_share_one_pace(tmp_path, monkeypatch):
    inara, s = _inara_sender(tmp_path)
    slept = []
    monkeypatch.setattr(inara.time, "sleep", lambda t: slept.append(t))
    assert s.gate.take_turn() is True        # an upload
    assert s.gate.take_turn() is True        # a goal fetch straight after
    assert slept and slept[0] > inara.SEND_INTERVAL_S - 1


def test_is_throttled():
    from components.inara import is_throttled
    assert is_throttled(400, TOO_MUCH["header"]["eventStatusText"])
    assert is_throttled(429, "")
    assert not is_throttled(400, "Invalid API key.")
    assert not is_throttled(200, "Too much requests")
