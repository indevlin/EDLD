"""Journal discovery and tailing across directories, routed by commander FID.

Each Journal.*.log is assigned to a commander by its first Commander or
NewCommander event. Historic files are read once at start (prefiltered on
the events state.py uses); the newest file per directory is then tailed.
"""
import json
import re
from pathlib import Path
from typing import Callable

NAME_RE = re.compile(r'^Journal\.(\d{4}-\d{2}-\d{2}T\d{6}|\d{12})\.\d{2}\.log$')
HEAD_LINES = 60


def journal_files(d: Path) -> list[Path]:
    try:
        files = [p for p in d.iterdir() if NAME_RE.match(p.name)]
    except OSError:
        return []
    return sorted(files, key=lambda p: (_stamp(p.name), p.name))


def _stamp(name: str) -> str:
    s = NAME_RE.match(name).group(1)
    if 'T' in s:
        return s.replace('-', '').replace('T', '')
    return '20' + s


def read_owner(path: Path) -> tuple[str, str] | None:
    """(FID, name) from the file's first Commander/NewCommander event."""
    try:
        with path.open('r', encoding='utf-8', errors='replace') as f:
            for i, line in enumerate(f):
                if i >= HEAD_LINES:
                    break
                if '"Commander"' not in line and '"NewCommander"' not in line:
                    continue
                try:
                    ev = json.loads(line)
                except ValueError:
                    continue
                if ev.get('event') in ('Commander', 'NewCommander') and isinstance(ev.get('FID'), str):
                    return ev['FID'], str(ev.get('Name', ''))
    except OSError:
        pass
    return None


class Watcher:
    """Call poll() regularly; each journal event goes to on_event(fid, event)."""

    def __init__(self, dirs: list[Path], on_event: Callable[[str, dict], None],
                 interesting: frozenset[str] | None = None):
        self.dirs = dirs
        self.on_event = on_event
        self.needles = tuple(f'"{e}"' for e in interesting) if interesting else None
        self.owner: dict[Path, tuple[str, str] | None] = {}
        self.offset: dict[Path, int] = {}
        self.partial: dict[Path, str] = {}
        self.tail: dict[Path, Path] = {}
        self.imported = False
        self.current: Path | None = None
        self.where: dict[str, Path] = {}

    def commanders(self) -> dict[str, str]:
        out = {}
        for o in self.owner.values():
            if o:
                out[o[0]] = o[1]
        return out

    def set_dirs(self, dirs: list[Path]) -> None:
        self.dirs = dirs
        self.imported = False

    def _wanted(self, line: str) -> bool:
        return self.needles is None or any(n in line for n in self.needles)

    def _read(self, path: Path, fid: str) -> None:
        pos = self.offset.get(path, 0)
        try:
            with path.open('rb') as f:
                f.seek(pos)
                chunk = f.read()
        except OSError:
            return
        if not chunk:
            return
        self.offset[path] = pos + len(chunk)
        self.current = path.parent
        self.where[fid] = path.parent
        text = self.partial.pop(path, '') + chunk.decode('utf-8', errors='replace')
        lines = text.split('\n')
        if lines[-1] != '':
            self.partial[path] = lines[-1]
        for line in lines[:-1]:
            if not line.strip() or not self._wanted(line):
                continue
            try:
                ev = json.loads(line)
            except ValueError:
                continue
            if isinstance(ev, dict) and isinstance(ev.get('event'), str):
                self.on_event(fid, ev)

    def _owner(self, path: Path) -> tuple[str, str] | None:
        if self.owner.get(path) is None:
            self.owner[path] = read_owner(path) or self._continues(path)
        return self.owner[path]

    def _continues(self, path: Path) -> tuple[str, str] | None:
        """A continuation file (Fileheader part 2 and up) has no Commander event: it belongs to the file before it."""
        try:
            with path.open('r', encoding='utf-8', errors='replace') as f:
                head = json.loads(f.readline() or '{}')
        except (OSError, ValueError):
            return None
        if head.get('event') != 'Fileheader' or not isinstance(head.get('part'), int) or head['part'] < 2:
            return None
        files = journal_files(path.parent)
        i = files.index(path) if path in files else 0
        return self._owner(files[i - 1]) if i > 0 else None

    def poll(self) -> None:
        for d in self.dirs:
            files = journal_files(d)
            if not files:
                continue
            if not self.imported:
                for p in files[:-1]:
                    if p not in self.offset and (o := self._owner(p)):
                        self._read(p, o[0])
            newest = files[-1]
            if self.tail.get(d) != newest:
                prev = self.tail.get(d)
                if prev is not None and (o := self._owner(prev)):
                    self._read(prev, o[0])
                self.tail[d] = newest
            o = self._owner(newest)
            if o:
                self._read(newest, o[0])
        self.imported = True
