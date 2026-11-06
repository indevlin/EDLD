"""
core/dossier/sources.py — what the dossier reads besides the journals.

* Surface deposits, from the survey database (``<shared>/mining.db``), read
  only. The dossier never writes to it, never repairs it, and never runs its
  migrations: it opens the file read-only and reads what is there.
* The fleet carrier's Frontier (CAPI) snapshot, ``core.fleetcarrier.json``,
  for what the journal does not carry: weekly upkeep and the itinerary.
* Career income by source, from the journal-history component's scan — the
  same figures as Career's Credits tab — when it is running.

Each returns something empty rather than raising when its source is missing.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Optional


def deposits(db_path: Path) -> list[dict]:
    """Surface deposits, newest confirmation first, test rows left out."""
    path = Path(db_path)
    if not path.is_file():
        return []
    try:
        con = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=2)
    except sqlite3.Error:
        return []
    try:
        con.row_factory = sqlite3.Row
        cols = {r[1] for r in con.execute("PRAGMA table_info(deposits)")}
        notes = "d.notes" if "notes" in cols else "''"
        rows = con.execute(f"""
            SELECT d.deposit_id, d.commodity, d.commodity_display,
                   d.latitude, d.longitude, d.amount, d.density_observed,
                   d.density_claimed, d.rigs, d.refine_count, d.first_seen,
                   d.last_confirmed, {notes} AS notes,
                   b.system_name, b.body_name,
                   (SELECT max(noted_at) FROM depletion_log l
                     WHERE l.deposit_id = d.deposit_id) AS depleted_at
              FROM deposits d
              LEFT JOIN bodies b
                ON b.system_address = d.system_address AND b.body_id = d.body_id
             WHERE d.is_test = 0
        """).fetchall()
        return [dict(r) for r in rows]
    except sqlite3.Error:
        return []
    finally:
        con.close()


def capi_carrier(cmdr_dir: Path) -> dict:
    """The carrier's CAPI snapshot, or {} when CAPI is off or there is none."""
    path = Path(cmdr_dir) / "data" / "core.fleetcarrier.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def career(core) -> Optional[dict]:
    """Career income and spending by source, from journal_history.

    Waits for that component's startup scan to finish (briefly — the dossier
    is built in the background) and returns None when it is not loaded.
    """
    plugins = getattr(core, "_plugins", {}) if core is not None else {}
    jh = plugins.get("journal_history")
    if jh is None:
        return None
    done = getattr(jh, "scan_done", None)
    if done is not None and not done.wait(timeout=120):
        return None
    results = getattr(jh, "results", None) or {}
    finance = results.get("finance") or {}
    return {"in": dict(finance.get("in") or {}),
            "out": dict(finance.get("out") or {})}
