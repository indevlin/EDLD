"""
tests/test_modes.py — the interfaces: flags, the default, config migration and
the launcher shortcuts.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core import modes as M  # noqa: E402


def _parser():
    src = (ROOT / "edld.py").read_text(encoding="utf-8")
    marker = "args = parser.parse_args()"
    ns: dict = {"__file__": str(ROOT / "edld.py"), "__name__": "_probe"}
    exec(compile(src[: src.index(marker)], "edld.py", "exec"), ns)
    return ns["parser"]


# ── Flags ─────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("argv, mode", [
    (["--edcars"], "edcars"),
    (["--dashg"], "gui"), (["--gui"], "gui"),
    (["--dasht"], "textual"), (["--tui"], "textual"),
    (["--term"], "terminal"), (["--text"], "terminal"),
    (["--terminal"], "terminal"),          # the old name, still accepted
    (["--headless"], "headless"),
])
def test_each_flag_opens_its_interface(argv, mode):
    assert _parser().parse_args(argv).mode_flag == mode


def test_no_flag_leaves_it_to_config_and_the_default_is_edcars():
    args = _parser().parse_args([])
    assert args.mode_flag is None and args.mode is None
    assert M.DEFAULT == "edcars"
    assert M.normalise(None) == "edcars" and M.normalise("nonsense") == "edcars"


def test_two_interfaces_cannot_be_asked_for_at_once():
    with pytest.raises(SystemExit):
        _parser().parse_args(["--dasht", "--gui"])


def test_mode_accepts_every_id():
    for mid in M.IDS:
        assert _parser().parse_args(["--mode", mid]).mode == mid
    with pytest.raises(SystemExit):
        _parser().parse_args(["--mode", "nonsense"])


def test_the_old_flags_are_not_advertised():
    text = _parser().format_help()
    assert "--terminal" not in text and "--edcars" in text


def test_gtk4_still_reads_as_the_terminal_dashboard():
    assert M.normalise("gtk4") == "textual"


def test_window_and_terminal_kinds():
    assert M.is_window("edcars") and M.is_window("gui")
    assert not M.is_window("textual") and not M.is_window("terminal")
    assert M.needs_terminal("textual") and M.needs_terminal("terminal")
    assert not M.needs_terminal("edcars") and not M.needs_terminal("headless")


def test_options_never_offer_headless():
    assert [mid for mid, _ in M.options_choices()] == ["edcars", "gui", "textual", "terminal"]


def test_one_shortcut_per_interface_and_none_for_the_server():
    assert [m.id for m in M.shortcut_modes()] == ["edcars", "gui", "textual", "terminal"]
    assert [m.id for m in M.shortcut_modes(server_build=True)] == ["terminal"]


# ── Migration from Mode + Style ───────────────────────────────────────────────

@pytest.mark.parametrize("mode, style, want", [
    ("textual", "dashboard", "edcars"),   # the default every config carried
    ("textual", None, "edcars"),
    ("gui", "dashboard", "gui"),
    ("gui", "edcars", "edcars"),
    ("gui", None, "gui"),
    ("terminal", "helm", "terminal"),
    ("headless", None, "headless"),
    (None, "helm", None),
    (None, "dashboard", None),
])
def test_legacy_pairs(mode, style, want):
    assert M.from_legacy(mode, style) == want


CONFIG = """\
# my notes
[Settings]
JournalFolder = "/j"

[UI]
Mode = "gui"          # I like the window
Theme = "default"
Style = "dashboard"
EdcarsAlerts = "pulse"

[EDP1]
UI.Mode = "textual"
UI.Style = "edcars"
UI.Theme = "default-green"

[EDP2]
UI.Mode = "terminal"
"""


def test_the_file_is_migrated_once_keeping_comments(tmp_path):
    import tomllib
    from core.config import migrate_ui_interface, backfill_config_defaults
    p = tmp_path / "config.toml"
    p.write_text(CONFIG, encoding="utf-8")
    report = migrate_ui_interface(p)
    assert len(report) == 3
    text = p.read_text(encoding="utf-8")
    assert "# my notes" in text
    d = tomllib.loads(text)
    assert d["UI"] == {"Interface": "gui", "Theme": "default", "EdcarsAlerts": "pulse"}
    assert d["EDP1"]["UI"] == {"Interface": "edcars", "Theme": "default-green"}
    assert d["EDP2"]["UI"] == {"Interface": "terminal"}
    assert migrate_ui_interface(p) == []
    added = backfill_config_defaults(p)
    # Mode and Style are not added back; Console and HelmPanel are new.
    assert sorted(k for k in added if k.startswith("UI.")) == ["UI.Console", "UI.HelmPanel"]


def test_a_config_that_never_set_an_interface_opens_edcars(tmp_path):
    import tomllib
    from core.config import migrate_ui_interface
    p = tmp_path / "config.toml"
    p.write_text('[UI]\nMode = "textual"\nTheme = "default"\n', encoding="utf-8")
    migrate_ui_interface(p)
    assert tomllib.loads(p.read_text())["UI"]["Interface"] == "edcars"


# ── Shortcuts ─────────────────────────────────────────────────────────────────

def test_desktop_entries(monkeypatch, tmp_path):
    from core import shortcuts as S
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    monkeypatch.setattr("core.state.EDLD_DATA_DIR", tmp_path)
    lines = S.install()
    files = sorted((tmp_path / "applications").glob("*.desktop"))
    assert [f.name for f in files] == ["edld-edcars.desktop", "edld-gui.desktop",
                                       "edld-terminal.desktop", "edld-textual.desktop"]
    assert len(lines) == 4
    edcars = (tmp_path / "applications" / "edld-edcars.desktop").read_text()
    assert "Name=EDLD EDCARS" in edcars and edcars.rstrip().count("\n") >= 5
    assert "--edcars" in edcars and "Terminal=false" in edcars
    tui = (tmp_path / "applications" / "edld-textual.desktop").read_text()
    assert "--dasht" in tui and "Terminal=true" in tui
    assert not any(" -s" in f.read_text() or "--server" in f.read_text() for f in files)
    S.remove()
    assert not list((tmp_path / "applications").glob("*.desktop"))


def test_exec_quoting():
    from core.shortcuts import _desktop_quote
    assert _desktop_quote("/usr/bin/python3") == "/usr/bin/python3"
    assert _desktop_quote("/home/me/My Games/edld.py") == '"/home/me/My Games/edld.py"'


def test_the_binary_only_makes_its_own_shortcuts_on_windows(monkeypatch):
    from core import shortcuts as S
    monkeypatch.setattr(sys, "platform", "linux")
    assert S.ensure_for_binary() is False
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.delattr(sys, "frozen", raising=False)
    assert S.ensure_for_binary() is False       # a source run never does


def test_windows_shortcut_commands(monkeypatch):
    from core import shortcuts as S
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", r"C:\Games\EDLD.exe")
    for m in M.shortcut_modes():
        prog, args = S.command(m)
        assert prog == r"C:\Games\EDLD.exe" and args == [m.flags[0]]


# ── The last interface chosen ─────────────────────────────────────────────────

REMEMBER = """\
# notes
[UI]
Interface = "edcars"   # mine
Theme = "default"

[EDP1]
UI.Theme = "default-green"

[REMOTE]
UI.Interface = "textual"
"""


def _remember(tmp_path, profile, mode):
    import tomllib
    from core.config import remember_interface
    p = tmp_path / "config.toml"
    if not p.exists():
        p.write_text(REMEMBER, encoding="utf-8")
    changed = remember_interface(p, profile, mode)
    return changed, tomllib.loads(p.read_text(encoding="utf-8")), p


def test_an_interface_started_by_name_is_remembered(tmp_path):
    changed, d, p = _remember(tmp_path, None, "textual")
    assert changed and d["UI"]["Interface"] == "textual"
    assert "# notes" in p.read_text() and "# mine" in p.read_text()


def test_it_is_written_where_it_is_read(tmp_path):
    _, d, _ = _remember(tmp_path, "REMOTE", "gui")
    assert d["REMOTE"]["UI"]["Interface"] == "gui" and d["UI"]["Interface"] == "edcars"
    _, d, _ = _remember(tmp_path, "EDP1", "terminal")
    assert d["UI"]["Interface"] == "terminal" and "Interface" not in d["EDP1"]["UI"]


def test_headless_and_no_change_leave_the_file_alone(tmp_path):
    changed, d, p = _remember(tmp_path, None, "headless")
    assert not changed and d["UI"]["Interface"] == "edcars"
    before = p.read_text()
    changed, _, _ = _remember(tmp_path, None, "edcars")
    assert not changed and p.read_text() == before


def test_edld_remembers_only_an_interface_named_on_the_command_line():
    src = (ROOT / "edld.py").read_text(encoding="utf-8")
    # Captured before EDLD-server fills in the terminal log itself.
    assert src.index("_chosen_mode = args.mode") < src.index("args.mode = _modes.TERMINAL")
    assert "remember_interface(config_path, _config_profile, _chosen_mode)" in src


def test_bare_server_flag_opens_the_default_interface():
    # -s is "also serve", not an interface: only EDLD-server, which has no
    # window, falls back to the terminal log.  `edld -s` opens EDCARS (or
    # whatever [UI] Interface says), like a plain `edld`.
    src = (ROOT / "edld.py").read_text(encoding="utf-8")
    assert "if args.server and not args.mode" not in src
    build = src.index("if SERVER_BUILD:")
    assert build < src.index("args.mode = _modes.TERMINAL") < src.index("_cfg_mode =")


def test_a_changed_value_keeps_its_comment(tmp_path):
    from core.config import edit_config_keys
    p = tmp_path / "config.toml"
    p.write_text('[Radio]\nStation = "a # b"   # the usual\nVolume = 5#loud\n',
                 encoding="utf-8")
    edit_config_keys(p, {("Radio",): {"Station": "c", "Volume": 7}})
    assert p.read_text() == '[Radio]\nStation = "c"   # the usual\nVolume = 7#loud\n'
