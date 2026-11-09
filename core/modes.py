"""core/modes.py — EDLD's interfaces: their ids, flags, names and shortcuts.

    edcars    the desktop window, EDCARS layout                --edcars (default)
    gui       the desktop window, Dashboard layout             --dashg, --gui
    textual   the terminal dashboard                           --dasht, --tui
    terminal  the scrolling terminal event log                 --term, --text
    headless  no interface, for running as a service           --headless
"""
from __future__ import annotations

from dataclasses import dataclass

from core.edcars import EDCARS_ID, EDCARS_NAME

EDCARS = EDCARS_ID
GUI = "gui"
TEXTUAL = "textual"
TERMINAL = "terminal"
HEADLESS = "headless"

#: What a launch with no flag and no ``[UI] Interface`` runs.
DEFAULT = EDCARS


@dataclass(frozen=True)
class Mode:
    id: str
    name: str                    # Options and the shortcut's name
    flags: tuple[str, ...]       # command-line flags, first is the one shortcuts pass
    window: bool                 # draws the desktop window
    in_terminal: bool            # needs a terminal to run in
    shortcut: bool               # gets a launcher shortcut
    help: str


MODES: tuple[Mode, ...] = (
    Mode(EDCARS, EDCARS_NAME, ("--edcars",), True, False, True,
         "Desktop window, EDCARS layout (default)"),
    Mode(GUI, "Dashboard", ("--dashg", "--gui"), True, False, True,
         "Desktop window, Dashboard layout"),
    Mode(TEXTUAL, "Terminal dashboard", ("--dasht", "--tui"), False, True, True,
         "Terminal dashboard"),
    Mode(TERMINAL, "Terminal text", ("--term", "--text"), False, True, True,
         "Scrolling terminal event log"),
    Mode(HEADLESS, "Headless", ("--headless",), False, False, False,
         "No interface and no terminal output, for running as a service; "
         "diagnostics go to the log file"),
)

BY_ID: dict[str, Mode] = {m.id: m for m in MODES}
IDS: tuple[str, ...] = tuple(m.id for m in MODES)

#: Flags kept working for scripts written before the current names, but not
#: shown in --help.
HIDDEN_FLAGS: dict[str, str] = {"--terminal": TERMINAL}

#: The interfaces EDLD-server can run: it is built without either dashboard.
SERVER_BUILD_IDS: tuple[str, ...] = (TERMINAL, HEADLESS)


def normalise(value: object, default: str = DEFAULT) -> str:
    """A configured interface id, or ``default`` for anything unrecognized.
    """
    raw = str(value or "").strip().lower()
    if raw == "gtk4":
        return TEXTUAL
    return raw if raw in BY_ID else default


def is_window(mode_id: str) -> bool:
    m = BY_ID.get(mode_id)
    return bool(m and m.window)


def needs_terminal(mode_id: str) -> bool:
    m = BY_ID.get(mode_id)
    return bool(m and m.in_terminal)


def options_choices() -> list[tuple[str, str]]:
    """(id, label) pairs Options offers for the interface a bare launch opens.
    Headless is left out: picking it from a window would leave the next launch
    with nothing on screen to change it back from."""
    return [(m.id, m.name) for m in MODES if m.id != HEADLESS]


def shortcut_modes(server_build: bool = False) -> list[Mode]:
    if server_build:
        return [BY_ID[TERMINAL]]
    return [m for m in MODES if m.shortcut]


# ── Migration from [UI] Mode + Style ──────────────────────────────────────────

def from_legacy(mode: object, style: object) -> str | None:
    """The interface an old ``[UI] Mode`` / ``Style`` pair becomes, or None
    when the pair says nothing (the table should simply lose both keys).
    """
    m = str(mode or "").strip().lower()
    s = str(style or "").strip().lower()
    if m == "gui":
        return EDCARS if s == EDCARS else GUI
    if m in (TERMINAL, HEADLESS):
        return m
    if m in (TEXTUAL, "gtk4"):
        return EDCARS
    return None
