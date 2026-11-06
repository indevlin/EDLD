"""
tests/test_game_detection.py — is the game running?

Under Proton the kernel truncates process names to fifteen characters, so the
game runs as ``EliteDangerous6`` and a check by name never matched.  At the
main menu Status.json also goes quiet, so the other signal said nothing either,
and a commander at the main menu was told the game was not running.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import core.journal as J  # noqa: E402

PROTON_ARGV0 = (r"Z:\home\cmdr\.steam\steam\steamapps\common\Elite Dangerous"
                r"\Products\elite-dangerous-odyssey-64\EliteDangerous64.exe")


@pytest.mark.parametrize("args, expected", [
    ([PROTON_ARGV0], True),
    (["C:/Games/EliteDangerous64.exe", "/novr"], True),
    (["ELITEDANGEROUS64.EXE"], True),
    (["EDLaunch.exe", "/frontier"], False),
    (["python", "watch EliteDangerous64.exe logs"], False),   # only mentions it
    ([], False),
    (None, False),
])
def test_command_line_matching(args, expected):
    assert J._is_game_cmdline(args) is expected


@pytest.fixture
def fake_game(tmp_path):
    """A process that looks like the game does under Proton."""
    if not sys.platform.startswith("linux"):
        pytest.skip("Proton process layout is Linux-only")
    exe = tmp_path / "EliteDangerous64.exe"
    shutil.copy(shutil.which("sleep"), exe)
    p = subprocess.Popen([PROTON_ARGV0, "30"], executable=str(exe))
    time.sleep(0.2)
    assert Path(f"/proc/{p.pid}/comm").read_text().strip() == "EliteDangerous6"
    yield p
    p.kill()
    p.wait()


def test_found_through_psutil(fake_game):
    if J.psutil is None:
        pytest.skip("psutil not installed")
    assert J._game_process_running() is True


def test_found_without_psutil(fake_game, monkeypatch):
    monkeypatch.setattr(J, "psutil", None)
    assert J._game_process_running() is True


def test_at_the_main_menu_the_game_is_running(fake_game, tmp_path):
    """Status.json untouched for ten minutes, game process present."""
    status = tmp_path / "Status.json"
    status.write_text('{"event":"Status","Flags":0}')
    old = time.time() - 600
    os.utime(status, (old, old))
    assert J._ed_client_running(tmp_path) is True


def test_nothing_running_is_reported_as_such(tmp_path, monkeypatch):
    monkeypatch.setattr(J, "_game_process_running", lambda: False)
    status = tmp_path / "Status.json"
    status.write_text("{}")
    old = time.time() - 600
    os.utime(status, (old, old))
    assert J._ed_client_running(tmp_path) is False


def test_fresh_status_is_enough_for_a_game_elsewhere(tmp_path, monkeypatch):
    monkeypatch.setattr(J, "_game_process_running", lambda: None)
    (tmp_path / "Status.json").write_text("{}")
    assert J._ed_client_running(tmp_path) is True
