"""components/navigation.py — route store and clipboard route-follower.

1. **Route store.**  Routes plotted inside EDLD (Spansh neutron, EDSM FSD,
   Spansh fleet carrier) are converted to the game's own ``NavRoute.json``
   shape and persisted to ``<cmdr>/data/navigation.route.json``.  Keeping the
   game's schema means anything that can already read a NavRoute can read
   ours, and the follower below needs exactly one code path for both.

2. **Route follower.**  When enabled, arriving in a system copies the *next*
   system on the route to the clipboard, ready to paste into the galaxy map.
   That is the whole workflow for neutron jumping and carrier hauling, where
   every leg has to be plotted by hand.

Hyperspace awareness
--------------------
``StartJump`` with ``JumpType: "Hyperspace"`` names the system being jumped
to, and once that fires the jump cannot be canceled.  The commander's
effective position is therefore the destination, not the system they are
leaving.  Copy Next uses that so pressing it mid-tunnel gives the system
*after* the one you are arriving at, not the one you are arriving at.

Clearing
--------
"Clear Route" wipes EDLD's stored route and suppresses the current
``NavRoute.json`` by recording a signature of it.  The game's file is left
alone: it is shared state that other software on the machine may be reading,
and the game rewrites it on the next plot anyway.  When NavRoute.json next changes, the signature stops matching
and following resumes automatically.
"""

from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path

from core.plugin_loader import BasePlugin
from core.settings_spec import Heading, Setting, SettingsSpecMixin

#: Journal events that mean "the commander is now somewhere new".
_ARRIVAL_EVENTS = ("FSDJump", "CarrierJump", "Location")


def _utc_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _norm(name) -> str:
    return str(name or "").strip().casefold()


def read_nav_route_file(journal_dir) -> dict | None:
    """Read the game's NavRoute.json, or None if absent/empty/unreadable."""
    try:
        path = Path(journal_dir) / "NavRoute.json"
        if not path.is_file():
            return None
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    if not isinstance(data, dict) or not (data.get("Route") or []):
        return None
    return data


def route_signature(doc: dict | None) -> str:
    """Stable identity for a route document."""
    if not doc:
        return ""
    route = doc.get("Route") or []
    if not route:
        return ""
    first = route[0].get("StarSystem", "")
    last = route[-1].get("StarSystem", "")
    return f"{doc.get('timestamp', '')}|{first}|{last}|{len(route)}"


def spansh_result_to_navroute(result: dict, kind: str, plot: dict | None = None) -> dict | None:
    """Convert an EDLD-plotted route into the game's NavRoute.json shape.

    Handles all three shapes EDLD produces:

      neutron  Spansh /api/route      → system_jumps[], keys system/x/y/z
      fsd      EDSM greedy router     → system_jumps[], keys system/star_pos
      carrier  Spansh fleetcarrier    → jumps[],        keys name/id64/x/y/z
    """
    if not isinstance(result, dict):
        return None
    waypoints = result.get("system_jumps") or result.get("jumps") or []
    if not waypoints:
        return None

    route: list[dict] = []
    for wp in waypoints:
        name = wp.get("system") or wp.get("name") or ""
        if not name:
            continue

        star_pos = wp.get("star_pos")
        if not star_pos:
            x, y, z = wp.get("x"), wp.get("y"), wp.get("z")
            if None not in (x, y, z):
                star_pos = [x, y, z]

        entry: dict = {
            "StarSystem": str(name),
            "SystemAddress": wp.get("id64") or wp.get("system_address") or 0,
            "StarPos": [float(v) for v in star_pos] if star_pos else [0.0, 0.0, 0.0],
            "StarClass": str(wp.get("star_class") or ("N" if wp.get("neutron_star") else "")),
        }

        extra = {k: wp[k] for k in (
            "distance", "distance_jumped", "distance_to_destination",
            "fuel_used", "fuel_in_tank", "must_restock", "restock_amount",
            "tritium_in_market", "has_icy_ring", "is_system_pristine",
            "neutron_star", "must_refuel", "is_supercharged", "jumps",
            "is_scoopable", "must_inject",
            # Survey routes (core/survey.py): what each stop holds.
            "bodies", "trade",
        ) if k in wp}
        if extra:
            entry["EDLD"] = extra
        route.append(entry)

    if not route:
        return None

    return {
        "timestamp": _utc_iso(),
        "event": "NavRoute",
        "Route": route,
        # EDLD provenance — ignored by anything reading this as a NavRoute.
        "EDLDSource": kind,
        # How it was plotted, so it can be plotted again from wherever the
        # commander is after leaving it, or in another ship.
        "EDLDPlot": plot or {},
        "EDLDSurvey": result.get("survey") or "",
    }


class NavigationPlugin(SettingsSpecMixin, BasePlugin):
    PLUGIN_NAME = "navigation"
    PLUGIN_DISPLAY = "Navigation & Route Follower"
    PLUGIN_VERSION = "1.0.0"
    PLUGIN_DESCRIPTION = (
        "Stores routes plotted in EDLD and copies the next system on the "
        "route to the clipboard as you travel."
    )

    SUBSCRIBED_EVENTS = [
        "FSDJump", "CarrierJump", "Location",
        "StartJump", "NavRoute", "NavRouteClear",
        "FSDTarget", "Loadout", "JetConeBoost",
    ]

    SETTINGS_SECTION = "Navigation"
    SETTINGS_TAB = ("pref-tab-routes", "Routes")
    SETTINGS = (
        Heading("Following a route",
                "Levels for these messages are under Notifications: Route warnings "
                "and Survey arrivals."),
        Setting("AutoReplot", "Re-plot after leaving the route or changing ship", bool, True,
                help="FSD, exact and neutron routes are plotted again from where you are."),
        Setting("WarnWrongTarget", "Warn when the system targeted is not the next on the route",
                bool, True),
        Setting("CheckPermits", "Check plotted routes for permit-locked systems", bool, True),
        Setting("SurveyArrival", "Say what is left to do on arriving at a survey stop", bool, True),
    )

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    def on_load(self, core) -> None:
        super().on_load(core)
        s = core.state
        s.nav_follow_enabled = False
        s.nav_follow_source = ""
        s.nav_follow_next = ""
        s.nav_follow_status = ""
        s.nav_transit_to = ""
        s.nav_last_copied = ""

        saved = self.storage.read_json()
        s.nav_follow_enabled = bool(saved.get("follow_enabled", False))
        self._dismissed_sig = str(saved.get("dismissed_journal_sig", ""))

        self._edld_route = self.storage.read_json("route") or None
        if self._edld_route and not (self._edld_route.get("Route") or []):
            self._edld_route = None
        # Jump pace for "time left": arrival clock times of recent jumps.
        self._arrivals: list[float] = []
        self._replotting = False
        self._replotted_from = ""
        self._warned_target = ""
        self._permits: dict[int, bool] = {}

        self._refresh_status()

    # ── Persistence ───────────────────────────────────────────────────────────

    def _save_settings(self) -> None:
        try:
            self.storage.write_json({
                "follow_enabled": bool(self.core.state.nav_follow_enabled),
                "dismissed_journal_sig": self._dismissed_sig,
            })
        except Exception as exc:
            from core import debug as _dbg
            _dbg.info(f"  [Nav] could not persist follower settings: {exc}")

    # ── Route access ──────────────────────────────────────────────────────────

    def _journal_route(self) -> dict | None:
        doc = read_nav_route_file(self.core.journal_dir)
        if doc and route_signature(doc) == self._dismissed_sig:
            return None      # cleared by the user and unchanged since
        return doc

    def active_route(self) -> tuple[list, str]:
        """Return (route entries, source label).

        Source is "edld", "journal", or "" when there is no route.
        """
        edld = self._edld_route
        journal = self._journal_route()

        if edld and journal:
            if str(edld.get("timestamp", "")) >= str(journal.get("timestamp", "")):
                return edld.get("Route") or [], "edld"
            return journal.get("Route") or [], "journal"
        if edld:
            return edld.get("Route") or [], "edld"
        if journal:
            return journal.get("Route") or [], "journal"
        return [], ""

    def store_route(self, result: dict, kind: str, plot: dict | None = None) -> bool:
        """Persist an EDLD-plotted route and make it the followed route.

        ``plot`` is how it was plotted (kind-specific inputs), kept so the
        route can be plotted again from somewhere else; FSD and neutron plots
        record their own when not given one."""
        if plot is None and kind in ("fsd", "neutron") and isinstance(result, dict):
            plot = {"kind": kind, "to": result.get("destination_system") or "",
                    "range": result.get("range"), "efficiency": result.get("efficiency"),
                    "neutrons": bool(result.get("neutrons"))}
        doc = spansh_result_to_navroute(result, kind, plot)
        if not doc:
            return False
        self._edld_route = doc
        try:
            self.storage.write_json(doc, "route")
        except Exception as exc:
            from core import debug as _dbg
            _dbg.info(f"  [Nav] could not persist route: {exc}")
        # A freshly plotted route supersedes any earlier dismissal.
        self._dismissed_sig = ""
        self._save_settings()
        self._refresh_status()
        self._notify()
        self._check_route_async(doc)
        return True

    # ── Checks on a new route ────────────────────────────────────────────────

    def _check_route_async(self, doc: dict | None) -> None:
        """Permit-locked stops, and a ship without a fuel scoop on a route
        longer than its tank — looked at off the journal thread."""
        if not doc or getattr(self.core.state, "in_preload", False):
            return
        import threading
        threading.Thread(target=self._check_route, args=(doc,), daemon=True,
                         name="nav-route-check").start()

    def _check_route(self, doc: dict) -> None:
        try:
            self._check_route_inner(doc)
        except Exception as exc:
            from core import debug as _dbg
            _dbg.log(f"  [Nav] route check failed: {type(exc).__name__}: {exc}")

    def _check_route_inner(self, doc: dict) -> None:
        from core.callout import say
        route = doc.get("Route") or []
        if not route:
            return
        s = self.settings()
        if s.get("CheckPermits", True):
            ids = [int(e.get("SystemAddress") or 0) for e in route]
            ids = [i for i in ids if i and i not in self._permits]
            sp = (getattr(self.core, "_plugins", None) or {}).get("spansh")
            if ids and sp is not None:
                try:
                    found = sp.systems_by_id64(ids)
                    if found is None:
                        raise ConnectionError("Spansh unreachable")
                    for i in ids:
                        self._permits[i] = bool((found.get(i) or {}).get("needs_permit"))
                except Exception:
                    pass
            locked = [e.get("StarSystem") for e in route
                      if self._permits.get(int(e.get("SystemAddress") or 0))]
            if locked:
                say(self.core, "RouteWarning", "🔒",
                    f"Route passes permit-locked systems: {', '.join(locked[:5])}"
                    + (f" and {len(locked) - 5} more" if len(locked) > 5 else ""),
                    sigil="!  ROUT", alert=True, sound="attention")
        from core import route_fuel
        st = self.core.state
        a = route_fuel.analyse(st, route)
        if a and st.ship_has_scoop is False and a.get("runs_out_at"):
            say(self.core, "RouteWarning", "⛽",
                f"No fuel scoop fitted, and the tank runs dry at {a['runs_out_at']} "
                f"({a['runs_out_after']} jumps in)", sigil="!  ROUT", alert=True,
                urgent=True, sound="warning")
        elif a and a.get("dry"):
            d = a["dry"][0]
            say(self.core, "RouteWarning", "⛽",
                f"Dry stretch ahead: {d['jumps']} jumps without a scoopable star after "
                f"{d['after']}" + (" — more than a full tank covers" if d["too_long"] else ""),
                sigil="!  ROUT", alert=bool(d["too_long"]), sound="attention" if d["too_long"] else None)

    def navigation_tool_tabs(self):
        """The FSD, Neutron and Carrier plot forms (core/plot_tools.py)."""
        from core import plot_tools
        return plot_tools.tabs()

    def plotted_route(self) -> dict | None:
        """The EDLD route as stored, with how it was plotted."""
        return self._edld_route

    def time_left(self, jumps: int) -> float | None:
        """Seconds for ``jumps`` more jumps at this session's pace: the
        median interval between recent arrivals, ignoring long stops."""
        gaps = [b - a for a, b in zip(self._arrivals, self._arrivals[1:]) if 0 < b - a < 600]
        if len(gaps) < 2 or jumps <= 0:
            return None
        gaps.sort()
        return gaps[len(gaps) // 2] * jumps

    def _retire_completed_route(self) -> None:
        """Drop the EDLD route once its final destination has been reached.
        """
        doc = self._edld_route
        route = (doc or {}).get("Route") or []
        if not route:
            return
        current = self.effective_current_system()
        if not current:
            return
        if _norm(route[-1].get("StarSystem")) != _norm(current):
            return

        self._edld_route = None
        try:
            self.storage.write_json({}, "route")
        except Exception as exc:
            from core import debug as _dbg
            _dbg.info(f"  [Nav] could not retire completed route: {exc}")
        self.core.state.nav_last_copied = ""

    def clear_route(self) -> str:
        """Wipe the EDLD route and suppress the current NavRoute.json."""
        self._edld_route = None
        try:
            self.storage.write_json({}, "route")
        except Exception as exc:
            from core import debug as _dbg
            _dbg.info(f"  [Nav] could not clear stored route: {exc}")

        journal = read_nav_route_file(self.core.journal_dir)
        self._dismissed_sig = route_signature(journal)

        s = self.core.state
        s.nav_follow_next = ""
        s.nav_last_copied = ""
        self._save_settings()
        self._refresh_status()
        self._notify()
        return ("Route cleared — following resumes when a new route is "
                "plotted in EDLD or in game.")

    # ── Follower ──────────────────────────────────────────────────────────────

    def set_follow_enabled(self, enabled: bool) -> None:
        self.core.state.nav_follow_enabled = bool(enabled)
        self._save_settings()
        self._refresh_status()
        self._notify()

    def toggle_follow(self) -> bool:
        self.set_follow_enabled(not self.core.state.nav_follow_enabled)
        return self.core.state.nav_follow_enabled

    def effective_current_system(self) -> str:
        """The system to route from."""
        s = self.core.state
        return (s.nav_transit_to or "").strip() or (s.pilot_system or "").strip()

    @staticmethod
    def _index_of(route: list, system: str) -> int | None:
        target = _norm(system)
        if not target:
            return None
        for i, entry in enumerate(route):
            if _norm(entry.get("StarSystem")) == target:
                return i
        return None

    def next_system(self) -> tuple[str, str]:
        """Return (next system name, reason-if-empty).

        Never raises; an empty name always comes with an explanation the UI
        can show verbatim.
        """
        route, source = self.active_route()
        if not route:
            return "", "No route stored."

        current = self.effective_current_system()
        if not current:
            return "", "Current system unknown."

        idx = self._index_of(route, current)
        if idx is None:
            # Kept short: this renders in a one-row footer that clips.
            return "", f"Off the {source} route"
        if idx >= len(route) - 1:
            return "", "At final destination"
        return str(route[idx + 1].get("StarSystem") or ""), ""

    def copy_next(self) -> tuple[bool, str]:
        """Copy the next system to the clipboard.  Returns (ok, message)."""
        system, why = self.next_system()
        if not system:
            return False, why

        from core import clipboard
        ok, detail = clipboard.copy(system)
        if ok:
            self.core.state.nav_last_copied = system
            self._refresh_status()
            return True, f"Copied {system}"
        return False, f"Could not copy {system} — {detail}"

    # ── Status / notification ─────────────────────────────────────────────────

    def _refresh_status(self) -> None:
        s = self.core.state
        route, source = self.active_route()
        s.nav_follow_source = source

        if not route:
            s.nav_follow_next = ""
            s.nav_follow_status = "No route"
            return

        nxt, why = self.next_system()
        s.nav_follow_next = nxt
        label = {"edld": "EDLD", "journal": "in-game"}.get(source, source)

        if nxt:
            idx = self._index_of(route, self.effective_current_system())
            remaining = len(route) - 1 - (idx if idx is not None else 0)
            s.nav_follow_status = f"{label}: {nxt}  ({remaining} to go)"
        else:
            s.nav_follow_status = f"{label}: {why}"

    # ── Arrival: survey stops, leaving the route ─────────────────────────────

    def _on_arrival(self, route: list, source: str, event: dict) -> None:
        here = str(event.get("StarSystem") or "")
        if not route or not here:
            return
        idx = self._index_of(route, here)
        if idx is None:
            if source == "edld":
                self._replot(f"left the route at {here}")
            return
        self._replotted_from = ""
        extra = route[idx].get("EDLD") or {}
        if (extra.get("bodies") or extra.get("trade")) and self.settings().get("SurveyArrival", True):
            from core import survey
            from core.callout import say
            t = survey.todo(self.core, here, event.get("SystemAddress"), extra)
            line = survey.todo_text(t)
            if line:
                detail = survey.todo_detail(t)
                say(self.core, "SurveyArrival", "🧭", f"{here}: {line}",
                    term=f"{here}: {line}" + ("".join(f"\n    {d}" for d in detail[:12])),
                    sigil="-  SURV", sound="found" if (t["map"] or t["sample"]) else None)

    def _replot(self, why: str) -> None:
        """Plot the EDLD route again from where the commander is, with the
        same destination and options, on a worker thread."""
        doc = self._edld_route or {}
        plot = doc.get("EDLDPlot") or {}
        if plot.get("kind") not in ("fsd", "neutron") or not plot.get("to"):
            return
        if not self.settings().get("AutoReplot", True) or self._replotting:
            return
        here = self.effective_current_system()
        if not here or here == self._replotted_from:
            return
        self._replotting = True
        self._replotted_from = here
        import threading
        threading.Thread(target=self._replot_worker, args=(dict(plot), here, why),
                         daemon=True, name="nav-replot").start()

    def _replot_worker(self, plot: dict, here: str, why: str) -> None:
        from core.callout import say
        from core import route_view as RV
        try:
            sp = (getattr(self.core, "_plugins", None) or {}).get("spansh")
            if sp is None:
                return
            rng = RV.plan_range(self.core.state) or float(plot.get("range") or 0)
            if plot["kind"] == "neutron":
                result = sp.plot_neutron_route(here, plot["to"], rng, int(plot.get("efficiency") or 60))
            else:
                result = sp.plot_fsd_route(here, plot["to"], rng, bool(plot.get("neutrons")))
            if not isinstance(result, dict) or result.get("_error"):
                say(self.core, "RouteWarning", "🧭",
                    f"Could not re-plot to {plot['to']}: {(result or {}).get('_error', 'no route')}",
                    sigil="!  ROUT")
                return
            if plot["kind"] == "neutron":
                result["efficiency"] = plot.get("efficiency")
            self.store_route(result, plot["kind"], dict(plot, range=rng))
            jumps = result.get("total_jumps") or max(len(result.get("system_jumps") or []) - 1, 0)
            say(self.core, "RouteWarning", "🧭",
                f"You {why} — re-plotted to {plot['to']} from {here}: {jumps} jumps",
                sigil="-  ROUT", sound="attention")
        finally:
            self._replotting = False

    def _check_target(self, event: dict, state) -> None:
        """A system targeted that is not the next on EDLD's route."""
        if getattr(state, "in_preload", False) or not self.settings().get("WarnWrongTarget", True):
            return
        route, source = self.active_route()
        if source != "edld":
            return
        target = str(event.get("Name") or "")
        nxt, _ = self.next_system()
        if not target or not nxt or _norm(target) == _norm(nxt):
            self._warned_target = ""
            return
        if self._index_of(route, target) is not None or target == self._warned_target:
            return    # further along the route: deliberate, not a mistake
        self._warned_target = target
        from core.callout import say
        say(self.core, "RouteWarning", "🎯",
            f"Targeted {target}; the route's next system is {nxt}",
            sigil="!  ROUT", sound="attention")

    def _notify(self) -> None:
        gq = self.core.gui_queue
        if gq:
            gq.put(("plugin_refresh", "navigation"))

    # ── Events ────────────────────────────────────────────────────────────────

    def on_event(self, event: dict, state) -> None:
        ev = event.get("event")

        if ev == "JetConeBoost":
            try:
                state.nav_jet_boost = float(event.get("BoostValue") or 0.0)
            except (TypeError, ValueError):
                state.nav_jet_boost = 0.0
            self._notify()
            return
        if ev == "FSDJump":
            state.nav_jet_boost = 0.0          # the jump spends the supercharge

        if ev == "StartJump":
            # Only a hyperspace jump commits us to a destination; a
            # supercharge/supercruise StartJump does not move systems.
            if event.get("JumpType") == "Hyperspace":
                state.nav_transit_to = str(event.get("StarSystem") or "")
                self._refresh_status()
                self._notify()
            return

        if ev == "NavRouteClear":
            self._refresh_status()
            self._notify()
            return

        if ev == "NavRoute":
            # A newly plotted in-game route is never the one that was
            # dismissed, so drop the suppression.
            self._dismissed_sig = ""
            self._save_settings()
            self._refresh_status()
            self._notify()
            if not getattr(state, "in_preload", False):
                # The game writes the route to NavRoute.json just after the
                # event; read it a moment later.
                import threading
                threading.Timer(1.0, lambda: self._check_route_async(
                    read_nav_route_file(self.core.journal_dir))).start()
            return

        if ev == "FSDTarget":
            self._check_target(event, state)
            return

        if ev == "Loadout":
            ship = event.get("ShipID")
            if (not getattr(state, "in_preload", False) and ship is not None
                    and getattr(self, "_last_ship", None) not in (None, ship)):
                self._replot("changed ship")
            self._last_ship = ship
            return

        if ev in _ARRIVAL_EVENTS:
            state.nav_transit_to = ""
            if ev == "FSDJump" and not getattr(state, "in_preload", False):
                self._arrivals = (self._arrivals + [time.monotonic()])[-12:]
            route_before, source_before = self.active_route()
            self._retire_completed_route()
            self._refresh_status()
            if not getattr(state, "in_preload", False) and ev == "FSDJump":
                self._on_arrival(route_before, source_before, event)

            # Replaying history at startup must not touch the clipboard.
            if getattr(state, "in_preload", False):
                return
            if not state.nav_follow_enabled:
                self._notify()
                return

            nxt = state.nav_follow_next
            if nxt and nxt != state.nav_last_copied:
                from core import clipboard
                ok, detail = clipboard.copy(nxt)
                if ok:
                    state.nav_last_copied = nxt
                else:
                    from core import debug as _dbg
                    _dbg.info(f"  [Nav] clipboard copy failed: {detail}")
            self._notify()
