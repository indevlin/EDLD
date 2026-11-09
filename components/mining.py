"""components/mining.py — Mining session tracking.

Income from selling mined cargo is tracked by the trade component.

Tab title: Mining
"""

import time
import re
from collections import deque

from core.plugin_loader import BasePlugin
from core.activity import ActivityProviderMixin
from core.emit import fmt_credits
from core import callout

#: Refining rate for "full in", over this many seconds of recent refines.
_FILL_WINDOW = 600
#: "Nearly full" at this share of the hold.
_NEARLY_FULL = 0.9

# Rolling window for RPM calculation (seconds)
_RPM_WINDOW = 10


def _canonicalise(raw: str) -> str:
    """Strip $..._name; localization wrapper and lowercase."""
    s = (raw or "").strip().lower()
    if s.startswith("$") and s.endswith(";"):
        inner = s[1:-1]
        if inner.endswith("_name"):
            s = inner[:-5]
        else:
            s = inner
    return s


def _mineral_key(name: str) -> str:
    """One spelling for a mineral however the journal writes it:
    "LowTemperatureDiamond", "Low Temperature Diamonds", "$tritium_name;"."""
    return re.sub(r"[^a-z]", "", _canonicalise(name)).rstrip("s")


def _content_label(raw: str) -> str:
    """Return High / Medium / Low from the Content field."""
    s = (raw or "").lower()
    if "high"   in s: return "High"
    if "medium" in s: return "Medium"
    if "low"    in s: return "Low"
    return "Unknown"


#: Surface scans return two unrelated families of signal under one event.
#: Bare commodity names ("Painite", "LowTemperatureDiamond") are mining
#: hotspots.  Anything spelled as a ``$SAA_SignalType_*`` token is a surface
#: point-of-interest category — Human settlements, Biological and Geological
#: sites — and ``$PlanetaryMiningLocation_Name`` is a marker for the body
#: itself, not a commodity.  Counting those as hotspots put rows like
#: "Human  3 hotspots" in the mining panel.
_NON_HOTSPOT_PREFIXES = ("$saa_signaltype_", "$planetarymininglocation")


def _hotspot_name(signal: dict) -> str:
    """Return the commodity name for a hotspot signal, or "" if it is not one.
    """
    raw = str(signal.get("Type", "") or "").strip()
    if not raw:
        return ""
    if raw.lower().startswith(_NON_HOTSPOT_PREFIXES):
        return ""
    localised = str(signal.get("Type_Localised", "") or "").strip()
    if localised:
        return localised
    # "LowTemperatureDiamond" -> "Low Temperature Diamond"
    spaced = re.sub(r"(?<=[a-z])(?=[A-Z])", " ", raw)
    return spaced[:1].upper() + spaced[1:]


def _ring_hotspot_name(event: dict) -> str:
    """Commodity name from a SupercruiseDestinationDrop onto a ring hotspot.

    Returns "" for any other drop destination.
    """
    raw = str(event.get("Type", "") or "")
    if "RingHotspot" not in raw:
        return ""
    localised = str(event.get("Type_Localised", "") or "").strip()
    if localised:
        return re.sub(r"\s*Hotspot$", "", localised)
    match = re.search(r"\$([A-Za-z]+)_name;", raw)
    if not match:
        return ""
    spaced = re.sub(r"(?<=[a-z])(?=[A-Z])", " ", match.group(1))
    return spaced[:1].upper() + spaced[1:]


def _ring_class(raw: str) -> str:
    """Turn eRingClass_Metalic into "Metallic"."""
    key = (raw or "").replace("eRingClass_", "").strip().lower()
    return {
        "metalic":   "Metallic",
        "metallic":  "Metallic",
        "metalrich": "Metal-rich",
        "rocky":     "Rocky",
        "icy":       "Icy",
    }.get(key, key.title())


def _prospect_key(materials: list[dict]) -> tuple:
    """Deterministic key for a set of prospected materials."""
    return tuple(sorted(
        (_canonicalise(m.get("Name", "")), round(m.get("Proportion", 0.0), 1))
        for m in materials
    ))


class ActivityMiningPlugin(BasePlugin, ActivityProviderMixin):
    PLUGIN_NAME         = "mining"
    PLUGIN_DISPLAY      = "Mining Activity"
    PLUGIN_VERSION      = "2.0.0"
    PLUGIN_DESCRIPTION  = "Tracks prospecting, refined tonnage, yield quality, and limpet efficiency."
    ACTIVITY_TAB_TITLE  = "Mining"

    SUBSCRIBED_EVENTS = [
        "MiningRefined",
        "ProspectedAsteroid",
        "LaunchDrone",
        # Limpet stock lives in Cargo as the "drones" commodity — the only
        # place the journal reports it.  Running dry ends a session, so the
        # remaining count is the single most actionable number here.
        "Cargo",
        "MaterialCollected",
        "Scan",
        "SAASignalsFound",
        # Names the specific ring hotspot dropped into, which overlapping
        # hotspots make ambiguous from the ring's signal list alone.
        "SupercruiseDestinationDrop",
        # Dropping into a ring: the ring callout.
        "SupercruiseExit",
    ]

    def on_load(self, core) -> None:
        super().on_load(core)
        core.register_session_provider(self)
        self._reset_counters()
        # What this commander has found in each type of ring, kept across
        # sessions: {ring type: {"rocks": n, "laser": {mineral: [rocks, sum %]},
        # "cores": {mineral: n}}}. Laser yields from each prospected rock's
        # materials, cores from its motherlode.
        try:
            self.ring_stats: dict = self.storage.read_json("ringstats") or {}
        except Exception:
            self.ring_stats = {}
        self._ring_stats_dirty = 0

    def _reset_counters(self) -> None:
        self.tonnes_refined:        float = 0.0
        self.asteroids_prospected:  int   = 0
        self.limpets_collection:    int   = 0
        self.limpets_prospector:    int   = 0
        self.duplicates:            int   = 0
        self.already_mined:         int   = 0
        self.session_start_time           = None

        # Content distribution: High / Medium / Low / Unknown → count
        self.content_counts: dict[str, int] = {}

        # Per-commodity yield % samples from ProspectedAsteroid
        # key: canonical commodity name, value: list of float proportions
        self.yield_samples: dict[str, list[float]] = {}

        # Per-commodity refined tons (for tab breakdown)
        self.material_tally: dict[str, float] = {}

        # Duplicate detection: set of prospect keys seen this session
        self._seen_keys: set[tuple] = set()
        # The same, for the callouts and hit rates: a rock prospected twice
        # is one rock.
        self._seen_before: set[tuple] = set()

        # Rolling window of MiningRefined timestamps for RPM
        self._recent_refines: deque = deque()
        self.max_rpm: float = 0.0

        # Limpet stock, observed from Cargo events
        self.limpets_remaining: int | None = None
        self.limpets_start:     int | None = None

        # Raw materials collected while mining (MaterialCollected)
        self.materials_collected: dict[str, int] = {}

        self.mining_body:   str = ""

        # Every body scanned this session that can be mined, keyed by body
        # name.  Rings and planetary surfaces are different kinds of site and
        # are listed separately; see _site() for the record shape.
        self.mining_sites: dict[str, dict] = {}

        # The specific ring hotspot currently dropped into, when the commander
        # supercruise-drops onto one.  A ring can carry several overlapping
        # hotspots, so knowing which one is being worked is worth more than
        # knowing they exist.
        self.active_hotspot: str = ""
        self.ring_type:     str = ""
        self.reserve_level: str = ""
        self.hotspots: dict[str, int] = {}

        # Hit rate per hotspot: (body, mineral) → [rocks prospected there,
        # rocks holding the mineral]. What says whether a hotspot is a good one.
        self.hotspot_hits: dict[tuple[str, str], list[int]] = {}
        # Refine times for the "full in" estimate, and the hold warnings given.
        self._fill_times: deque = deque()
        self._hold_said = ""

    def on_session_reset(self) -> None:
        self._reset_counters()

    def _update_rpm(self) -> float:
        """Recompute RPM from the rolling window; prune stale entries."""
        now    = time.monotonic()
        cutoff = now - _RPM_WINDOW
        while self._recent_refines and self._recent_refines[0] < cutoff:
            self._recent_refines.popleft()
        count = len(self._recent_refines)
        rpm   = (count * 60.0) / _RPM_WINDOW if _RPM_WINDOW else 0.0
        if rpm > self.max_rpm:
            self.max_rpm = rpm
        return rpm

    def _tph(self) -> float | None:
        """Tons per session hour, or None if insufficient data.

        Divides by the session clock, like every other rate in the summary;
        see ActivityProviderMixin._duration_seconds.
        """
        if self.session_start_time is None or self.tonnes_refined <= 0:
            return None
        state = self.core.state
        if not state.event_time:
            return None
        clock = (getattr(self.core, "_plugins", None) or {}).get("session_stats")
        elapsed = 0.0
        if clock is not None:
            try:
                elapsed = float(clock.session_duration_seconds() or 0.0)
            except Exception:
                elapsed = 0.0
        if elapsed <= 0:
            elapsed = (state.event_time - self.session_start_time).total_seconds()
        if elapsed < 60:
            return None
        return self.tonnes_refined / (elapsed / 3600.0)

    def on_event(self, event: dict, state) -> None:
        ev      = event.get("event")
        logtime = event.get("_logtime")
        gq      = self.core.gui_queue

        match ev:

            case "MiningRefined":
                if self.session_start_time is None:
                    self.session_start_time = logtime
                raw_name   = event.get("Type_Localised") or event.get("Type", "Unknown")
                canon_name = _canonicalise(event.get("Type", ""))
                display    = raw_name.strip() if raw_name.strip() else canon_name
                self.tonnes_refined += 1.0
                self.material_tally[display] = self.material_tally.get(display, 0.0) + 1.0
                self._recent_refines.append(time.monotonic())
                self._update_rpm()
                self._fill_times.append(time.monotonic())
                self._hold_callout(state)
                if gq: gq.put(("stats_update", None))

            case "ProspectedAsteroid":
                if self.session_start_time is None:
                    self.session_start_time = logtime

                self.asteroids_prospected += 1

                # Content distribution
                content = _content_label(event.get("Content_Localised") or event.get("Content", ""))
                self.content_counts[content] = self.content_counts.get(content, 0) + 1

                # Already-mined detection (Remaining < 100 %)
                remaining = event.get("Remaining", 100.0)
                if remaining is not None and remaining < 99.9:
                    self.already_mined += 1

                # Duplicate detection via material composition hash
                materials = event.get("Materials", [])
                key = _prospect_key(materials)
                if key in self._seen_keys:
                    self.duplicates += 1
                else:
                    self._seen_keys.add(key)

                # Accumulate yield % samples per commodity
                for mat in materials:
                    name = (mat.get("Name_Localised") or mat.get("Name", "")).strip()
                    pct  = float(mat.get("Proportion", 0.0))
                    if name and pct > 0:
                        if name not in self.yield_samples:
                            self.yield_samples[name] = []
                        self.yield_samples[name].append(pct)

                fresh = key not in self._seen_before and (remaining is None or remaining >= 99.9)
                self._seen_before.add(key)
                if fresh:
                    self._note_hotspot_hits(materials)
                    self._note_ring_stats(event, materials, state)
                    self._prospect_callout(event, materials, state)

            case "LaunchDrone":
                dtype = event.get("Type", "")
                if dtype == "Collection":
                    self.limpets_collection += 1
                elif dtype == "Prospector":
                    self.limpets_prospector += 1

            case "Cargo":
                # Limpets are carried as the "drones" commodity.  A Cargo
                # event with no Inventory is the summary form written when
                # the full list went to Cargo.json; ignore those rather than
                # reading them as "zero limpets".
                inventory = event.get("Inventory")
                if not isinstance(inventory, list):
                    return
                drones = 0
                for item in inventory:
                    if _canonicalise(item.get("Name", "")) == "drones":
                        drones = int(item.get("Count", 0) or 0)
                        break
                self.limpets_remaining = drones
                if self.limpets_start is None or drones > self.limpets_start:
                    self.limpets_start = drones
                if gq: gq.put(("stats_update", None))

            case "MaterialCollected":
                name = (event.get("Name_Localised")
                        or event.get("Name", "")).strip()
                if name:
                    count = int(event.get("Count", 1) or 1)
                    self.materials_collected[name] = (
                        self.materials_collected.get(name, 0) + count)

            case "SupercruiseExit":
                if event.get("BodyType") == "PlanetaryRing":
                    ring = str(event.get("Body") or "")
                    site = self.mining_sites.get(ring) or {}
                    self.mining_body = ring
                    if site.get("ring_type"):
                        self.ring_type = site["ring_type"]
                    if site.get("reserves"):
                        self.reserve_level = site["reserves"]
                    if site.get("hotspots"):
                        self.hotspots = dict(site["hotspots"])
                    self._ring_callout(ring, site, state)

            case "SupercruiseDestinationDrop":
                # "$SAA_RingHotspot:#type=$painite_name;;" names the hotspot
                # actually dropped into, which overlapping hotspots make
                # ambiguous from the ring's signal list alone.
                self.active_hotspot = _ring_hotspot_name(event)

            case "Scan":
                # A body's Scan carries its reserve level, and its Rings list
                # names and classes each ring hanging off it.  Both the body
                # and its rings are recorded, so the site list can show a
                # planetary surface and its rings as separate entries.
                reserve = (event.get("ReserveLevel") or "").replace(
                    "Resources", "").strip()
                scanned = str(event.get("BodyName", "") or "")
                if reserve:
                    self.reserve_level = reserve
                    if scanned:
                        self._site(scanned)["reserves"] = reserve

                for ring in (event.get("Rings") or []):
                    ring_name = str(ring.get("Name", "") or "")
                    if not ring_name:
                        continue
                    entry = self._site(ring_name)
                    entry["kind"] = "ring"
                    entry["ring_type"] = _ring_class(ring.get("RingClass", ""))
                    if reserve:
                        entry["reserves"] = reserve

                body = str(getattr(state, "pilot_body", "") or "")
                for ring in (event.get("Rings") or []):
                    if str(ring.get("Name", "")) == body:
                        self.mining_body = body
                        self.ring_type = _ring_class(ring.get("RingClass", ""))
                        break

            case "SAASignalsFound":
                body = str(event.get("BodyName", "") or "")
                if body:
                    self.mining_body = body
                entry = self._site(body) if body else None

                for sig in (event.get("Signals") or []):
                    count = int(sig.get("Count", 0) or 0)
                    raw = str(sig.get("Type", "") or "")

                    if raw.lower().startswith("$planetarymininglocation"):
                        # The journal reports how many surface sites the body
                        # has, and nothing about what any individual one
                        # holds — that detail is only on the in-game surface
                        # map.  The count is still the useful signal.
                        if entry is not None:
                            entry["kind"] = "planet"
                            entry["planetary_sites"] = count
                        continue

                    name = _hotspot_name(sig)
                    if not name:
                        continue          # surface POI category, not a commodity
                    self.hotspots[name] = count
                    if entry is not None:
                        entry.setdefault("kind", "ring")
                        entry["hotspots"][name] = count

    # ── Callouts ──────────────────────────────────────────────────────────────

    def _callout_settings(self) -> dict:
        """The Callouts component's settings. With that component turned off
        every switch reads off, so the mining callouts go quiet with it."""
        p = (getattr(self.core, "_plugins", None) or {}).get("callouts")
        if p is None:
            return {"Motherlodes": False, "ProspectorMinerals": "", "HoldWarning": False,
                    "RingCallout": False}
        try:
            return p.settings()
        except Exception:
            return {}

    def _prospect_callout(self, event: dict, materials: list, state) -> None:
        if getattr(state, "in_preload", False):
            return
        cfg = self._callout_settings()
        content = _content_label(event.get("Content_Localised") or event.get("Content", ""))
        mother = (event.get("MotherlodeMaterial_Localised")
                  or event.get("MotherlodeMaterial") or "").strip()
        if mother and cfg.get("Motherlodes", True):
            callout.say(self.core, "MiningCallout", "💎",
                        f"Motherlode: {mother} — {content.lower()} content",
                        sigil="*  MINE", sound="found")
            return
        watch = {_mineral_key(w) for w in str(cfg.get("ProspectorMinerals", "") or "").split(",")
                 if w.strip()}
        least = float(cfg.get("ProspectorPercent", 20) or 0)
        hits = []
        for mat in materials:
            name = (mat.get("Name_Localised") or mat.get("Name", "")).strip()
            pct = float(mat.get("Proportion", 0.0) or 0)
            if name and pct >= least and (_mineral_key(name) in watch
                                          or _mineral_key(mat.get("Name", "")) in watch):
                hits.append(f"{name[:1].upper()}{name[1:]} {pct:.0f}%")
        if hits:
            callout.say(self.core, "MiningCallout", "⛏", " · ".join(hits),
                        sigil="*  MINE", sound="found")

    def _note_hotspot_hits(self, materials: list) -> None:
        site = self.mining_sites.get(self.mining_body) or {}
        spots = site.get("hotspots") or self.hotspots
        if not self.mining_body or not spots:
            return
        held = {_mineral_key(m.get("Name", "")) for m in materials}
        held |= {_mineral_key(m.get("Name_Localised") or "") for m in materials}
        for mineral in spots:
            rec = self.hotspot_hits.setdefault((self.mining_body, mineral), [0, 0])
            rec[0] += 1
            if _mineral_key(mineral) in held:
                rec[1] += 1

    def _note_ring_stats(self, event: dict, materials: list, state) -> None:
        if getattr(state, "in_preload", False) or not self.ring_type:
            return
        rec = self.ring_stats.setdefault(self.ring_type, {"rocks": 0, "laser": {}, "cores": {}})
        rec["rocks"] += 1
        for mat in materials:
            name = (mat.get("Name_Localised") or mat.get("Name", "")).strip()
            pct = float(mat.get("Proportion", 0.0) or 0)
            if name and pct > 0:
                m = rec["laser"].setdefault(name, [0, 0.0])
                m[0] += 1
                m[1] = round(m[1] + pct, 2)
        mother = (event.get("MotherlodeMaterial_Localised")
                  or event.get("MotherlodeMaterial") or "").strip()
        if mother:
            rec["cores"][mother] = rec["cores"].get(mother, 0) + 1
        self._ring_stats_dirty += 1
        if self._ring_stats_dirty >= 10 or mother:
            self._save_ring_stats()

    def _save_ring_stats(self) -> None:
        try:
            self.storage.write_json(self.ring_stats, "ringstats")
            self._ring_stats_dirty = 0
        except Exception:
            pass

    def on_unload(self) -> None:
        if getattr(self, "_ring_stats_dirty", 0):
            self._save_ring_stats()

    def ring_yields(self, ring_type: str, top: int = 4) -> tuple[list, list, int]:
        """This commander's laser yields in rings of a type — (mineral, share
        of rocks %, mean %) best first — its cores, and rocks prospected."""
        rec = self.ring_stats.get(ring_type) or {}
        rocks = int(rec.get("rocks") or 0)
        if not rocks:
            return [], [], 0
        laser = sorted(((n, v[0] / rocks * 100, v[1] / v[0]) for n, v in rec["laser"].items() if v[0]),
                       key=lambda t: -(t[1] * t[2]))[:top]
        cores = sorted(rec.get("cores", {}).items(), key=lambda kv: -kv[1])
        return laser, cores, rocks

    def _ring_callout(self, ring: str, site: dict, state) -> None:
        if getattr(state, "in_preload", False) or not self._callout_settings().get("RingCallout", True):
            return
        kind = site.get("ring_type") or ""
        parts = [kind or "ring type not scanned", site.get("reserves") or ""]
        spots = site.get("hotspots") or {}
        if spots:
            parts.append("hotspots " + ", ".join(
                f"{n} ×{c}" if c > 1 else n for n, c in sorted(spots.items(), key=lambda kv: -kv[1])))
        text = f"{ring}: " + " · ".join(p for p in parts if p)
        laser, cores, rocks = self.ring_yields(kind) if kind else ([], [], 0)
        if laser:
            text += (f" — your {kind.lower()} rings ({rocks} rocks): "
                     + ", ".join(f"{n} {share:.0f}% of rocks at {mean:.0f}%" for n, share, mean in laser))
        if cores:
            text += "; cores " + ", ".join(f"{n} ×{c}" for n, c in cores[:3])
        callout.say(self.core, "MiningCallout", "🪐", text, sigil="*  MINE")

    def fill_estimate(self) -> tuple[float, float] | None:
        """(tons a minute lately, minutes to a full hold), or None."""
        fill = self.cargo_fill()
        now = time.monotonic()
        while self._fill_times and self._fill_times[0] < now - _FILL_WINDOW:
            self._fill_times.popleft()
        if not fill or len(self._fill_times) < 3:
            return None
        span = max(now - self._fill_times[0], 60.0)
        rate = len(self._fill_times) / (span / 60.0)
        carried, cap = fill
        return rate, max(cap - carried, 0) / rate if rate > 0 else float("inf")

    def _hold_callout(self, state) -> None:
        if getattr(state, "in_preload", False) or not self._callout_settings().get("HoldWarning", True):
            return
        fill = self.cargo_fill()
        if not fill:
            return
        carried, cap = fill
        # MiningRefined comes before the Cargo event that counts the ton.
        carried = min(carried + 1, cap)
        if carried >= cap:
            if self._hold_said != "full":
                self._hold_said = "full"
                callout.say(self.core, "MiningWarning", "📦", f"Hold full — {cap} t",
                            sigil="!  MINE", sound="attention", alert=True)
        elif carried >= cap * _NEARLY_FULL:
            if not self._hold_said:
                self._hold_said = "nearly"
                est = self.fill_estimate()
                when = ""
                if est and est[1] < 1:
                    when = ", full in under a minute"
                elif est and est[1] < 600:
                    when = f", full in about {est[1]:.0f} min"
                callout.say(self.core, "MiningWarning", "📦",
                            f"Hold {carried / cap * 100:.0f}% full{when}",
                            sigil="!  MINE", sound="low")
        else:
            self._hold_said = ""

    # ── ActivityProviderMixin ─────────────────────────────────────────────────

    def has_activity(self) -> bool:
        return self.tonnes_refined > 0 or self.asteroids_prospected > 0

    def _refined_value_est(self) -> int:
        mean_prices = getattr(self.core.state, "cargo_mean_prices", {}) or {}
        total = 0
        for material, tonnes in self.material_tally.items():
            price = mean_prices.get(material.lower(), 0)
            total += price * tonnes
        return total

    def _site(self, body: str) -> dict:
        """Get or create the record for a mineable body."""
        return self.mining_sites.setdefault(body, {
            "kind": "",              # "ring" | "planet"
            "hotspots": {},          # commodity -> hotspot count (rings)
            "planetary_sites": 0,    # surface site count (planets)
            "reserves": "",
            "ring_type": "",
        })

    def sites_by_kind(self) -> tuple[list, list]:
        """Return (ring sites, planetary sites) as (body, record) pairs."""
        rings, planets = [], []
        for body, rec in sorted(self.mining_sites.items()):
            if rec.get("kind") == "planet" and rec.get("planetary_sites"):
                planets.append((body, rec))
            elif rec.get("hotspots"):
                rings.append((body, rec))
        return rings, planets

    def ring_context(self) -> str:
        """One-line description of where we're mining, or "" if unknown."""
        parts = [p for p in (self.mining_body, self.reserve_level,
                             self.ring_type) if p]
        if self.hotspots:
            top = sorted(self.hotspots.items(), key=lambda kv: -kv[1])
            parts.append(", ".join(
                f"{name} x{n}" if n > 1 else name for name, n in top[:3]))
        return " · ".join(parts)

    def cargo_fill(self) -> tuple[int, int] | None:
        """(tons carried, capacity), or None when capacity is unknown."""
        state = self.core.state
        cap = int(getattr(state, "cargo_capacity", 0) or 0)
        if cap <= 0:
            return None
        items = getattr(state, "cargo_items", {}) or {}
        carried = sum(int((v or {}).get("count", 0) or 0) for v in items.values())
        return carried, cap

    def get_summary_rows(self) -> list[dict]:
        rows = []
        tph  = self._tph()
        if self.tonnes_refined > 0:
            value_est = self._refined_value_est()
            rate_parts = []
            if tph is not None:
                rate_parts.append(f"{tph:.1f} t/hr")
            if value_est:
                rate_parts.append(f"{fmt_credits(value_est)} est.")
            rows.append({
                "label": "Tons refined",
                "value": f"{self.tonnes_refined:.0f} t",
                "rate":  "  ".join(rate_parts) if rate_parts else None,
            })
        if self.asteroids_prospected > 0:
            rpm = self._update_rpm()
            rpm_str = f"{rpm:.0f} RPM" if rpm > 0 else (f"max {self.max_rpm:.0f} RPM" if self.max_rpm > 0 else None)
            # Hit rate is what tells you whether the ring is worth staying in.
            hit = None
            high = self.content_counts.get("High", 0)
            if self.asteroids_prospected:
                hit = f"{high / self.asteroids_prospected * 100:.0f}% high"
            rows.append({
                "label": "Prospected",
                "value": str(self.asteroids_prospected),
                "rate":  "  ".join(x for x in (rpm_str, hit) if x) or None,
            })

        # Cargo fill — the thing that decides when the run ends.
        fill = self.cargo_fill()
        if fill and self.tonnes_refined > 0:
            carried, cap = fill
            est = self.fill_estimate()
            rate = f"{carried / cap * 100:.0f}% full" if cap else None
            if est and carried < cap and est[1] < 600:
                when = "full in under a minute" if est[1] < 1 else f"full in {est[1]:.0f} min"
                rate = f"{rate} · {when}" if rate else when
            rows.append({
                "label": "Cargo",
                "value": f"{carried} / {cap} t",
                "rate":  rate,
            })

        # Limpet stock and yield distribution are states of the hold and of
        # the ring, not things the session produced.  They stay on the Mining
        # tab, where the question is "how is this run going".

        # Where this was mined.  Without it the numbers above have no
        # context — 180 t is excellent in a depleted ring and mediocre in a
        # pristine one.
        site = self.ring_context()
        if site and rows:
            rows.append({"label": "Site", "value": site, "rate": None})
        return rows

    def get_session_rows(self) -> list[dict]:
        """What this session produced, for the Session view.

        Deliberately narrower than the Mining tab.  Where the ore came from —
        the body, its reserve level, its hotspots — and a line per commodity
        describe the *place*, not the session, and belong in the window that
        is about the place.  Cargo currently held is a state of the hold, not
        something the session produced, and it is already on the Ship window.
        """
        rows: list[dict] = []
        tph = self._tph()
        if self.tonnes_refined > 0:
            value_est = self._refined_value_est()
            rate_parts = []
            if tph is not None:
                rate_parts.append(f"{tph:.1f} t/hr")
            if value_est:
                rate_parts.append(f"{fmt_credits(value_est)} est.")
            rows.append({
                "label": "Refined",
                "value": f"{self.tonnes_refined:,.0f} t",
                "rate":  "  ".join(rate_parts) or None,
            })

        if self.asteroids_prospected > 0:
            high = self.content_counts.get("High", 0)
            rows.append({
                "label": "Prospected",
                "value": str(self.asteroids_prospected),
                "rate":  f"{high / self.asteroids_prospected * 100:.0f}% high",
            })

        return rows

    def get_tab_rows(self) -> list[dict]:
        # The condensed "Ring" row exists for the Discord summary, where
        # there is no room to expand it.  The tab has that room and breaks
        # the same information out in full below, so showing both would just
        # print the ring twice.
        rows = [r for r in self.get_summary_rows() if r["label"] != "Site"]

        # Limpet stock belongs here.
        if self.limpets_remaining is not None and (
                self.limpets_prospector or self.limpets_collection):
            used = None
            if self.limpets_start is not None:
                used = max(self.limpets_start - self.limpets_remaining, 0)
            rows.append({
                "label": "Limpets left",
                "value": str(self.limpets_remaining),
                "rate":  f"{used} used" if used else None,
            })

        # Mining sites, ring and planetary under separate headings.
        rings, planets = self.sites_by_kind()

        if rings:
            rows.append({"label": "─── Ring sites ───", "value": "", "rate": None})
            for body, rec in rings:
                detail = " · ".join(p for p in (rec.get("reserves"),
                                                rec.get("ring_type")) if p)
                marker = "▸ " if body == self.mining_body else "  "
                rows.append({"label": f"{marker}{body}", "value": detail,
                             "rate": None})
                for name, n in sorted(rec["hotspots"].items(), key=lambda kv: -kv[1]):
                    active = "  ◂ here" if name == self.active_hotspot else ""
                    hit = self.hotspot_hits.get((body, name))
                    rows.append({
                        "label": f"    {name}",
                        "value": f"{n} hotspot{'s' if n != 1 else ''}{active}",
                        "rate": (f"in {hit[1]}/{hit[0]} rocks ({hit[1] / hit[0] * 100:.0f}%)"
                                 if hit and hit[0] else None)})

        if planets:
            rows.append({"label": "─── Planetary sites ───", "value": "",
                         "rate": None})
            # The journal reports how many surface sites a body has and
            # nothing about what any one of them holds — that detail is only
            # on the in-game surface map.  Not worth a row saying so: the
            # panel is short on width and a caveat is not information.
            for body, rec in planets:
                marker = "▸ " if body == self.mining_body else "  "
                count = rec.get("planetary_sites", 0)
                rows.append({
                    "label": f"{marker}{body}",
                    "value": f"{count} site{'s' if count != 1 else ''}",
                    "rate": None})
                if rec.get("reserves"):
                    rows.append({"label": "    Reserves",
                                 "value": rec["reserves"], "rate": None})

        # Content distribution
        if self.content_counts:
            parts = []
            for label in ("High", "Medium", "Low", "Unknown"):
                n = self.content_counts.get(label, 0)
                if n:
                    parts.append(f"{label}: {n}")
            if parts:
                rows.append({
                    "label": "Content",
                    "value": "  ".join(parts),
                    "rate":  None,
                })

        # Already-mined and duplicates
        if self.already_mined > 0:
            rows.append({"label": "Already mined", "value": str(self.already_mined), "rate": None})
        if self.duplicates > 0:
            rows.append({"label": "Duplicates",    "value": str(self.duplicates),    "rate": None})

        # Limpets
        if self.limpets_prospector > 0 or self.limpets_collection > 0:
            rows.append({"label": "─── Limpets ───", "value": "", "rate": None})
            if self.limpets_prospector > 0:
                # Prospector efficiency: asteroids per limpet
                eff = (f"{self.asteroids_prospected / self.limpets_prospector:.1f}/limpet"
                       if self.limpets_prospector > 0 and self.asteroids_prospected > 0 else None)
                rows.append({"label": "  Prospector", "value": str(self.limpets_prospector), "rate": eff})
            if self.limpets_collection > 0:
                coll_eff = (f"{self.tonnes_refined / self.limpets_collection:.1f} t/limpet"
                            if self.tonnes_refined > 0 else None)
                rows.append({"label": "  Collection", "value": str(self.limpets_collection), "rate": coll_eff})

        # Per-commodity yield stats
        if self.yield_samples:
            rows.append({"label": "─── Yield % by commodity ───", "value": "", "rate": None})
            for name in sorted(self.yield_samples, key=lambda n: -len(self.yield_samples[n])):
                samples = self.yield_samples[name]
                n_ast   = len(samples)
                mn      = min(samples)
                avg     = sum(samples) / n_ast
                mx      = max(samples)
                pct_ast = (n_ast / self.asteroids_prospected * 100.0) if self.asteroids_prospected else 0.0
                rows.append({
                    "label": f"  {name}",
                    "value": f"{n_ast} ast ({pct_ast:.0f}%)",
                    "rate":  f"{mn:.1f}–{avg:.1f}–{mx:.1f}%",
                })

        # What this commander has found in rings of the type being worked.
        if self.ring_type:
            laser, cores, rocks = self.ring_yields(self.ring_type, top=6)
            if laser:
                rows.append({"label": f"─── Your {self.ring_type.lower()} rings ───",
                             "value": f"{rocks} rocks", "rate": None})
                for n, share, mean in laser:
                    rows.append({"label": f"  {n}", "value": f"{share:.0f}% of rocks",
                                 "rate": f"avg {mean:.0f}%"})
                for n, c in cores[:4]:
                    rows.append({"label": f"  {n} (core)", "value": f"{c} motherlode{'s' if c != 1 else ''}",
                                 "rate": None})

        # Refined material breakdown
        if self.material_tally:
            rows.append({"label": "─── Refined ───", "value": "", "rate": None})
            for mat, count in sorted(self.material_tally.items(), key=lambda x: -x[1]):
                rows.append({"label": f"  {mat}", "value": f"{count:.0f} t", "rate": None})

        # Raw materials picked up alongside the ore.  Not tonnage, but part
        # of what the session produced.
        if self.materials_collected:
            rows.append({"label": "─── Materials ───", "value": "", "rate": None})
            for mat, count in sorted(self.materials_collected.items(),
                                     key=lambda x: -x[1]):
                rows.append({"label": f"  {mat}", "value": str(count), "rate": None})

        return rows
