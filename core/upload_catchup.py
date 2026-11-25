"""core/upload_catchup.py — uploads catch up on journals EDLD did not see.

At startup EDLD replays only the current journal. Play in earlier journals
while EDLD was not running would never reach EDDN, EDSM, EDAstro or Inara.
Before that replay, the journals between the uploaders' marks and the current
journal are read once and handed to those uploaders as a replay: each sends
what comes after its own mark (core/upload_mark.py) and moves its mark on.
Only journals of the current journal's commander are read, and nothing older
than CATCHUP_DAYS.
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from core import debug as _dbg

UPLOADERS = ("eddn", "edsm", "edastro", "inara")
CATCHUP_DAYS = 30
HEAD_LINES = 60
_NAME_RE = re.compile(r"^Journal\.(\d{4}-\d{2}-\d{2}T\d{6}|\d{12})\.\d{2}\.log$")

_done = False


def _stamp(name: str) -> str:
    s = _NAME_RE.match(name).group(1)
    return s.replace("-", "").replace("T", "") if "T" in s else "20" + s


def journal_files(journal_dir: Path) -> list[Path]:
    try:
        files = [p for p in Path(journal_dir).iterdir() if _NAME_RE.match(p.name)]
    except OSError:
        return []
    return sorted(files, key=lambda p: (_stamp(p.name), p.name))


def _head(path: Path) -> tuple[str | None, int | None]:
    """(FID of the first Commander/NewCommander, Fileheader part)."""
    fid, part = None, None
    try:
        with path.open("r", encoding="utf-8", errors="replace") as f:
            for i, line in enumerate(f):
                if i >= HEAD_LINES:
                    break
                try:
                    ev = json.loads(line)
                except ValueError:
                    continue
                if ev.get("event") == "Fileheader" and isinstance(ev.get("part"), int):
                    part = ev["part"]
                if ev.get("event") in ("Commander", "NewCommander") and isinstance(ev.get("FID"), str):
                    fid = ev["FID"]
                    break
    except OSError:
        pass
    return fid, part


def owners(files: list[Path]) -> dict[Path, str | None]:
    """Each file's commander; a continuation file (part 2 and up) belongs to the one before it."""
    out: dict[Path, str | None] = {}
    last = None
    for p in files:
        fid, part = _head(p)
        if fid is None and isinstance(part, int) and part >= 2:
            fid = last
        out[p] = fid
        last = fid
    return out


def _when(ts: str) -> datetime | None:
    try:
        return datetime.strptime(str(ts), "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return None


class _Replay:
    """The monitor state as uploaders see it during the catch-up: a replay,
    with nothing live (no CAPI answers, no current powerplay) to mix in."""

    in_preload = True
    capi_raw = None
    pp_power = pp_rank = pp_merits_total = None

    def __init__(self, state: Any) -> None:
        self._state = state

    def __getattr__(self, name: str):
        return getattr(self._state, name)


def catch_up(jfile: Path, journal_dir: Path, state: Any, plugin_dispatch: dict | None,
             now: datetime | None = None) -> int:
    """Hand journals older than jfile, back to the earliest uploader mark, to the
    enabled uploaders. Runs once per process. Returns how many events were read."""
    global _done
    if _done or not plugin_dispatch:
        return 0
    _done = True
    seen: dict[int, Any] = {}
    for plugins in plugin_dispatch.values():
        for p in plugins:
            if getattr(p, "PLUGIN_NAME", "") in UPLOADERS and getattr(p, "_enabled", False):
                seen[id(p)] = p
    marks = []
    for p in seen.values():
        try:
            through = _when(p._upload_mark().through)
        except Exception:
            through = None
        if through is not None:
            marks.append(through)
    if not marks:
        return 0
    now = now or datetime.now(timezone.utc)
    start = max(min(marks), now - timedelta(days=CATCHUP_DAYS))
    files = journal_files(journal_dir)
    jfile = Path(jfile)
    older = [p for p in files if (_stamp(p.name), p.name) < (_stamp(jfile.name), jfile.name)]
    if not older:
        return 0
    own = owners(files)
    fid = own.get(jfile)
    first = 0
    begin = start.strftime("%Y%m%d%H%M%S")
    for i, p in enumerate(older):
        if _stamp(p.name) <= begin:
            first = i
    picked = [p for p in older[first:] if fid is not None and own.get(p) == fid]
    if not picked:
        return 0
    uploaders = list(seen.values())
    replay = _Replay(state)
    floor = start.strftime("%Y-%m-%dT%H:%M:%SZ")
    n = 0
    _dbg.info(f"  [catch-up] reading {len(picked)} journal(s) EDLD did not see, from {floor}")
    for p in picked:
        try:
            lines = p.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            continue
        for line in lines:
            try:
                ev = json.loads(line)
            except ValueError:
                continue
            if not isinstance(ev, dict) or not isinstance(ev.get("event"), str):
                continue
            ts = str(ev.get("timestamp", ""))
            if ts and ts <= floor and ev["event"] not in ("Fileheader", "Commander"):
                continue
            ev["_logtime"] = _when(ts)
            n += 1
            for up in uploaders:
                try:
                    up.on_event(ev, replay)
                except Exception as exc:
                    _dbg.info(f"  [catch-up] {up.PLUGIN_NAME} error on {ev['event']}: {exc}")
    for up in uploaders:
        try:
            up._upload_mark().save()
        except Exception:
            pass
    _dbg.info(f"  [catch-up] {n} event(s) replayed to {', '.join(u.PLUGIN_NAME for u in uploaders)}")
    return n
