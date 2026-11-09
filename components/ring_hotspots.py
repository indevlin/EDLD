"""components/ring_hotspots.py — Ring hotspots: capture, edit, sheet sync.

  Scan             a body's ``Rings`` (class) and ``ReserveLevel`` → rings table
  SAASignalsFound  on a ``… Ring`` body: one hotspot per commodity signal
  FSDJump/Location fetch the system's hotspots from the shared sheet (once per
                   system per session)
  Docked/FSDJump/  publish unpublished hotspots
  LeaveBody

Journal history is read once at load (background thread) for Scan and
SAASignalsFound, so rings mapped before this component existed are listed.
Sheet settings are ``[SurfaceSurvey]``.
"""

from __future__ import annotations

import queue
import threading

from core.plugin_loader import BasePlugin
from core import ring_hotspots as RH
from core.sheets_publish import CFG_DEFAULTS as SHEET_DEFAULTS, publisher_from_config


class RingHotspotsPlugin(BasePlugin):
    PLUGIN_NAME        = "ring_hotspots"
    PLUGIN_DISPLAY     = "Ring Hotspots"
    PLUGIN_VERSION     = "1.0.0"
    PLUGIN_DESCRIPTION = "Records planetary ring hotspots and shares them on the survey sheet."

    SUBSCRIBED_EVENTS = ["Scan", "SAASignalsFound", "FSDJump", "Location",
                         "CarrierJump", "Docked", "LeaveBody"]

    def on_load(self, core) -> None:
        self._core = core
        self._db = RH.get_db()
        self._system_name = ""
        self._system_address = None
        self._publisher = None
        self._reporter = ""
        self._include_test = False
        self._mark_as_test = False
        self._fetch_enabled = False
        self._fetched: set[str] = set()
        self.status = "off"
        try:
            cfg = core.load_setting("SurfaceSurvey", SHEET_DEFAULTS, warn=False)
            self._publisher = publisher_from_config(cfg, log=self._log)
            self._reporter = str(cfg.get("ReporterName", "") or "")
            self._include_test = bool(cfg.get("IncludeTest", False))
            self._mark_as_test = bool(cfg.get("MarkFindsAsTest", False))
            self._fetch_enabled = bool(cfg.get("Fetch", True))
            if self._publisher:
                self.status = "configured"
        except Exception as exc:
            self._log(f"sheet unavailable: {type(exc).__name__}: {exc}")
        self._jobs: queue.Queue = queue.Queue()
        threading.Thread(target=self._worker, daemon=True, name="edld-hotspots").start()
        self._jobs.put(("backfill", None))

    def on_unload(self) -> None:
        self._jobs.put(("publish", None))
        self._jobs.put(None)

    def _log(self, message: str) -> None:
        try:
            from core import debug as _debug
            _debug.info(f"[ring_hotspots] {message}")
        except Exception:
            pass

    # ── background work ───────────────────────────────────────────────────────

    def _worker(self) -> None:
        while True:
            job = self._jobs.get()
            if job is None:
                return
            kind, arg = job
            try:
                if kind == "backfill":
                    self._backfill()
                elif kind == "publish":
                    self.publish_now()
                elif kind == "fetch":
                    self.fetch_system(*arg)
            except Exception as exc:
                self._log(f"{kind} failed: {type(exc).__name__}: {exc}")

    def _backfill(self) -> None:
        jdir = getattr(self._core, "journal_dir", None)
        if not jdir:
            return
        from core.journal_index import index_for
        system, created = "", 0
        for _f, ev in index_for(jdir).events(("Scan", "SAASignalsFound", "FSDJump",
                                              "Location", "CarrierJump")):
            name = ev.get("event")
            if name in ("FSDJump", "Location", "CarrierJump"):
                system = ev.get("StarSystem") or system
            elif name == "Scan":
                self._on_scan(ev)
            else:
                created += self._on_signals(ev, system, seen_at=ev.get("timestamp", ""))
        counts = self._db.counts()
        self._log(f"history read — {created} new hotspot(s); {counts['hotspots']} hotspot(s) "
                  f"in {counts['rings']} ring(s), {counts['pending']} unpublished")
        self._refresh()

    # ── events ────────────────────────────────────────────────────────────────

    def on_event(self, event: dict, state) -> None:
        name = event.get("event")
        if name in ("FSDJump", "Location", "CarrierJump"):
            self._system_name = event.get("StarSystem") or self._system_name
            self._system_address = event.get("SystemAddress", self._system_address)
            if not getattr(state, "in_preload", False):
                self._jobs.put(("fetch", (self._system_name, self._system_address)))
                if name == "FSDJump":
                    self._jobs.put(("publish", None))
        elif name == "Scan":
            self._on_scan(event)
        elif name == "SAASignalsFound":
            if self._on_signals(event, event.get("StarSystem") or self._system_name):
                self._refresh()
        elif name in ("Docked", "LeaveBody") and not getattr(state, "in_preload", False):
            self._jobs.put(("publish", None))

    def _on_scan(self, ev: dict) -> None:
        rings = ev.get("Rings") or []
        if not rings:
            return
        system = ev.get("StarSystem") or self._system_name
        reserve = RH.reserve_level(ev.get("ReserveLevel"))
        for r in rings:
            name = str(r.get("Name", "") or "")
            if not name.lower().endswith(" ring"):
                continue
            self._db.upsert_ring(system, name, system_address=ev.get("SystemAddress"),
                                 ring_type_=RH.ring_type(r.get("RingClass")),
                                 reserve_level_=reserve)

    def _on_signals(self, ev: dict, system: str, seen_at: str = "") -> int:
        body, ring = RH.split_ring(ev.get("BodyName", ""))
        if not (body and system):
            return 0
        created = 0
        for sig in ev.get("Signals", []) or []:
            raw = str(sig.get("Type", "") or "")
            if not raw or raw.startswith("$"):
                continue
            _hid, new = self._db.observe(
                system_name=system, body_name=body, ring=ring,
                commodity=sig.get("Type_Localised") or raw,
                system_address=ev.get("SystemAddress"), count=sig.get("Count"),
                reported_by=self._reporter, is_test=self._mark_as_test, seen_at=seen_at)
            created += int(new)
        return created

    def _refresh(self) -> None:
        q = getattr(self._core, "gui_queue", None)
        if q is not None:
            try:
                q.put_nowait(("plugin_refresh", self.PLUGIN_NAME))
            except Exception:
                pass

    # ── sheet ─────────────────────────────────────────────────────────────────

    def publish_now(self) -> str:
        if not self._publisher:
            return "off"
        pending = self._db.unpublished(include_test=self._include_test)
        if not pending:
            self.status = "nothing pending"
            return self.status
        result = self._publisher.publish_hotspots(pending, reporter=self._reporter)
        if result.ok:
            self._db.mark_published(result.sent_ids)
        self.status = result.summary()
        return self.status

    def fetch_system(self, system: str, system_address=None) -> str:
        if not (self._publisher and self._fetch_enabled and system):
            return ""
        key = system.lower()
        if key in self._fetched:
            return ""
        self._fetched.add(key)
        rows, error = self._publisher.fetch_hotspots(system_address, system)
        if error:
            self._log(f"fetch failed — {error}")
            return error
        added, updated = self._db.import_rows(rows)
        if added or updated:
            self._log(f"{system}: {added} shared hotspot(s) added, {updated} updated")
            self._refresh()
        return f"{added} added, {updated} updated"

    # ── front-end API ─────────────────────────────────────────────────────────

    def records(self) -> list[dict]:
        return self._db.all_hotspots()

    def form_for(self, hid: str | None) -> tuple[dict, str]:
        """(prefilled form, heading). ``hid`` None: a new hotspot in the
        current system."""
        if not hid:
            return (RH.prefill(None, system_name=self._system_name),
                    "New ring hotspot")
        h = self._db.hotspot(hid)
        if h is None:
            return RH.prefill(None), "Hotspot not found"
        return (RH.prefill(h),
                f"{h['body_name']} {h['ring']} Ring — {h.get('commodity_display') or h['commodity']}")

    def submit_form_for(self, hid: str | None, raw: dict) -> str:
        """Apply a form. Returns "recorded …", "updated …", "nothing to change"
        or the validation errors."""
        cleaned = RH.clean(raw, new=not hid)
        if cleaned.errors:
            return RH.describe(cleaned.errors)
        values = cleaned.values
        if not hid:
            if values["system_name"].lower() == (self._system_name or "").lower():
                values["system_address"] = self._system_address
            new_id = self._db.add(values, reported_by=self._reporter,
                                  is_test=values.get("is_test", self._mark_as_test))
            self._refresh()
            return f"recorded hotspot {new_id}"
        if self._db.hotspot(hid) is None:
            return f"hotspot {hid} is not in the store"
        for key in RH.IDENTITY:
            values.pop(key, None)
        if "overlap" in values and values["overlap"] != "Hotspot [NOTE]":
            values["note"] = ""
        elif values.get("note") and "overlap" not in values:
            values["overlap"] = "Hotspot [NOTE]"
        if not self._db.annotate(hid, values):
            return "nothing to change"
        self._refresh()
        return f"updated hotspot {hid}"

    def save_cell(self, hid: str, key: str, value: str) -> str:
        """One field from an in-place table edit; same rules as submit_form_for."""
        return self.submit_form_for(hid, {key: value})

    def delete(self, hid: str) -> bool:
        ok = self._db.delete(hid)
        if ok:
            self._refresh()
        return ok
