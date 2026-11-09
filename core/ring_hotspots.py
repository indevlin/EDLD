"""core/ring_hotspots.py — Ring hotspot store, vocabularies and form.

A hotspot is one commodity's hotspot in one planetary ring, identified by
system name, ring name and canonical commodity (``hotspot_id``). Rows come
from ``SAASignalsFound`` on a ring, joined to the ring class and the parent
body's reserve level from ``Scan``; overlap and note are entered by hand.

Store: ``<shared data>/ring_hotspots.db``.
"""

from __future__ import annotations

import hashlib
import os
import re
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, NamedTuple, Optional

from core.surface_survey import canonical_commodity

SCHEMA_VERSION = 1

#: RingClass → display name.
RING_TYPES = {
    "eringclass_icy":       "Icy",
    "eringclass_metalic":   "Metallic",
    "eringclass_metallic":  "Metallic",
    "eringclass_metalrich": "Metal Rich",
    "eringclass_rocky":     "Rocky",
}
RING_TYPE_LEVELS = ("Icy", "Metallic", "Metal Rich", "Rocky")

#: ReserveLevel → display name.
RESERVES = {
    "pristineresources": "Pristine",
    "majorresources":    "Major",
    "commonresources":   "Common",
    "lowresources":      "Low",
    "depletedresources": "Depleted",
}
RESERVE_LEVELS = ("Pristine", "Major", "Common", "Low", "Depleted")

OVERLAPS = ("Resource [LOW]", "Resource [HIGH]", "Resource [HAZ]",
            "Resource [BLANK]", "Hotspot [NOTE]")

#: Commodities mined by laser, abrasion or core, as the game names them.
MINEABLE = (
    "Alexandrite", "Bauxite", "Benitoite", "Bertrandite", "Bromellite",
    "Coltan", "Cryolite", "Gallite", "Gold", "Goslarite", "Grandidierite",
    "Hydrogen Peroxide", "Indite", "Jadeite", "Lanthanum", "Lepidolite",
    "Liquid Oxygen", "Lithium Hydroxide", "Low Temperature Diamonds",
    "Methane Clathrate", "Methanol Monohydrate Crystals", "Moissanite",
    "Monazite", "Musgravite", "Osmium", "Painite", "Palladium", "Platinum",
    "Praseodymium", "Pyrophyllite", "Rhodplumsite", "Rutile", "Samarium",
    "Serendibite", "Silver", "Taaffeite", "Thorium", "Tritium", "Uraninite",
    "Void Opals", "Water",
)

_RING_NAME = re.compile(r"^(?P<body>.*?)\s+(?P<ring>[A-Z])\s+Ring$", re.I)


def _utcnow() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def ring_type(raw) -> str:
    """RingClass (``eRingClass_Metalic``) → ``Metallic``; display names pass."""
    s = str(raw or "").strip()
    if s in RING_TYPE_LEVELS:
        return s
    return RING_TYPES.get(s.lower(), "")


def reserve_level(raw) -> str:
    """ReserveLevel (``PristineResources``) → ``Pristine``; display names pass."""
    s = str(raw or "").strip()
    if s in RESERVE_LEVELS:
        return s
    return RESERVES.get(s.lower(), "")


def split_ring(name: str) -> tuple[str, str]:
    """``Col 285 Sector X 3 A Ring`` → (``Col 285 Sector X 3``, ``A``); ("", "")
    when not a ring name."""
    m = _RING_NAME.match(str(name or "").strip())
    if not m:
        return "", ""
    return m.group("body"), m.group("ring").upper()


def ring_name(body: str, ring: str) -> str:
    return f"{body.strip()} {ring.strip().upper()} Ring"


def commodity_display(raw: str) -> str:
    """The MINEABLE spelling of ``raw`` where there is one, else ``raw``."""
    key = canonical_commodity(raw)
    for name in MINEABLE:
        if canonical_commodity(name) == key:
            return name
    return str(raw or "").strip()


def hotspot_id(system: str, body: str, ring: str, commodity: str) -> str:
    """12 hex digits of SHA-1 over lowercased system, ring name and canonical
    commodity."""
    key = "|".join((str(system or "").strip().lower(),
                    ring_name(body, ring).lower(),
                    canonical_commodity(commodity)))
    return hashlib.sha1(key.encode("utf-8")).hexdigest()[:12]


_SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS rings (
    system_name    TEXT NOT NULL,
    ring_name      TEXT NOT NULL,
    system_address INTEGER,
    ring_type      TEXT NOT NULL DEFAULT '',
    reserve_level  TEXT NOT NULL DEFAULT '',
    PRIMARY KEY (system_name, ring_name)
);
CREATE TABLE IF NOT EXISTS hotspots (
    hotspot_id       TEXT PRIMARY KEY,
    system_name      TEXT NOT NULL,
    system_address   INTEGER,
    body_name        TEXT NOT NULL,
    ring             TEXT NOT NULL,
    ring_type        TEXT NOT NULL DEFAULT '',
    reserve_level    TEXT NOT NULL DEFAULT '',
    commodity        TEXT NOT NULL,
    commodity_display TEXT NOT NULL DEFAULT '',
    count            INTEGER,
    overlap          TEXT NOT NULL DEFAULT '',
    note             TEXT NOT NULL DEFAULT '',
    overlap_updated  TEXT NOT NULL DEFAULT '',
    reported_by      TEXT NOT NULL DEFAULT '',
    is_test          INTEGER NOT NULL DEFAULT 0,
    first_seen       TEXT NOT NULL,
    last_confirmed   TEXT NOT NULL,
    published_at     TEXT NOT NULL DEFAULT '',
    remote           INTEGER NOT NULL DEFAULT 0
);
"""


class HotspotDB:
    """sqlite3 store; one cached connection per process, RLock around writes."""

    def __init__(self, path: Path | str) -> None:
        self._path = Path(path)
        self._lock = threading.RLock()
        self._conn: Optional[sqlite3.Connection] = None
        self._pid = -1

    @property
    def path(self) -> Path:
        return self._path

    def _connect(self) -> sqlite3.Connection:
        with self._lock:
            if self._conn is not None and self._pid == os.getpid():
                return self._conn
            self._path.parent.mkdir(parents=True, exist_ok=True)
            conn = sqlite3.connect(str(self._path), check_same_thread=False)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA busy_timeout=30000")
            conn.executescript(_SCHEMA)
            conn.execute("INSERT OR IGNORE INTO meta(key, value) VALUES('schema_version', ?)",
                         (str(SCHEMA_VERSION),))
            conn.commit()
            self._conn, self._pid = conn, os.getpid()
            return conn

    def close(self) -> None:
        with self._lock:
            if self._conn is not None:
                self._conn.close()
            self._conn = None

    # ── rings ─────────────────────────────────────────────────────────────────

    def upsert_ring(self, system_name: str, ring_name_: str, *, system_address=None,
                    ring_type_: str = "", reserve_level_: str = "") -> None:
        """Record a ring's type and reserve; blanks leave stored values. Fills
        blank ring_type / reserve_level on that ring's hotspots."""
        if not system_name or not ring_name_:
            return
        conn = self._connect()
        with self._lock:
            conn.execute(
                "INSERT INTO rings(system_name, ring_name, system_address, ring_type, reserve_level) "
                "VALUES(?,?,?,?,?) ON CONFLICT(system_name, ring_name) DO UPDATE SET "
                "system_address=COALESCE(excluded.system_address, rings.system_address), "
                "ring_type=CASE WHEN excluded.ring_type<>'' THEN excluded.ring_type ELSE rings.ring_type END, "
                "reserve_level=CASE WHEN excluded.reserve_level<>'' THEN excluded.reserve_level "
                "ELSE rings.reserve_level END",
                (system_name, ring_name_, system_address, ring_type_, reserve_level_))
            body, ring = split_ring(ring_name_)
            if body:
                for col, val in (("ring_type", ring_type_), ("reserve_level", reserve_level_)):
                    if val:
                        conn.execute(
                            f"UPDATE hotspots SET {col}=?, published_at='' WHERE {col}='' "
                            "AND lower(system_name)=lower(?) AND lower(body_name)=lower(?) AND ring=?",
                            (val, system_name, body, ring))
            conn.commit()

    def ring(self, system_name: str, ring_name_: str) -> Optional[dict]:
        r = self._connect().execute(
            "SELECT * FROM rings WHERE lower(system_name)=lower(?) AND lower(ring_name)=lower(?)",
            (system_name, ring_name_)).fetchone()
        return dict(r) if r else None

    # ── hotspots ──────────────────────────────────────────────────────────────

    def observe(self, *, system_name: str, body_name: str, ring: str, commodity: str,
                system_address=None, count=None, reported_by: str = "",
                is_test: bool = False, seen_at: str = "") -> tuple[str, bool]:
        """Insert or confirm a hotspot from a scan. Returns (hotspot_id, created).
        Ring type and reserve come from ``rings`` where known."""
        canon = canonical_commodity(commodity)
        hid = hotspot_id(system_name, body_name, ring, canon)
        known = self.ring(system_name, ring_name(body_name, ring)) or {}
        now = seen_at or _utcnow()
        conn = self._connect()
        with self._lock:
            have = conn.execute("SELECT * FROM hotspots WHERE hotspot_id=?", (hid,)).fetchone()
            if have is None:
                conn.execute(
                    "INSERT INTO hotspots(hotspot_id, system_name, system_address, body_name, ring, "
                    "ring_type, reserve_level, commodity, commodity_display, count, reported_by, "
                    "is_test, first_seen, last_confirmed) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (hid, system_name, system_address, body_name, ring.upper(),
                     known.get("ring_type", ""), known.get("reserve_level", ""), canon,
                     commodity_display(commodity), count, reported_by, int(bool(is_test)),
                     now, now))
                conn.commit()
                return hid, True
            changed = (have["remote"] or (count is not None and have["count"] != count)
                       or (system_address and not have["system_address"])
                       or (known.get("ring_type") and not have["ring_type"])
                       or (known.get("reserve_level") and not have["reserve_level"]))
            conn.execute(
                "UPDATE hotspots SET last_confirmed=MAX(last_confirmed, ?), remote=0, "
                "count=COALESCE(?, count), system_address=COALESCE(system_address, ?), "
                "ring_type=CASE WHEN ring_type='' THEN ? ELSE ring_type END, "
                "reserve_level=CASE WHEN reserve_level='' THEN ? ELSE reserve_level END"
                + (", published_at=''" if changed else "") + " WHERE hotspot_id=?",
                (now, count, system_address, known.get("ring_type", ""),
                 known.get("reserve_level", ""), hid))
            conn.commit()
            return hid, False

    def add(self, values: dict, *, reported_by: str = "", is_test: bool = False) -> str:
        """Insert a hand-entered hotspot (cleaned form values). Returns its id."""
        hid, _ = self.observe(system_name=values["system_name"], body_name=values["body_name"],
                              ring=values["ring"], commodity=values["commodity"],
                              system_address=values.get("system_address"),
                              reported_by=reported_by, is_test=is_test)
        self.annotate(hid, values)
        return hid

    def annotate(self, hid: str, values: dict) -> bool:
        """Apply cleaned form values; overlap/note changes stamp overlap_updated.
        Marks the row unpublished when anything changed."""
        conn = self._connect()
        with self._lock:
            row = conn.execute("SELECT * FROM hotspots WHERE hotspot_id=?", (hid,)).fetchone()
            if row is None:
                return False
            sets, args = [], []
            for col in ("ring_type", "reserve_level", "is_test"):
                if col in values and values[col] != row[col]:
                    sets.append(f"{col}=?")
                    args.append(int(values[col]) if col == "is_test" else values[col])
            stamped = False
            for col in ("overlap", "note"):
                if col in values and values[col] != row[col]:
                    sets.append(f"{col}=?")
                    args.append(values[col])
                    stamped = True
            if stamped:
                sets.append("overlap_updated=?")
                args.append(_utcnow())
            if not sets:
                return False
            sets.append("published_at=''")
            sets.append("remote=0")
            conn.execute(f"UPDATE hotspots SET {', '.join(sets)} WHERE hotspot_id=?",
                         args + [hid])
            conn.commit()
            return True

    def hotspot(self, hid: str) -> Optional[dict]:
        r = self._connect().execute("SELECT * FROM hotspots WHERE hotspot_id=?", (hid,)).fetchone()
        return dict(r) if r else None

    def all_hotspots(self) -> list[dict]:
        """Every hotspot, ordered system, body, ring, commodity."""
        return [dict(r) for r in self._connect().execute(
            "SELECT * FROM hotspots ORDER BY lower(system_name), lower(body_name), ring, "
            "lower(commodity_display)").fetchall()]

    def delete(self, hid: str) -> bool:
        conn = self._connect()
        with self._lock:
            cur = conn.execute("DELETE FROM hotspots WHERE hotspot_id=?", (hid,))
            conn.commit()
            return bool(cur.rowcount)

    def unpublished(self, limit: int = 500, include_test: bool = False) -> list[dict]:
        sql = "SELECT * FROM hotspots WHERE published_at='' AND remote=0"
        if not include_test:
            sql += " AND is_test=0"
        sql += " ORDER BY last_confirmed LIMIT ?"
        return [dict(r) for r in self._connect().execute(sql, (int(limit),)).fetchall()]

    def mark_published(self, ids: Iterable[str]) -> int:
        ids = [i for i in ids if i]
        if not ids:
            return 0
        now = _utcnow()
        conn = self._connect()
        with self._lock:
            cur = conn.executemany("UPDATE hotspots SET published_at=? WHERE hotspot_id=?",
                                   [(now, i) for i in ids])
            conn.commit()
            return cur.rowcount or 0

    def import_rows(self, rows: Iterable[dict]) -> tuple[int, int]:
        """Merge sheet rows. New rows are stored as remote and published.
        Blank local fields are filled; overlap/note take the newer stamp.
        Returns (added, updated)."""
        added = updated = 0
        conn = self._connect()
        with self._lock:
            for r in rows:
                hid = str(r.get("hotspot_id", "") or "").strip()
                system, body = str(r.get("system", "") or ""), str(r.get("body", "") or "")
                ring, commodity = str(r.get("ring", "") or "").upper(), str(r.get("commodity", "") or "")
                if not (hid and system and body and ring and commodity):
                    continue
                if str(r.get("is_test", "")) in ("1", "True", "true"):
                    continue
                have = conn.execute("SELECT * FROM hotspots WHERE hotspot_id=?", (hid,)).fetchone()
                stamp = str(r.get("overlap_updated", "") or "")
                if have is None:
                    now = _utcnow()
                    conn.execute(
                        "INSERT INTO hotspots(hotspot_id, system_name, system_address, body_name, "
                        "ring, ring_type, reserve_level, commodity, commodity_display, count, "
                        "overlap, note, overlap_updated, reported_by, first_seen, last_confirmed, "
                        "published_at, remote) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,1)",
                        (hid, system, _int(r.get("system_address")), body, ring,
                         ring_type(r.get("ring_type")), reserve_level(r.get("reserve_level")),
                         canonical_commodity(commodity), commodity_display(commodity),
                         _int(r.get("count")), _choice(r.get("overlap"), OVERLAPS),
                         _choice(commodity_display(str(r.get("note", "") or "")), MINEABLE, free=True),
                         stamp, str(r.get("reported_by", "") or ""),
                         str(r.get("first_seen", "") or now), str(r.get("last_confirmed", "") or now),
                         now))
                    added += 1
                    continue
                sets, args = [], []
                for col, val in (("ring_type", ring_type(r.get("ring_type"))),
                                 ("reserve_level", reserve_level(r.get("reserve_level")))):
                    if val and not have[col]:
                        sets.append(f"{col}=?")
                        args.append(val)
                if stamp and stamp > (have["overlap_updated"] or ""):
                    sets += ["overlap=?", "note=?", "overlap_updated=?"]
                    args += [_choice(r.get("overlap"), OVERLAPS),
                             _choice(commodity_display(str(r.get("note", "") or "")), MINEABLE,
                                     free=True), stamp]
                if sets:
                    conn.execute(f"UPDATE hotspots SET {', '.join(sets)} WHERE hotspot_id=?",
                                 args + [hid])
                    updated += 1
            conn.commit()
        return added, updated

    def counts(self) -> dict:
        conn = self._connect()
        one = lambda sql: int(conn.execute(sql).fetchone()[0])  # noqa: E731
        return {"hotspots": one("SELECT COUNT(*) FROM hotspots"),
                "rings": one("SELECT COUNT(*) FROM rings"),
                "pending": one("SELECT COUNT(*) FROM hotspots WHERE published_at='' AND remote=0")}


def _int(v):
    try:
        return int(v) if v not in (None, "") else None
    except (TypeError, ValueError):
        return None


def _choice(v, allowed, free: bool = False) -> str:
    s = str(v or "").strip()
    if not s:
        return ""
    match = next((a for a in allowed if a.lower() == s.lower()), None)
    return match or (s if free else "")


_instance: Optional[HotspotDB] = None
_instance_lock = threading.Lock()


def get_db() -> HotspotDB:
    global _instance
    with _instance_lock:
        if _instance is None:
            from core.state import shared_data_dir
            _instance = HotspotDB(shared_data_dir() / "ring_hotspots.db")
        return _instance


# ── form ──────────────────────────────────────────────────────────────────────

class Field(NamedTuple):
    key:     str
    label:   str
    kind:    str              # "text" | "choice" | "bool"
    choices: tuple[str, ...] = ()
    hint:    str = ""


RINGS = ("A", "B", "C", "D")

#: Editable fields, in display order. ``identity`` fields are fixed once a
#: hotspot exists.
FIELDS: tuple[Field, ...] = (
    Field("system_name", "System", "text", hint="as the galaxy map names it"),
    Field("body_name", "Body", "text", hint="the planet the ring belongs to"),
    Field("ring", "Ring", "choice", RINGS),
    Field("ring_type", "Ring type", "choice", RING_TYPE_LEVELS),
    Field("reserve_level", "Reserve", "choice", RESERVE_LEVELS),
    Field("commodity", "Commodity", "choice", MINEABLE),
    Field("overlap", "Overlap", "choice", OVERLAPS,
          "a resource site at the hotspot, or another hotspot (named in Note)"),
    Field("note", "Note", "choice", MINEABLE, "the overlapping hotspot's commodity"),
    Field("is_test", "Test data", "bool", hint="held back from the sheet"),
)
IDENTITY = ("system_name", "body_name", "ring", "commodity")


class Cleaned(NamedTuple):
    values: dict
    errors: dict


def clean(raw: dict, *, new: bool = False) -> Cleaned:
    """Validate form contents. Choice fields accept any case; a blank choice
    leaves the stored value unless it is overlap or note, where blank clears.
    ``new`` requires the identity fields."""
    values: dict = {}
    errors: dict = {}
    for key in ("system_name", "body_name"):
        text = " ".join(str(raw.get(key, "") or "").split())
        if text:
            values[key] = text
        elif new:
            errors[key] = f"{dict((f.key, f.label) for f in FIELDS)[key]} is required"
    ring = str(raw.get("ring", "") or "").strip().upper()
    if ring:
        if len(ring) != 1 or not ring.isalpha():
            errors["ring"] = "Ring must be a single letter"
        else:
            values["ring"] = ring
    elif new:
        errors["ring"] = "Ring is required"
    commodity = str(raw.get("commodity", "") or "").strip()
    if commodity:
        values["commodity"] = commodity_display(commodity)
    elif new:
        errors["commodity"] = "Commodity is required"
    for key, allowed, label in (("ring_type", RING_TYPE_LEVELS, "Ring type"),
                                ("reserve_level", RESERVE_LEVELS, "Reserve")):
        text = str(raw.get(key, "") or "").strip()
        if not text:
            continue
        match = next((a for a in allowed if a.lower() == text.lower()), None)
        if match is None:
            errors[key] = f"{label} must be one of {', '.join(allowed)}"
        else:
            values[key] = match
    if "overlap" in raw:
        text = str(raw.get("overlap", "") or "").strip()
        match = next((a for a in OVERLAPS if a.lower() == text.lower()), None)
        if text and match is None:
            errors["overlap"] = f"Overlap must be one of {', '.join(OVERLAPS)}"
        else:
            values["overlap"] = match or ""
    if "note" in raw:
        text = str(raw.get("note", "") or "").strip()
        values["note"] = commodity_display(text) if text else ""
    if values.get("note") and values.get("overlap", "Hotspot [NOTE]") != "Hotspot [NOTE]":
        errors["note"] = "Note names an overlapping hotspot; set Overlap to Hotspot [NOTE]"
    flag = raw.get("is_test", None)
    if flag not in (None, ""):
        values["is_test"] = str(flag).strip().lower() in ("1", "true", "yes", "on")
    return Cleaned(values, errors)


def prefill(h: dict | None, **defaults) -> dict:
    """Form contents for a hotspot, or ``defaults`` over blanks for a new one."""
    if not h:
        out = {f.key: "" for f in FIELDS}
        out.update({k: v for k, v in defaults.items() if k in out and v})
        return out
    return {
        "system_name": h.get("system_name", ""),
        "body_name": h.get("body_name", ""),
        "ring": h.get("ring", ""),
        "ring_type": h.get("ring_type", ""),
        "reserve_level": h.get("reserve_level", ""),
        "commodity": h.get("commodity_display") or h.get("commodity", ""),
        "overlap": h.get("overlap", ""),
        "note": h.get("note", ""),
        "is_test": "true" if h.get("is_test") else "",
    }


def describe(errors: dict) -> str:
    return "; ".join(errors[k] for k in sorted(errors))
