"""core/body_ingest.py — Journal event → body-database dispatcher.

``FSSBodySignals`` / ``SAASignalsFound`` are handled here.
"""

from __future__ import annotations

import json
from typing import Any, Optional

from core import exobio_ingest as _exobio
from core import explo_ingest as _explo
from core.bodies_db import BodyDB, get_db
from core.journal_fields import signal_kind

# Events the importer / live path care about.  Exposed so callers can subscribe
# exactly this set rather than the firehose.  Assembled from the two domain
# modules plus the context and shared-signal events this module handles itself,
# so adding a handler in either domain updates the subscription automatically.
_CONTEXT_EVENTS = ("Commander", "LoadGame", "Location", "FSDJump", "CarrierJump")
_SIGNAL_EVENTS  = ("FSSBodySignals", "SAASignalsFound")
_CODEX_EVENTS   = ("CodexEntry",)

INGEST_EVENTS = tuple(
    dict.fromkeys(_CONTEXT_EVENTS + _SIGNAL_EVENTS + _CODEX_EVENTS + _explo.EVENTS + _exobio.EVENTS)
)


class Ingestor:
    """Stateful translator from journal events to body-database rows."""

    def __init__(self, db: Optional[BodyDB] = None) -> None:
        self._db = db or get_db()
        self._cmdr_id: Optional[int] = None
        self._cmdr_fid: str = ""
        self._sys_id: Optional[int] = None
        self._sys_addr: Optional[int] = None
        self._last_flora_id: Optional[int] = None   # set on ScanOrganic, for waypoint capture

    # ── context the domain handlers read ──────────────────────────────────

    @property
    def db(self) -> BodyDB:
        """The database the handlers write through."""
        return self._db

    @property
    def commander_id(self) -> Optional[int]:
        return self._cmdr_id

    def set_commander(self, fid: str, name: str = "") -> Optional[int]:
        if fid and fid != self._cmdr_fid:
            self._cmdr_fid = fid
            self._cmdr_id = self._db.ensure_commander(fid, name)
        return self._cmdr_id

    def current_system_address(self) -> Optional[int]:
        """The SystemAddress of the system last entered (live location)."""
        return self._sys_addr

    def current_commander_id(self) -> Optional[int]:
        """The db id of the active commander (None until LoadGame/Commander)."""
        return self._cmdr_id

    def last_flora_id(self) -> Optional[int]:
        """Flora id from the most recent ScanOrganic (for waypoint capture)."""
        return self._last_flora_id

    def note_flora(self, flora_id: int) -> None:
        """Record the flora row a sample just touched, for waypoint capture."""
        self._last_flora_id = flora_id

    def resolve_system(self, event: dict) -> Optional[int]:
        """Upsert the event's system and make it current; return its row id."""
        addr = event.get("SystemAddress")
        if addr is None:
            return self._sys_id
        props: dict[str, Any] = {}
        name = event.get("StarSystem") or event.get("SystemName") or event.get("System")
        if name:
            props["name"] = name
        pos = event.get("StarPos")
        if isinstance(pos, (list, tuple)) and len(pos) == 3:
            props["x"], props["y"], props["z"] = pos
        if "Population" in event:
            props["population"] = event["Population"]
        sid = self._db.upsert_system(int(addr), **props)
        self._sys_id, self._sys_addr = sid, int(addr)
        return sid

    # ── dispatch ──────────────────────────────────────────────────────────

    def ingest(self, event: dict) -> None:
        ev = event.get("event")
        if ev == "Commander" or ev == "LoadGame":
            self.set_commander(event.get("FID", ""), event.get("Name") or event.get("Commander", ""))
        elif ev in ("Location", "FSDJump", "CarrierJump"):
            self.resolve_system(event)
        elif ev == "FSSDiscoveryScan":
            _explo.fss_discovery(self, event)
        elif ev == "FSSAllBodiesFound":
            _explo.all_bodies_found(self, event)
        elif ev == "Scan":
            _explo.scan(self, event)
        elif ev in ("FSSBodySignals", "SAASignalsFound"):
            self._body_signals(event)
        elif ev == "SAAScanComplete":
            _explo.saa_complete(self, event)
        elif ev == "ScanOrganic":
            _exobio.scan_organic(self, event)
        elif ev == "Disembark":
            _exobio.disembark(self, event)
        elif ev == "CodexEntry":
            self._codex(event)

    def ingest_line(self, line: str) -> bool:
        try:
            event = json.loads(line)
        except (ValueError, TypeError):
            return False
        self.ingest(event)
        return True

    def _codex(self, event: dict) -> None:
        """``CodexEntry`` — an entry in the commander's codex, kept per region."""
        from core.region import region_id_from_codex
        if self._cmdr_id is None or not event.get("Name"):
            return
        region = region_id_from_codex(event.get("Region", ""))
        if region is None:
            return
        self._db.add_codex(self._cmdr_id, str(event["Name"]),
                           str(event.get("Name_Localised") or ""), region,
                           str(event.get("timestamp") or ""))

    # ── shared seam: signals ──────────────────────────────────────────────

    def _body_signals(self, event: dict) -> None:
        """``FSSBodySignals`` / ``SAASignalsFound`` — the shared signal table.
        """
        sid = self.resolve_system(event)
        body_id = event.get("BodyID")
        if sid is None or body_id is None:
            return
        planet_id = self._db.upsert_planet(sid, int(body_id), name=event.get("BodyName", ""))
        bio = geo = 0
        for sig in event.get("Signals", []) or []:
            if not isinstance(sig, dict):
                continue
            kind = signal_kind(sig.get("Type", ""))
            cnt = int(sig.get("Count", 0) or 0)
            if kind == "bio":
                bio += cnt
            elif kind == "geo":
                geo += cnt
            self._db.set_planet_signal(planet_id, kind, cnt)
        for g in event.get("Genuses", []) or []:
            if isinstance(g, dict):
                genus = g.get("Genus_Localised") or g.get("Genus") or ""
                if genus:
                    self._db.set_planet_signal(planet_id, "bio", 0, genus=genus)
        props: dict[str, Any] = {}
        if bio:
            props["bio_signals"] = bio
        if geo:
            props["geo_signals"] = geo
        if props:
            self._db.upsert_planet(sid, int(body_id), **props)
