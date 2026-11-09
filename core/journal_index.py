"""core/journal_index.py — where every journal event is, read once.

    from core.journal_index import index_for
    for name, ev in index_for(journal_dir).events({"CrewHire", "CrewFire"}):
        ...

The journals stay the record.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
import threading
from pathlib import Path
from typing import Iterable, Iterator

#: Bump to rebuild every index: when what is stored, or how, changes.
INDEX_VERSION = 1


# The game writes every line as { "timestamp":"…", "event":"…", … }.
_PREFIX = re.compile(rb'^\{\s*"timestamp"\s*:\s*"([^"]*)"\s*,\s*"event"\s*:\s*"([^"]*)"')

#: How much of a journal's first line identifies it.
_HEAD = 160

#: A file with more wanted events than this is read whole rather than seeked
#: into line by line.
_WHOLE_FILE_AT = 48

_OLD_NAME = re.compile(r"Journal\.(\d{2})(\d{2})(\d{2})(\d{6})\.(\d+)\.log$")


def journal_sort_key(name: str) -> str:
    """Chronological order for journal file names, old style and new.

    New: ``Journal.2026-10-14T205310.01.log``.
    """
    m = _OLD_NAME.match(name)
    if m:
        yy, mm, dd, hms, part = m.groups()
        return f"Journal.20{yy}-{mm}-{dd}T{hms}.{part}.log"
    return name


def loads(raw: bytes | str):
    """One journal line decoded, as json.loads would; ValueError if not JSON."""
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8", errors="replace")
    return json.loads(raw)


def _peek(line: bytes) -> tuple[str, str] | None:
    """(timestamp, event) of one line, or None when it is not an event."""
    m = _PREFIX.match(line)
    if m:
        return (m.group(1).decode("ascii", "replace"),
                m.group(2).decode("utf-8", "replace"))
    try:
        ev = loads(line)
    except ValueError:
        return None
    if not isinstance(ev, dict):
        return None
    return str(ev.get("timestamp") or ""), str(ev.get("event") or "")


def default_db_path(journal_dir: Path) -> Path:
    """Where the index of ``journal_dir`` is kept: one per journal folder, in
    EDLD's data directory, shared by every profile that reads that folder."""
    from core.state import EDLD_DATA_DIR
    key = hashlib.sha1(str(Path(journal_dir).resolve()).encode("utf-8")).hexdigest()[:12]
    return EDLD_DATA_DIR / "cache" / f"journal-index-{key}.sqlite3"


class JournalIndex:
    """The index of one journal folder. Safe to share between threads."""

    def __init__(self, journal_dir: Path | str, db_path: Path | str | None = None):
        self.journal_dir = Path(journal_dir)
        self._explicit = db_path is not None
        self.db_path = Path(db_path) if db_path else default_db_path(self.journal_dir)
        self._lock = threading.RLock()
        self._db: sqlite3.Connection | None = None
        #: Files as last seen: name → (size, mtime_ns).
        self._seen: dict[str, tuple[int, int]] = {}
        self._names: dict[str, int] = {}

    # ── the database ─────────────────────────────────────────────────────────

    def _open(self) -> sqlite3.Connection:
        if self._db is not None:
            return self._db
        if os.environ.get("EDLD_JOURNAL_INDEX") == "memory" and not self._explicit:
            return self._memory()
        try:
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
        except OSError:
            pass
        for attempt in (1, 2):
            try:
                db = sqlite3.connect(str(self.db_path), timeout=10,
                                     check_same_thread=False, isolation_level=None)
                db.execute("PRAGMA journal_mode=WAL")
                db.execute("PRAGMA synchronous=NORMAL")
                if db.execute("PRAGMA user_version").fetchone()[0] != INDEX_VERSION:
                    self._create(db)
                db.execute("SELECT count(*) FROM files").fetchone()
                self._db = db
                return db
            except sqlite3.DatabaseError:
                # Corrupt, or not an index at all: it holds nothing that
                # cannot be read again from the journals.
                try:
                    db.close()
                except Exception:
                    pass
                if attempt == 2:
                    break
                self._remove_db()
            except OSError:
                break
        # The data directory cannot hold it (read-only, full): an index in
        # memory still reads each journal once per run.
        return self._memory()

    def _memory(self) -> sqlite3.Connection:
        db = sqlite3.connect(":memory:", check_same_thread=False, isolation_level=None)
        self._create(db)
        self._db = db
        return db

    def _remove_db(self) -> None:
        for suffix in ("", "-wal", "-shm"):
            try:
                os.remove(str(self.db_path) + suffix)
            except OSError:
                pass

    @staticmethod
    def _create(db: sqlite3.Connection) -> None:
        db.executescript(f"""
            DROP TABLE IF EXISTS events;
            DROP TABLE IF EXISTS files;
            DROP TABLE IF EXISTS names;
            CREATE TABLE files (
                id    INTEGER PRIMARY KEY,
                name  TEXT NOT NULL UNIQUE,
                sort  TEXT NOT NULL,
                size  INTEGER NOT NULL,   -- bytes indexed: whole lines only
                mtime INTEGER NOT NULL,   -- when the file was, at that size
                head  BLOB NOT NULL
            );
            CREATE TABLE names (
                id    INTEGER PRIMARY KEY,
                name  TEXT NOT NULL UNIQUE
            );
            -- One row an event, in the order the journal holds them.
            CREATE TABLE events (
                file  INTEGER NOT NULL,
                off   INTEGER NOT NULL,
                len   INTEGER NOT NULL,
                ev    INTEGER NOT NULL
            );
            CREATE INDEX events_by_name ON events (ev, file, off);
            CREATE INDEX events_by_file ON events (file, off);
            PRAGMA user_version = {INDEX_VERSION};
        """)

    def close(self) -> None:
        with self._lock:
            if self._db is not None:
                try:
                    self._db.close()
                except Exception:
                    pass
                self._db = None
                self._seen.clear()

    # ── keeping it current ──────────────────────────────────────────────────

    def refresh(self) -> int:
        """Index whatever the journals hold that the index does not yet.

        Returns the number of events added.
        """
        with self._lock:
            try:
                return self._refresh()
            except sqlite3.DatabaseError:
                # Damaged under us (another program, a full disk): start over.
                self.close()
                self._remove_db()
                return self._refresh()

    def _refresh(self) -> int:
        db = self._open()
        # os.scandir rather than Path.glob: this runs on every query, and a
        # Path a journal costs more than the stat it wraps.
        now: dict[str, tuple[int, int]] = {}
        try:
            with os.scandir(self.journal_dir) as it:
                for entry in it:
                    name = entry.name
                    if not (name.startswith("Journal") and name.endswith(".log")):
                        continue
                    try:
                        st = entry.stat()
                    except OSError:
                        continue
                    now[name] = (st.st_size, st.st_mtime_ns)
        except OSError:
            return 0
        if now == self._seen:
            return 0
        added = 0
        # IMMEDIATE: one writer at a time, and what is already indexed is read
        # inside the transaction — two EDLD profiles on one journal folder
        # share the index, and must not both add the same lines.
        db.execute("BEGIN IMMEDIATE")
        try:
            known = {name: (fid, size, mtime, bytes(head)) for fid, name, size, mtime, head in
                     db.execute("SELECT id, name, size, mtime, head FROM files")}
            self._names = {n: i for i, n in db.execute("SELECT id, name FROM names")}
            for name in set(known) - set(now):          # deleted journals
                fid = known[name][0]
                db.execute("DELETE FROM events WHERE file = ?", (fid,))
                db.execute("DELETE FROM files WHERE id = ?", (fid,))
            for name in sorted(now, key=journal_sort_key):
                size, mtime = now[name]
                fid, done, was, head = known.get(name, (None, 0, 0, b""))
                if fid is not None and size == done:
                    if mtime == was:
                        continue
                    # The same size but written since: not an append — the
                    # game only ever appends — so read it again whole.
                    done = 0
                added += self._ingest(db, name, fid, size, mtime, done, head)
            db.execute("COMMIT")
        except BaseException:
            db.execute("ROLLBACK")
            self._seen = {}
            raise
        self._seen = now
        return added

    def _name_id(self, db, name: str) -> int:
        nid = self._names.get(name)
        if nid is None:
            nid = db.execute("INSERT INTO names (name) VALUES (?)", (name,)).lastrowid
            self._names[name] = nid
        return nid

    def _ingest(self, db, name: str, fid: int | None, size: int, mtime: int,
                done: int, head: bytes) -> int:
        """Index journal ``name`` from byte ``done`` on (from the start if it
        is not the file that was indexed)."""
        try:
            with open(self.journal_dir / name, "rb") as fh:
                first = fh.read(_HEAD)
                if done and (size < done or first[:len(head)] != head):
                    done = 0                     # rewritten: read it again
                fh.seek(done)
                data = fh.read()
        except OSError:
            return 0
        if fid is None:
            fid = db.execute(
                "INSERT INTO files (name, sort, size, mtime, head) VALUES (?,?,0,0,?)",
                (name, journal_sort_key(name), first)).lastrowid
        elif done == 0:
            db.execute("DELETE FROM events WHERE file = ?", (fid,))
        end = data.rfind(b"\n")
        whole = data[:end + 1] if end >= 0 else b""
        # A last line with no newline yet is taken when it is a whole event:
        # the game ends every line, but files written by other tools may not
        # end the last one. A line half written does not decode, and waits.
        rest = data[end + 1:]
        if rest.strip().endswith(b"}"):
            try:
                if isinstance(loads(rest), dict):
                    whole = data
            except ValueError:
                pass
        rows = []
        pos = 0
        n = len(whole)
        name_id = self._name_id
        while pos < n:
            nl = whole.find(b"\n", pos)
            if nl < 0:
                nl = n
            line = whole[pos:nl]
            if line.endswith(b"\r"):
                line = line[:-1]
            stripped = line.strip()
            if stripped:
                peek = _peek(stripped)
                if peek is not None:
                    rows.append((fid, done + pos, len(line), name_id(db, peek[1])))
            pos = nl + 1
        if rows:
            db.executemany("INSERT INTO events (file, off, len, ev) VALUES (?,?,?,?)", rows)
        # A line still being written is left for the next refresh, and so is
        # the file's time: it is not yet the time of what was indexed.
        db.execute("UPDATE files SET size = ?, mtime = ?, head = ? WHERE id = ?",
                   (done + len(whole), mtime if done + len(whole) == size else 0,
                    first, fid))
        return len(rows)

    # ── asking it ────────────────────────────────────────────────────────────

    def files(self) -> list[str]:
        """Every indexed journal's name, oldest first."""
        self.refresh()
        with self._lock:
            return [r[0] for r in self._open().execute(
                "SELECT name FROM files ORDER BY sort")]

    def file_stats(self) -> dict[str, tuple[int, int]]:
        """Every indexed journal's name → (bytes of it indexed, its mtime_ns
        when they were).
        """
        self.refresh()
        with self._lock:
            return {n: (size, mtime) for n, size, mtime in
                    self._open().execute("SELECT name, size, mtime FROM files")}

    def _name_ids(self, names) -> list[int]:
        return [self._names[n] for n in names if n in self._names]

    def positions(self, names: Iterable[str] | None = None, *,
                  newest_first: bool = False,
                  files: Iterable[str] | None = None) -> list[tuple[str, int, int]]:
        """(file, offset, length) of each wanted event, in journal order."""
        self.refresh()
        with self._lock:
            where, args = [], []
            if names is not None:
                ids = self._name_ids(set(names))
                if not ids:
                    return []
                where.append(f"e.ev IN ({','.join('?' * len(ids))})")
                args += ids
            if files is not None:
                files = list(files)
                if not files:
                    return []
                where.append(f"f.name IN ({','.join('?' * len(files))})")
                args += files
            order = "DESC" if newest_first else "ASC"
            sql = ("SELECT f.name, e.off, e.len FROM events e JOIN files f ON f.id = e.file"
                   + (" WHERE " + " AND ".join(where) if where else "")
                   + f" ORDER BY f.sort {order}, e.off {order}")
            return self._open().execute(sql, args).fetchall()

    def lines(self, names: Iterable[str] | None = None, *, newest_first: bool = False,
              files: Iterable[str] | None = None) -> Iterator[tuple[str, bytes]]:
        """(file name, raw line) of each wanted event, in journal order."""
        rows = self.positions(names, newest_first=newest_first, files=files)
        i = 0
        while i < len(rows):
            name = rows[i][0]
            j = i
            while j < len(rows) and rows[j][0] == name:
                j += 1
            group = rows[i:j]
            i = j
            try:
                with open(self.journal_dir / name, "rb") as fh:
                    if len(group) >= _WHOLE_FILE_AT:
                        data = fh.read()
                        for _f, off, ln in group:
                            yield name, data[off:off + ln]
                    else:
                        for _f, off, ln in group:
                            fh.seek(off)
                            yield name, fh.read(ln)
            except OSError:
                continue

    def events(self, names: Iterable[str] | None = None, *, newest_first: bool = False,
               files: Iterable[str] | None = None) -> Iterator[tuple[str, dict]]:
        """(file name, event) of each wanted event, decoded, in journal order.

        ``names`` None is every event. ``newest_first`` walks backwards from
        the newest. ``files`` limits it to those journals.
        """
        for name, raw in self.lines(names, newest_first=newest_first, files=files):
            try:
                ev = loads(raw)
            except ValueError:
                continue
            if isinstance(ev, dict):
                yield name, ev

    def last(self, names: Iterable[str], files: Iterable[str] | None = None
             ) -> tuple[str, dict] | None:
        """The newest of the wanted events, or None."""
        for item in self.events(names, newest_first=True, files=files):
            return item
        return None

    def count(self, names: Iterable[str] | None = None) -> int:
        self.refresh()
        with self._lock:
            if names is None:
                return self._open().execute("SELECT count(*) FROM events").fetchone()[0]
            ids = self._name_ids(set(names))
            if not ids:
                return 0
            return self._open().execute(
                f"SELECT count(*) FROM events WHERE ev IN ({','.join('?' * len(ids))})",
                ids).fetchone()[0]


# ── one index per journal folder ─────────────────────────────────────────────

_indexes: dict[str, JournalIndex] = {}
_indexes_lock = threading.Lock()


def index_for(journal_dir: Path | str) -> JournalIndex:
    """The shared index of ``journal_dir`` (made on first use)."""
    key = str(Path(journal_dir))
    with _indexes_lock:
        idx = _indexes.get(key)
        if idx is None:
            idx = _indexes[key] = JournalIndex(journal_dir)
        return idx


def forget(journal_dir: Path | str | None = None) -> None:
    """Close and drop the shared index (all of them with no argument).
    For tests, and for a journal folder that has been changed in Options."""
    with _indexes_lock:
        keys = [str(Path(journal_dir))] if journal_dir is not None else list(_indexes)
        for k in keys:
            idx = _indexes.pop(k, None)
            if idx is not None:
                idx.close()
