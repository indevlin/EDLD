"""core/win_console.py: console target selection and off-Windows no-ops."""
from __future__ import annotations

import sys
from types import SimpleNamespace

from core import win_console
from core.emit import Emitter


def test_child_of_bootloader_borrows_grandparent_console():
    procs = {
        300: (200, "EDLD.exe"),     # Python, run by the one-file bootloader
        200: (100, "EDLD.exe"),     # bootloader, windowed, no console
        100: (50, "cmd.exe"),
    }
    assert win_console.attach_target(300, "EDLD.exe", procs) == 100


def test_exe_name_match_ignores_case():
    procs = {3: (2, "EDLD.EXE"), 2: (1, "edld.exe"), 1: (0, "pwsh.exe")}
    assert win_console.attach_target(3, "EDLD.exe", procs) == 1


def test_no_target_when_parent_is_another_program():
    procs = {300: (100, "EDLD.exe"), 100: (50, "explorer.exe")}
    assert win_console.attach_target(300, "EDLD.exe", procs) is None


def test_no_target_when_process_unknown():
    assert win_console.attach_target(9, "EDLD.exe", {}) is None
    assert win_console.attach_target(9, "EDLD.exe", {9: (8, "EDLD.exe")}) is None


def test_startup_error_is_a_noop_off_windows(monkeypatch):
    monkeypatch.setattr(sys, "platform", "linux")
    win_console.startup_error("boom")
    assert win_console.hold_own_console() is False


def test_startup_hook_only_reports_during_startup(monkeypatch):
    seen = []
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(sys, "excepthook", lambda *a: None)
    monkeypatch.setattr(win_console, "startup_error", seen.append)
    monkeypatch.setattr(win_console, "_starting", True)
    win_console.install_startup_hook()
    try:
        raise ValueError("early")
    except ValueError:
        sys.excepthook(*sys.exc_info())
    win_console.startup_complete()
    try:
        raise ValueError("late")
    except ValueError:
        sys.excepthook(*sys.exc_info())
    assert len(seen) == 1 and "early" in seen[0]


def _emitter(url: str, notify_test: bool = False) -> Emitter:
    from core import emit
    emit.notify_enabled = True
    cfg = SimpleNamespace(discord_cfg={"WebhookURL": url})
    return Emitter(cfg, SimpleNamespace(), notify_test=notify_test)


def test_unset_webhook_is_info_not_warning(capsys):
    _emitter("")
    out = capsys.readouterr().out
    assert "Info:" in out and "not set up" in out


def test_malformed_webhook_warns(capsys):
    _emitter("https://discord.com/api/webhook/1/x")
    assert "Warning:" in capsys.readouterr().out


def test_padded_webhook_is_accepted():
    e = _emitter("  https://discord.com/api/webhooks/123/abc \n")
    assert e._discord_up


def test_test_mode_prints_startup_embed_instead_of_sending(capsys):
    from core.discord import Embed
    e = _emitter("https://discord.com/api/webhooks/123/abc", notify_test=True)
    sent = []
    e._send = lambda **k: sent.append(k)
    e.post_embed(Embed(title="Startup").add_field("Ship", "Cobra"))
    assert not sent
    assert "Startup" in capsys.readouterr().out


def test_no_dialogs_suppresses_the_dialog(monkeypatch):
    import ctypes
    calls = []
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(win_console, "_own_console", False)
    monkeypatch.setattr(win_console, "_output_visible", False)
    monkeypatch.setattr(win_console, "_dialogs", True)
    monkeypatch.setattr(ctypes, "WinDLL", lambda *a, **k: calls.append(a) or
                        SimpleNamespace(MessageBoxW=lambda *x: calls.append(x)),
                        raising=False)
    win_console.startup_error("\x1b[93mERROR:\x1b[0m no journal")
    assert calls and "no journal" in calls[-1][1] and "\x1b" not in calls[-1][1]
    calls.clear()
    win_console.no_dialogs()
    win_console.startup_error("again")
    assert not calls
