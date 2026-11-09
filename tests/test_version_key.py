"""tests/test_version_key.py — how EDLD orders its own versions."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.state import version_key  # noqa: E402


@pytest.mark.parametrize("older, newer", [
    ("20260924-dev", "20260926"),     # a dev build, then the release after it
    ("20260926-dev", "20260926"),     # the work leading up to a release
    ("20260926", "20260930-dev"),     # a release, then work toward the next
    ("20260325a", "20260325b"),
    ("20260325b", "20260326"),
    ("20260926", "v20260927"),        # tags may carry a v
])
def test_ordering(older, newer):
    assert version_key(older) < version_key(newer)


def test_a_newer_dev_build_is_not_told_to_update():
    assert not version_key("20260926") > version_key("20260930-dev")


@pytest.mark.parametrize("junk", ["", "latest", "2026-09-26", None])
def test_nonsense_sorts_first_and_never_raises(junk):
    assert version_key(junk) < version_key("20200101")


def test_the_update_check_uses_it():
    src = (ROOT / "edld.py").read_text(encoding="utf-8")
    assert "version_key(tag) > version_key(VERSION)" in src
    assert "def _vkey" not in src
