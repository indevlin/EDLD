"""
components/callouts.py — things worth saying the moment they happen.

Sounds        One switch and a volume for every cue (core/sounds.py), and a
              cue on targeting a system: never reported, reported but not
              fully scanned, or done.
Firsts watch  An undiscovered system on arrival; a world no one has mapped
              when the commander maps it; ground no one has set foot on, on
              touching down and on stepping out. From the Scan's own
              WasDiscovered / WasMapped / WasFootfalled.
Exobiology    A genus not yet in the commander's codex for this region,
              when the surface scan reveals it; a sample run left
              unfinished on heading for supercruise, while there is still
              time to turn back; and, while flying low or on
              foot with a run in progress, the moment the commander is far
              enough from every earlier sample to take the next.
Limpets       Undocking with a limpet controller fitted and no limpets aboard,
              each type of controller switched on or off on its own.

Mining callouts (prospector, motherlode, hold, ring) live with the Mining
component, which owns that data; their settings are here so every callout is
set up in one place. Each callout honours its level under Notifications.
"""
from __future__ import annotations

import threading
import time

from core import callout
from core.plugin_loader import BasePlugin
from core.settings_spec import Heading, Setting, SettingsSpecMixin

#: Seconds between position checks while a sample run is in progress.
_SAMPLE_POLL_S = 1.0

#: Limpet controller types, as core/commander.py reads them from the
#: Loadout ("int_dronecontrol_prospector_size1_class5" → "prospector",
#: "int_multidronecontrol_miningv2_size5_class5" → "mining"): the setting
#: that switches the reminder for each, and the name it is said by. One per
#: type, whatever its size and class.
LIMPET_TYPES: tuple[tuple[str, str, str], ...] = (
    ("prospector", "LimpetProspector", "prospector"),
    ("collection", "LimpetCollection", "collector"),
    ("mining", "LimpetMining", "mining multi-limpet"),
    ("operations", "LimpetOperations", "operations multi-limpet"),
    ("rescue", "LimpetRescue", "rescue multi-limpet"),
    ("xeno", "LimpetXeno", "xeno multi-limpet"),
    ("universal", "LimpetUniversal", "universal multi-limpet"),
    ("repair", "LimpetRepair", "repair"),
    ("fueltransfer", "LimpetFuelTransfer", "fuel transfer"),
    ("resourcesiphon", "LimpetHatchBreaker", "hatch breaker"),
    ("decontamination", "LimpetDecontamination", "decontamination"),
    ("recon", "LimpetRecon", "recon"),
    ("unkvesselresearch", "LimpetResearch", "research"),
)
_LIMPET_NAMES = {t: name for t, _key, name in LIMPET_TYPES}
_LIMPET_KEYS = {t: key for t, key, _name in LIMPET_TYPES}


class CalloutsPlugin(SettingsSpecMixin, BasePlugin):
    PLUGIN_NAME = "callouts"
    PLUGIN_DISPLAY = "Callouts"
    PLUGIN_VERSION = "1.0.0"
    PLUGIN_DESCRIPTION = ("Firsts, codex, sample-run, limpet and targeting callouts, "
                          "and the sounds every callout plays.")
    SUBSCRIBED_EVENTS = [
        "FSDTarget", "FSDJump", "CarrierJump", "Location", "Scan", "FSSAllBodiesFound",
        "SAAScanComplete", "SAASignalsFound", "Touchdown", "Disembark",
        "ScanOrganic", "SupercruiseEntry", "LeaveBody", "Undocked",
        "Died", "Resurrect",
    ]

    SETTINGS_SECTION = "Callouts"
    SETTINGS_TAB = ("pref-tab-callouts", "Callouts")
    SETTINGS = (
        Heading("Sounds", "Short chimes, one per kind of callout."),
        Setting("Sounds", "Play sounds", bool, True),
        Setting("Volume", "Volume (%)", int, 70),
        Setting("TargetSound", "Sound on targeting a system (new · unscanned · done)", bool, True),
        Heading("Exploration"),
        Setting("FirstsWatch", "Call out undiscovered systems, unmapped worlds and untrodden ground",
                bool, True),
        Heading("Exobiology"),
        Setting("CodexCallout", "Call out genera new to your codex in this region", bool, True),
        Setting("UnfinishedRun", "Warn on leaving a body with a sample run unfinished", bool, True),
        Setting("SafeToSample", "Say when far enough from earlier samples for the next", bool, True),
        Heading("Mining"),
        Setting("ProspectorMinerals", "Minerals to call out (comma-separated)", str,
                "Platinum, Painite, Low Temperature Diamonds, Tritium, Osmium, Palladium, Gold"),
        Setting("ProspectorPercent", "Call out at this share or more (%)", int, 20),
        Setting("Motherlodes", "Call out motherlodes (core material)", bool, True),
        Setting("HoldWarning", "Say when the hold is nearly full and full", bool, True),
        Setting("RingCallout", "Describe a ring on dropping into it", bool, True),
        Heading("Limpets",
                "Undocking with a limpet controller fitted and no limpets aboard. "
                "A ship with no controller is never reminded."),
        Setting("LimpetReminder", "Warn on undocking with no limpets aboard", bool, True),
        *(Setting(key, f"{name[:1].upper()}{name[1:]} controller", bool, True)
          for _t, key, name in LIMPET_TYPES),
    )

    def on_load(self, core) -> None:
        super().on_load(core)
        self._lock = threading.Lock()
        self._scans: dict[str, dict] = {}       # BodyName → Scan flags, this system
        self._system = ""
        self._run: dict | None = None           # the sample run in progress
        self._run_thread: threading.Thread | None = None
        self._target_seq = 0

    # ── Events ───────────────────────────────────────────────────────────────

    def on_event(self, event: dict, state) -> None:
        ev = event.get("event")
        try:
            match ev:
                case "FSDTarget":
                    self._on_target(event, state)
                case "FSDJump" | "CarrierJump" | "Location":
                    self._scans.clear()
                    self._system = str(event.get("StarSystem") or "")
                case "Scan":
                    self._on_scan(event, state)
                case "FSSAllBodiesFound":
                    self._on_all_found(event, state)
                case "SAAScanComplete":
                    self._on_mapped(event, state)
                case "SAASignalsFound":
                    self._on_bio_signals(event, state)
                case "Touchdown":
                    self._on_touchdown(event, state)
                case "Disembark":
                    self._on_disembark(event, state)
                case "ScanOrganic":
                    self._on_sample(event, state)
                case "SupercruiseEntry" | "LeaveBody":
                    self._on_leaving(ev, event, state)
                case "Undocked":
                    self._on_undocked(event, state)
                case "Died" | "Resurrect":
                    self._stop_run()
        except Exception as exc:
            from core import debug as _dbg
            _dbg.log(f"  [Callouts] {ev}: {type(exc).__name__}: {exc}")

    def _quiet(self, state) -> bool:
        return bool(getattr(state, "in_preload", False))

    # ── Targeting ────────────────────────────────────────────────────────────

    def _on_target(self, event: dict, state) -> None:
        if self._quiet(state) or not self.settings().get("TargetSound", True):
            return
        address = event.get("SystemAddress")
        if not address:
            return
        self._target_seq += 1
        seq = self._target_seq
        threading.Thread(target=self._target_worker, args=(int(address), seq,
                         str(event.get("Name") or "")), daemon=True,
                         name="callouts-target").start()

    def _target_worker(self, address: int, seq: int, name: str) -> None:
        status = self.target_status(address)
        if status is None or seq != self._target_seq:
            return
        cue = {"new": "target_new", "star": "target_unscanned",
               "partial": "target_unscanned", "done": "target_done"}[status]
        callout.play(self.core, cue)
        if status == "new":
            callout.say(self.core, "ExploTarget", "✨", f"{name or 'Target'}: never reported",
                        sigil="*  EXPL")

    def target_status(self, address: int) -> str | None:
        """"new", "star", "partial" or "done" for a system, from the last
        Nearby search or Spansh; None when Spansh cannot be reached."""
        finder = self.core._plugins.get("finder")
        known = getattr(finder, "known_status", {}) if finder is not None else {}
        if address in known:
            return known[address]
        sp = self.core._plugins.get("spansh")
        if sp is None:
            return None
        try:
            found = sp.systems_by_id64([address])
        except Exception:
            return None
        if found is None:
            return None
        rec = found.get(address)
        if rec is None:
            return "new"
        from core.survey import system_status
        return system_status(rec)

    # ── Firsts watch ─────────────────────────────────────────────────────────

    def _on_scan(self, event: dict, state) -> None:
        body = str(event.get("BodyName") or "")
        if not body or event.get("ScanType") == "NavBeaconDetail":
            return
        self._scans[body] = {
            "was_discovered": bool(event.get("WasDiscovered")),
            "was_mapped": bool(event.get("WasMapped")),
            "was_footfalled": event.get("WasFootfalled"),
            "landable": bool(event.get("Landable")),
            "star": bool(event.get("StarType")),
            "distance": event.get("DistanceFromArrivalLS"),
        }
        if self._quiet(state) or not self.settings().get("FirstsWatch", True):
            return
        # The arrival star's scan says whether anyone has been here before.
        if (event.get("StarType") and not event.get("WasDiscovered")
                and float(event.get("DistanceFromArrivalLS") or 0) == 0):
            callout.say(self.core, "FirstsWatch", "✨",
                        f"{self._system or body}: undiscovered system",
                        sigil="*  EXPL", sound="found")

    def _on_all_found(self, event: dict, state) -> None:
        if self._quiet(state) or not self.settings().get("FirstsWatch", True):
            return
        fresh = [b for b, s in self._scans.items() if not s["was_discovered"]]
        if fresh and len(fresh) < len(self._scans):
            callout.say(self.core, "FirstsWatch", "✨",
                        f"{len(fresh)} of {len(self._scans)} bodies scanned here were undiscovered",
                        sigil="*  EXPL")

    def _on_mapped(self, event: dict, state) -> None:
        body = str(event.get("BodyName") or "")
        s = self._scans.get(body)
        if self._quiet(state) or not s or not self.settings().get("FirstsWatch", True):
            return
        if not s["was_mapped"]:
            callout.say(self.core, "FirstsWatch", "🗺", f"{body}: first to map it",
                        sigil="*  EXPL", sound="found")

    def _on_touchdown(self, event: dict, state) -> None:
        body = str(event.get("Body") or "")
        s = self._scans.get(body)
        if (self._quiet(state) or not s or not event.get("PlayerControlled", True)
                or not self.settings().get("FirstsWatch", True)):
            return
        if s["was_footfalled"] is False:
            callout.say(self.core, "FirstsWatch", "👣",
                        f"{body}: no one has set foot here — step out for first footfall",
                        sigil="*  EXPL", sound="attention")

    def _on_disembark(self, event: dict, state) -> None:
        body = str(event.get("Body") or "")
        s = self._scans.get(body)
        if (self._quiet(state) or not s or not event.get("OnPlanet")
                or not self.settings().get("FirstsWatch", True)):
            return
        if s["was_footfalled"] is False:
            s["was_footfalled"] = True
            callout.say(self.core, "FirstsWatch", "👣", f"{body}: first footfall",
                        sigil="*  EXPL", sound="found")

    # ── Exobiology ───────────────────────────────────────────────────────────

    def _on_bio_signals(self, event: dict, state) -> None:
        genera = [str(g.get("Genus_Localised") or g.get("Genus") or "")
                  for g in event.get("Genuses") or []]
        genera = [g for g in genera if g]
        if not genera or self._quiet(state) or not self.settings().get("CodexCallout", True):
            return
        new = self.codex_new(genera, event.get("SystemAddress"),
                             getattr(state, "pilot_star_pos", None))
        if new:
            region = new.pop()
            callout.say(self.core, "ExobioCallout", "📖",
                        f"{event.get('BodyName') or 'Here'}: {', '.join(new)} "
                        f"new to your codex in {region}",
                        sigil="*  BIO", sound="found")

    def codex_new(self, genera: list[str], address, star_pos) -> list[str]:
        """The genera not in the commander's codex for the region, with the
        region's name last; [] when nothing is new or the codex is unknown."""
        from core.bodies_db import get_db
        from core.region import region_for
        reg = region_for(address, star_pos)
        cid = self.core.plugin_call("explo_sync", "current_commander_id")
        if not reg or not cid:
            return []
        db = get_db()
        if not db.codex_size(cid):
            return []
        have = db.codex_names(cid, reg[0])
        new = [g for g in genera if not any(n == g or n.startswith(g + " ") for n in have)]
        return new + [reg[1]] if new else []

    def _on_sample(self, event: dict, state) -> None:
        from core import exobio_data as B
        kind = event.get("ScanType")
        species = str(event.get("Species_Localised") or event.get("Species") or "")
        body = str(getattr(state, "current_body_name", "") or getattr(state, "pilot_body", "") or "")
        lat, lon = getattr(state, "surface_latitude", None), getattr(state, "surface_longitude", None)
        with self._lock:
            run = self._run
            if kind == "Analyse" or not species:
                self._run = None
                return
            if run is None or run["species"] != species or kind == "Log":
                run = self._run = {"species": species, "body": body, "samples": [],
                                   "clonal": B.clonal_distance(species), "clear": False}
            run["stage"] = 1 if kind == "Log" else 2
            run["clear"] = False
            if lat is not None and lon is not None:
                run["samples"].append((float(lat), float(lon)))
        if not self._quiet(state) and self.settings().get("SafeToSample", True):
            self._start_run_watch()

    def _stop_run(self) -> None:
        with self._lock:
            self._run = None

    def _start_run_watch(self) -> None:
        if self._run_thread is not None and self._run_thread.is_alive():
            return
        self._run_thread = threading.Thread(target=self._run_watch, daemon=True,
                                            name="callouts-sample")
        self._run_thread.start()

    def _run_watch(self) -> None:
        from core import geo
        s = self.core.state
        while True:
            time.sleep(_SAMPLE_POLL_S)
            with self._lock:
                run = self._run
                if run is None:
                    return
                lat, lon = s.surface_latitude, s.surface_longitude
                radius = s.planet_radius
                if lat is None or lon is None or not radius or not run["samples"]:
                    continue
                near = geo.nearest_waypoint(float(lat), float(lon), float(radius), run["samples"])
                if near is None:
                    continue
                clear = near["distance"] >= run["clonal"]
                changed = clear != run["clear"]
                run["clear"] = clear
                species, done = run["species"], run.get("stage", 1)
            if changed and clear:
                callout.say(self.core, "ExobioCallout", "🧬",
                            f"Clear of earlier samples — {species} sample {done + 1}/3 here",
                            sigil="*  BIO", sound="clear")

    def _on_leaving(self, ev: str, event: dict, state) -> None:
        with self._lock:
            run = dict(self._run) if self._run else None
        if run is None:
            return
        if ev == "LeaveBody":
            # Gone from the body: the game has dropped the run.
            self._stop_run()
            return
        # Lifting off between sample sites is how a run is flown; only
        # heading for supercruise, which takes the ship off the body, loses it.
        if ev != "SupercruiseEntry":
            return
        if self._quiet(state) or not self.settings().get("UnfinishedRun", True):
            return
        left = 3 - int(run.get("stage", 1))
        text = (f"{run['species']}: {left} sample{'s' if left != 1 else ''} short — "
                "leaving the body loses the run")
        callout.say(self.core, "ExobioWarning", "🧬", text, sigil="!  BIO",
                    sound="warning", alert=True, urgent=True)

    # ── Limpets ──────────────────────────────────────────────────────────────

    def _on_undocked(self, event: dict, state) -> None:
        cfg = self.settings()
        if self._quiet(state) or not cfg.get("LimpetReminder", True):
            return
        if getattr(state, "vessel_mode", "ship") not in ("ship", "", None):
            return
        # Any controller fitted whose type is switched on; a type this table
        # does not know (one added to the game later) counts as on.
        controllers = [c for c in getattr(state, "ship_limpet_controllers", []) or []
                       if cfg.get(_LIMPET_KEYS.get(c, ""), True)]
        if not controllers or not int(getattr(state, "cargo_capacity", 0) or 0):
            return
        items = getattr(state, "cargo_items", {}) or {}
        drones = int((items.get("drones") or {}).get("count", 0) or 0)
        ship = getattr(state, "ship_id", None)
        warned = self.__dict__.setdefault("_limpets_warned", set())
        if drones > 0:
            warned.discard(ship)
            return
        # Once per ship until it next leaves with limpets: a mining ship sent
        # hauling empty on purpose is reminded once, not at every station.
        if ship in warned:
            return
        warned.add(ship)
        names = ", ".join(_LIMPET_NAMES.get(c, c) for c in controllers)
        callout.say(self.core, "MiningWarning", "🛸",
                    f"No limpets aboard — {names} controller{'s' if len(controllers) > 1 else ''} fitted",
                    sigil="!  SHIP", sound="warning", alert=True)
