"""core/layout_model.py — UI-agnostic dashboard layout model.

The single source of truth for what windows exist, what size class each is, and
where they sit.

Size classes
------------
Windows are grouped into interchangeable classes.

    panel    Every interchangeable window (Career, Session, Ship Health,
             Cargo, Missions, Navigation, Colonisation, Exploration,
             Exobiology, Assets, Engineering)
    compact  Alerts · Crew/SLF   (two halves of one Panel height)
    anchor   Commander           (one Panel height)

Positions
---------
Columns are ``A`` (left), ``B`` (centre), ``C`` (right).  A position is a column
letter plus a 1-based index within that column: ``A1``, ``A2``, ``B3`` …  Each
position carries a size class and a default window.

Heights
-------
Each class has a relative *weight*.  Within a column the occupied positions'
weights are normalised to 100% within each column, so a column always fills
cleanly and empty positions simply reflow — and every window
of a class renders at a consistent proportion.  The weights are the single knob
for tuning standardised box sizes.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

# ── Size classes ──────────────────────────────────────────────────────────────

PANEL  = "panel"    # the large left/right windows
CENTER = "centre"   # the three equal center windows

SIZE_CLASSES = (PANEL, CENTER)

# Retained so an older windows.json or an out-of-tree caller naming the
# previous three-class scheme still resolves instead of raising.
COMPACT = CENTER
ANCHOR  = CENTER

# Relative height weight per class.  Two classes, and every column adds up to
# the same height so rows line up across all three:
#
#   left / right   PANEL  + PANEL                   = 50 + 50           = 100
#   center         CENTER + CENTER + CENTER         = 33 + 33 + 33      = 100
#
# Every window is interchangeable with every other window of its class: four
# positions for PANEL (A1, A2, C1, C2) and three for CENTER (B1, B2, B3).
CLASS_WEIGHT = {PANEL: 50, CENTER: 33}

CLASS_LABEL = {PANEL: "Large", CENTER: "Center"}

#: Column widths as percentages of the dashboard, left to right.  Both front
#: ends read this so the terminal and the desktop window open with identical
#: proportions; changing it here changes both.  The center column is slightly
#: narrower because its windows are label/value rows, while the outer columns
#: carry tables and routes that benefit from the extra characters.
COLUMN_WIDTH_PCT: dict[str, int] = {"A": 34, "B": 32, "C": 34}


# ── Window registry ─────────────────────────────────────────────────────────
# Every dashboard window, its size class, and its display title.  Exploration
# and Exobiology are registered ahead of their widgets so the Display selector
# can offer them; callers pass an ``available`` set to hide not-yet-built ones.

BLOCK_CLASS = {
    # Large left/right windows — interchangeable across A1, A2, C1 and C2.
    "exploration":  PANEL,
    "navigation":   PANEL,
    "ship_info":    PANEL,
    "career":       PANEL,
    # Center column: three equal windows, freely interchangeable.
    "commander":    CENTER,
    "objectives":   CENTER,
    "status":       CENTER,
}

BLOCK_DISPLAY = {
    "exploration":  "Exploration / Exobiology",
    "navigation":   "Navigation",
    "ship_info":    "Ship",
    "career":       "Career / Session",
    "objectives":   "Objectives",
    "commander":    "Commander",
    "status":       "Crew / Alerts",
}

# ── Columns ───────────────────────────────────────────────────────────────────

COLUMNS = ("A", "B", "C")
COLUMN_TITLE = {"A": "Left", "B": "Center", "C": "Right"}

# ── Default arrangement ─────────────────────────────────────────────────────
# Each column is an ordered list of (size_class, default_window | None).  This
# reproduces the current on-screen layout; Workstreams C/D change A1/A2 to the
# new windows.

# Left and right columns mirror each other: two large windows apiece.  All
# four of those positions take the same class, so any large window can live in
# any of them.  The center column is the tall pair with the short pair
# between them.
DEFAULT_SLOTS: dict[str, list[tuple[str, Optional[str]]]] = {
    "A": [(PANEL, "exploration"), (PANEL, "navigation")],
    "B": [(CENTER, "commander"), (CENTER, "status"), (CENTER, "objectives")],
    "C": [(PANEL, "ship_info"), (PANEL, "career")],
}

ASSIGNMENT_VERSION = 2


# ── Slot helpers ────────────────────────────────────────────────────────────

def slot_ids() -> list[str]:
    """All position ids in display order: A1, A2, …, B1, …, C1, …."""
    out: list[str] = []
    for col in COLUMNS:
        for i in range(len(DEFAULT_SLOTS[col])):
            out.append(f"{col}{i + 1}")
    return out


def slots_in_column(col: str) -> list[str]:
    return [f"{col}{i + 1}" for i in range(len(DEFAULT_SLOTS.get(col, [])))]


def column_of(slot_id: str) -> str:
    return slot_id[0]


def _index_of(slot_id: str) -> int:
    return int(slot_id[1:]) - 1


def slot_class(slot_id: str) -> str:
    return DEFAULT_SLOTS[column_of(slot_id)][_index_of(slot_id)][0]


def default_block(slot_id: str) -> Optional[str]:
    return DEFAULT_SLOTS[column_of(slot_id)][_index_of(slot_id)][1]


def block_class(block: str) -> Optional[str]:
    return BLOCK_CLASS.get(block)


def block_display(block: str) -> str:
    return BLOCK_DISPLAY.get(block, block)


def eligible_blocks(size_class: str, available: Optional[set[str]] = None) -> list[str]:
    """Windows that may occupy a position of ``size_class``.

    ``available`` optionally restricts to windows that currently have a widget
    (so the Display selector hides not-yet-built ones).
    """
    out = [b for b, c in BLOCK_CLASS.items() if c == size_class]
    if available is not None:
        out = [b for b in out if b in available]
    return sorted(out, key=lambda b: block_display(b).lower())


# ── Assignment (position → window) ──────────────────────────────────────────

def default_assignment() -> dict[str, Optional[str]]:
    return {sid: default_block(sid) for sid in slot_ids()}


def normalize_assignment(raw: dict) -> dict[str, Optional[str]]:
    """Return a valid assignment from arbitrary input.

    Enforces the invariants the UIs rely on:
      - every known position is present;
      - a window only occupies a position of its own class (else cleared);
      - a window appears in at most one position (later duplicates cleared);
      - positions absent from ``raw`` (e.g. a position added in a newer model
        version) fall back to their default window when that window is free.
    """
    raw = raw or {}
    result: dict[str, Optional[str]] = {}
    seen: set[str] = set()
    for sid in slot_ids():
        blk = raw[sid] if sid in raw else default_block(sid)
        if (
            blk
            and BLOCK_CLASS.get(blk) == slot_class(sid)
            and blk not in seen
        ):
            result[sid] = blk
            seen.add(blk)
        else:
            result[sid] = None

    # Windows whose saved position no longer exists must not be silently
    # lost.  Merging windows changed the slot layout — column A went from
    # three positions to two — so an assignment written by an earlier version
    # can name a window in a slot that is now gone.  Rehome any such window
    # into the first free position of its own class rather than dropping it.
    orphans = [
        blk for sid, blk in (raw or {}).items()
        if blk and blk in BLOCK_CLASS and blk not in seen and sid not in result
    ]
    for blk in orphans:
        for sid in slot_ids():
            if result.get(sid) is None and slot_class(sid) == BLOCK_CLASS[blk]:
                result[sid] = blk
                seen.add(blk)
                break
    return result


# ── Layout derivation ───────────────────────────────────────────────────────

def _apportion(weights: list[int], total: int) -> list[int]:
    """Split ``total`` across ``weights`` as integers summing exactly to total
    (largest-remainder method)."""
    if not weights:
        return []
    s = sum(weights) or 1
    raw = [w / s * total for w in weights]
    floors = [int(x) for x in raw]
    rem = total - sum(floors)
    order = sorted(range(len(weights)), key=lambda i: raw[i] - floors[i], reverse=True)
    for i in order[: max(0, rem)]:
        floors[i] += 1
    return floors


def occupied_slots(assignment: dict) -> dict[str, list[tuple[str, str]]]:
    """Per-column ordered ``[(slot_id, block), …]`` for non-empty positions."""
    out: dict[str, list[tuple[str, str]]] = {}
    for col in COLUMNS:
        col_slots = []
        for sid in slots_in_column(col):
            blk = assignment.get(sid)
            if blk:
                col_slots.append((sid, blk))
        out[col] = col_slots
    return out


def tui_columns(assignment: dict) -> dict[str, list[tuple[str, int]]]:
    """Per-column ordered ``[(block, height_percent), …]`` for the TUI."""
    occ = occupied_slots(assignment)
    out: dict[str, list[tuple[str, int]]] = {}
    for col in COLUMNS:
        slots = occ[col]
        pcts = _apportion([CLASS_WEIGHT[slot_class(sid)] for sid, _ in slots], 100)
        out[col] = [(blk, p) for (sid, blk), p in zip(slots, pcts)]
    return out


def summary(assignment: dict, available: Optional[set[str]] = None) -> list[dict]:
    """Display-tab view: one row per position with its class, current window,
    and eligible windows."""
    rows = []
    for sid in slot_ids():
        cls = slot_class(sid)
        rows.append({
            "slot": sid,
            "column": COLUMN_TITLE[column_of(sid)],
            "class": cls,
            "class_label": CLASS_LABEL[cls],
            "block": assignment.get(sid),
            "eligible": eligible_blocks(cls, available),
        })
    return rows


# ── Persistence ─────────────────────────────────────────────────────────────

def assignment_path() -> Path:
    from core.state import cmdr_data_dir
    return cmdr_data_dir() / "windows.json"


def load_assignment(path: Optional[Path] = None) -> dict[str, Optional[str]]:
    """Load the saved assignment, or the default arrangement when none exists.
    """
    p = path or assignment_path()
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return default_assignment()

    try:
        version = int(data.get("version", 1))
    except (TypeError, ValueError):
        version = 1

    if version < ASSIGNMENT_VERSION:
        fresh = default_assignment()
        try:
            save_assignment(fresh, p)
        except Exception:
            pass          # read-only home is not a reason to refuse to draw
        return fresh

    return normalize_assignment(data.get("slots", {}))


def save_assignment(assignment: dict, path: Optional[Path] = None) -> None:
    p = path or assignment_path()
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "version": ASSIGNMENT_VERSION,
            "slots": normalize_assignment(assignment),
        }
        tmp = p.with_suffix(".tmp")
        tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        tmp.replace(p)
    except OSError:
        pass
