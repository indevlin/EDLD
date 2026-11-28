"""tests/test_capi_reminder.py — the lasting Frontier sign-in notice."""
from __future__ import annotations

import time
import urllib.error
from types import SimpleNamespace

import pytest

pytest.importorskip("edcmdr_core")

from core import data as D  # noqa: E402

DAY = 86400


class _Store:
    def __init__(self, tokens=None):
        self.saved = tokens or {}

    def read_json(self, purpose=None):
        return dict(self.saved)

    def write_json(self, d, purpose=None):
        self.saved = dict(d)


def _capi(tokens=None):
    calls = []
    dp = SimpleNamespace(_plugin_call=lambda *a, **k: calls.append(a), _state=SimpleNamespace())
    c = D.CAPISource(dp, _Store(tokens))
    loaded = c._load_tokens()
    if loaded.get("access_token"):
        c._tokens = loaded
    elif loaded.get("expired_at"):
        c._expired_at = float(loaded["expired_at"])
    return c, calls


def _last(calls):
    return calls[-1][1] if calls else None


def test_quiet_while_fresh():
    c, calls = _capi({"access_token": "a", "signed_in": time.time() - 10 * DAY})
    c.check_reminder()
    assert _last(calls) == "drop_notice"


def test_warns_before_it_ends():
    c, calls = _capi({"access_token": "a", "signed_in": time.time() - 27 * DAY})
    c.check_reminder()
    assert _last(calls) == "push_notice"
    assert "ends in about" in calls[-1][4]


def test_ended_sign_in_survives_a_restart(monkeypatch):
    c, calls = _capi({"access_token": "a", "refresh_token": "r", "expiry": 0})

    def refused(*a, **k):
        raise urllib.error.HTTPError("u", 400, "bad", {}, None)
    monkeypatch.setattr(D, "_http_post", refused)
    assert c._refresh_token() is False
    assert "expired_at" in c._storage.saved
    assert _last(calls) == "push_notice" and "has ended" in calls[-1][4]
    again, calls2 = _capi(c._storage.saved)
    again.check_reminder()
    assert _last(calls2) == "push_notice", "still said after a restart"


def test_turned_off_or_disconnected_goes():
    c, calls = _capi({"expired_at": time.time()})
    c.reminders_on = lambda: False
    c.check_reminder()
    assert _last(calls) == "drop_notice"
    c.reminders_on = lambda: True
    c.disconnect()
    assert _last(calls) == "drop_notice"
    assert c._storage.saved == {}
