"""Whether Elite Dangerous is running on this computer."""
import sys
import time
from pathlib import Path

try:
    import psutil
except ImportError:  # pragma: no cover
    psutil = None

EXE = 'elitedangerous64.exe'
NAMES = {'EliteDangerous64.exe', 'EliteDangerous32.exe', 'EliteDangerous.exe'}
STATUS_FRESH = 90
CACHE = 15.0

_seen: tuple[float, bool | None] = (0.0, None)


def _is_game(args) -> bool:
    return any(str(a).replace('\\', '/').rsplit('/', 1)[-1].strip().lower() == EXE for a in args or ())


def process_running() -> bool | None:
    """The game's process, by name or command line (Proton runs it under wine); None if that cannot be told."""
    if psutil is not None:
        try:
            for p in psutil.process_iter(['name', 'cmdline']):
                if p.info.get('name') in NAMES or _is_game(p.info.get('cmdline')):
                    return True
            return False
        except Exception:  # noqa: BLE001
            pass
    if sys.platform.startswith('linux'):
        try:
            pids = [e.name for e in Path('/proc').iterdir() if e.name.isdigit()]
        except OSError:
            return None
        for pid in pids:
            try:
                raw = Path(f'/proc/{pid}/cmdline').read_bytes()[:4096]
            except OSError:
                continue
            if raw and _is_game(raw.decode('utf-8', 'replace').split('\0')):
                return True
        return False
    return None


def running(journal_dir: Path | None) -> bool:
    """Status.json written in the last 90 s (the game rewrites it constantly in flight), or the game's process.

    The process answers at the main menu and docked and idle, when Status.json goes quiet; Status.json
    answers for a game on another computer sharing its journal folder.
    """
    global _seen
    if journal_dir is not None:
        try:
            if time.time() - (Path(journal_dir) / 'Status.json').stat().st_mtime < STATUS_FRESH:
                return True
        except OSError:
            pass
    if time.monotonic() - _seen[0] > CACHE:
        _seen = (time.monotonic(), process_running())
    return bool(_seen[1])
