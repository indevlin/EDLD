"""Settings in config_dir()/settings.json: journal directories and per-commander sharing."""
import json
import os
import threading
from pathlib import Path

from . import paths

SPEC = json.loads(paths.spec_path().read_text())
SHAREABLE = [c for c in SPEC['categories'] if c not in SPEC['always_shared']]
DELAYS = SPEC['delays']
DELAY_LABELS = {0: 'None', 3600: '1 hour', 43200: '12 hours', 86400: '1 day', 604800: '1 week'}


def default_prefs() -> dict:
    return {'share': {c: False for c in SHAREABLE}, 'delay': {c: 0 for c in SHAREABLE},
            'presence': False, 'wealth': False, 'name_history': False}


class Settings:
    def __init__(self, path: Path | None = None):
        self.path = path or paths.config_dir() / 'settings.json'
        self.lock = threading.RLock()
        self.data = {'journal_dirs': [], 'commanders': {}, 'start_paused': False}
        if self.path.exists():
            try:
                self.data.update(json.loads(self.path.read_text()))
            except (OSError, ValueError):
                pass
        if not self.data['journal_dirs']:
            self.data['journal_dirs'] = [str(p) for p in paths.default_journal_dirs()]

    def save(self) -> None:
        with self.lock:
            tmp = self.path.with_suffix('.tmp')
            tmp.write_text(json.dumps(self.data, indent=2))
            if os.name != 'nt':
                os.chmod(tmp, 0o600)
            os.replace(tmp, self.path)

    @property
    def journal_dirs(self) -> list[Path]:
        return [Path(p) for p in self.data['journal_dirs']]

    def set_journal_dirs(self, dirs: list[str]) -> None:
        with self.lock:
            self.data['journal_dirs'] = list(dict.fromkeys(dirs))
            self.save()

    def prefs(self, fid: str) -> dict:
        with self.lock:
            c = self.data['commanders'].setdefault(fid, {})
            p = default_prefs()
            stored = c.get('prefs') or {}
            p['share'].update({k: bool(v) for k, v in stored.get('share', {}).items() if k in p['share']})
            p['delay'].update({k: int(v) for k, v in stored.get('delay', {}).items() if k in p['delay'] and int(v) in DELAYS})
            for k in ('presence', 'wealth', 'name_history'):
                p[k] = bool(stored.get(k, False))
            return p

    def set_prefs(self, fid: str, prefs: dict) -> None:
        with self.lock:
            self.data['commanders'].setdefault(fid, {})['prefs'] = prefs
            self.save()

    def commander(self, fid: str) -> dict:
        with self.lock:
            return dict(self.data['commanders'].get(fid, {}))

    def set_commander(self, fid: str, **kw) -> None:
        with self.lock:
            self.data['commanders'].setdefault(fid, {}).update(kw)
            self.save()

    def forget_commander(self, fid: str) -> None:
        with self.lock:
            self.data['commanders'].pop(fid, None)
            self.save()
