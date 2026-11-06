"""
core/journal.py — Journal file monitoring, event dispatch, and bootstrap logic.

Depends on: core.state, core.config, core.emit
"""

import json
import queue
import re
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

# psutil backs one defensive fallback below (scanning process names to decide
# whether the game is running) and is otherwise unused here.  The call site is
# already wrapped in try/except, so a missing psutil should degrade that single
# check rather than stop EDLD from starting — which is what an unguarded import
# at module scope would do, since this module is imported during startup.
#
# It is documented as a distro-package install because of its C extensions, so
# a source install legitimately may not have it.
try:
    import psutil
except ImportError:            # pragma: no cover - environment dependent
    psutil = None

from core.state import (
    EDLD_DATA_DIR,
    FIGHTER_LOADOUT_NAMES,
    FIGHTER_TYPE_NAMES,
    FUEL_CRIT_THRESHOLD,
    FUEL_WARN_THRESHOLD,
    GITHUB_REPO,
    LABEL_UNKNOWN,
    PIRATE_NOATTACK_MSGS,
    RANK_NAMES,
    RECENT_KILL_WINDOW,
    normalise_ship_name,
    resolve_fighter_name,
    MonitorState,
    SessionData,
    load_session_state,
    save_session_state,
)
from data.ships import is_suit, suit_display
from core.emit import (
    Terminal,
    Emitter,
    emit_summary,
    fmt_credits,
    fmt_duration,
    rate_per_hour,
    clip_name,
)
from core import surface_survey as _surface_survey
from core.ranks import combat_rank_text


# ── Process detection ─────────────────────────────────────────────────────────

_ED_PROCESS_NAMES = {"EliteDangerous64.exe", "EliteDangerous32.exe", "EliteDangerous.exe"}

# Maximum age (seconds) for Status.json to be considered evidence the game is running.
# Status.json is rewritten every ~500ms while the game is active.  90 seconds is
# generous enough to cover loading screens and carrier-jump freezes.
_STATUS_FRESH_THRESHOLD = 90


#: The game's executable, lower-cased, as it appears at the end of a path.
_GAME_EXE = "elitedangerous64.exe"


def _is_game_cmdline(args) -> bool:
    """Whether a process's argument list is the game itself.

    Matched on the last component of any argument, with either separator: under
    Proton argv[0] is a Windows path such as ``Z:\\...\\EliteDangerous64.exe``.
    Only an argument that *is* the executable counts, so a launcher that merely
    mentions the game somewhere in a longer argument does not.
    """
    for arg in args or ():
        tail = str(arg).replace("\\", "/").rsplit("/", 1)[-1].strip().lower()
        if tail == _GAME_EXE:
            return True
    return False


def _game_process_running() -> bool | None:
    """Whether the game's process is running here, or None if that cannot be told.

    Matched on the command line, not the process name.  Under Proton the kernel
    keeps only the first fifteen characters of a process name, so the game runs
    as ``EliteDangerous6`` and a name check can never succeed — which is how a
    commander sitting at the main menu was told the game was not running.
    Session management's kill has always searched the command line, which is
    why it worked where this did not.

    Without psutil — it is a distro package for source installs, and a
    virtualenv may not see it — Linux's /proc gives the same answer.
    """
    if psutil is not None:
        try:
            for proc in psutil.process_iter(["name", "cmdline"]):
                info = proc.info
                if info.get("name") in _ED_PROCESS_NAMES:
                    return True
                if _is_game_cmdline(info.get("cmdline")):
                    return True
            return False
        except Exception:
            pass
    if sys.platform.startswith("linux"):
        import os
        try:
            entries = [e.name for e in os.scandir("/proc") if e.name.isdigit()]
        except OSError:
            return None
        for pid in entries:
            try:
                with open(f"/proc/{pid}/cmdline", "rb") as fh:
                    raw = fh.read(4096)
            except OSError:
                continue                 # exited, or not ours to read
            if raw and _is_game_cmdline(raw.decode("utf-8", "replace").split("\0")):
                return True
        return False
    return None


def _ed_client_running(journal_dir: Path | None = None) -> bool:
    """Return True if Elite Dangerous appears to be running.

    Two signals, either of which is enough:

    * Status.json written within the last 90 seconds.  The game rewrites it
      whenever anything it reports changes, which in flight is constantly —
      but at the main menu, or docked and idle, nothing changes and the file
      goes quiet while the game is still running.  So a stale file is not
      evidence the game has stopped.
    * The game's process, found by command line (see _game_process_running).
      This is what answers at the main menu.  It cannot see a game on another
      machine, which is where the first signal still helps.
    """
    if journal_dir is not None:
        try:
            status_path = Path(journal_dir) / "Status.json"
            if status_path.is_file():
                age_wall = time.time() - status_path.stat().st_mtime
                if age_wall < _STATUS_FRESH_THRESHOLD:
                    return True
        except Exception:
            pass
    return bool(_game_process_running())


def _max_notify_level(notify_levels: dict) -> int:
    return max((v for v in notify_levels.values() if isinstance(v, int)), default=2)


# ── Status.json polling ───────────────────────────────────────────────────────

_STATUS_JSON_POLL_INTERVAL = 0.5


def _status_log(message: str) -> None:
    """Report a Status.json poller fault.  Never raises: the poller is a
    daemon thread and a logging failure must not be what stops it."""
    try:
        from core import debug as _debug
        _debug.log(message, level="ERROR")
    except Exception:
        pass


def _discard_gui_queue(gui_queue: "queue.Queue | None") -> None:
    """Background thread: empty the dashboard queue when there is no dashboard.

    The journal reader, the Status.json poller and a dozen components post
    redraw requests to this queue in every mode, but only the TUI and the
    desktop window ever take anything off it.  In ``--term`` mode nothing
    did, so every request since launch stayed in memory for the life of the
    process — a slow, unbounded leak in the one mode meant for day-long AFK
    sessions.  The messages are redraw hints with no reader, so they are
    simply dropped.
    """
    if gui_queue is None:
        return
    while True:
        try:
            gui_queue.get()
        except Exception:
            time.sleep(1.0)


def _status_epoch(data: dict) -> float:
    """Status.json's own timestamp as epoch seconds; now if it has none."""
    try:
        return datetime.fromisoformat(
            str(data["timestamp"]).replace("Z", "+00:00")).timestamp()
    except (KeyError, ValueError, TypeError):
        return time.time()


def _poll_status_json(
    journal_dir: Path,
    state: MonitorState,
    gui_queue: queue.Queue | None,
) -> None:
    """Background thread: poll Status.json for live shield/hull/SLF flags.

    Status.json is rewritten by the game every ~500ms.  We read it on the
    same cadence.  Fields consumed:

      Flags   (int)   — bit 0x08: ShieldsUp, bit 0x2000000: InFighter
      Balance (int)   — live credit balance; updates immediately on spend

    Status.json does NOT expose hull integrity (Health).  Hull is tracked
    exclusively from HullDamage journal events and repair journal events.
    """
    status_path  = journal_dir / "Status.json"
    last_flags   = None
    last_fuel    = None
    last_balance = None
    last_on_foot = False
    last_body    = ""
    last_pos_emit = 0.0
    last_error_sig: str | None = None
    error_repeats = 0

    while True:
        try:
            if status_path.is_file():
                raw = status_path.read_text(encoding="utf-8").strip()
                if raw:
                    data  = json.loads(raw)
                    flags = data.get("Flags", 0)
                    changed = False

                    # In danger, or being interdicted: a fight, for as long
                    # as the game says so (core/engagement.py).
                    if not state.in_preload:
                        from core import engagement as _eng
                        _eng.note_status_flags(state, flags or 0, data.get("timestamp"))
                        _eng.note_gui_focus(state, data.get("GuiFocus"), data.get("timestamp"))

                    # ── Shield and fighter flags ──────────────────────────
                    if flags != last_flags:
                        last_flags = flags

                        shields_up = bool(flags & 0x08)
                        if state.ship_shields != shields_up:
                            state.ship_shields = shields_up
                            if shields_up:
                                state.ship_shields_recharging = False
                            changed = True

                        in_fighter = bool(flags & 0x2000000)
                        if state.cmdr_in_slf != in_fighter:
                            state.cmdr_in_slf = in_fighter
                            changed = True

                    # ── Fuel level (500ms live updates for display) ───────
                    # Status.json Fuel.FuelMain is updated every ~500ms.
                    # We update state.fuel_current here for the display only.
                    # Fuel threshold checks use ReservoirReplenished events.
                    # Only while in the ship: in an SRV or on foot, Status.json
                    # reports that vehicle's tank — FuelMain 0 in an SRV — and
                    # the ship's fuel read 0% in red the whole time.
                    in_vehicle = bool(flags & 0x04000000) or bool(data.get("Flags2", 0) & 0x1)
                    fuel_main = (None if in_vehicle
                                 else (data.get("Fuel") or {}).get("FuelMain"))
                    if fuel_main is not None and fuel_main != last_fuel:
                        last_fuel = fuel_main
                        state.fuel_current = float(fuel_main)
                        changed = True

                    # ── Credit balance (live spend tracking) ──────────
                    balance = data.get("Balance")
                    if balance is not None and balance != last_balance:
                        last_balance = balance
                        state.assets_balance = float(balance)
                        # With the moment the game wrote it, for reconciling
                        # against the journal (core/credit_flows.py).
                        state.status_balance = int(balance)
                        state.status_balance_ts = _status_epoch(data)
                        changed = True

                    # ── Surface position (Odyssey on-foot exobiology aids) ─
                    # Flags2 bit 0x1 = OnFoot; Flags bit 0x200000 = HasLatLong.
                    flags2  = data.get("Flags2", 0)
                    on_foot = bool(flags2 & 0x1)
                    has_ll  = bool(flags & 0x200000)
                    state.on_foot = on_foot
                    if on_foot != last_on_foot:
                        last_on_foot = on_foot
                        changed = True
                    if has_ll:
                        state.surface_latitude  = data.get("Latitude")
                        state.surface_longitude = data.get("Longitude")
                        state.surface_heading   = data.get("Heading")
                        state.surface_altitude  = data.get("Altitude")
                        state.planet_radius     = data.get("PlanetRadius")
                        body = data.get("BodyName", "") or ""
                        # Surface mining carries no position of its own: every
                        # deposit EDLD records is a MiningRefined event joined
                        # against one of these samples on time.  See
                        # core/surface_survey.py.
                        pos = _surface_survey.position_from_status(data, time.time())
                        if pos is not None:
                            _surface_survey.POSITIONS.add(pos)
                    else:
                        state.surface_latitude = state.surface_longitude = None
                        state.surface_heading  = state.surface_altitude  = None
                        state.planet_radius    = None
                        body = ""
                    body_changed = body != last_body
                    last_body = body
                    state.current_body_name = body
                    now = time.time()
                    emit_pos = body_changed
                    if on_foot and has_ll and (now - last_pos_emit) >= 1.5:
                        last_pos_emit = now
                        emit_pos = True
                    if emit_pos and gui_queue:
                        gui_queue.put(("exobiology_update", None))

                    if changed and gui_queue:
                        gui_queue.put(("vessel_update", None))
                        gui_queue.put(("slf_update",    None))
                        gui_queue.put(("plugin_refresh", "assets"))
        except Exception as exc:
            # This was `except Exception: pass`, which is why a Status.json the
            # poller could never parse looked exactly like a game that was not
            # running: no hull, no fuel, no balance, no position, and nothing
            # anywhere saying why.  A torn read of a file the game rewrites
            # twice a second is normal and must not flood the log, so the first
            # of each distinct fault is reported and repeats are counted.
            sig = f"{type(exc).__name__}: {exc}"
            if sig != last_error_sig:
                if last_error_sig is not None and error_repeats:
                    _status_log(f"...previous Status.json fault repeated "
                                f"{error_repeats} more time(s)")
                last_error_sig, error_repeats = sig, 0
                _status_log(f"Status.json poll failed — {sig}")
            else:
                error_repeats += 1
        time.sleep(_STATUS_JSON_POLL_INTERVAL)


# ── Journal utilities ─────────────────────────────────────────────────────────

def find_latest_journal(journal_dir: Path) -> Path | None:
    journals = sorted(journal_dir.glob("Journal*.log"), reverse=True)
    return journals[0] if journals else None


def trace(message: str, trace_mode: bool = False) -> None:
    """Emit a trace line.  When ``trace_mode`` is enabled the message goes
    both to stdout (terminal mode) and to the debug log via core.debug;
    in UI modes stdout has been silenced so the log is the only sink.
    """
    if not trace_mode:
        return
    print(
        f"{Terminal.WHITE}[Debug]{Terminal.END} {message} "
        f"[{datetime.strftime(datetime.now(), '%H:%M:%S')}]"
    )
    try:
        from core import debug as _debug
        _debug.trace(message)
    except Exception:
        # debug facility errors must never crash callers
        pass


# ── Bootstrap functions ───────────────────────────────────────────────────────

def bootstrap_fighter_bay(state: MonitorState, journal_dir: Path) -> None:
    """Scan the most recent Loadout event to set has_fighter_bay and slf_stock_total.

    Must run before bootstrap_slf and bootstrap_crew, which both guard on
    state.has_fighter_bay being True.
    """
    import re as _re
    from core.journal_index import index_for
    _FIGHTERBAY_CAPACITY = {"3": 1, "5": 4, "6": 6, "7": 9, "8": 12}
    for _name, je in index_for(journal_dir).events(("Loadout", "LoadGame"), newest_first=True):
        if je.get("event") != "Loadout":
            return   # don't go further back than the current session start
        slf_found = False
        slf_cap   = 0
        for mod in je.get("Modules", []):
            item = mod.get("Item", "").lower()
            if "fighterbay" in item:
                slf_found = True
                m = _re.search(r"fighterbay_size(\d+)", item)
                if m:
                    slf_cap = max(slf_cap, _FIGHTERBAY_CAPACITY.get(m.group(1), 1))
        state.has_fighter_bay = slf_found
        if slf_found:
            state.slf_stock_total = slf_cap or 1
        return   # found the most recent Loadout — done


def bootstrap_slf(state: MonitorState, journal_dir: Path, trace_mode: bool = False) -> None:
    """Recover SLF type and deployed/docked state from journal history."""
    if not state.has_fighter_bay:
        return

    from core.journal_index import index_for
    STATE_EVENTS = {"LaunchFighter", "DockFighter", "FighterDestroyed"}
    slf_state_known = False
    slf_type_known  = state.slf_type is not None

    for fname, je in index_for(journal_dir).events(STATE_EVENTS | {"RestockVehicle"},
                                                   newest_first=True):
        ev = je.get("event")

        if not slf_state_known and ev in STATE_EVENTS:
            if ev == "LaunchFighter" and not je.get("PlayerControlled", True):
                state.slf_deployed = True
                state.slf_docked   = False
                lo = je.get("Loadout", "")
                state.slf_loadout  = lo or state.slf_loadout
                # Resolve type from LaunchFighter - Type field may be absent
                # when only one fighter type is stocked (Frontier limitation).
                if not slf_type_known:
                    _ft = je.get("Type", "")
                    if _ft:
                        state.slf_type = resolve_fighter_name(_ft, lo or "")
                        slf_type_known = True
                        trace(f"SLF bootstrap: type={state.slf_type!r} from LaunchFighter", trace_mode)
                    # else: Type absent (Frontier omits when one type stocked)
                    # RestockVehicle scan below will resolve it
                trace(f"SLF bootstrap: deployed from {fname}", trace_mode)
            elif ev == "DockFighter":
                state.slf_deployed = False
                state.slf_docked   = True
                trace(f"SLF bootstrap: docked from {fname}", trace_mode)
            elif ev == "FighterDestroyed":
                state.slf_deployed = False
                state.slf_docked   = False
                state.slf_hull     = 0
                trace(f"SLF bootstrap: destroyed from {fname}", trace_mode)
            slf_state_known = True

        # LaunchFighter (NPC-controlled) is most authoritative for type.
        # Already handled above when slf_state_known was set.
        # Fallback: RestockVehicle if no LaunchFighter found yet.
        if not slf_type_known and ev == "RestockVehicle":
            ft  = je.get("Type", "")
            lo  = je.get("Loadout", "")
            # Skip restocks without a Loadout — Frontier omits it
            # when only one variant is stocked; keep scanning for
            # one with a specific variant to get the full name.
            if not lo:
                continue
            state.slf_type = resolve_fighter_name(ft, lo)
            trace(f"SLF bootstrap: type={state.slf_type!r} from RestockVehicle in {fname}", trace_mode)
            slf_type_known = True

        if slf_state_known and slf_type_known:
            break


def wage_already_counted(state, timestamp) -> bool:
    """Whether a NpcCrewPaidWage is one bootstrap_crew already counted.

    The bootstrap counts every wage in every journal, the current one
    included; the start-up replay of the current journal then handed the
    same wages to the crew handlers, which counted them again — 48.6M cr
    too much in one case, and only in whichever interface happened to
    replay after the bootstrap ran, so the desktop window and the terminal
    dashboard showed different figures for the same crew member.
    """
    through = getattr(state, "crew_paid_through", None)
    if through is None or not timestamp:
        return False
    try:
        return datetime.fromisoformat(str(timestamp)) <= through
    except ValueError:
        return False


def bootstrap_crew(state: MonitorState, journal_dir: Path, trace_mode: bool = False) -> None:
    """Recover crew name, hire date, rank, and total paid from journal history.

    Whatever ship is flown at start-up: crew are paid whichever ship the
    commander flies. It used to do nothing unless that ship had a fighter
    bay, so starting in one without left the paid figure at this session's
    wages alone — "≥ 48.6M cr" for a crew member paid 798M.
    """
    from core.journal_index import index_for
    idx = index_for(journal_dir)

    if not state.crew_name:
        fired: set = set()
        # Newest first. Within a journal nothing before its LoadGame counts
        # (the scan of that file ends there); the journals before it do.
        stopped_in = None
        for fname, je in idx.events(("CrewFire", "CrewAssign", "NpcCrewPaidWage", "LoadGame"),
                                    newest_first=True):
            if fname == stopped_in:
                continue
            ev = je.get("event")
            if ev == "CrewFire" and je.get("Name"):
                fired.add(je["Name"])         # newest first: gone since
            elif ev == "CrewAssign" and je.get("Name") not in fired:
                name = je.get("Name")
                if name:
                    state.crew_name   = name
                    state.crew_active = True
                    trace(f"Crew bootstrap: name from history: {name!r}", trace_mode)
                    break
            elif ev == "NpcCrewPaidWage" and je.get("NpcCrewName") not in fired:
                name = je.get("NpcCrewName")
                if name:
                    state.crew_name   = name
                    state.crew_active = True
                    trace(f"Crew bootstrap: name from NpcCrewPaidWage: {name!r}", trace_mode)
                    break
            elif ev == "LoadGame":
                stopped_in = fname

    if not state.crew_name:
        return

    # Hired is when CrewHire says, not the first CrewAssign: a crew member
    # can sit on the roster for days before first flying. Every hire seen is
    # kept by name, so a crew change later in the run shows the right date
    # at once.
    earliest_assign = None
    hire_time       = None
    found_rank      = None
    wages: list     = []          # (time, amount) for this crew member
    hires: dict     = {}

    for _fname, je in idx.events(("CrewHire", "CrewFire", "CrewAssign",
                                  "NpcCrewRank", "NpcCrewPaidWage")):
        ev = je.get("event")
        try:
            t = datetime.fromisoformat(je["timestamp"])
        except (KeyError, ValueError):
            t = None
        if ev == "CrewHire" and je.get("Name") and t:
            hires[je["Name"]] = t
            if je["Name"] == state.crew_name:
                hire_time = t
        elif ev == "CrewFire" and je.get("Name"):
            hires.pop(je["Name"], None)
        elif ev == "CrewAssign" and je.get("Name") == state.crew_name:
            if t and (earliest_assign is None or t < earliest_assign):
                earliest_assign = t
        elif ev == "NpcCrewRank" and je.get("NpcCrewName") == state.crew_name:
            found_rank = je.get("RankCombat", found_rank)
        elif ev == "NpcCrewPaidWage" and je.get("NpcCrewName") == state.crew_name:
            wages.append((t, je.get("Amount", 0) or 0))

    state.crew_known_hires = hires
    if hire_time is not None:
        state.crew_hire_time = hire_time
        trace(f"Crew bootstrap: {state.crew_name} hired {hire_time}", trace_mode)
    elif earliest_assign is not None:
        # Hired before the oldest journal: the first assignment is the best
        # date there is.
        state.crew_hire_time = earliest_assign
        trace(f"Crew bootstrap: {state.crew_name} first assigned {earliest_assign}", trace_mode)
    if found_rank is not None and state.crew_rank is None:
        state.crew_rank = found_rank
    counted = [(t, a) for t, a in wages
               if hire_time is None or t is None or t >= hire_time]
    total_paid = sum(a for _t, a in counted)
    if total_paid > 0:
        state.crew_total_paid = total_paid
    # The newest wage counted: replayed or live wages up to it are not new.
    times = [t for t, _a in wages if t is not None]
    state.crew_paid_through = max(times) if times else None
    # Whether the journals hold the whole employment. Even then the figure is
    # a floor: the game's own Total Paid includes wages it writes no
    # NpcCrewPaidWage for, so the dashboards always show it as "≥".
    state.crew_paid_complete = hire_time is not None


def bootstrap_last_session_end(
    state: MonitorState, journal_dir: Path, current: Path,
    trace_mode: bool = False,
) -> None:
    """Find when the previous play session ended, from earlier journals.

    A session ends when the commander stops playing, which the journal records
    three different ways:

      * ``Shutdown``                     — a clean quit to desktop
      * ``Music`` with ``MainMenu``      — exited to the main menu
      * the last event in the file       — the client crashed, so neither of
                                           the above was ever written

    Only a marker with no ``LoadGame`` after it ends the session: dropping to
    the main menu and picking a mode again is a bounce mid-session, not an
    end, and dating the session's end to that bounce counts everything played
    afterwards as idle time.

    None of these can be seen from the file being preloaded: Elite opens a new
    journal on every launch, so the marker always lives in an earlier one.  In
    a 269-journal capture, a ``LoadGame`` never once followed a ``Shutdown``
    within the same file, which is why the gap test that reads only the
    current journal could never fire.

    Sets ``state.last_shutdown_time`` so the ``LoadGame`` handler can compare
    against it.  Left as None when no earlier journal exists.
    """
    try:
        journals = sorted(journal_dir.glob("Journal*.log"))
    except OSError:
        return

    earlier = [j for j in journals if j.name < current.name]
    if not earlier:
        return

    marker = None      # Shutdown / MainMenu — an explicit end
    last_ts = None     # final timestamped event — the crash fallback
    try:
        with open(earlier[-1], encoding="utf-8", errors="replace") as fh:
            for line in fh:
                if '"timestamp"' not in line:
                    continue
                try:
                    ev = json.loads(line)
                except ValueError:
                    continue
                stamp = ev.get("timestamp")
                if not stamp:
                    continue
                try:
                    when = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
                except ValueError:
                    continue
                last_ts = when
                name = ev.get("event")
                if name == "Shutdown" or (
                        name == "Music" and ev.get("MusicTrack") == "MainMenu"):
                    marker = when
                elif name == "LoadGame":
                    # Play resumed, so the marker above did not end the
                    # session after all.  A commander who drops to the main
                    # menu and picks a mode again seconds later leaves a
                    # MainMenu behind mid-file; keeping it would date the end
                    # of the session to that bounce rather than to whenever
                    # play actually stopped, and every hour played afterwards
                    # would be counted as idle.
                    marker = None
    except OSError:
        return

    state.last_shutdown_time = marker or last_ts
    if trace_mode and state.last_shutdown_time:
        kind = "explicit" if marker else "last event (no clean exit)"
        from core import debug as _dbg
        _dbg.info(f"  [Session] previous session ended "
                   f"{state.last_shutdown_time.isoformat()} — {kind}")


def bootstrap_hull(state: MonitorState, journal_dir: Path, trace_mode: bool = False) -> None:
    """Recover hull integrity from journal history.

    The game does not write current hull to the current session's journal at
    login — only HullDamage events do.  If damage occurred in a previous
    session, we scan backwards through recent journals to find the last
    meaningful hull event (HullDamage, RepairAll, Resurrect, Repair).
    Only called when the current-session preload produced no HullDamage.
    """
    # ship_hull is initialised to 100 in MonitorState.__init__.
    # If any HullDamage fired during preload it will have set a real value;
    # in that case hull < 100 and we can skip the expensive journal scan.
    if state.ship_hull < 100:
        trace("hull bootstrap: current session has hull data, skipping", trace_mode)
        return

    from core.journal_index import index_for
    idx = index_for(journal_dir)
    RESET_EVENTS  = {"RepairAll", "Resurrect"}
    DAMAGE_EVENTS = {"HullDamage"}
    files = idx.files()
    newest = files[-1] if files else None

    # HullDamage is also written for an SRV, and an SRV's damage is not
    # the ship's: an SRV rolled down a hill at 20% left the ship reading
    # 20% on the next start. Walking backwards, a DockSRV means the events
    # before it were in the SRV, and its LaunchSRV — or a LoadGame that
    # resumed in one — is where that ends. The newest journal starts from
    # wherever the commander is now; each older one from the ship.
    current = None
    in_srv = False
    for fname, je in idx.events(RESET_EVENTS | DAMAGE_EVENTS |
                                {"DockSRV", "LaunchSRV", "LoadGame", "Repair"},
                                newest_first=True):
        if fname != current:
            current = fname
            in_srv = (fname == newest and getattr(state, "vessel_mode", "ship") == "srv")
        ev = je.get("event")

        if ev == "DockSRV":
            in_srv = True
            continue
        if ev in ("LaunchSRV", "LoadGame"):
            in_srv = False
            continue

        if ev in RESET_EVENTS:
            # A repair/rebuy before any damage in scan order means hull was
            # full at the end of that session — stop scanning this file.
            trace(f"hull bootstrap: {ev} found in {fname}, hull=100", trace_mode)
            return  # state.ship_hull stays 100 — correct

        if ev == "Repair":
            item = je.get("Item", "").lower()
            if "hull" in item or item == "":
                trace(f"hull bootstrap: Repair found in {fname}, hull=100", trace_mode)
                return  # hull was repaired — stays 100

        if ev in DAMAGE_EVENTS:
            if je.get("PlayerPilot") and not je.get("Fighter") and not in_srv:
                hull_pct = round(je["Health"] * 100)
                state.ship_hull = hull_pct
                trace(
                    f"hull bootstrap: HullDamage {hull_pct}% from {fname}",
                    trace_mode,
                )
                return

    trace("hull bootstrap: no hull history found, leaving at 100", trace_mode)



def bootstrap_burn_rate(
    state: MonitorState,
    journal_dir: Path,
    active_session,
    trace_mode: bool = False,
) -> None:
    """Seed fuel burn rate from recent journal history.

    Called after current-journal preload when state.fuel_burn_rate is still None
    (e.g. short session with fewer than 2 ReservoirReplenished events, or first
    launch after a crash with no Shutdown).  Scans the two most recent journals
    for consecutive ReservoirReplenished events on the same ship and derives an
    initial burn rate.  The rate will be refined once two live events fire.
    """
    if state.fuel_burn_rate is not None:
        trace("burn rate bootstrap: already set, skipping", trace_mode)
        return

    from core.journal_index import index_for
    idx = index_for(journal_dir)
    # Collect up to 10 reservoir events from recent journals
    reservoir_events: list[tuple] = []  # (datetime, fuel_main, ship_type)
    current_ship = getattr(state, "pilot_ship", None)

    for fname in reversed(idx.files()[-3:]):   # look back no further than 3 journals
        ship_in_file = None
        for _f, je in idx.events(("Loadout", "ShipyardSwap", "ReservoirReplenished"),
                                 files=(fname,)):
            ev = je.get("event")
            if ev == "Loadout":
                ship_in_file = je.get("Ship_Localised") or je.get("Ship")
            elif ev == "ShipyardSwap":
                ship_in_file = je.get("ShipType_Localised") or je.get("ShipType")
            elif ev == "ReservoirReplenished" and je.get("FuelMain") is not None:
                ts = je.get("timestamp", "")
                try:
                    dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
                    reservoir_events.append((dt, float(je["FuelMain"]), ship_in_file))
                except Exception:
                    pass

    # Find two consecutive events for the current ship within a reasonable window
    current_ship_lower = (current_ship or "").lower()
    candidates = [
        (dt, fuel) for dt, fuel, ship in reservoir_events
        if ship is None or current_ship is None
        or (ship or "").lower() == current_ship_lower
    ]
    candidates.sort(key=lambda x: x[0])  # oldest first

    for i in range(len(candidates) - 1):
        dt1, f1 = candidates[i]
        dt2, f2 = candidates[i + 1]
        gap = (dt2 - dt1).total_seconds()
        consumed = f1 - f2
        # Sanity check: gap 10–30 min (reservoir fires every ~17 min), consumed > 0
        if 600 <= gap <= 2400 and consumed > 0:
            rate = 3600 / gap * consumed
            state.fuel_burn_rate = rate
            # Seed anchors with the most recent event so next live event refines rate
            active_session.fuel_check_time  = dt2
            active_session.fuel_check_level = f2
            trace(
                f"burn rate bootstrap: {rate:.3f} t/hr from "
                f"{dt1.strftime('%H:%M')}–{dt2.strftime('%H:%M')} "
                f"({consumed:.3f}t in {gap/60:.0f}m)",
                trace_mode,
            )
            return

    trace("burn rate bootstrap: no usable reservoir pair found", trace_mode)

def bootstrap_missions(
    state: MonitorState,
    journal_dir: Path,
    cfg_mgr,
    trace_mode: bool = False,
) -> None:
    """Reconstruct active massacre mission list and stack value from all journals."""
    from core.journal_index import index_for
    accepted  = {}
    redirected = set()

    for _f, j in index_for(journal_dir).events(
            ("MissionAccepted", "MissionCompleted", "MissionAbandoned",
             "MissionFailed", "MissionRedirected")):
        ev  = j.get("event")
        mid = j.get("MissionID")

        if ev == "MissionAccepted" and "Mission_Massacre" in j.get("Name", ""):
            accepted[mid] = {"reward": j.get("Reward", 0), "expires": j.get("Expiry", None)}
        elif ev in ("MissionCompleted", "MissionAbandoned", "MissionFailed"):
            accepted.pop(mid, None)
            redirected.discard(mid)
        elif ev == "MissionRedirected" and "Mission_Massacre" in j.get("Name", ""):
            redirected.add(mid)

    if not accepted:
        from core import debug as _dbg
        _dbg.info(f"  [Mission bootstrap] No active massacre missions found")
        return

    now = datetime.now(timezone.utc)

    def _not_expired(data):
        exp = data.get("expires")
        if not exp:
            return True
        try:
            return datetime.fromisoformat(str(exp)) > now
        except (ValueError, TypeError):
            return True

    accepted           = {mid: d for mid, d in accepted.items() if _not_expired(d)}
    active_redirected  = redirected & accepted.keys()

    state.active_missions         = list(accepted.keys())
    state.mission_value_map       = {mid: d["reward"] for mid, d in accepted.items()}
    state.stack_value             = sum(d["reward"] for d in accepted.values())
    state.missions_complete       = len(active_redirected)
    state.missions                = True

    from core import debug as _dbg
    _dbg.info(
        f"  [Mission bootstrap] "
        f"{len(state.active_missions)} active | "
        f"{state.missions_complete} complete | "
        f"Stack: {fmt_credits(state.stack_value)}"
    )


# ── Dispatch map builder ─────────────────────────────────────────────────────

def build_dispatch_map(plugins: list) -> dict:
    """Build an event_name -> [plugin, ...] lookup from a list of loaded plugins.

    Called once after PluginLoader.load_all() completes.  The resulting dict
    is passed into monitor_journal / run_monitor as plugin_dispatch.

    Wildcard subscriptions: a plugin may include the sentinel ``"*"`` in its
    SUBSCRIBED_EVENTS list to receive every journal event.  Wildcard
    subscribers are stored under the literal ``"*"`` key and dispatched
    after name-specific subscribers, with deduplication so a plugin
    declaring both "*" and a specific event name only fires once.
    """
    dispatch: dict = {}
    for plugin in plugins:
        for event_name in plugin.SUBSCRIBED_EVENTS:
            dispatch.setdefault(event_name, []).append(plugin)
    return dispatch


# ── Event handler ─────────────────────────────────────────────────────────────

def handle_event(
    line: str,
    state: MonitorState,
    active_session: SessionData,
    lifetime: SessionData,
    emitter: Emitter,
    cfg_mgr,
    gui_queue: queue.Queue | None,
    journal_dir: Path,
    trace_mode: bool = False,
    plugin_dispatch: dict | None = None,
    data_provider=None,
    core=None,
) -> None:
    if not line.strip():
        return
    try:
        j = json.loads(line)
    except ValueError:
        # Printed to the terminal and recorded in the diagnostic log: in the
        # dashboards stdout is /dev/null, so a lost event was invisible.
        print(f"{Terminal.WHITE}Warning:{Terminal.END} Journal parsing error, skipping line")
        try:
            from core import debug as _dbg
            _dbg.log(f"Journal line could not be parsed and was skipped: "
                     f"{line[:160]!r}", level="WARNING")
        except Exception:
            pass
        return

    # ── Event ring buffer — feed DataProvider before plugin dispatch ──────────
    if data_provider is not None:
        data_provider.push_event(j)

    # ── Plugin dispatch (Phase 2+) ────────────────────────────────────────────
    # When plugin_dispatch is provided, forward the event to all subscribed
    # plugins.  The legacy match block below is retained during this transition.
    if plugin_dispatch is not None:
        ev_name = j.get("event", "")
        # This parse sits outside any try in the original code, so one journal
        # line with a timestamp fromisoformat cannot read aborts the preload
        # loop, unwinds through monitor_journal into run_monitor, and kills the
        # monitor thread — leaving the dashboard alive on frozen state with no
        # visible error.  A bad timestamp is not worth losing the session over:
        # treat it as absent and carry on.
        logtime = None
        if "timestamp" in j:
            try:
                logtime = datetime.fromisoformat(j["timestamp"])
            except (ValueError, TypeError):
                trace(
                    f"unparseable timestamp {j.get('timestamp')!r} on {ev_name!r}",
                    trace_mode,
                )
        j["_logtime"] = logtime
        state.event_time = logtime
        # Before any component sees the event, so all of them ask
        # core/engagement.py the same question and get the same answer.
        try:
            from core import engagement as _eng
            _eng.note_event(state, j, logtime)
        except Exception as exc:
            trace(f"engagement note failed: {exc}", trace_mode)
        # Ship display names the game supplies, for every consumer.
        try:
            from data.ships import learn_ship_names_from_event
            learn_ship_names_from_event(j)
        except Exception:
            pass
        # A manual session reset is replayed at the moment it happened, before
        # anything at or after that moment is counted.  See
        # components/session_stats.py.
        if core is not None and logtime is not None:
            try:
                core.plugin_call("session_stats", "before_event", logtime)
            except Exception as exc:
                trace(f"session reset replay failed: {exc}", trace_mode)
        # Name-specific subscribers fire first.  Wildcard subscribers (key "*")
        # fire after, with dedupe so plugins declaring both "*" and a specific
        # name only see the event once.  Empty event names get no dispatch.
        fired_ids: set = set()
        if ev_name:
            for plugin in plugin_dispatch.get(ev_name, []):
                if id(plugin) in fired_ids:
                    continue
                fired_ids.add(id(plugin))
                try:
                    plugin.on_event(j, state)
                except Exception as e:
                    print(
                        f"{Terminal.WARN}Warning:{Terminal.END} "
                        f"Plugin {plugin.PLUGIN_NAME!r} error on {ev_name!r}: {e}"
                    )
            for plugin in plugin_dispatch.get("*", []):
                if id(plugin) in fired_ids:
                    continue
                fired_ids.add(id(plugin))
                try:
                    plugin.on_event(j, state)
                except Exception as e:
                    print(
                        f"{Terminal.WARN}Warning:{Terminal.END} "
                        f"Plugin {plugin.PLUGIN_NAME!r} error on {ev_name!r}: {e}"
                    )
        # Anchor the session clock on LoadGame so ALL activity types (not just
        # combat) get periodic summaries.  Only set on the first LoadGame seen —
        # subsequent ones (ship swap back from menu) preserve the existing anchor.
        if ev_name == "LoadGame" and not state.session_start_time and logtime:
            state.session_start_time  = logtime
            state.last_periodic_summary = time.monotonic()
        # ── Quarter-hour summary — fires at :00, :15, :30, :45 ───────────
        # Checked on every live event so it fires even when the journal is
        # written continuously during active play.  Skipped during preload.
        if not state.in_preload and not state.output_suspended:
            _qh_slot = (datetime.now().minute // 15) * 15
            if _qh_slot != getattr(state, "_last_summary_slot", -1):
                state._last_summary_slot = _qh_slot
                _providers   = getattr(core, "session_providers", [])
                _sess_plugin = (core._plugins.get("session_stats")
                                if core and hasattr(core, "_plugins") else None)
                # Always attempt — emit_summary's own guard suppresses output
                # when dur < 60s and nothing to report.  Fuel is now included
                # unconditionally so summaries fire during any active session.
                emit_summary(emitter, state, _providers, _sess_plugin)
                # Update so the idle-alert fallback timer never drifts
                # further than 15 minutes from the last actual summary.
                state.last_periodic_summary = time.monotonic()
                # Notify activity providers so they can refresh their own
                # summary-based fallback timers.
                for _p in _providers:
                    try:
                        _p.on_summary()
                    except Exception:
                        pass
        # Docked/Undocked: notify DataProvider for CAPI dock-gating
        if ev_name in ("Docked", "Location") and data_provider is not None:
            data_provider.notify_docked(True)
        elif ev_name in ("Undocked", "SupercruiseEntry", "FSDJump") \
                and data_provider is not None:
            data_provider.notify_docked(False)
        state.prev_event = ev_name
        return

    # Legacy path: no plugin_dispatch provided.
    # plugin_call is a no-op in this path — plugin calls become no-ops.
    def plugin_call(_name, _method, *_a, **_kw):  # noqa: E306
        return None

    notify = cfg_mgr.notify_levels
    settings = cfg_mgr.app_settings
    max_trunc = settings.get("TruncateNames", 30)

    try:
        logtime     = datetime.fromisoformat(j["timestamp"]) if "timestamp" in j else None
        state.event_time = logtime
        from core import engagement as _eng
        _eng.note_event(state, j, logtime)

        match j["event"]:

            # ── NPC TEXT ──────────────────────────────────────────────────
            case "ReceiveText" if j["Channel"] == "npc":
                if "$Pirate_OnStartScanCargo" in j["Message"]:
                    piratename = j.get("From_Localised", LABEL_UNKNOWN)
                    if piratename not in active_session.recent_inbound_scans:
                        active_session.inbound_scan_count += 1
                        lifetime.inbound_scan_count       += 1
                        count_str = (
                            f" (x{active_session.inbound_scan_count})"
                            if settings.get("ExtendedStats") else ""
                        )
                        pirate_str = f" [{piratename}]" if settings.get("PirateNames") else ""
                        if len(active_session.recent_inbound_scans) == 5:
                            active_session.recent_inbound_scans.pop(0)
                        active_session.recent_inbound_scans.append(piratename)
                        emitter.emit(
                            msg_term=f"Cargo scan{count_str}{pirate_str}",
                            msg_discord=f"**Cargo scan{count_str}**{pirate_str}",
                            emoji="📦", sigil="-  SCAN",
                            timestamp=logtime, loglevel=notify["InboundScan"],
                        )
                elif any(x in j["Message"] for x in PIRATE_NOATTACK_MSGS):
                    active_session.low_cargo_count += 1
                    count_str = (
                        f" (x{active_session.low_cargo_count})"
                        if settings.get("ExtendedStats") else ""
                    )
                    emitter.emit(
                        msg_term=(
                            f"{Terminal.WARN}"
                            "Pirate didn't engage due to insufficient cargo value"
                            f"{count_str}{Terminal.END}"
                        ),
                        msg_discord=(
                            "**Pirate didn't engage due to insufficient cargo value**"
                            f"{count_str}"
                        ),
                        emoji="📦", sigil="-  SCAN",
                        timestamp=logtime, loglevel=notify["LowCargoValue"],
                        event="LowCargoValue",
                    )
                elif "Police_Attack" in j["Message"]:
                    emitter.emit(
                        msg_term=f"{Terminal.BAD}Under attack by security services!{Terminal.END}",
                        msg_discord="**Under attack by security services!**",
                        emoji="🚨", sigil="!! ATCK",
                        timestamp=logtime, loglevel=notify["PoliceAttack"],
                    )

            # ── TARGET SCANNED ────────────────────────────────────────────
            case "ShipTargeted" if "Ship" in j:
                ship = normalise_ship_name(j.get("Ship_Localised") or j.get("Ship"))
                rank = "" if "PilotRank" not in j else f" ({j['PilotRank']})"
                if (
                    ship != active_session.last_security_ship
                    and "PilotName" in j
                    and "$ShipName_Police" in j["PilotName"]
                ):
                    active_session.last_security_ship = ship
                    emitter.emit(
                        msg_term=f"{Terminal.WARN}Scanned security{Terminal.END} ({ship})",
                        msg_discord=f"**Scanned security** ({ship})",
                        emoji="🔍", sigil="-  SCAN",
                        timestamp=logtime, loglevel=notify["PoliceScan"],
                    )
                else:
                    state.sessionstart(active_session)
                    piratename = j.get("PilotName_Localised", LABEL_UNKNOWN)
                    check      = piratename if settings.get("MinScanLevel") != 0 else ship
                    scanstage  = j.get("ScanStage", 0)
                    if (
                        scanstage >= settings.get("MinScanLevel", 1)
                        and check not in active_session.recent_outbound_scans
                    ):
                        if len(active_session.recent_outbound_scans) == 10:
                            active_session.recent_outbound_scans.pop(0)
                        active_session.recent_outbound_scans.append(check)
                        pirate_str = (
                            f" [{piratename}]"
                            if settings.get("PirateNames") and piratename != LABEL_UNKNOWN
                            else ""
                        )
                        emitter.emit(
                            msg_term=f"{Terminal.WHITE}Scan{Terminal.END}: {ship}{rank}{pirate_str}",
                            msg_discord=f"**{ship}**{rank}{pirate_str}",
                            emoji="🔍", sigil="-  SCAN",
                            timestamp=logtime, loglevel=notify["InboundScan"],
                        )

            # ── KILLS ─────────────────────────────────────────────────────
            case "Bounty" | "FactionKillBond":
                state.sessionstart(active_session)
                if settings.get("MinScanLevel") == 0:
                    active_session.recent_outbound_scans.clear()

                active_session.kills   += 1
                lifetime.kills         += 1
                thiskill                = logtime
                killtime_str            = ""
                state.last_rate_check   = time.monotonic()
                active_session.pending_merit_events += 1

                if active_session.last_kill_time:
                    secs = (thiskill - active_session.last_kill_time).total_seconds()
                    killtime_str = f" (+{fmt_duration(secs)})"
                    active_session.kill_interval_total += secs
                    if len(active_session.recent_kill_times) == RECENT_KILL_WINDOW:
                        active_session.recent_kill_times.pop(0)
                    active_session.recent_kill_times.append(secs)
                    lifetime.kill_interval_total += secs

                active_session.last_kill_time = logtime
                if not state.in_preload:
                    state.last_kill_mono = time.monotonic()

                if j["event"] == "Bounty":
                    bountyvalue = j["Rewards"][0]["Reward"]
                    ship        = normalise_ship_name(j.get("Target_Localised") or j.get("Target"))
                else:
                    bountyvalue      = j["Reward"]
                    ship             = "Bond"
                    state.reward_type = "bonds"

                pirate_str = (
                    f" [{clip_name(j['PilotName_Localised'], max_trunc)}]"
                    if "PilotName_Localised" in j and settings.get("PirateNames")
                    else ""
                )
                active_session.credit_total += bountyvalue
                lifetime.credit_total       += bountyvalue

                kills_t = f" x{active_session.kills}" if settings.get("ExtendedStats") else ""
                kills_d = f"x{active_session.kills} " if settings.get("ExtendedStats") else ""
                bv_str  = (
                    f" [{fmt_credits(bountyvalue)} cr]"
                    if settings.get("BountyValue") else ""
                )
                victimfaction = j.get("VictimFaction_Localised") or j.get("VictimFaction", "")
                active_session.faction_tally[victimfaction] = (
                    active_session.faction_tally.get(victimfaction, 0) + 1
                )
                lifetime.faction_tally[victimfaction] = (
                    lifetime.faction_tally.get(victimfaction, 0) + 1
                )
                fc_count = (
                    f" x{active_session.faction_tally[victimfaction]}"
                    if settings.get("ExtendedStats") else ""
                )
                bf_str = (
                    f" [{clip_name(victimfaction, max_trunc)}{fc_count}]"
                    if settings.get("BountyFaction") else ""
                )
                emitter.emit(
                    msg_term=(
                        f"{Terminal.WHITE}Kill{Terminal.END}{kills_t}: "
                        f"{ship}{killtime_str}{pirate_str}{bv_str}{bf_str}"
                    ),
                    msg_discord=(
                        f"{kills_d}**{ship}{killtime_str}**"
                        f"{pirate_str}{bv_str}{bf_str}"
                    ),
                    emoji="💥", sigil="*  KILL",
                    timestamp=logtime, loglevel=notify["RewardEvent"],
                )

            # ── FUEL ──────────────────────────────────────────────────────
            case "ReservoirReplenished":
                fuel_pct = round((j["FuelMain"] / state.fuel_tank_size) * 100)
                fuel_time_remain = ""
                if (
                    active_session.fuel_check_time
                    and state.session_start_time
                    and logtime > active_session.fuel_check_time
                ):
                    fuel_time   = (logtime - active_session.fuel_check_time).total_seconds()
                    fuel_hour   = 3600 / fuel_time * (active_session.fuel_check_level - j["FuelMain"])
                    fuel_remain = fmt_duration(j["FuelMain"] / fuel_hour * 3600) if fuel_hour > 0 else None
                    if fuel_remain:
                        fuel_time_remain = f" (~{fuel_remain})"
                active_session.fuel_check_time  = logtime
                active_session.fuel_check_level = j["FuelMain"]
                col = ""; level = ":"; fuel_loglevel = 0
                if j["FuelMain"] < state.fuel_tank_size * FUEL_CRIT_THRESHOLD:
                    col = Terminal.BAD;  fuel_loglevel = notify["FuelCritical"]; level = " critical!"
                elif j["FuelMain"] < state.fuel_tank_size * FUEL_WARN_THRESHOLD:
                    col = Terminal.WARN; fuel_loglevel = notify["FuelWarning"];  level = " low:"
                elif state.session_start_time:
                    fuel_loglevel = notify["FuelStatus"]
                emitter.emit(
                    msg_term=f"{col}Fuel: {fuel_pct}% remaining{Terminal.END}{fuel_time_remain}",
                    msg_discord=f"**Fuel{level} {fuel_pct}% remaining**{fuel_time_remain}",
                    emoji="⛽", sigil="+  FUEL",
                    timestamp=logtime, loglevel=fuel_loglevel,
                )

            # ── FIGHTER EVENTS ────────────────────────────────────────────
            case "FighterDestroyed" if not _eng.jumping_away(state, logtime):
                state.slf_deployed       = False
                state.slf_docked         = False
                state.slf_hull           = 0
                state.slf_orders         = None
                state.slf_destroyed_count += 1
                if gui_queue: gui_queue.put(("slf_update", None))
                emitter.emit(
                    msg_term=f"{Terminal.BAD}Fighter destroyed!{Terminal.END}",
                    msg_discord="**Fighter destroyed!**",
                    emoji="💀", sigil="!! SLF ",
                    timestamp=logtime, loglevel=notify["FighterLost"],
                )

            case "LaunchFighter" if not j["PlayerControlled"]:
                state.slf_deployed = True
                state.slf_docked   = False
                state.slf_hull     = 100
                state.slf_orders   = "Defend"
                state.slf_loadout  = j.get("Loadout")
                if gui_queue: gui_queue.put(("slf_update", None))
                emitter.emit(
                    msg_term="Fighter launched",
                    emoji="🛩️", sigil="-  SLF ",
                    timestamp=logtime, loglevel=2,
                )

            case "RestockVehicle":
                ft   = j.get("Type", "")
                lo   = j.get("Loadout", "")
                lkey = (ft, lo)
                if lkey in FIGHTER_LOADOUT_NAMES:
                    state.slf_type = FIGHTER_LOADOUT_NAMES[lkey]
                elif ft in FIGHTER_TYPE_NAMES:
                    state.slf_type = FIGHTER_TYPE_NAMES[ft]
                elif ft:
                    state.slf_type = ft.replace("_", " ").title()
                state.slf_destroyed_count = 0
                state.slf_docked          = True
                state.slf_deployed        = False
                if gui_queue: gui_queue.put(("slf_update", None))

            case "DockFighter":
                state.slf_deployed = False
                state.slf_docked   = True
                state.slf_hull     = 100
                state.slf_orders   = None
                if gui_queue: gui_queue.put(("slf_update", None))

            case "FighterRebuilt":
                state.slf_destroyed_count = max(0, state.slf_destroyed_count - 1)
                if gui_queue: gui_queue.put(("slf_update", None))

            case "FighterOrders":
                state.slf_orders = j.get("Orders")
                if gui_queue: gui_queue.put(("slf_update", None))

            # ── SHIELDS / HULL ────────────────────────────────────────────
            case "ShieldState":
                if j["ShieldsUp"]:
                    shields = "back up"; col = Terminal.GOOD
                    state.ship_shields            = True
                    state.ship_shields_recharging = False
                else:
                    shields = "down!"; col = Terminal.BAD
                    state.ship_shields            = False
                    state.ship_shields_recharging = True
                if gui_queue: gui_queue.put(("vessel_update", None))
                emitter.emit(
                    msg_term=f"{col}Ship shields {shields}{Terminal.END}",
                    msg_discord=f"**Ship shields {shields}**",
                    emoji="🛡️", sigil="^  SHLD",
                    timestamp=logtime, loglevel=notify["ShieldEvent"],
                )

            case "HullDamage":
                hullhealth = round(j["Health"] * 100)
                if j["Fighter"] and not j["PlayerPilot"] and state.fighter_integrity != j["Health"]:
                    state.fighter_integrity = j["Health"]
                    state.slf_hull          = hullhealth
                    if gui_queue: gui_queue.put(("slf_update", None))
                    emitter.emit(
                        msg_term=(
                            f"{Terminal.WARN}Fighter hull damaged!{Terminal.END} "
                            f"(Integrity: {hullhealth}%)"
                        ),
                        msg_discord=f"**Fighter hull damaged!** (Integrity: {hullhealth}%)",
                        emoji="🛩️", sigil="^  SLF ",
                        timestamp=logtime, loglevel=notify["FighterDamage"],
                    )
                elif j["PlayerPilot"] and not j["Fighter"]:
                    state.ship_hull = hullhealth
                    if gui_queue: gui_queue.put(("vessel_update", None))
                    emitter.emit(
                        msg_term=(
                            f"{Terminal.BAD}Ship hull damaged!{Terminal.END} "
                            f"(Integrity: {hullhealth}%)"
                        ),
                        msg_discord=f"**Ship hull damaged!** (Integrity: {hullhealth}%)",
                        emoji="⚠️", sigil="^  HULL",
                        timestamp=logtime, loglevel=notify["HullEvent"],
                    )

            case "Died":
                emitter.emit(
                    msg_term=f"{Terminal.BAD}Ship destroyed!{Terminal.END}",
                    msg_discord="**Ship destroyed!**",
                    emoji="💀", sigil="!! DEAD",
                    timestamp=logtime, loglevel=notify["Died"],
                )

            # ── SESSION TRANSITIONS ───────────────────────────────────────
            case "Music" if j["MusicTrack"] == "MainMenu":
                state.sessionend()
                state.in_game = False
                if state.offline_since_mono is None:
                    state.offline_since_mono = time.monotonic()
                emitter.emit(
                    msg_term="Exited to main menu",
                    emoji="🚪", sigil="-  INFO",
                    timestamp=logtime, loglevel=2,
                )

            case "LoadGame":
                state.reset_missions()
                state.crew_active = False
                state.in_game     = True
                state.offline_since_mono  = None
                state.last_offline_alert  = None
                # Reset the kill timer on every LoadGame so the idle-alert
                # cooldown restarts from when the player enters the game,
                # not from when the last periodic summary fired.
                state.last_kill_mono = time.monotonic()
                # Resumed on foot, "Ship" is the suit (components/commander.py):
                # the ship stays as it was.
                _on_foot = is_suit(j.get("Ship"))
                if not _on_foot:
                    state.pilot_ship = normalise_ship_name(j.get("Ship_Localised") or j.get("Ship"))
                if j.get("ShipName"):  state.ship_name  = j["ShipName"]
                if j.get("ShipIdent"): state.ship_ident = j["ShipIdent"]
                if "GameMode" in j:
                    state.pilot_mode = (
                        "Private Group" if j["GameMode"] == "Group" else j["GameMode"]
                    )
                # Anchor session clock here so ALL activity types trigger summaries,
                # not just combat.  Only set on first LoadGame of the session.
                if not state.session_start_time:
                    state.session_start_time = logtime
                    state.last_periodic_summary = time.monotonic()
                if gui_queue: gui_queue.put(("vessel_update", None))
                # The game now writes LoadGame before Rank and Progress, so
                # on the first LoadGame of a run the rank is not known yet;
                # it is left out rather than shown as "None +None%".
                _rank = combat_rank_text(state)
                cmdrinfo = (
                    f"{suit_display(j.get('Ship'), j.get('Ship_Localised')) if _on_foot else state.pilot_ship}"
                    f" / {state.pilot_mode}"
                    + (f" / {_rank}" if _rank else "")
                )
                emitter.emit(
                    msg_term=f"CMDR {state.pilot_name} ({cmdrinfo})",
                    msg_discord=f"**CMDR {state.pilot_name}** ({cmdrinfo})",
                    emoji="👤", sigil="-  INFO",
                    timestamp=logtime, loglevel=2,
                )

            case "Loadout":
                # More fuel than the new tank holds is the last ship's
                # (components/commander.py says why).
                _main = float((j.get("FuelCapacity") or {}).get("Main") or 0)
                if (state.fuel_current is not None and _main >= 2
                        and state.fuel_current > _main + 0.01):
                    state.fuel_current = None
                state.fuel_tank_size = (
                    j["FuelCapacity"]["Main"] if j["FuelCapacity"]["Main"] >= 2 else 64
                )
                state.ship_name  = j.get("ShipName") or None
                state.ship_ident = j.get("ShipIdent") or None
                if gui_queue: gui_queue.put(("vessel_update", None))
                _FIGHTERBAY_CAPACITY = {"3": 1, "5": 4, "6": 6}
                slf_found = False; slf_cap = 0
                for mod in j.get("Modules", []):
                    item = mod.get("Item", "").lower()
                    if "fighterbay" in item:
                        slf_found = True
                        m = re.search(r"fighterbay_size(\d+)", item)
                        if m:
                            slf_cap = max(slf_cap, _FIGHTERBAY_CAPACITY.get(m.group(1), 1))
                state.has_fighter_bay = slf_found
                if slf_found:
                    state.slf_stock_total     = slf_cap or 1
                    state.slf_destroyed_count = 0
                if not slf_found:
                    state.slf_type     = None
                    state.slf_deployed = False
                    state.slf_docked   = False
                    state.slf_hull     = 100
                    state.slf_loadout  = None
                    state.crew_active  = False
                    state.crew_name    = None
                if slf_found and state.crew_name and not state.crew_active:
                    state.crew_active = True
                if gui_queue:
                    gui_queue.put(("slf_update",  None))
                    gui_queue.put(("crew_update", None))

            # ── VEHICLE SWITCH ────────────────────────────────────────────
            case "VehicleSwitch":
                to = j.get("To", "")
                if to == "Fighter":   state.cmdr_in_slf = True
                elif to == "Mothership": state.cmdr_in_slf = False
                if gui_queue:
                    gui_queue.put(("vessel_update", None))
                    gui_queue.put(("slf_update",    None))

            # ── NPC CREW ──────────────────────────────────────────────────
            case "CrewAssign":
                name = j.get("Name")
                if name:
                    if state.crew_name != name:
                        state.crew_total_paid = 0
                    state.crew_name   = name
                    state.crew_active = True
                if gui_queue: gui_queue.put(("crew_update", None))

            case "NpcCrewPaidWage":
                wage_name = j.get("NpcCrewName")
                if not state.crew_name and wage_name:
                    state.crew_name = wage_name
                if wage_name and wage_name == state.crew_name:
                    state.crew_active = True
                    if state.crew_total_paid is None:
                        state.crew_total_paid = 0
                    if not wage_already_counted(state, j.get("timestamp")):
                        state.crew_total_paid += j.get("Amount", 0)
                if gui_queue: gui_queue.put(("crew_update", None))

            case "NpcCrewRank":
                rank_name = j.get("NpcCrewName")
                if not state.crew_name and rank_name:
                    state.crew_name = rank_name
                if rank_name and rank_name == state.crew_name:
                    state.crew_rank = j.get("RankCombat", state.crew_rank)
                if gui_queue: gui_queue.put(("crew_update", None))

            # ── NAVIGATION ───────────────────────────────────────────────
            case "SupercruiseDestinationDrop" if any(
                x in j["Type"] for x in ["$MULTIPLAYER", "$Warzone"]
            ):
                state.sessionstart(active_session, True)
                type_local    = j.get("Type_Localised", LABEL_UNKNOWN)
                state.pilot_body = type_local
                if gui_queue: gui_queue.put(("cmdr_update", None))
                emoji = "🪐" if "Resource Extraction Site" in type_local else "⚔️"
                emitter.emit(
                    msg_term=f"Dropped at {type_local}",
                    emoji=emoji, sigil=">  DROP",
                    timestamp=logtime, loglevel=2,
                )

            case "EjectCargo" if not j.get("Abandoned"):
                name = normalise_ship_name(j.get("Type_Localised") or j.get("Type"))
                count = int(j.get("Count", 1) or 1)
                kind, pirate = _eng.judge_jettison(state, logtime)
                if kind == "taken":
                    emitter.emit(
                        msg_term=f"{Terminal.BAD}Cargo stolen!{Terminal.END} ({name})",
                        msg_discord=f"**Cargo stolen!** ({name})",
                        emoji="📦", sigil="^  SHLD",
                        timestamp=logtime, loglevel=notify["CargoLost"],
                        event="CargoLost",
                    )
                else:
                    emitter.emit(
                        msg_term=_eng.jettison_text(count, name, kind, pirate),
                        emoji="📦", sigil="-  CRGO",
                        timestamp=logtime, loglevel=2 if kind == "payment" else 1,
                    )

            case "Rank" | "Progress":
                from core import ranks as _ranks
                _ranks.apply(state, j)

            case ("SquadronStartup" | "JoinedSquadron" | "SquadronCreated"
                  | "SquadronPromotion" | "SquadronDemotion" | "LeftSquadron"
                  | "KickedFromSquadron" | "DisbandedSquadron"):
                from core import squadron as _squadron
                _squadron.apply(state, j)

            # ── POWERPLAY ─────────────────────────────────────────────────
            case "Powerplay":
                if j.get("Power"):     state.pp_power        = j["Power"]
                if j.get("Rank") is not None: state.pp_rank  = j["Rank"]
                if j.get("Merits") is not None: state.pp_merits_total = j["Merits"]
                if gui_queue: gui_queue.put(("cmdr_update", None))

            case "PowerplayJoin":
                state.pp_power = j.get("Power"); state.pp_rank = 1
                if gui_queue: gui_queue.put(("cmdr_update", None))

            case "PowerplayLeave":
                state.pp_power = state.pp_rank = state.pp_merits_total = None
                if gui_queue: gui_queue.put(("cmdr_update", None))

            case "PowerplayDefect":
                state.pp_power = j.get("ToPower"); state.pp_rank = 1
                if gui_queue: gui_queue.put(("cmdr_update", None))

            case "PowerplayRank":
                state.pp_rank = j.get("Rank")
                if gui_queue: gui_queue.put(("cmdr_update", None))

            case "PowerplayMerits":
                if j.get("TotalMerits") is not None:
                    state.pp_merits_total = j["TotalMerits"]
                    if gui_queue: gui_queue.put(("cmdr_update", None))
                if j.get("Power") and not state.pp_power:
                    state.pp_power = j["Power"]
                if active_session.pending_merit_events > 0 and j["MeritsGained"] < 500:
                    active_session.merits += j["MeritsGained"]
                    lifetime.merits       += j["MeritsGained"]
                    emitter.emit(
                        msg_term=f"Merits: +{j['MeritsGained']:,} ({j['Power']})",
                        emoji="⭐", sigil="+  MERC",
                        timestamp=logtime, loglevel=notify["MeritEvent"],
                    )
                    active_session.pending_merit_events -= 1

            # ── LOCATION ──────────────────────────────────────────────────
            case "Location":
                if j.get("StarSystem"): state.pilot_system = j["StarSystem"]
                if j.get("Body"):
                    state.pilot_body = j["Body"] if j.get("Docked") is False else None
                if j.get("Docked") and j.get("StationName"):
                    state.pilot_body = j["StationName"]
                elif j.get("Docked") and not j.get("StationName"):
                    state.pilot_body = None
                if gui_queue: gui_queue.put(("cmdr_update", None))
                if j["BodyType"] == "PlanetaryRing":
                    state.sessionstart(active_session)

            case "Docked":
                if j.get("StationName"): state.pilot_body   = j["StationName"]
                if j.get("StarSystem"):  state.pilot_system = j["StarSystem"]
                if gui_queue: gui_queue.put(("cmdr_update", None))

            case "Undocked":
                state.pilot_body = None
                if gui_queue: gui_queue.put(("cmdr_update", None))

            case "ShipyardSwap":
                state.pilot_ship = normalise_ship_name(j.get("ShipType_Localised") or j.get("ShipType"))
                state.fuel_current = None      # the old ship's; the swap gives no level
                emitter.emit(
                    msg_term=f"Swapped ship to {state.pilot_ship}",
                    emoji="🚢", sigil="-  SHIP",
                    timestamp=logtime, loglevel=2,
                )

            case "Shutdown":
                state.in_game = False
                if state.offline_since_mono is None:
                    state.offline_since_mono = time.monotonic()
                emitter.emit(
                    msg_term="Quit to desktop",
                    emoji="🛑", sigil="-  INFO",
                    timestamp=logtime, loglevel=2,
                )
                if __name__ == "__main__" and not state.in_preload:
                    sys.exit()

            case "SupercruiseEntry" | "FSDJump":
                if j["event"] == "SupercruiseEntry":
                    event_name = "Supercruise entry in"; emoji = "🚀"; sigil = ">  JUMP"
                    state.pilot_system = j.get("StarSystem", state.pilot_system)
                    state.pilot_body   = None
                else:
                    event_name = "FSD jump to"; emoji = "🌌"; sigil = ">  JUMP"
                    state.pilot_system = j.get("StarSystem", state.pilot_system)
                    state.pilot_body   = None
                if gui_queue: gui_queue.put(("cmdr_update", None))
                emitter.emit(
                    msg_term=f"{event_name} {j['StarSystem']}",
                    emoji=emoji, sigil=sigil,
                    timestamp=logtime, loglevel=2,
                )
                state.sessionend()

        state.prev_event = j["event"]

    except Exception as e:
        event_name  = j.get("event", LABEL_UNKNOWN) if isinstance(j, dict) else LABEL_UNKNOWN
        logtime_fmt = datetime.strftime(logtime, "%H:%M:%S") if logtime else LABEL_UNKNOWN
        print(
            f"{Terminal.WARN}Warning:{Terminal.END} "
            f"Process event error for [{event_name}]: "
            f"{e} (logtime: {logtime_fmt})"
        )


# ── Journal monitor ───────────────────────────────────────────────────────────

def _complete_line(pending: list, chunk: str) -> str | None:
    """Join a journal line read in pieces; None until the line is complete.

    The game does not always write a line in one go: a long event — FSDJump
    with its factions and conflicts runs to several kilobytes — can reach the
    file in two writes, and a read between them returns the first half with
    no newline. Parsed as it stood, that half was rejected and skipped, then
    the second half was rejected and skipped too: the event was lost, with a
    warning printed to a terminal the dashboards had sent to /dev/null. The
    commonest casualty was the jump itself, which is why the location stayed
    on the system just left.

    ``pending`` is a one-element list holding the part read so far. A chunk
    without a trailing newline is added to it and None is returned; the chunk
    that ends the line returns the whole of it.
    """
    if not chunk.endswith("\n"):
        pending[0] += chunk
        return None
    line = pending[0] + chunk
    pending[0] = ""
    return line


def _announce_monitoring(state: MonitorState, emitter: Emitter) -> None:
    """The "Monitoring Active" banner in the terminal and embed in Discord."""
    # ── Terminal startup banner ───────────────────────────────────────
    term_bar = "=" * 42
    stack_line    = ""
    location_line = ""
    pp_line       = ""

    if state.stack_value > 0:
        _done = state.missions_complete
        _tot  = len(state.active_missions)
        _rem  = _tot - _done
        _status = (
            "all complete — turn in!"
            if _rem == 0
            else f"{_done}/{_tot} complete, {_rem} remaining"
        )
        stack_line = f"  Stack: {fmt_credits(state.stack_value)} ({_status})\n"

    if state.pilot_system:
        _loc = state.pilot_system
        if state.pilot_body:
            _loc += f"  |  {state.pilot_body}"
        location_line = f"  {_loc}\n"

    if state.pp_power:
        _pp_rank   = f"  Rank {state.pp_rank}" if state.pp_rank else ""
        _pp_merits = f"  ({state.pp_merits_total:,} merits)" if state.pp_merits_total else ""
        pp_line = f"  {state.pp_power}{_pp_rank}{_pp_merits}\n"

    rank_line = f"  {combat_rank_text(state)}\n" if combat_rank_text(state) else ""
    term_msg = (
        f"\n{term_bar}\n"
        f"  ▶  MONITORING ACTIVE\n"
        f"  CMDR {state.pilot_name}\n"
        f"  {state.pilot_ship}  |  {state.pilot_mode}\n"
        f"{rank_line}"
        f"{pp_line}"
        f"{location_line}"
        f"{stack_line}"
        f"{term_bar}"
    )
    print(f"{Terminal.CYAN}{term_msg}{Terminal.END}\n")

    # ── Discord startup embed ─────────────────────────────────────────
    try:
        from discord_webhook import DiscordEmbed
        embed = DiscordEmbed(title="▶  Monitoring Active", color="00e5ff")

        # Lead with who and where — the two things that orient a reader
        # scrolling past in a channel.  Ship, mode and rank are compact
        # enough to share a row of inline fields underneath.
        embed.add_embed_field(
            name="Commander", value=f"CMDR {state.pilot_name}", inline=False)

        if state.pilot_system:
            # pilot_body doubles as the station name when docked — the
            # journal's StationName is written into it, so there is no
            # separate station field to add here.
            _loc_val = state.pilot_system
            if state.pilot_body:
                _loc_val += f" / {state.pilot_body}"
            embed.add_embed_field(name="Location", value=_loc_val, inline=False)

        embed.add_embed_field(name="Ship",  value=state.pilot_ship  or "Unknown", inline=True)
        embed.add_embed_field(name="Mode",  value=state.pilot_mode  or "Unknown", inline=True)
        embed.add_embed_field(
            name="Combat Rank",
            value=combat_rank_text(state) or "Unknown", inline=True,
        )

        # Credits on hand, cargo aboard and fuel say what shape the
        # commander is starting in; the embed never reported any of it.
        _balance = getattr(state, "assets_balance", None)
        if _balance:
            embed.add_embed_field(
                name="Credits", value=fmt_credits(_balance), inline=True)

        _cap = int(getattr(state, "cargo_capacity", 0) or 0)
        if _cap > 0:
            _items = getattr(state, "cargo_items", {}) or {}
            _carried = sum(int((v or {}).get("count", 0) or 0)
                           for v in _items.values())
            embed.add_embed_field(
                name="Cargo", value=f"{_carried} / {_cap} t", inline=True)

        _fuel = getattr(state, "fuel_current", None)
        _tank = getattr(state, "fuel_tank_size", None)
        if _fuel is not None and _tank:
            embed.add_embed_field(
                name="Fuel", value=f"{_fuel / _tank * 100:.0f}%", inline=True)

        if state.pp_power:
            _pp_val = state.pp_power
            if state.pp_rank:        _pp_val += f" — Rank {state.pp_rank}"
            if state.pp_merits_total: _pp_val += f" ({state.pp_merits_total:,} merits)"
            embed.add_embed_field(name="Powerplay", value=_pp_val, inline=False)

        # A carrier parked somewhere else is easy to forget about.
        _carrier = getattr(state, "assets_carrier", None)
        if _carrier:
            _c_name = _carrier.get("name") or _carrier.get("callsign") or "Carrier"
            _c_val = f"{_c_name} — {_carrier.get('system') or 'unknown system'}"
            _c_fuel = _carrier.get("fuel")
            if _c_fuel is not None:
                _c_val += f"\n{int(_c_fuel)} t tritium"
            embed.add_embed_field(name="Fleet Carrier", value=_c_val, inline=False)

        if state.stack_value > 0:
            _done = state.missions_complete; _tot = len(state.active_missions)
            _rem  = _tot - _done
            _status = (
                "All complete — turn in!" if _rem == 0
                else f"{_done}/{_tot} complete, {_rem} remaining"
            )
            embed.add_embed_field(
                name="Mission Stack",
                value=f"{fmt_credits(state.stack_value)} — {_status}",
                inline=False,
            )
        from core.state import VERSION
        embed.set_footer(text=f"ED Live Dashboard v{VERSION}")
        embed.set_timestamp()
        emitter.post_embed(embed)
    except ImportError:
        pass


def monitor_journal(
    jfile: Path,
    state: MonitorState,
    active_session: SessionData,
    lifetime: SessionData,
    emitter: Emitter,
    cfg_mgr,
    gui_queue: queue.Queue | None,
    journal_dir: Path,
    journal_file_ref: list,   # [Path] — mutable single-element list for current file
    _edld_start_mono: float,
    trace_mode: bool = False,
    plugin_dispatch: dict | None = None,
    data_provider=None,
    core=None,
) -> Path | None:
    """Preload a journal then tail it live. Returns path of new journal if one appears."""

    print(f"{Terminal.YELL}Journal file:{Terminal.END} {jfile}")
    state.in_preload = True

    # The marker that closes the previous session is always in an earlier
    # journal, so it has to be recovered before this one is replayed.
    bootstrap_last_session_end(state, journal_dir, jfile, trace_mode)

    # A line the game has only half written is held back until the rest
    # arrives (see _complete_line).  Started from preload, which can meet the
    # same half line at the end of the file.
    pending = [""]

    with open(jfile, mode="r", encoding="utf-8") as file:
        print("Preloading journal... (Press Ctrl+C to stop)")
        for chunk in file:
            line = _complete_line(pending, chunk)
            if line is None:
                continue
            handle_event(
                line, state, active_session, lifetime,
                emitter, cfg_mgr, gui_queue, journal_dir, trace_mode,
                plugin_dispatch=plugin_dispatch,
                data_provider=data_provider,
                core=core,
            )

        state.in_preload = False

        # Bootstrap missing data after preload
        if not state.missions or (state.active_missions and not state.stack_value):
            bootstrap_missions(state, journal_dir, cfg_mgr, trace_mode)

        load_session_state(jfile, active_session)
        bootstrap_slf(state, journal_dir, trace_mode)
        bootstrap_crew(state, journal_dir, trace_mode)
        bootstrap_hull(state, journal_dir, trace_mode)

        # Restore session start time if persisted
        from core.state import _session_start_iso
        if not state.session_start_time and _session_start_iso:
            try:
                state.session_start_time = datetime.fromisoformat(_session_start_iso)
            except ValueError:
                pass

        # Final fallback: if no LoadGame was in this journal (EDLD launched mid-session
        # or attached to a journal that started before the game session) and no persisted
        # session_start_iso, use the last event timestamp so the summary clock has an
        # anchor.  last_periodic_summary is already set (from edld.py sessionstart call).
        if not state.session_start_time and state.event_time:
            state.session_start_time = state.event_time

        # A reset made after the last replayed event has nothing to cross
        # during the replay; apply it now, so counts from before it do not
        # survive a restart.
        if core is not None:
            try:
                core.plugin_call("session_stats", "after_preload")
            except Exception as exc:
                trace(f"session reset replay failed: {exc}", trace_mode)

        print("Preload complete. Monitoring live...\n")

        # ── Startup banner and embed: once per run ─────────────────────────
        # This function runs again for every journal the game opens; the
        # banner belongs to EDLD starting, not to the game opening a file.
        if not state.monitoring_announced:
            state.monitoring_announced = True
            _announce_monitoring(state, emitter)

        # ── Live tail loop ────────────────────────────────────────────────
        while True:
            chunk = file.readline()
            line = _complete_line(pending, chunk) if chunk else ""
            if chunk and line is None:
                continue          # half a line: wait for the rest

            if not line:
                time.sleep(1)
                cfg_mgr.refresh()

                # Check for a new journal file
                latest = find_latest_journal(journal_dir)
                if latest and latest != jfile:
                    print(f"{Terminal.YELL}New journal detected:{Terminal.END} {latest.name}")
                    return latest

                now_mono = time.monotonic()

                # ── Not-in-game detection ─────────────────────────────────
                # Said once. After the alert, EDLD stays quiet — no repeat of
                # it, no summaries, no other terminal or Discord output — until
                # LoadGame says the commander is back in the game, or EDLD is
                # restarted.  It used to repeat the alert every hour and keep
                # posting quarter-hour summaries of a session that had ended.
                OFFLINE_STARTUP_GRACE = 5  * 60
                OFFLINE_MENU_GRACE    = 15 * 60
                _startup_elapsed = now_mono - _edld_start_mono
                _not_in_game     = not state.in_game and not state.in_preload

                if _not_in_game and state.output_suspended:
                    continue
                if _not_in_game:
                    if state.offline_since_mono is None:
                        state.offline_since_mono = now_mono
                    offline_elapsed = now_mono - state.offline_since_mono
                    if _startup_elapsed < OFFLINE_STARTUP_GRACE:
                        _grace_ok = False
                    elif offline_elapsed < OFFLINE_MENU_GRACE:
                        _grace_ok = False
                    else:
                        _grace_ok = True

                    if _grace_ok:
                        _ed_up   = _ed_client_running(journal_dir)
                        _reason  = (
                            "Elite Dangerous client not detected"
                            if not _ed_up
                            else "Player at main menu — not in session"
                        )
                        _level = _max_notify_level(cfg_mgr.notify_levels)
                        emitter.emit(
                            msg_term=(f"Not in game: {_reason} — output paused "
                                      f"until you load into the game"),
                            msg_discord=(f"⛔ **Not in game** — {_reason}. Output "
                                         f"paused until you load into the game."),
                            emoji="⛔", sigil="!  WARN",
                            timestamp=state.event_time, loglevel=_level,
                        )
                        state.last_offline_alert = now_mono
                        state.output_suspended = True
                        try:
                            from core import debug as _dbg
                            _dbg.log(f"Not in game ({_reason}); terminal and "
                                     f"Discord output paused until LoadGame",
                                     level="INFO")
                        except Exception:
                            pass
                        continue
                else:
                    state.offline_since_mono = None



                continue

            handle_event(
                line, state, active_session, lifetime,
                emitter, cfg_mgr, gui_queue, journal_dir, trace_mode,
                plugin_dispatch=plugin_dispatch,
                data_provider=data_provider,
                core=core,
            )

    return None


def run_monitor(
    journal_file: Path,
    state: MonitorState,
    active_session: SessionData,
    lifetime: SessionData,
    emitter: Emitter,
    cfg_mgr,
    gui_queue: queue.Queue | None,
    journal_dir: Path,
    _edld_start_mono: float,
    trace_mode: bool = False,
    plugin_dispatch: dict | None = None,
    data_provider=None,
    core=None,
) -> None:
    """Outer loop: run monitor_journal, switching files when a new one appears."""
    try:
        current = journal_file
        journal_file_ref = [current]
        while True:
            next_journal = monitor_journal(
                current, state, active_session, lifetime,
                emitter, cfg_mgr, gui_queue, journal_dir,
                journal_file_ref, _edld_start_mono, trace_mode,
                plugin_dispatch=plugin_dispatch,
                data_provider=data_provider,
                core=core,
            )
            if next_journal:
                current = next_journal
            else:
                break

    except KeyboardInterrupt:
        print("\nExiting...")
        # Read the clock before sessionend() clears it.  The guard used to be
        # state.session_start_time, which the line above had just set to None,
        # so the session was never actually saved.
        _sess = (core._plugins.get("session_stats")
                 if core is not None else None)
        _session_start = (getattr(_sess, "_session_start_time", None)
                          or state.session_start_time)
        state.sessionend()
        if _session_start and journal_file:
            save_session_state(journal_file, active_session, _session_start)

    except FileNotFoundError:
        _monitor_died("Journal file not found", state, core)
        if threading.current_thread() is threading.main_thread():
            sys.exit(1)

    except Exception as e:
        _monitor_died(f"Fatal error: {e}", state, core)
        if threading.current_thread() is threading.main_thread():
            sys.exit(1)


def _monitor_died(summary: str, state: MonitorState, core=None) -> None:
    """Record the loss of the journal monitor everywhere it can be seen.

    In both UI modes run_monitor runs on a daemon thread with stdout pointed
    at /dev/null, so the original print + sys.exit(1) pair was doubly silent:
    the message went nowhere and SystemExit only unwound that one thread.  The
    dashboard kept running on whatever state had accumulated, with the
    Status.json poller still refreshing hull, shields, fuel and balance — which
    reads as "some windows stopped updating" rather than "the journal reader is
    gone".  Record it on the state, in the diagnostic log, on the real stderr,
    and as a dashboard alert.
    """
    import traceback as _tb
    detail = _tb.format_exc()

    try:
        state.monitor_error = summary
    except Exception:
        pass

    try:
        from core import debug as _debug
        _debug.log(f"Journal monitor stopped: {summary}\n{detail}", level="ERROR")
    except Exception:
        pass

    try:
        sys.__stderr__.write(f"\nERROR: Journal monitor stopped: {summary}\n{detail}\n")
        sys.__stderr__.flush()
    except Exception:
        pass

    # The alerts pane is the one place a running dashboard can still say this.
    try:
        alerts = core._plugins.get("alerts") if core is not None else None
        if alerts is not None:
            alerts.push_fault(
                "🛑", f"Journal monitor stopped — {summary}. Restart EDLD."
            )
    except Exception:
        pass
