"""core/shortcuts.py — launcher shortcuts, one per interface.

* **Windows** — Start-menu shortcuts in ``Programs\\EDLD``. The binary is a
  single file with no installer, so it makes them itself: on its first run,
  and again whenever it has been moved or updated (``ensure_for_binary``).
  ``--remove-shortcuts`` deletes them and stops the binary making them again
  until ``--shortcuts`` is run.
* **Linux** — XDG desktop entries in ``~/.local/share/applications``, made by
  ``--shortcuts`` (install.sh runs it). The terminal interfaces are marked
  ``Terminal=true`` so the desktop opens them in a terminal.
* **macOS** — the app bundle is the launcher; there is nothing to add.

EDLD-server gets one shortcut, its terminal event log.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

from core import modes

#: Folder name in the Start menu, and the prefix of every entry.
GROUP = "EDLD"
#: Where the binary records what it made, so it only makes them again when
#: something changed, and so --remove-shortcuts knows what to take away.
MARKER = "shortcuts.json"


class ShortcutError(Exception):
    """Shortcuts could not be made here; the message says why."""


# ── What each shortcut runs ───────────────────────────────────────────────────

def _frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def _script() -> Path:
    return Path(__file__).resolve().parents[1] / "edld.py"


def _program_name(server_build: bool) -> str:
    return "EDLD-server" if server_build else "EDLD"


def entry_name(mode: modes.Mode, server_build: bool = False) -> str:
    """The name a launcher shows: "EDLD EDCARS", "EDLD Terminal text", …"""
    if server_build:
        return "EDLD-server"
    return f"{GROUP} {mode.name}"


def command(mode: modes.Mode) -> tuple[str, list[str]]:
    """(program, arguments) a shortcut for ``mode`` runs."""
    flag = mode.flags[0]
    if _frozen():
        return sys.executable, [flag]
    exe = Path(sys.executable)
    if sys.platform == "win32" and not mode.in_terminal:
        pyw = exe.with_name("pythonw.exe")
        if pyw.is_file():
            exe = pyw
    return str(exe), [str(_script()), flag]


def _icon_source() -> Path | None:
    base = Path(getattr(sys, "_MEIPASS", "")) if _frozen() else _script().parent
    for name in ("edld.ico", "edld.png") if sys.platform == "win32" else ("edld.png",):
        p = base / "packaging" / "icons" / name
        if p.is_file():
            return p
    return None


# ── Windows ───────────────────────────────────────────────────────────────────

def _start_menu() -> Path:
    appdata = os.environ.get("APPDATA") or str(Path.home() / "AppData" / "Roaming")
    return Path(appdata) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / GROUP


def _ps_quote(text: str) -> str:
    return "'" + str(text).replace("'", "''") + "'"


def _win_args(args: list[str]) -> str:
    return subprocess.list2cmdline(args)


def _windows_install(mode_list: list[modes.Mode], server_build: bool) -> list[Path]:
    folder = _start_menu()
    folder.mkdir(parents=True, exist_ok=True)
    made: list[Path] = []
    script = ["$sh = New-Object -ComObject WScript.Shell"]
    for m in mode_list:
        prog, args = command(m)
        link = folder / f"{entry_name(m, server_build)}.lnk"
        icon = prog if _frozen() else str(_icon_source() or prog)
        script += [
            f"$s = $sh.CreateShortcut({_ps_quote(link)})",
            f"$s.TargetPath = {_ps_quote(prog)}",
            f"$s.Arguments = {_ps_quote(_win_args(args))}",
            f"$s.WorkingDirectory = {_ps_quote(Path(prog).parent if _frozen() else _script().parent)}",
            f"$s.IconLocation = {_ps_quote(str(icon) + ',0')}",
            f"$s.Description = {_ps_quote(m.help)}",
            "$s.Save()",
        ]
        made.append(link)
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    try:
        run = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive",
             "-ExecutionPolicy", "Bypass", "-Command", "; ".join(script)],
            capture_output=True, text=True, timeout=60, creationflags=flags)
    except (OSError, subprocess.SubprocessError) as exc:
        raise ShortcutError(f"could not run PowerShell to make the shortcuts: {exc}")
    if run.returncode != 0:
        raise ShortcutError("PowerShell could not make the shortcuts: "
                            + (run.stderr or run.stdout or "").strip()[:400])
    return made


def _windows_remove(names: list[str]) -> list[Path]:
    """Remove the named shortcuts, and the folder once it is empty. Only the
    names given: EDLD and EDLD-server share the folder."""
    folder = _start_menu()
    gone: list[Path] = []
    if folder.is_dir():
        for name in names:
            p = folder / f"{name}.lnk"
            if p.is_file():
                p.unlink(missing_ok=True)
                gone.append(p)
        try:
            folder.rmdir()
        except OSError:
            pass
    return gone


# ── Linux (XDG) ───────────────────────────────────────────────────────────────

def _applications() -> Path:
    base = os.environ.get("XDG_DATA_HOME") or str(Path.home() / ".local" / "share")
    return Path(base) / "applications"


def _desktop_quote(arg: str) -> str:
    """Quote one Exec argument per the Desktop Entry spec."""
    if arg and not any(c in arg for c in ' \t\n"\'\\><~|&;$*?#()`'):
        return arg
    escaped = arg.replace("\\", "\\\\").replace('"', '\\"').replace("`", "\\`").replace("$", "\\$")
    return f'"{escaped}"'


def desktop_entry(mode: modes.Mode, icon: str | None, server_build: bool = False) -> str:
    prog, args = command(mode)
    exec_line = " ".join(_desktop_quote(a) for a in [prog, *args]).replace("%", "%%")
    lines = [
        "[Desktop Entry]",
        "Type=Application",
        f"Name={entry_name(mode, server_build)}",
        f"Comment=Elite Dangerous Live Dashboard — {mode.help}",
        f"Exec={exec_line}",
        f"Terminal={'true' if mode.in_terminal else 'false'}",
        "Categories=Game;Utility;",
        "StartupNotify=false",
    ]
    if icon:
        lines.append(f"Icon={icon}")
    return "\n".join(lines) + "\n"


def _desktop_file(mode: modes.Mode, server_build: bool) -> Path:
    stem = "edld-server" if server_build else f"edld-{mode.id}"
    return _applications() / f"{stem}.desktop"


def _xdg_install(mode_list: list[modes.Mode], server_build: bool) -> list[Path]:
    from core.state import EDLD_DATA_DIR
    folder = _applications()
    folder.mkdir(parents=True, exist_ok=True)
    icon = None
    src = _icon_source()
    if src is not None:
        # A binary's icon lives in a folder that is deleted when it exits.
        dest = EDLD_DATA_DIR / "edld.png"
        try:
            shutil.copyfile(src, dest)
            icon = str(dest)
        except OSError:
            icon = str(src) if not _frozen() else None
    made: list[Path] = []
    for m in mode_list:
        path = _desktop_file(m, server_build)
        path.write_text(desktop_entry(m, icon, server_build), encoding="utf-8")
        path.chmod(0o755)
        made.append(path)
    _refresh_xdg(folder)
    return made


def _xdg_remove(server_build: bool) -> list[Path]:
    folder = _applications()
    gone: list[Path] = []
    pattern = "edld-server.desktop" if server_build else "edld-*.desktop"
    for p in sorted(folder.glob(pattern)):
        if not server_build and p.name == "edld-server.desktop":
            continue
        p.unlink(missing_ok=True)
        gone.append(p)
    if gone:
        _refresh_xdg(folder)
    return gone


def _refresh_xdg(folder: Path) -> None:
    tool = shutil.which("update-desktop-database")
    if tool:
        try:
            subprocess.run([tool, str(folder)], capture_output=True, timeout=30)
        except (OSError, subprocess.SubprocessError):
            pass


# ── Entry points ──────────────────────────────────────────────────────────────

def _marker_path(server_build: bool = False) -> Path:
    from core.state import EDLD_DATA_DIR
    return EDLD_DATA_DIR / (MARKER.replace(".json", "-server.json")
                            if server_build else MARKER)


def _wanted(server_build: bool) -> dict:
    from core.state import VERSION
    mode_list = modes.shortcut_modes(server_build)
    return {
        "program": sys.executable if _frozen() else str(_script()),
        "version": VERSION,
        "entries": [entry_name(m, server_build) for m in mode_list],
        "flags": [m.flags[0] for m in mode_list],
    }


def _read_marker(server_build: bool) -> dict:
    try:
        data = json.loads(_marker_path(server_build).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _write_marker(data: dict, server_build: bool) -> None:
    try:
        _marker_path(server_build).write_text(json.dumps(data, indent=1), encoding="utf-8")
    except OSError:
        pass


def install(server_build: bool = False) -> list[str]:
    """Make (or remake) the shortcuts. Returns a line per shortcut made."""
    mode_list = modes.shortcut_modes(server_build)
    if sys.platform == "win32":
        made = _windows_install(mode_list, server_build)
    elif sys.platform == "darwin":
        raise ShortcutError("on macOS the EDLD app is the launcher; "
                            "start the other interfaces from a terminal")
    else:
        made = _xdg_install(mode_list, server_build)
    _write_marker(_wanted(server_build), server_build)
    return [f"Added {p}" for p in made]


def remove(server_build: bool = False) -> list[str]:
    """Remove the shortcuts, and stop the binary making them again."""
    if sys.platform == "win32":
        names = set(_read_marker(server_build).get("entries") or [])
        names |= set(_wanted(server_build)["entries"])
        gone = _windows_remove(sorted(names))
    elif sys.platform == "darwin":
        gone = []
    else:
        gone = _xdg_remove(server_build)
    _write_marker({"removed": True}, server_build)
    return [f"Removed {p}" for p in gone]


def ensure_for_binary(server_build: bool = False) -> bool:
    """On the Windows binary, make the shortcuts if they are missing or out of
    date. Returns True when it made them.
    """
    if sys.platform != "win32" or not _frozen():
        return False
    current = _read_marker(server_build)
    if current.get("removed"):
        return False
    wanted = _wanted(server_build)
    present = all((_start_menu() / f"{n}.lnk").is_file() for n in wanted["entries"])
    if current == wanted and present:
        return False
    try:
        # An older binary's set may have had other names; clear those first.
        _windows_remove(list(current.get("entries") or []))
        install(server_build)
    except ShortcutError:
        return False
    return True
