#!/usr/bin/env python3
"""
edld.py — ED Live Dashboard — entry point

All business logic lives in the packages below:
  core/       — state, config, emit, journal loop, plugin loader, shared API
  components/ — all application components
  plugins/    — user plugin directory
  tui/        — Textual TUI interface
"""

import argparse
import json
import os
import sys
import threading
import time
import queue
from pathlib import Path
from urllib.request import urlopen

# ── Ensure repo root is on sys.path ───────────────────────────────────────────
_HERE = Path(__file__).parent.resolve()
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

from core.state  import PROGRAM, VERSION, AUTHOR, GITHUB_REPO, DEBUG_MODE

from core.emit   import Terminal
from core        import modes as _modes
from core.config import (
    resolve_config_path, load_config_file, ConfigManager,
    migrate_config_if_needed, backfill_config_defaults, migrate_ui_interface,
    remember_interface,
)


# ── Argument parsing ──────────────────────────────────────────────────────────

parser = argparse.ArgumentParser(
    prog=PROGRAM,
    description="Continuous monitoring of Elite Dangerous AFK sessions.",
)
parser.add_argument("-p", "--config_profile",
                    help="Load a specific config profile")
parser.add_argument("-t", "--test", action="store_true", default=None,
                    help="Re-route Discord output to terminal instead of webhook")
parser.add_argument("-d", "--trace", action="store_true", default=None,
                    help="Write the diagnostic log with trace detail")
parser.add_argument("--debug", action="store_true", default=None,
                    help="Write the diagnostic log")
parser.add_argument("--mode", choices=list(_modes.IDS),
                    default=None, metavar="MODE",
                    help="Interface by id: " + " | ".join(_modes.IDS)
                         + f" (default {_modes.DEFAULT})")

# One flag group for the interfaces, built from core/modes.py so the flags,
# Options and the launcher shortcuts cannot disagree.  Each interface has its
# flags (--dasht and --tui both open the terminal dashboard, and so on); they
# are mutually exclusive, and equivalent to the matching --mode value, which
# stays supported for existing scripts.  Without any of them EDLD opens what
# [UI] Interface says, and EDCARS when that is not set.
_mode_group = parser.add_mutually_exclusive_group()
for _m in _modes.MODES:
    for _i, _flag in enumerate(_m.flags):
        _mode_group.add_argument(
            _flag, dest="mode_flag", action="store_const", const=_m.id,
            help=(_m.help if _i == 0 else f"Same as {_m.flags[0]}"))
for _flag, _mid in _modes.HIDDEN_FLAGS.items():
    _mode_group.add_argument(_flag, dest="mode_flag", action="store_const",
                             const=_mid, help=argparse.SUPPRESS)

# Server mode, for the EDAM mobile client.  It is a setting, not an interface:
# [Server] Enabled (Options → Server) runs it beside whichever interface opens,
# which is how a launcher shortcut gets it without a server copy of every
# shortcut.  -s is the same for one run, beside whichever interface opens:
# the one named by flag or --mode, otherwise the one a plain launch opens.
parser.add_argument("-s", "--server", action="store_true",
                    help="Serve paired EDAM devices for this run (see docs/SERVER.md); "
                         "Options → Server turns it on for every run")
parser.add_argument("--pair", action="store_true",
                    help="Show a one-time code for pairing a device, then exit")
parser.add_argument("--paired", action="store_true",
                    help="List paired devices, then exit")
parser.add_argument("--unpair", metavar="ID",
                    help="Remove a paired device by the ID --paired shows, then exit")

parser.add_argument("--shortcuts", action="store_true",
                    help="Add (or refresh) a launcher shortcut for each interface, "
                         "then exit")
parser.add_argument("--remove-shortcuts", action="store_true",
                    help="Remove the launcher shortcuts --shortcuts made, then exit")

parser.add_argument("--version", action="store_true",
                    help="Print the version and exit")
parser.add_argument("--selftest", action="store_true",
                    help="Report whether each interface, the server and the radio load, then exit")
parser.add_argument("--overlay-renderer", action="store_true",
                    help=argparse.SUPPRESS)
parser.add_argument("--overlay-probe", action="store_true",
                    help="Report whether this machine can show the overlay, then exit")
parser.add_argument("--overlay-doctor", action="store_true",
                    help="Explain why the overlay is or is not drawing, then exit")
parser.add_argument("--overlay-selftest", action="store_true",
                    help="Draw a fixed test frame for 20 seconds, then exit")

args = parser.parse_args()

# EDLD-server is this program built without either dashboard (see
# core/build_info.py).  It always serves, and its default is the terminal log.
from core.build_info import is_server_build as _is_server_build
SERVER_BUILD = _is_server_build()

# ── Windows: reconnect stdout before anything prints ──────────────────────────
# The Windows binary is built windowed so the GUI has no console behind it,
# which leaves stdout unusable until this runs.  A no-op everywhere else.
try:
    from core.win_console import enable_console_output
    enable_console_output()
except Exception:
    pass

# ── HTTPS trust store ─────────────────────────────────────────────────────────
# Must run before anything opens a connection.  A frozen build ships its own
# OpenSSL, which looks for certificates where the *build* machine kept them, so
# without this every HTTPS call fails verification and CAPI, EDDN, EDSM,
# EDAstro, Inara and Spansh all stop working without any of them saying so.
try:
    from core import certs as _certs
    _certs.install()
except Exception:
    pass

# --version answers before any config, journal or plugin work, so it succeeds
# on a machine that has never run Elite Dangerous.  The release workflow uses
# it to prove the built artefact actually starts.
if args.version:
    print(VERSION)
    sys.exit(0)

# The overlay renderer is a child of a running EDLD, re-executing this binary
# because a frozen build has no interpreter beside it to run a module with.  It
# must be dispatched before anything else here touches stdout, which the
# renderer uses as its protocol channel.  --overlay-probe is the same code path
# with the window skipped, for answering "will this work on my machine" without
# starting EDLD at all.
if args.overlay_renderer or args.overlay_probe or args.overlay_selftest:
    from core.overlay_proc import main as _overlay_main
    _flags = (["--probe"] if args.overlay_probe
              else ["--selftest"] if args.overlay_selftest else [])
    sys.exit(_overlay_main(_flags))

# --selftest imports each front end and reports, then exits. It exists because
# a packaged build can fail at import in ways a source checkout never does:
# Textual resolves its widgets through a runtime __getattr__, so a frozen
# binary can be missing a widget module and still start, run, and only die at
# the moment the dashboard is drawn. Importing both front ends up front turns
# that into something the release workflow can catch on every platform.
if args.selftest:
    import importlib as _il
    _results, _failed = [], False
    _frontends = () if SERVER_BUILD else (
        ("terminal dashboard (--dasht)",     "tui.app"),
        ("desktop window (--edcars, --dashg)", "gui.app"))
    # Both builds carry the server: its key generation (cryptography's
    # compiled half is the part a bundle can lose) and the QR code.
    if True:
        try:
            import tempfile as _tf
            from core.server import service as _svc  # noqa: F401
            from core.server.identity import load_or_create as _loc
            with _tf.TemporaryDirectory() as _d:
                _fp = _loc(Path(_d), "selftest").fingerprint
            _results.append(f"  OK    server (identity {_fp[:8]}…)")
        except Exception as _e:
            _failed = True
            _results.append(f"  FAIL  server: {type(_e).__name__}: {_e}")
        try:
            from core.server.pairing import qr_text as _qr
            assert _qr("edld://pair?v=1")
            _results.append("  OK    pairing QR code")
        except Exception as _e:
            _failed = True
            _results.append(f"  FAIL  pairing QR code: {type(_e).__name__}: {_e}")
    for _label, _mod in _frontends:
        try:
            _il.import_module(_mod)
            _results.append(f"  OK    {_label}")
        except Exception as _e:
            _failed = True
            _results.append(f"  FAIL  {_label}: {type(_e).__name__}: {_e}")
    # The radio is only exercised when someone presses Play, so a binary
    # missing miniaudio's compiled half would otherwise ship looking fine.
    if not SERVER_BUILD:
        try:
            from core.radio import selftest as _radio_selftest
            _results.append(f"  OK    radio ({_radio_selftest()})")
        except Exception as _e:
            _failed = True
            _results.append(f"  FAIL  radio: {type(_e).__name__}: {_e}")
    # A binary must carry the license text of everything inside it; the build
    # collects them (packaging/build_common.py), and this proves they landed.
    if getattr(sys, "frozen", False):
        _lic = Path(getattr(sys, "_MEIPASS", "")) / "licenses" / "third-party"
        _n = len([p for p in _lic.iterdir() if p.is_dir()]) if _lic.is_dir() else 0
        if _n:
            _results.append(f"  OK    license texts ({_n} packages)")
        else:
            _failed = True
            _results.append(f"  FAIL  license texts: none bundled at {_lic}")
    print(f"EDLD{'-server' if SERVER_BUILD else ''} {VERSION} selftest")
    print("\n".join(_results))
    sys.exit(1 if _failed else 0)

# A convenience flag and an explicit --mode should not disagree silently.
if args.mode_flag and args.mode and args.mode != args.mode_flag:
    parser.error(
        f"--mode {args.mode} conflicts with the {_modes.BY_ID[args.mode_flag].flags[0]} "
        f"flag; pass only one."
    )
if args.mode_flag and not args.mode:
    args.mode = args.mode_flag
# The interface asked for by name, before -s and EDLD-server fill in their own
# default: only this one is remembered for the next plain launch.
_chosen_mode = args.mode
if SERVER_BUILD:
    if args.mode and args.mode not in _modes.SERVER_BUILD_IDS:
        parser.error("this is EDLD-server, built without the dashboards; "
                     "use EDLD for the desktop window and the terminal dashboard")
    args.server = True
    # EDLD-server has no window to open: its default is the terminal log.
    if not args.mode:
        args.mode = _modes.TERMINAL
# -s is "also serve", not an interface: on its own it opens whatever a plain
# launch would ([UI] Interface, else EDCARS), with the server beside it.  A
# service names its interface explicitly: -s --headless.

# A terminal interface asked for on the command line needs a console now, so
# the banner below is seen: on Windows a launcher shortcut starts the windowed
# binary with none (core/win_console.py).  One chosen by config.toml is given
# its console once the config has been read.
if args.mode and _modes.needs_terminal(args.mode):
    try:
        from core.win_console import ensure_console
        ensure_console()
    except Exception:
        pass

# --shortcuts / --remove-shortcuts: the launcher entries, one per interface
# (core/shortcuts.py).  Before any config or journal work, like --version.
if args.shortcuts or args.remove_shortcuts:
    from core import shortcuts as _shortcuts
    try:
        _lines = (_shortcuts.remove(server_build=SERVER_BUILD) if args.remove_shortcuts
                  else _shortcuts.install(server_build=SERVER_BUILD))
    except _shortcuts.ShortcutError as _e:
        print(f"{Terminal.WARN}ERROR:{Terminal.END} {_e}")
        sys.exit(1)
    print("\n".join(_lines) if _lines else "Nothing to do.")
    sys.exit(0)

# The Windows binary is a single file with no installer, so it puts its own
# Start-menu shortcuts in place: on the first run, and again whenever it has
# moved or been updated.  A no-op from source and on other platforms.
try:
    from core import shortcuts as _shortcuts
    _shortcuts.ensure_for_binary(server_build=SERVER_BUILD)
except Exception:
    pass


# ── Header ────────────────────────────────────────────────────────────────────

title = f"{PROGRAM} v{VERSION} by {AUTHOR}"
print(f"{Terminal.CYAN}{'=' * len(title)}\n{title}\n{'=' * len(title)}{Terminal.END}\n")


# ── Background update check ───────────────────────────────────────────────────
# Checks two things in order of severity:
#   1. New tagged release on GitHub   → "release" notice
#   2. New commits on origin/main     → "commits" notice (only if git is present
#      and _HERE is a git working tree)
#
# _update_notice  = ("release", version_str)   — a tagged release is available
# _update_notice  = ("commits", N_str)          — N new commits ahead of local
# _update_notice  = None                        — nothing new
#
# In both cases File → Upgrade runs the same git-pull path.

_update_notice: tuple[str, str] | None = None

def _check_for_update() -> None:
    global _update_notice

    # Check for a newer tagged release via GitHub API. Compares VERSION against
    # the latest release tag using a (date, suffix) key so 20260325a <
    # 20260325b < 20260326 all sort correctly.
    try:
        url = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"
        with urlopen(url, timeout=4) as resp:
            if resp.status == 200:
                tag = json.loads(resp.read()).get("tag_name", "").lstrip("v").strip()
                if tag and tag != VERSION:
                    from core.state import version_key
                    if version_key(tag) > version_key(VERSION):
                        _update_notice = ("release", tag)
    except Exception:
        pass

_update_thread = threading.Thread(target=_check_for_update, daemon=True)


# ── Config ────────────────────────────────────────────────────────────────────

config_path = resolve_config_path(Path(__file__))
if config_path is None:
    # No config found — generate a default one in the user data directory
    # so EDLD can start immediately.  The user can edit it via Preferences.
    from core.state import EDLD_DATA_DIR
    from core.config import (
        config_to_toml,
        CFG_DEFAULTS_SETTINGS, CFG_DEFAULTS_EXTRA, CFG_DEFAULTS_UI,
        CFG_DEFAULTS_DISCORD, CFG_DEFAULTS_EDDN, CFG_DEFAULTS_EDSM,
        CFG_DEFAULTS_EDASTRO, CFG_DEFAULTS_INARA, CFG_DEFAULTS_NOTIFY,
        CFG_DEFAULTS_CAPI, CFG_DEFAULTS_COLONISATION, CFG_DEFAULTS_RADIO,
        CFG_DEFAULTS_SERVER,
    )
    # SessionMgmt's defaults are owned by the component that reads them.
    from components.ksw import CFG_DEFAULTS as CFG_DEFAULTS_SESSIONMGMT
    config_path = EDLD_DATA_DIR / "config.toml"
    _default_cfg = {
        "Settings":  {**CFG_DEFAULTS_SETTINGS, **CFG_DEFAULTS_EXTRA},
        "Discord":   CFG_DEFAULTS_DISCORD,
        "UI":        CFG_DEFAULTS_UI,
        "LogLevels": CFG_DEFAULTS_NOTIFY,
        "EDDN":      CFG_DEFAULTS_EDDN,
        "EDSM":      CFG_DEFAULTS_EDSM,
        "EDAstro":   CFG_DEFAULTS_EDASTRO,
        "Inara":     CFG_DEFAULTS_INARA,
        # These three were absent from the generated config, so a new install
        # got a file that did not mention them at all.
        "CAPI":        CFG_DEFAULTS_CAPI,
        "Colonisation": CFG_DEFAULTS_COLONISATION,
        "SessionMgmt": CFG_DEFAULTS_SESSIONMGMT,
        "Radio":       CFG_DEFAULTS_RADIO,
        "Server":      CFG_DEFAULTS_SERVER,
    }
    # The commented example, which carries every setting at its default and
    # says what each does, is what a new install starts from — as install.sh
    # already did. The generated file, kept as the fallback, has no comments
    # and only the core sections.
    _bundle = getattr(sys, "_MEIPASS", None)
    _example = (Path(_bundle) if _bundle else _HERE) / "example.config.toml"
    try:
        config_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            config_path.write_text(_example.read_text(encoding="utf-8"), encoding="utf-8")
        except OSError:
            config_path.write_text(config_to_toml(_default_cfg), encoding="utf-8")
        print(f"[EDLD] No config found — wrote default config to: {config_path}")
    except OSError as _e:
        print(f"{Terminal.WARN}WARNING:{Terminal.END} Could not write default config: {_e}")
        # Fall through — ConfigManager will use built-in defaults

migrate_config_if_needed(config_path)  # silently rewrite old [GUI]/sub-table format before loading
# [UI] Mode and Style became [UI] Interface when EDCARS became the default.
_ui_moved = migrate_ui_interface(config_path)
if _ui_moved:
    print("[EDLD] " + "; ".join(_ui_moved))
# Settings added since this config was written are appended to it, so they are
# visible and editable.
_added_keys = backfill_config_defaults(config_path)
if _added_keys:
    print(f"[EDLD] Added {len(_added_keys)} new setting(s) to {config_path}: "
          + ", ".join(_added_keys))
config_dict = load_config_file(config_path)
notify_test = bool(args.test)  if args.test  is not None else False
trace_mode  = bool(args.trace) if args.trace is not None else DEBUG_MODE
log_level   = "trace" if trace_mode else ("debug" if args.debug else None)

# Preliminary manager — profile may be updated after commander name is known.
# Debug log facility is initialized LATER (after the commander/profile
# auto-detection runs), so the per-run log header includes the right
# profile overrides.
mgr = ConfigManager(config_dict, config_path, config_profile=args.config_profile)

# Reads the live ConfigManager, so it sees the same file, profile and
# resolution order the running app does. A doctor that built its own view of
# the config would end up diagnosing itself.
if args.overlay_doctor:
    from core.overlay_doctor import run as _overlay_doctor
    sys.exit(_overlay_doctor(mgr))


# ── State and session objects ─────────────────────────────────────────────────

from core.state import MonitorState, SessionData, load_session_state

state          = MonitorState()
active_session = SessionData()
lifetime       = SessionData()
gui_queue: queue.Queue = queue.Queue()


# ── Find journal ──────────────────────────────────────────────────────────────

from core.journal import find_latest_journal

journal_dir_str = mgr.app_settings.get("JournalFolder", "")
journal_dir     = Path(journal_dir_str).expanduser() if journal_dir_str else None

if not journal_dir or not journal_dir.is_dir():
    # Auto-detect the game's own journal folder: Windows' Saved Games, then the
    # Steam/Proton prefix on Linux.  This lets users launch without needing to
    # set JournalFolder up front.  Windows was missing until 20261102, so a
    # blank JournalFolder — what a new config has — stopped EDLD there.
    _candidates = [
        Path.home() / "Saved Games" / "Frontier Developments" / "Elite Dangerous",
        Path.home() / ".steam" / "steam" / "steamapps" / "compatdata"
        / "359320" / "pfx" / "drive_c" / "users" / "steamuser"
        / "Saved Games" / "Frontier Developments" / "Elite Dangerous",
        Path.home() / ".local" / "share" / "Steam" / "steamapps"
        / "compatdata" / "359320" / "pfx" / "drive_c" / "users"
        / "steamuser" / "Saved Games" / "Frontier Developments"
        / "Elite Dangerous",
    ]
    for _c in _candidates:
        if _c.is_dir():
            print(f"[EDLD] JournalFolder not set — auto-detected: {_c}")
            journal_dir = _c
            journal_dir_str = str(_c)
            break

if not journal_dir or not journal_dir.is_dir():
    _msg = (
        f"JournalFolder is not set or the directory does not exist.\n\n"
        f"Configured path: {journal_dir_str!r}\n\n"
        f"Set JournalFolder in your config.toml to the Elite Dangerous journal directory.\n"
        f"On Windows the game's folder is:\n"
        f"  %USERPROFILE%\\Saved Games\\Frontier Developments\\Elite Dangerous\n"
        f"For Steam/Proton on Linux the default location is:\n"
        f"  ~/.steam/steam/steamapps/compatdata/359320/pfx/drive_c/users/"
        f"steamuser/Saved Games/Frontier Developments/Elite Dangerous"
    )
    print(f"{Terminal.WARN}ERROR:{Terminal.END} {_msg}")
    sys.exit(1)

journal_file = find_latest_journal(journal_dir)
if not journal_file:
    _msg = (
        f"No Elite Dangerous journal files found in:\n  {journal_dir}\n\n"
        f"Launch Elite Dangerous at least once to generate journal files, "
        f"or check that JournalFolder points to the correct directory."
    )
    print(f"{Terminal.WARN}ERROR:{Terminal.END} {_msg}")
    sys.exit(1)


# ── Commander name — for profile auto-detection ───────────────────────────────

# Scan backwards through journals, newest first.

def _scan_journals(jdir: Path, field: str) -> str:
    """Return ``field`` from Commander/LoadGame in the newest journal that has it.

    The first call builds or brings up to date the journal index
    (core/journal_index.py) every history reader below uses.
    """
    from core.journal_index import index_for
    try:
        for _f, _ev in index_for(jdir).events(("Commander", "LoadGame"), newest_first=True):
            if _ev.get(field):
                return _ev[field]
    except Exception as _e:   # an unusable index costs history, not the start
        print(f"{Terminal.WARN}WARNING:{Terminal.END} journal index unavailable: {_e}")
    return ""


state.pilot_name = _scan_journals(journal_dir, "Name") or None

# ── Commander FID — for per-commander data directory ─────────────────────────

def _scan_fid_from_journals(jdir: Path) -> str:
    """Return the Frontier account FID from the most recent journal that has one."""
    return _scan_journals(jdir, "FID")

from core.state import set_active_fid, get_last_fid

_fid = _scan_fid_from_journals(journal_dir) or get_last_fid()
if _fid:
    set_active_fid(_fid)
    state.pilot_fid = _fid
    print(f"{Terminal.YELL}Commander FID:{Terminal.END} {_fid}")
else:
    print(f"{Terminal.YELL}Commander FID:{Terminal.END} (not yet determined)")

print(f"{Terminal.YELL}Commander name:{Terminal.END} {state.pilot_name or '(unknown)'}")

_config_profile = args.config_profile
_config_info    = ""
if not _config_profile and state.pilot_name and state.pilot_name in config_dict:
    _config_profile = state.pilot_name
    _config_info    = " (auto)"
    mgr = ConfigManager(config_dict, config_path, config_profile=_config_profile)

print(
    f"{Terminal.YELL}Config profile:{Terminal.END} "
    f"{_config_profile or 'Default'}{_config_info}"
)


# ── Server settings and pairing commands ─────────────────────────────────────
# Resolved after the profile, because each profile is its own server: its own
# port, identity and paired devices.  --pair, --paired and --unpair act on the
# files in that directory and exit; a running EDLD picks up their changes.

from core.config import CFG_DEFAULTS_SERVER
from core.state  import EDLD_DATA_DIR as _DATA_DIR

server_cfg = mgr.load_setting("Server", CFG_DEFAULTS_SERVER, warn_missing=False)
server_dir = _DATA_DIR / "server" / (_config_profile or "default")
server_on  = bool(args.server or server_cfg.get("Enabled"))

if args.pair or args.paired or args.unpair:
    from core.server import cli as _server_cli
    from core.server.identity import ServerDependencyError, default_server_name
    try:
        if args.paired:
            sys.exit(_server_cli.paired(server_dir))
        if args.unpair:
            sys.exit(_server_cli.unpair(server_dir, args.unpair))
        sys.exit(_server_cli.pair(server_dir, server_cfg,
                                  default_server_name(_config_profile)))
    except ServerDependencyError as _e:
        print(f"{Terminal.WARN}ERROR:{Terminal.END} {_e}")
        sys.exit(1)


# ── UI mode ───────────────────────────────────────────────────────────────────
# Priority: an interface flag or --mode > config [UI] Interface > EDCARS.  A
# flag also becomes [UI] Interface, below.  The old [UI] Mode and Style keys
# were folded into Interface before the config was loaded
# (migrate_ui_interface).

_cfg_mode = _modes.normalise(mgr.ui_cfg.get("Interface"), default=_modes.DEFAULT)
ui_mode = args.mode or _cfg_mode

# A plain launch opens whatever was last chosen: in Options, or by starting an
# interface by name (its flag or launcher shortcut).  So an interface named on
# the command line becomes [UI] Interface.  Headless is not remembered — a
# service would otherwise leave the next desktop launch with no window — and
# neither is EDLD-server's own terminal-log default.
if _chosen_mode and not SERVER_BUILD:
    try:
        if remember_interface(config_path, _config_profile, _chosen_mode):
            mgr.reload_now()
    except Exception as _e:
        print(f"{Terminal.WARN}WARNING:{Terminal.END} could not remember the "
              f"interface in {config_path}: {_e}")
if SERVER_BUILD and ui_mode not in _modes.SERVER_BUILD_IDS:
    ui_mode = _modes.TERMINAL
if _modes.needs_terminal(ui_mode):
    try:
        from core.win_console import ensure_console
        ensure_console()
    except Exception:
        pass


# ── Debug log facility ────────────────────────────────────────────────────────
# A file-only diagnostic channel separate from stdout.  Standard output stays
# on the terminal (terminal mode) or routed to /dev/null (textual mode);
# trace lines, plugin errors, and unhandled exceptions go here instead.
# The log file lives at <data_dir>/logs/error[_<profile>]_<YYYYMMDD>.log and
# is written only under --debug or --trace; a run without either leaves no
# file behind.  --debug writes errors, warnings, info and debug lines;
# --trace adds trace lines.  Each run's section starts with a header recording version,
# timestamp, exact launch command, and a fenced copy of the effective config
# (defaults from config file, plus any active profile's overrides).
#
# Initialized here — after profile auto-detection so the header reflects the
# *effective* profile, and before the fork/silence step so the file is ready
# to receive output from the post-fork child.

from core.state import EDLD_DATA_DIR
from core       import debug as _debug

_profile_overrides: dict | None = None
if _config_profile and isinstance(config_dict, dict):
    _po = config_dict.get(_config_profile)
    if isinstance(_po, dict):
        _profile_overrides = _po

_debug.init(
    data_dir=EDLD_DATA_DIR,
    profile=_config_profile or None,
    version=VERSION,
    config_dict=config_dict if isinstance(config_dict, dict) else {},
    profile_overrides=_profile_overrides,
    trace_echo=trace_mode,
    level=log_level,
)
_debug.install_exception_hooks()


# ── Detach / silence for UI modes ─────────────────────────────────────────────
# This MUST run before any background thread spawns (update check, plugin
# senders, CAPI poll, monitor thread, Discord webhook).
#
#   textual — no fork (Textual needs the foreground process group for TTY
#             input).  Parent prints "Launching textual — logs: <path>" then
#             continues in-place; sys.stdout/sys.stderr are swapped for
#             /dev/null at the Python level so background-thread print()
#             calls don't punch through Textual's alt-screen rendering.
#             Textual writes through fd 1 directly and is unaffected.
#
#   terminal — neither.  Scrolling event output to the terminal is the whole
#             point of this mode.

# Record where TLS verification will look. When someone reports that uploads
# stopped, this line answers it outright instead of after a round of guessing.
try:
    _debug.log(_certs.diagnose(), level="INFO")
except Exception:
    pass


if ui_mode != _modes.TERMINAL:   # every interface but the scrolling log
    log_p = _debug.path()
    print(
        f"{Terminal.GOOD}Launching {_modes.BY_ID[ui_mode].name}{Terminal.END}"
        + (f" — diagnostic logs: {log_p}" if log_p else "")
    )
    sys.stdout.flush()
    sys.stderr.flush()
    # Python-level only — Textual writes to fd 1 directly and needs fd 0
    # for TTY input, so we don't touch the underlying file descriptors.
    #
    # EDLD_KEEP_STDERR=1 leaves both streams alone. A dashboard that dies
    # during startup otherwise takes its traceback to /dev/null with it, and
    # the only symptom is the process vanishing — so there has to be a way to
    # get the streams back without editing the source, which is impossible in
    # a shipped binary.
    if os.environ.get("EDLD_KEEP_STDERR") not in ("1", "true", "yes"):
        try:
            sys.stdout = open(os.devnull, "w", encoding="utf-8")
            sys.stderr = open(os.devnull, "w", encoding="utf-8")
        except OSError:
            pass


# ── Now safe to start background threads ──────────────────────────────────────
# Update check spins off here so its result is available by the time we
# render the update notice in the post-bootstrap section.  In textual mode
# this runs in the child; in textual/terminal mode it runs in-process.

_update_thread.start()


# ── Emitter ───────────────────────────────────────────────────────────────────

from core.emit import Emitter, emit_summary

emitter = Emitter(
    mgr, state,
    notify_test=notify_test,
)


# ── CoreAPI + plugins ─────────────────────────────────────────────────────────

from core.core_api      import CoreAPI
from core.plugin_loader import PluginLoader, PluginStorage
from core.journal       import build_dispatch_map
from core.data          import DataProvider
from core.state         import EDLD_DATA_DIR, cmdr_data_dir

# DataProvider — unified source of truth, instantiated before CoreAPI.
# Uses the "core" plugin namespace for its CAPI persisted snapshots; under
# the flat storage layout those land at <cmdr>/data/core.<purpose>.json.
_dp_storage = PluginStorage("core")
data_provider = DataProvider(
    state=state,
    storage=_dp_storage,
    gui_queue_fn=lambda: gui_queue,
    print_fn=lambda m: _debug.info(m),
)

core = CoreAPI(
    state=state,
    active_session=active_session,
    lifetime=lifetime,
    cfg_mgr=mgr,
    emitter=emitter,
    gui_queue=gui_queue,
    journal_dir=journal_dir,
    data_provider=data_provider,
    launch_argv=sys.argv,
    ui_mode=ui_mode,
)
data_provider._plugin_call = core.plugin_call

# Where the Server preferences page finds this profile's pairing files; the
# running server itself is attached as core.server once it has started.
core.server_dir = server_dir
core.server = None
try:
    from core.server.identity import default_server_name as _srv_name
    core.server_name = _srv_name(_config_profile)
except Exception:
    core.server_name = None

loader = PluginLoader(_HERE)
loader.load_all(core)

# A component that fails to load is otherwise invisible: its events are never
# dispatched and the windows reading it show their "nothing yet" placeholder,
# which looks exactly like an ordinary quiet session.  stdout is already
# /dev/null in both UI modes by this point, so the loader's own warning has
# nowhere to go — say it on the real stderr, in the diagnostic log, and (once
# the alerts component is up) in the dashboard itself.
if loader.failed:
    _names = ", ".join(f.name for f in loader.failed)
    _debug.log(
        "Components that failed to load: "
        + "; ".join(f"{f.name} ({f.error})" for f in loader.failed),
        level="ERROR",
    )
    try:
        sys.__stderr__.write(
            f"\nERROR: {len(loader.failed)} component(s) failed to load: {_names}\n"
            f"       Their windows will stay empty.  "
            + (f"See {_debug.path()}\n" if _debug.path()
               else "Run with --debug for details.\n")
        )
        sys.__stderr__.flush()
    except Exception:
        pass
    _alerts = core._plugins.get("alerts")
    if _alerts is not None:
        try:
            _alerts.push_fault(
                "⚠", f"Component(s) failed to load: {_names} — data will be missing."
            )
        except Exception:
            pass

plugin_dispatch = build_dispatch_map(list(core._plugins.values()))
data_provider.start()   # start CAPI poll thread after plugins loaded

# The windows answer with the last session's figures until the history has
# been read (core/lastknown.py). Before any window, or the server, exists.
try:
    from core import lastknown as _lastknown
    _lastknown.install(core)
except Exception as _e:
    _debug.log(f"Last session not restored: {_e}", level="WARNING")


# ── History, session restore, startup banner, server ──────────────────────────
# All of it reads or follows from the journals' history, and none of it has to
# happen before a window can open: it runs first thing on the monitor thread
# (_prepare_history, from run_monitor), before the current journal is
# replayed, which is the order it always ran in. The desktop window and the
# terminal dashboard open meanwhile and fill in as it lands; they used to wait
# for all of it, a full read of every journal included. The scrolling log runs
# the monitor on the main thread, so there it is simply the next thing done.

server = None
_history_prepared = threading.Event()


def _prepare_history() -> None:
    global server
    if _history_prepared.is_set():
        return
    _history_prepared.set()
    # ── Bootstrap from journal history ────────────────────────────────────────────

    _debug.info("Starting EDLD monitor (Press Ctrl+C to stop)")

    from core.journal import bootstrap_fighter_bay, bootstrap_slf, bootstrap_crew, bootstrap_missions, bootstrap_burn_rate

    bootstrap_fighter_bay(state, journal_dir)
    bootstrap_slf(state, journal_dir, trace_mode=trace_mode)
    bootstrap_crew(state, journal_dir, trace_mode=trace_mode)
    bootstrap_missions(state, journal_dir, mgr, trace_mode=trace_mode)
    bootstrap_burn_rate(state, journal_dir, active_session, trace_mode=trace_mode)

    # ── Update notice ─────────────────────────────────────────────────────────────

    _update_thread.join(timeout=2)
    if _update_notice:
        _kind, _value = _update_notice   # _kind is always "release" now
        _repo_url = f"https://github.com/{GITHUB_REPO}"
        _term_msg = (
            f"{Terminal.YELL}\u26a0 Update available: v{_value}{Terminal.END}"
            f"  {Terminal.WHITE}{_repo_url}/releases{Terminal.END}\n"
        )
        if ui_mode == "terminal":
            print(_term_msg)
        else:  # textual / gui — surface it in the dashboard's notice bar
            gui_queue.put(("update_notice", ("release", _value)))
        emitter.set_update_notice(_value)


    # ── Session restore + startup banner ─────────────────────────────────────────

    load_session_state(journal_file, active_session)
    state.sessionstart(active_session)
    emit_summary(
        emitter, state,
        core.session_providers,
        core._plugins.get("session_stats"),
    )


    # ── Server ────────────────────────────────────────────────────────────────────
    # Started after the bootstrap so the first snapshot a device receives already
    # reflects the journal history.  A server that cannot start is reported
    # everywhere a commander might be looking — terminal, log, Alerts — and EDLD
    # carries on without it rather than refusing to run.

    server = None
    if server_on:
        def _server_problem(message: str) -> None:
            _debug.log(message, level="ERROR")
            try:
                sys.__stderr__.write(f"\nERROR: {message}\n")
                sys.__stderr__.flush()
            except Exception:
                pass
            _al = core._plugins.get("alerts")
            if _al is not None:
                try:
                    _al.push_fault("📡", message)
                except Exception:
                    pass

        try:
            from core.server.identity import ServerDependencyError, default_server_name
            from core.server.service  import ServerService
            server = ServerService(
                core,
                directory=server_dir,
                settings=server_cfg,
                name=default_server_name(_config_profile),
                journal_dir=journal_dir,
                log=lambda m: _debug.log(m, level="INFO"),
                alert=lambda m: core.plugin_call("alerts", "_push", "📡", m),
            )
            server.start()
            core.server = server
            # Removes the router's port forward, if one was made, on the way out.
            import atexit as _atexit
            _atexit.register(server.stop)
            _debug.info(server.describe())
            if ui_mode == "terminal":
                print(f"{Terminal.GOOD}{server.describe()}{Terminal.END}")
                if server.firewall_certain:
                    print(f"{Terminal.WARN}This computer's firewall blocks "
                          f"devices from reaching EDLD:{Terminal.END}")
                    for _line in server.firewall_advice:
                        print(f"  {_line}")
                elif server.firewall_advice:
                    # Cannot tell whether it was already dealt with; one line, not
                    # a warning block at every start.
                    print(f"  {server.firewall_advice[0]} If a device cannot "
                          f"connect, see edld --pair.")
        except ServerDependencyError as _e:
            server = None
            _server_problem(f"Server not started: {_e}")
        except OSError as _e:
            import errno as _errno
            server = None
            if _e.errno in (_errno.EADDRINUSE, getattr(_errno, "WSAEADDRINUSE", -1)):
                _why = (f"port {server_cfg.get('Port')} is already in use — another "
                        f"EDLD profile or another program; set Server.Port")
            else:
                _why = (f"could not listen on port {server_cfg.get('Port')}"
                        + (f" at {server_cfg.get('BindAddress')}"
                           if server_cfg.get("BindAddress") else "")
                        + f": {_e}")
            _server_problem(f"Server not started: {_why}.")
        except Exception as _e:
            server = None
            _server_problem(f"Server not started: {type(_e).__name__}: {_e}")


# ── Monitor + launch ──────────────────────────────────────────────────────────

from core.journal      import (run_monitor as _run_monitor, _poll_status_json,
                              _discard_gui_queue)
from core.state        import save_session_state

_edld_start_mono = time.monotonic()

def run_monitor() -> None:
    _prepare_history()
    _run_monitor(
        journal_file,
        state, active_session, lifetime,
        emitter, mgr, gui_queue, journal_dir,
        _edld_start_mono,
        trace_mode=trace_mode,
        plugin_dispatch=plugin_dispatch,
        data_provider=data_provider,
        core=core,
    )


def _log_fatal(what: str) -> None:
    """Record a fatal dashboard error where it can actually be found.

    Called from the launch paths, which run with stdout and stderr pointed at
    /dev/null so terminal noise cannot corrupt the display.
    """
    import traceback as _tb
    detail = _tb.format_exc()
    message = f"{what} failed to start:\n{detail}"
    try:
        _debug.log(message, level="ERROR")
    except Exception:
        pass
    try:
        sys.__stderr__.write(f"\nERROR: {message}\n")
        sys.__stderr__.flush()
    except Exception:
        pass


def _start_status_poller() -> threading.Thread:
    """Start the Status.json poller.

    Every mode needs it, not just the dashboards.
    """
    status_thread = threading.Thread(
        target=_poll_status_json,
        args=(journal_dir, state, gui_queue),
        daemon=True,
    )
    status_thread.start()
    # And the components' once-a-second tick (core/ticker.py), which every
    # mode needs for the same reason.
    from core import ticker as _ticker
    _ticker.start(core, state)
    return status_thread


def _start_background_threads() -> tuple:
    """Start the journal monitor and Status.json poller."""
    monitor_thread = threading.Thread(target=run_monitor, daemon=True)
    monitor_thread.start()
    return monitor_thread, _start_status_poller()


if __name__ == "__main__":
    if _modes.is_window(ui_mode):    # EDCARS or the Dashboard layout
        try:
            from gui.app import run_gui
        except ImportError as _gui_err:
            import traceback as _tb
            # stdout is /dev/null by this point in GUI mode, so the message
            # has to go to the debug log as well as the (silenced) terminal.
            _msg = (
                f"PySide6 GUI import failed: {_gui_err}\n"
                f"Traceback:\n{_tb.format_exc()}\n"
                f"If PySide6 is missing: pip install PySide6"
            )
            _debug.log(_msg, level="ERROR")
            if args.mode:
                # Asked for by flag: say so and stop.
                try:
                    sys.__stderr__.write(f"ERROR: {_msg}\n")
                except Exception:
                    pass
                sys.exit(1)
            # Only the default (or [UI] Interface) chose the desktop window.
            try:
                sys.__stderr__.write(
                    "PySide6 is not installed, so the desktop window (EDCARS) "
                    "cannot open; starting the terminal dashboard instead. "
                    "pip install PySide6 for EDCARS, or pass --dasht to choose "
                    "the terminal dashboard.\n")
                sys.__stderr__.flush()
            except Exception:
                pass
            ui_mode = _modes.TEXTUAL
            core.ui_mode = ui_mode

    if _modes.is_window(ui_mode):
        _gui_theme = mgr.ui_cfg.get("Theme", "default")
        _start_background_threads()
        try:
            sys.exit(run_gui(core, PROGRAM, VERSION, AUTHOR, GITHUB_REPO,
                             theme=_gui_theme))
        except SystemExit:
            raise
        except Exception:
            _log_fatal("Desktop window")
            sys.exit(1)

    elif ui_mode == _modes.TEXTUAL:
        try:
            from tui.app import run_tui
        except ImportError as _tui_err:
            import traceback as _tb
            print(
                f"{Terminal.WARN}ERROR:{Terminal.END} Textual TUI import failed: {_tui_err}\n"
                f"sys.path: {sys.path}\n"
                f"Traceback:\n{_tb.format_exc()}"
                f"\nIf textual is missing: pip install textual"
            )
            sys.exit(1)

        _tui_theme = mgr.ui_cfg.get("Theme", "default")

        # Detach already happened up-front (before plugin loading) so by
        # this point sys.stdout/sys.stderr are already routed to /dev/null
        # in textual mode.  Just start the monitor + the TUI.

        _start_background_threads()

        try:
            run_tui(core, PROGRAM, VERSION, theme=_tui_theme)
        except Exception:
            # stdout and stderr are /dev/null by now, so an escaping exception
            # would leave nothing behind but a non-zero exit. The diagnostic
            # log is the one channel still open, and it is the file users are
            # asked for when something goes wrong, so the traceback belongs
            # there. sys.__stderr__ is the real stream and gets a copy.
            _log_fatal("Textual dashboard")
            sys.exit(1)

    else:  # terminal, and headless, which is terminal with nowhere to print
        # No dashboard drains the redraw queue in this mode, so something must,
        # or it grows for as long as EDLD runs.  See _discard_gui_queue().
        threading.Thread(target=_discard_gui_queue, args=(gui_queue,),
                         daemon=True).start()
        _start_status_poller()
        run_monitor()
