"""tests/test_upload_mark.py — uploaders do not send the startup replay again.

EDLD replays the current journal at startup.
"""
from __future__ import annotations

import ast
from pathlib import Path
from types import SimpleNamespace

import pytest

from core.upload_mark import UploadMark

ROOT = Path(__file__).resolve().parent.parent
UPLOADERS = ("eddn", "edsm", "inara", "edastro")


class _Storage:
    def __init__(self, root: Path, name: str = "x") -> None:
        self.root, self.name = root, name

    @property
    def path(self) -> Path:
        return self.root / f"{self.name}.json"

    def _p(self, purpose):
        return self.root / f"{self.name}.{purpose}.json"

    def read_json(self, purpose=None):
        import json
        p = self._p(purpose)
        return json.loads(p.read_text()) if p.exists() else {}

    def write_json(self, data, purpose=None):
        import json
        self._p(purpose).write_text(json.dumps(data))


def _ev(ts):
    return {"event": "FSDJump", "timestamp": ts}


PRELOAD = SimpleNamespace(in_preload=True)
LIVE = SimpleNamespace(in_preload=False)


def test_first_run_has_no_mark_and_sends_everything(tmp_path):
    m = UploadMark(_Storage(tmp_path))
    assert not m.replayed(_ev("2026-10-20T10:00:00Z"), PRELOAD)


def test_a_restart_skips_what_the_last_run_handled(tmp_path):
    st = _Storage(tmp_path)
    first = UploadMark(st)
    for ts in ("2026-10-20T10:00:00Z", "2026-10-20T10:05:00Z"):
        first.advance(_ev(ts), LIVE)
    second = UploadMark(st)                      # a new run, read from disk
    assert second.replayed(_ev("2026-10-20T10:00:00Z"), PRELOAD)
    assert second.replayed(_ev("2026-10-20T10:05:00Z"), PRELOAD)
    # Played after the last run stopped: new, and sent.
    assert not second.replayed(_ev("2026-10-20T10:06:00Z"), PRELOAD)


def test_live_events_are_never_skipped(tmp_path):
    m = UploadMark(_Storage(tmp_path))
    m.advance(_ev("2026-10-20T10:05:00Z"), LIVE)
    assert not m.replayed(_ev("2026-10-20T10:00:00Z"), LIVE)


def test_the_replay_is_saved_by_the_next_live_event_or_on_stop(tmp_path):
    st = _Storage(tmp_path)
    m = UploadMark(st)
    m.advance(_ev("2026-10-20T10:00:00Z"), PRELOAD)   # first write is at once
    m.advance(_ev("2026-10-20T10:01:00Z"), PRELOAD)   # throttled
    assert st.read_json("sent")["through"] == "2026-10-20T10:00:00Z"
    m.save()
    assert st.read_json("sent")["through"] == "2026-10-20T10:01:00Z"
    m.advance(_ev("2026-10-20T10:02:00Z"), LIVE)
    assert st.read_json("sent")["through"] == "2026-10-20T10:02:00Z"


def test_the_mark_never_goes_backwards(tmp_path):
    st = _Storage(tmp_path)
    m = UploadMark(st)
    m.advance(_ev("2026-10-20T10:05:00Z"), LIVE)
    m.advance(_ev("2026-10-20T09:00:00Z"), LIVE)
    assert m.through == "2026-10-20T10:05:00Z"


def test_a_new_commander_reads_its_own_mark(tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    a.mkdir(); b.mkdir()
    st = _Storage(a)
    m = UploadMark(st)
    m.advance(_ev("2026-10-20T10:05:00Z"), LIVE)
    st.root = b                                   # the active commander changes
    assert m.through == ""
    assert not m.replayed(_ev("2026-10-20T10:00:00Z"), PRELOAD)


@pytest.mark.parametrize("name", UPLOADERS)
def test_each_uploader_goes_through_the_mark(name):
    src = (ROOT / "components" / f"{name}.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    cls = next(n for n in tree.body if isinstance(n, ast.ClassDef)
               and any(isinstance(f, ast.FunctionDef) and f.name == "on_event"
                       for f in n.body))
    on_event = next(f for f in cls.body
                    if isinstance(f, ast.FunctionDef) and f.name == "on_event")
    body = ast.unparse(on_event)
    assert "replayed(" in body and "advance(" in body and "_on_event(" in body
    # and the place it sends checks the flag
    assert src.count("_replaying") >= 3, "the send must be gated"
    unload = next(f for f in cls.body
                  if isinstance(f, ast.FunctionDef) and f.name == "on_unload")
    assert "save()" in ast.unparse(unload)
