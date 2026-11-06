"""
core/disk_queue.py — sending what an uploader kept on disk, without losing it.

When an upload fails — Inara or EDSM unreachable, or refusing requests for a
while — the events are appended to ``<plugin>.queue.jsonl``, one
``{"queued_at": …, "msg": …}`` per line, and sent again later.

Inara, EDSM and EDAstro used to send that file and then delete it. But a batch
that failed again while being re-sent was appended to the same file — and the
delete that followed took it with it. Events were lost exactly when the
service was still having trouble, which is when the queue exists at all.

``drain`` moves the file aside before sending, so anything that fails again
lands in a fresh queue file that nothing deletes. The file set aside is
rewritten as each batch goes, so if EDLD stops part way through, the next
drain picks up what had not been tried yet.
"""
from __future__ import annotations

import builtins as _bi
import json
import time
from pathlib import Path
from typing import Callable, Optional

from core import debug as _dbg


def _read(path: Path) -> list[dict]:
    out: list[dict] = []
    try:
        with _bi.open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except Exception:
                    continue            # a torn last line — drop it
                if isinstance(rec, dict) and "msg" in rec:
                    out.append(rec)
    except FileNotFoundError:
        pass
    except Exception as exc:
        _dbg.info(f"  [disk-queue] could not read {path.name}: {exc}")
    return out


def _write(path: Path, records: list[dict]) -> None:
    if not records:
        path.unlink(missing_ok=True)
        return
    tmp = path.with_name(path.name + ".tmp")
    with _bi.open(tmp, "w", encoding="utf-8") as f:
        for rec in records:
            f.write(json.dumps(rec) + "\n")
    tmp.replace(path)


def restore(queue_file: Path, records: list[dict]) -> None:
    """Put records back at the front of the queue, untried."""
    if not records:
        return
    _write(queue_file, records + _read(queue_file))


def drain(queue_file: Path, batch_max: int,
          send_batch: Callable[[list[dict]], None], tag: str,
          pause_s: float = 0.0,
          prepare: Optional[Callable[[list[dict]], Optional[list[dict]]]] = None,
          ) -> int:
    """Send the queued events in batches of ``batch_max``.

    ``send_batch`` is the uploader's own: it appends whatever fails to
    ``queue_file`` again. ``prepare`` may adjust the events before they go,
    or return None to leave them all queued for later. Returns how many
    events were handed to ``send_batch``.
    """
    queue_file = Path(queue_file)
    staging = queue_file.with_name(queue_file.name + ".draining")
    try:
        records = _read(staging) + _read(queue_file)
        if not records:
            staging.unlink(missing_ok=True)
            queue_file.unlink(missing_ok=True)
            return 0
        _write(staging, records)
        queue_file.unlink(missing_ok=True)
    except Exception as exc:
        _dbg.info(f"  [{tag}] could not set the disk queue aside: {exc}")
        return 0

    events = [r["msg"] for r in records]
    if prepare is not None:
        prepared = prepare(events)
        if prepared is None:
            restore(queue_file, records)
            staging.unlink(missing_ok=True)
            return 0
        events = prepared

    _dbg.info(f"  [{tag}] Replaying {len(events)} queued event(s) from disk...")
    sent = 0
    for i in range(0, len(events), batch_max):
        chunk = events[i:i + batch_max]
        try:
            # What is still to go, this batch included, in case EDLD stops
            # while it is in flight: sent twice rather than not at all.
            _write(staging, [{"queued_at": r.get("queued_at", 0), "msg": e}
                             for r, e in zip(records[i:], events[i:])])
        except Exception:
            pass
        send_batch(chunk)
        sent += len(chunk)
        if pause_s and i + batch_max < len(events):
            time.sleep(pause_s)
    staging.unlink(missing_ok=True)
    return sent
