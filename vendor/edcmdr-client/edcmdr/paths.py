"""Per-OS locations: config directory, default journal directories, bundled data."""
import os
import sys
from pathlib import Path


def config_dir() -> Path:
    env = os.environ.get('EDCMDR_HOME')
    if env:
        p = Path(env)
    elif sys.platform == 'win32':
        p = Path(os.environ.get('APPDATA', Path.home() / 'AppData' / 'Roaming')) / 'EDCMDR'
    elif sys.platform == 'darwin':
        p = Path.home() / 'Library' / 'Application Support' / 'EDCMDR'
    else:
        p = Path(os.environ.get('XDG_CONFIG_HOME', Path.home() / '.config')) / 'edcmdr'
    p.mkdir(parents=True, exist_ok=True)
    if sys.platform != 'win32':
        os.chmod(p, 0o700)
    return p


def default_journal_dirs() -> list[Path]:
    home = Path.home()
    rel = Path('Saved Games') / 'Frontier Developments' / 'Elite Dangerous'
    if sys.platform == 'win32':
        cands = [Path(os.environ.get('USERPROFILE', home)) / rel]
    else:
        steam = [home / '.local/share/Steam', home / '.steam/steam',
                 home / '.var/app/com.valvesoftware.Steam/.local/share/Steam']
        cands = [s / 'steamapps/compatdata/359320/pfx/drive_c/users/steamuser' / rel for s in steam]
    return [c for c in cands if c.is_dir()]


def data_dir() -> Path:
    base = Path(getattr(sys, '_MEIPASS', Path(__file__).resolve().parent.parent))
    return base / 'edcmdr' / 'data' if (base / 'edcmdr' / 'data').is_dir() else Path(__file__).resolve().parent / 'data'


def spec_path() -> Path:
    base = Path(getattr(sys, '_MEIPASS', Path(__file__).resolve().parent.parent))
    return base / 'protocol' / 'v1' / 'spec.json'
