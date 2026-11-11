"""
tests/test_updates.py — the newer-release check, its retries, and where a
newer release is shown.
"""
from __future__ import annotations

import ast
import io
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core import updates  # noqa: E402


class _Resp(io.BytesIO):
    def __init__(self, body: dict, status: int = 200):
        super().__init__(json.dumps(body).encode())
        self.status = status

    def __enter__(self):
        return self

    def __exit__(self, *a):
        pass


def _opener(*answers):
    """Answers in turn: a tag string, or an exception to raise."""
    seen, queue = [], list(answers)

    def opener(req, timeout=None):
        seen.append((req.full_url, timeout))
        a = queue.pop(0)
        if isinstance(a, BaseException):
            raise a
        return _Resp({"tag_name": a})
    opener.seen = seen
    return opener


def test_only_a_newer_tag_counts():
    assert updates.newer_release("indevlin/EDLD", "20261111", _opener("20261201")) == "20261201"
    assert updates.newer_release("indevlin/EDLD", "20261111", _opener("v20261111")) is None
    assert updates.newer_release("indevlin/EDLD", "20261111a", _opener("20261111")) is None
    op = _opener("20261201")
    updates.newer_release("indevlin/EDLD", "20261111", op)
    assert op.seen[0] == ("https://api.github.com/repos/indevlin/EDLD/releases/latest",
                          updates.TIMEOUT)


def test_a_failed_check_raises_rather_than_saying_nothing_is_new():
    with pytest.raises(OSError):
        updates.newer_release("indevlin/EDLD", "20261111", _opener(OSError("HTTP 403")))
    with pytest.raises(ValueError):
        updates.newer_release("indevlin/EDLD", "20261111", _opener(""))


def test_the_watcher_announces_each_new_tag_once_and_keeps_trying():
    got = []
    w = updates.UpdateWatcher("indevlin/EDLD", "20261111", got.append,
                              opener=_opener(OSError("down"), "20261201", "20261201",
                                             "20261215"))
    assert w.check_once() is False and got == []         # failure: retried later
    assert w.check_once() is True and got == ["20261201"]
    assert w.check_once() is True and got == ["20261201"]  # not again
    w.check_once()
    assert got == ["20261201", "20261215"]                 # a later release is


def test_the_watcher_thread_retries_soon_after_a_failure():
    import threading
    got, done = [], threading.Event()

    def on_newer(tag):
        got.append(tag)
        done.set()
    w = updates.UpdateWatcher("indevlin/EDLD", "20261111", on_newer,
                              opener=_opener(OSError("down"), "20261201"),
                              interval=60, retry=0.01)
    w.start()
    assert done.wait(2) and got == ["20261201"]
    w.stop()


def _alerts():
    from components.alerts import AlertsPlugin
    from core.state import MonitorState
    from queue import Queue
    p = AlertsPlugin.__new__(AlertsPlugin)
    p.core = SimpleNamespace(state=MonitorState(), gui_queue=Queue())
    p.alert_queue, p.faults = __import__("collections").deque(maxlen=5), []
    return p


def test_a_newer_release_stays_in_the_alerts_panel():
    a = _alerts()
    a.core.state.in_preload = True                  # shown even during replay
    a.push_notice("update", "⬆", "EDLD v20261201 available")
    a.push_notice("update", "⬆", "EDLD v20261215 available")
    alerts = a.get_alerts()
    assert [x["text"] for x in alerts] == ["EDLD v20261215 available"]
    assert alerts[0]["mono_time"] is None and not alerts[0]["urgent"]
    assert a.opacity_for(alerts[0]) == 1.0          # does not fade
    a.alert_queue.clear()                           # a context reset leaves it
    assert len(a.get_alerts()) == 1
    a.clear_alerts()
    assert a.get_alerts() == []


def test_edld_announces_through_the_watcher_everywhere():
    src = (ROOT / "edld.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    fn = next(n for n in ast.walk(tree)
              if isinstance(n, ast.FunctionDef) and n.name == "_announce_update")
    body = ast.get_source_segment(src, fn)
    for needle in ('push_notice("update"', '"update_notice"', "set_update_notice"):
        assert needle in body
    assert "_update_watcher.start()" in src
    # Not a one-shot check read once during start-up, its answer lost when late.
    prep = next(n for n in ast.walk(tree)
                if isinstance(n, ast.FunctionDef) and n.name == "_prepare_history")
    assert "update" not in ast.get_source_segment(src, prep).lower()
