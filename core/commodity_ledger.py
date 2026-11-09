"""core/commodity_ledger.py — persistent CSV catalog of every commodity seen.

File layout
-----------
Path:  ``<cmdr>/data/cargo.commodities.csv`` (the cargo plugin owns the path;
this module is given it).  Columns:

    name                canonical internal symbol — ``gold``, ``bertrandite``
    id                  Frontier's numeric commodity id — ``128049154``
    name_localised      display name — ``Gold``
    category            canonical internal category — ``metals``
    category_localised  display category — ``Metals``
    mean_price          last recorded galactic average, in credits
    first_seen          ISO-8601 UTC, when the commodity was first recorded
    last_updated        ISO-8601 UTC, when ``mean_price`` last changed
    updates             number of price drifts recorded since ``first_seen``

Zero prices
-----------
Fleet Carrier markets publish trade orders with ``MeanPrice`` of 0, which is
not a galactic average — it is the absence of one.  A commodity first seen at
such a market is still recorded (identity is worth having), but a zero never
overwrites a price already on file, and it never counts as a drift.  The row
heals itself the first time the commodity turns up at a station market.
"""

from __future__ import annotations

import csv
import os
import re
import threading
from datetime import datetime, timezone
from pathlib import Path

# ── Schema ────────────────────────────────────────────────────────────────────

FIELDNAMES: list[str] = [
    "name",
    "id",
    "name_localised",
    "category",
    "category_localised",
    "mean_price",
    "first_seen",
    "last_updated",
    "updates",
]

#: Frontier wraps display keys as ``$<symbol>_name;`` — commodity names.
_NAME_RE = re.compile(r"^\$(.+)_name;$")
#: ...and categories as ``$MARKET_category_<symbol>;``.
_CAT_RE = re.compile(r"^\$market_category_(.+);$")


def canonical_name(raw: str) -> str:
    """Normalize a commodity name to its bare lowercase symbol."""
    s = (raw or "").strip().lower()
    m = _NAME_RE.match(s)
    return m.group(1) if m else s


def canonical_category(raw: str) -> str:
    """Normalize a commodity category to its bare lowercase symbol."""
    s = (raw or "").strip().lower()
    m = _CAT_RE.match(s)
    if m:
        return m.group(1)
    m = _NAME_RE.match(s)
    return m.group(1) if m else s


def _pretty(symbol: str) -> str:
    return symbol.replace("_", " ").title()


def _utcnow() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _int(value, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def row_from_item(item: dict) -> dict | None:
    """Build a ledger row from one Market.json ``Items`` entry.

    Returns None when the entry carries no usable name, which is the only
    field the row cannot be reconstructed without.
    """
    name = canonical_name(item.get("Name", ""))
    if not name:
        return None
    cat = canonical_category(item.get("Category", ""))
    return {
        "name":               name,
        "id":                 _int(item.get("id", "")) or "",
        "name_localised":     item.get("Name_Localised") or _pretty(name),
        "category":           cat,
        "category_localised": item.get("Category_Localised") or _pretty(cat),
        "mean_price":         max(0, _int(item.get("MeanPrice", 0))),
    }


# ── Ledger ────────────────────────────────────────────────────────────────────

class CommodityLedger:
    """The CSV catalog, held in memory and rewritten when it changes.

    Thread-safe: the Market.json watcher thread and the journal event thread
    both reach ``apply()``.
    """

    def __init__(self, path: Path | str, log=None) -> None:
        self._path = Path(path)
        self._log = log or (lambda msg: None)
        self._lock = threading.Lock()
        self._rows: dict[str, dict] = {}
        self._loaded = False

    # ── Public API ────────────────────────────────────────────────────────────

    @property
    def path(self) -> Path:
        return self._path

    def rows(self) -> dict[str, dict]:
        """A copy of the current catalog, keyed on canonical name."""
        with self._lock:
            return {k: dict(v) for k, v in self._rows.items()}

    def load(self) -> int:
        """Read the CSV into memory. Returns the number of rows loaded."""
        with self._lock:
            self._rows = {}
            self._loaded = True
            if not self._path.is_file():
                return 0
            try:
                with open(self._path, "r", encoding="utf-8", newline="") as f:
                    for raw in csv.DictReader(f):
                        name = canonical_name(raw.get("name", ""))
                        if not name:
                            continue
                        self._rows[name] = {
                            "name":               name,
                            "id":                 _int(raw.get("id", "")) or "",
                            "name_localised":     raw.get("name_localised", "") or _pretty(name),
                            "category":           raw.get("category", "") or "",
                            "category_localised": raw.get("category_localised", "") or "",
                            "mean_price":         _int(raw.get("mean_price", 0)),
                            "first_seen":         raw.get("first_seen", "") or "",
                            "last_updated":       raw.get("last_updated", "") or "",
                            "updates":            _int(raw.get("updates", 0)),
                        }
            except (OSError, csv.Error, UnicodeDecodeError) as exc:
                self._rows = {}
                self._log(f"commodity ledger unreadable at {self._path}: {exc}")
                return 0
            return len(self._rows)

    def apply(self, items) -> tuple[int, int]:
        """Fold one Market.json ``Items`` list into the catalog.

        Returns ``(added, drifted)`` — commodities recorded for the first
        time, and commodities whose mean price moved.
        """
        if not self._loaded:
            self.load()

        now = _utcnow()
        added = drifted = 0
        dirty = False

        with self._lock:
            for item in items or []:
                incoming = row_from_item(item if isinstance(item, dict) else {})
                if incoming is None:
                    continue
                existing = self._rows.get(incoming["name"])

                if existing is None:
                    incoming["first_seen"] = now
                    incoming["last_updated"] = now
                    incoming["updates"] = 0
                    self._rows[incoming["name"]] = incoming
                    added += 1
                    dirty = True
                    continue

                price = incoming["mean_price"]
                # A zero is the absence of a galactic average, not a new one.
                if price and price != existing["mean_price"]:
                    existing["mean_price"] = price
                    existing["last_updated"] = now
                    existing["updates"] = _int(existing.get("updates", 0)) + 1
                    drifted += 1
                    dirty = True

                # Identity fields follow the game without counting as drift,
                # so a renamed commodity or a row recovered from a truncated
                # file corrects itself.
                for field in ("id", "name_localised", "category",
                              "category_localised"):
                    value = incoming[field]
                    if value and value != existing.get(field):
                        existing[field] = value
                        dirty = True

            if dirty:
                self._write_locked()

        return added, drifted

    # ── Internals ─────────────────────────────────────────────────────────────

    def _sorted_rows(self) -> list[dict]:
        # By id, so the file tracks Frontier's own ordering and diffs cleanly.
        # Ids are sparse but stable; anything without one sorts to the end.
        def key(row):
            rid = _int(row.get("id", ""), default=0)
            return (1, 0, row["name"]) if not rid else (0, rid, row["name"])
        return sorted(self._rows.values(), key=key)

    def _write_locked(self) -> None:
        """Atomic full rewrite.  Caller holds the lock."""
        tmp = self._path.with_suffix(self._path.suffix + ".tmp")
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            with open(tmp, "w", encoding="utf-8", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=FIELDNAMES)
                writer.writeheader()
                for row in self._sorted_rows():
                    writer.writerow({k: row.get(k, "") for k in FIELDNAMES})
            os.replace(tmp, self._path)
        except OSError as exc:
            self._log(f"commodity ledger write failed at {self._path}: {exc}")
            try:
                tmp.unlink(missing_ok=True)
            except OSError:
                pass
