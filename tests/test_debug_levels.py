"""tests/test_debug_levels.py — the diagnostic log writes only under --debug or --trace."""

import pytest

from core import debug


@pytest.fixture
def fresh(monkeypatch):
    for name, value in (("_LOG_PATH", None), ("_FH", None), ("_HEADER_WRITTEN", False),
                        ("_PENDING_HEADER", ""), ("_INITIALIZED", False),
                        ("_TRACE_ECHO", False), ("_LEVEL", None)):
        monkeypatch.setattr(debug, name, value)
    yield
    if debug._FH is not None:
        debug._FH.close()


def _run(tmp_path, level):
    debug.init(tmp_path, "EDP1", "test", {}, level=level)
    debug.log("an error", level="ERROR")
    debug.log("a debug line")
    debug.info("an info line")
    debug.trace("a frame")
    debug.exception("caught", ValueError("bad"))
    return list((tmp_path / "logs").glob("*.log"))


def test_no_flag_writes_nothing(fresh, tmp_path):
    assert _run(tmp_path, None) == []
    assert not (tmp_path / "logs").exists()
    assert debug.is_enabled() is False
    assert debug.is_tracing() is False
    assert debug.path() is None


def test_debug_skips_trace(fresh, tmp_path):
    files = _run(tmp_path, "debug")
    text = files[0].read_text()
    assert "[ERROR] an error" in text
    assert "[DEBUG] a debug line" in text
    assert "[INFO] an info line" in text
    assert "ValueError: bad" in text
    assert "a frame" not in text
    assert debug.is_enabled() and not debug.is_tracing()
    assert debug.path() == files[0]


def test_trace_writes_everything(fresh, tmp_path):
    text = _run(tmp_path, "trace")[0].read_text()
    assert "[TRACE] a frame" in text
    assert "[DEBUG] a debug line" in text
    assert debug.is_tracing()


def test_unknown_level_is_off(fresh, tmp_path):
    assert _run(tmp_path, "verbose") == []
