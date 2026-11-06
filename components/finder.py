"""
components/finder.py — the Navigation window's Survey, Nearby and Services tabs.

Survey     Road to Riches, Exomastery, Earth-like / ammonia / terraformable
           worlds, a trade run, or a sweep through chosen systems, planned by
           Spansh (core/survey.py) and followed like any route EDLD plots.
Nearby     Every system anyone has reported within a radius, nearest first,
           each marked done (every body reported), partly scanned, or with
           nothing but its star known. A system the galaxy map shows that is
           not on the list has never been reported at all.
Services   The nearest stations and fleet carriers offering a service — and
           the Deep Space Support Array's carriers, stationed in the black
           for explorers, from the list EDAstro publishes.

The tabs are described here once (core/tooltab.py) and drawn the same way by
both interfaces.
"""
from __future__ import annotations

import json
import threading
import time
import urllib.request
from datetime import datetime, timezone

from core.plugin_loader import BasePlugin
from core.survey import system_status
from core.tooltab import Field, ToolResult, ToolTab, number

DSSA_URL = "https://edastro.com/json/DSSA-carriers.json"
DSSA_MAX_AGE_S = 3600

#: Spansh's service names, and the DSSA list's words for the same.
SERVICES = (
    ("Universal Cartographics", "Universal Cartographics"),
    ("Vista Genomics", "Vista Genomics"),
    ("Refuel", "Refuel"),
    ("Repair", "Repair"),
    ("Restock", "Restock"),
    ("Outfitting", "Outfitting"),
    ("Shipyard", "Shipyard"),
    ("Market", "Market"),
    ("Material Trader", "Material Trader"),
    ("Technology Broker", "Technology Broker"),
    ("Interstellar Factors Contact", "Interstellar Factors"),
    ("Black Market", "Black Market"),
    ("Search and Rescue", "Search and Rescue"),
)
_DSSA_WORDS = {
    "Universal Cartographics": {"uc", "cartographics", "universal"},
    "Vista Genomics": {"vista", "genomics"},
    "Refuel": {"refuel"}, "Repair": {"repair"}, "Restock": {"armoury", "restock"},
    "Outfitting": {"outfitting"}, "Shipyard": {"shipyard"},
}


def _here(core):
    s = core.state
    try:
        x, y, z = (float(v) for v in getattr(s, "pilot_star_pos", None))
        return {"x": x, "y": y, "z": z}
    except (TypeError, ValueError):
        return None


def _coords_of(core, name: str):
    """A system's coordinates: the one the commander is in from the journal,
    any other from EDSM."""
    s = core.state
    if not name or name.strip().lower() == str(getattr(s, "pilot_system", "") or "").lower():
        return _here(core)
    sp = core._plugins.get("spansh")
    rec = sp._edsm_system(name) if sp is not None else None
    c = (rec or {}).get("coords")
    return {"x": c["x"], "y": c["y"], "z": c["z"]} if c else None


def _age_days(when) -> float | None:
    if not when:
        return None
    s = str(when).replace("Z", "+00:00").replace(" ", "T", 1)
    try:
        t = datetime.fromisoformat(s)
    except ValueError:
        return None
    if t.tzinfo is None:
        t = t.replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - t).total_seconds() / 86400


class FinderPlugin(BasePlugin):
    PLUGIN_NAME = "finder"
    PLUGIN_DISPLAY = "Route & Place Finder"
    PLUGIN_VERSION = "1.0.0"
    PLUGIN_DESCRIPTION = ("Survey routes, systems nearby and their scan state, "
                          "and the nearest place offering a service.")
    SUBSCRIBED_EVENTS: list = []

    def on_load(self, core) -> None:
        super().on_load(core)
        self._dssa: list = []
        self._dssa_at = 0.0
        self._lock = threading.Lock()
        #: id64 → status from the last Nearby search, for the targeting cue.
        self.known_status: dict[int, str] = {}

    # ── Tabs ─────────────────────────────────────────────────────────────────

    def navigation_tool_tabs(self) -> list[ToolTab]:
        from core import survey
        kinds = tuple((k, v[0]) for k, v in survey.KINDS.items())
        bodies = ("riches", "exobiology", "elw", "aw", "tf")
        return [
            ToolTab(
                id="survey", title="Survey", button="Plot Survey",
                fields=(
                    Field("kind", "Route", "choice", kinds, "riches"),
                    Field("from", "From (current system)", system=True),
                    Field("station", "Station to start from (docked: filled in)", only_for=("trade",)),
                    Field("systems", "Systems to visit, separated by commas", only_for=("tourist",)),
                    Field("to", "Finish at (optional)", only_for=("tourist",), system=True),
                    Field("range", "Jump range, ly — filled from your ship"),
                    Field("radius", "Search radius, ly (25)", only_for=bodies),
                    Field("max_results", "Most systems (25)", only_for=bodies),
                    Field("min_value", "Least value per body, cr", only_for=bodies),
                    Field("max_ls", "Furthest from arrival, ls", only_for=bodies + ("trade",)),
                    Field("loop", "Return to the start", "check", only_for=bodies + ("tourist",)),
                    Field("capital", "Capital, cr (your balance)", only_for=("trade",)),
                    Field("cargo", "Cargo space, t (your hold)", only_for=("trade",)),
                    Field("hops", "Hops (5)", only_for=("trade",)),
                    Field("price_age_days", "Oldest prices, days (14)", only_for=("trade",)),
                    Field("large_pad", "Large pad needed", "check", only_for=("trade",)),
                    Field("planetary", "Include planetary ports", "check", only_for=("trade",)),
                ),
                run=self._run_survey, autofill=self._fill_survey, intro=self._survey_intro),
            ToolTab(
                id="nearby", title="Nearby", button="Search",
                fields=(
                    Field("from", "Around (current system)", system=True),
                    Field("radius", "Radius, ly (25, up to 50)"),
                    Field("show", "Show", "choice",
                          (("all", "Every system"), ("todo", "Not fully scanned")), "all"),
                ),
                run=self._run_nearby, autofill=self._fill_here, intro=self._nearby_intro),
            ToolTab(
                id="services", title="Services", button="Find",
                fields=(
                    Field("service", "Service", "choice", SERVICES, "Universal Cartographics"),
                    Field("from", "Near (current system)", system=True),
                    Field("carriers", "Include fleet carriers", "check", default=True),
                    Field("large_pad", "Large pad needed", "check"),
                    Field("max_age", "Carriers last reported within, days (30)"),
                ),
                run=self._run_services, autofill=self._fill_here),
        ]

    # ── Autofill ─────────────────────────────────────────────────────────────

    def _fill_here(self, core) -> dict:
        return {"from": str(getattr(core.state, "pilot_system", "") or "")}

    def _fill_survey(self, core) -> dict:
        from core import route_view as RV
        s = core.state
        plan = RV.plan_range(s)
        out = {"from": str(getattr(s, "pilot_system", "") or ""),
               "range": f"{plan:.2f}" if plan else ""}
        d = getattr(s, "docked_at", None) or {}
        if d.get("station"):
            out["station"] = d["station"]
        return out

    def _survey_intro(self, core) -> str:
        return ("[dim]Planned by Spansh and followed like any route: arriving at a "
                "stop says what is left to do there, from your own journal.[/dim]")

    def _nearby_intro(self, core) -> str:
        return ("[dim]Every system anyone has reported. One the galaxy map shows "
                "that is not listed has never been reported.[/dim]")

    # ── Survey ───────────────────────────────────────────────────────────────

    def _run_survey(self, core, v: dict) -> ToolResult:
        from core import survey
        from core import route_view as RV
        from core.emit import fmt_credits
        s = core.state
        kind = v.get("kind") or "riches"
        d = getattr(s, "docked_at", None) or {}
        docked = (d.get("system"), d.get("station")) if d.get("station") else None
        if kind == "trade" and not v.get("from") and docked:
            v["from"] = docked[0]
        params = survey.params(kind, v, RV.plan_range(s),
                               int(getattr(s, "assets_balance", 0) or 0) or None,
                               int(getattr(s, "cargo_capacity", 0) or 0) or None, docked)
        sp = core._plugins.get("spansh")
        if sp is None:
            return ToolResult("[red]The Spansh component is not loaded.[/red]")
        result = sp.plot_survey(kind, params)
        if not isinstance(result, dict) or result.get("_error"):
            return ToolResult(f"[red]Plot failed: {(result or {}).get('_error', 'no answer')}[/red]")
        label = survey.KINDS[kind][0]
        rows = result["system_jumps"]
        status = f"{label}: {len(rows) - (0 if kind == 'trade' else 1)} stops · " \
                 f"{result['total_jumps']} jumps · {RV.fmt_ly(result['distance'])}"
        if result.get("value"):
            status += f" · {fmt_credits(result['value'])} to collect"
        if result.get("profit"):
            status += f" · {fmt_credits(result['profit'])} profit"
        out = [("hdr", "Stops")]
        for i, r in enumerate(rows, start=1):
            t = survey.todo(core, r["system"], r.get("id64"), r)
            parts = []
            if r.get("jumps"):
                parts.append(f"{r['jumps']} jump{'s' if r['jumps'] != 1 else ''}")
            line = survey.todo_text(t)
            if line:
                parts.append(line)
            out.append(("kv", f"{i}. {r['system']}", " · ".join(parts) or "start"))
        return ToolResult(f"[green]{status}[/green]", out,
                          route=(result, f"survey-{kind}", {"kind": f"survey-{kind}", "params": params}))

    # ── Nearby ───────────────────────────────────────────────────────────────

    def _run_nearby(self, core, v: dict) -> ToolResult:
        radius = number(v, "radius", 1, 50, 25)
        where = v.get("from") or str(getattr(core.state, "pilot_system", "") or "")
        coords = _coords_of(core, where)
        if coords is None:
            return ToolResult(f"[red]Where {where or 'you are'} is is not known.[/red]")
        sp = core._plugins.get("spansh")
        if sp is None:
            return ToolResult("[red]The Spansh component is not loaded.[/red]")
        found = sp.systems_near(coords, radius)
        if not found:
            return ToolResult("[yellow]Spansh returned nothing — is it reachable?[/yellow]")
        mine = self._my_systems(core, [r.get("id64") for r in found])
        counts = {"done": 0, "partial": 0, "star": 0}
        rows = []
        for r in found:
            st = system_status(r)
            counts[st] += 1
            try:
                self.known_status[int(r.get("id64"))] = st
            except (TypeError, ValueError):
                pass
            if v.get("show") == "todo" and st == "done":
                continue
            known = sum(1 for b in r.get("bodies") or [] if (b or {}).get("type") in ("Star", "Planet"))
            mark = {"done": "[dim]done[/dim]", "partial": "[yellow]partly scanned[/yellow]",
                    "star": "[green]star only[/green]"}[st]
            parts = [f"{float(r.get('distance') or 0):.1f} ly", mark]
            if r.get("body_count"):
                parts.append(f"{known}/{r['body_count']} bodies")
            star = next((b.get("subtype") or b.get("subType") or b.get("sub_type") or "" for b in r.get("bodies") or []
                         if isinstance(b, dict) and (b.get("is_main_star") or b.get("mainStar"))), "")
            if star:
                parts.append(star)
            if mine.get(int(r.get("id64") or 0)):
                parts.append("[cyan]yours: " + mine[int(r["id64"])] + "[/cyan]")
            if r.get("needs_permit"):
                parts.append("[red]permit[/red]")
            rows.append(("kv", str(r.get("name") or "?"), " · ".join(parts)))
        status = (f"{len(found)} reported within {radius:g} ly: {counts['done']} done, "
                  f"{counts['partial']} partly scanned, {counts['star']} with only the star")
        return ToolResult(f"[green]{status}[/green]", rows)

    @staticmethod
    def _my_systems(core, ids: list) -> dict[int, str]:
        """What this commander has done in each system: honked, fully scanned,
        fully mapped."""
        out: dict[int, str] = {}
        try:
            from core.bodies_db import get_db
            db = get_db()
            cid = core.plugin_call("explo_sync", "current_commander_id")
            if not cid:
                return out
            for i in ids:
                try:
                    sid = db.system_id_by_address(int(i))
                except (TypeError, ValueError):
                    continue
                if not sid:
                    continue
                row = db._c.execute(
                    "SELECT honked, fully_scanned, fully_mapped FROM system_status "
                    "WHERE system_id=? AND commander_id=?", (sid, cid)).fetchone()
                if row:
                    out[int(i)] = ("mapped" if row["fully_mapped"] else "scanned"
                                   if row["fully_scanned"] else "honked" if row["honked"] else "visited")
                else:
                    out[int(i)] = "visited"
        except Exception:
            pass
        return out

    # ── Services ─────────────────────────────────────────────────────────────

    def _dssa_list(self) -> list:
        with self._lock:
            if self._dssa and time.monotonic() - self._dssa_at < DSSA_MAX_AGE_S:
                return self._dssa
        try:
            req = urllib.request.Request(DSSA_URL, headers={"User-Agent": "EDLD/1.0"})
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except Exception as exc:
            from core import debug as _dbg
            _dbg.log(f"  [Finder] DSSA list unavailable: {type(exc).__name__}: {exc}")
            return self._dssa
        items = data if isinstance(data, list) else (data or {}).get("carriers") or []
        with self._lock:
            self._dssa = [x for x in items if isinstance(x, dict)]
            self._dssa_at = time.monotonic()
            return self._dssa

    def _run_services(self, core, v: dict) -> ToolResult:
        import math
        service = v.get("service") or "Universal Cartographics"
        where = v.get("from") or str(getattr(core.state, "pilot_system", "") or "")
        coords = _coords_of(core, where)
        if coords is None:
            return ToolResult(f"[red]Where {where or 'you are'} is is not known.[/red]")
        max_age = number(v, "max_age", 1, 3650, 30)
        sp = core._plugins.get("spansh")
        if sp is None:
            return ToolResult("[red]The Spansh component is not loaded.[/red]")
        found = sp.stations_near(coords, service, size=40)
        rows: list[tuple] = []
        seen_callsigns = set()
        places = []
        for r in found:
            carrier = "carrier" in str(r.get("type") or "").lower()
            if carrier and not v.get("carriers"):
                continue
            if v.get("large_pad") and not r.get("has_large_pad"):
                continue
            age = _age_days(r.get("updated_at"))
            if carrier and age is not None and age > max_age:
                continue
            # A carrier whose owner lets no one dock is no help.
            if carrier and str(r.get("carrier_docking_access") or "").lower() == "none":
                continue
            if carrier:
                seen_callsigns.add(str(r.get("name") or "").upper())
            places.append({
                "name": r.get("carrier_name") or r.get("name") or "?",
                "callsign": r.get("name") if carrier else "",
                "system": r.get("system_name") or "", "ly": float(r.get("distance") or 0),
                "ls": r.get("distance_to_arrival"), "carrier": carrier, "age": age,
                "dssa": False, "type": r.get("type") or ""})
        if v.get("carriers"):
            words = _DSSA_WORDS.get(service)
            for x in self._dssa_list():
                if "operational" not in str(x.get("status") or "operational").lower():
                    continue
                svc = {str(w).strip().lower() for w in x.get("services") or []}
                if words is None or not (svc & words):
                    continue
                c = x.get("coords") or {}
                try:
                    pos = [float(c[k]) for k in "xyz"]
                except (KeyError, TypeError, ValueError):
                    continue
                call = str(x.get("callsign") or "").upper()
                if call in seen_callsigns:
                    for p in places:
                        if str(p["callsign"]).upper() == call:
                            p["dssa"] = True
                    continue
                places.append({
                    "name": str(x.get("name") or call), "callsign": call,
                    "system": x.get("lastSeenSystem") or x.get("designatedSystem") or "",
                    "ly": math.dist(pos, [coords["x"], coords["y"], coords["z"]]),
                    "ls": None, "carrier": True, "age": _age_days(x.get("lastSeenDate")),
                    "dssa": True, "type": "DSSA carrier"})
        places.sort(key=lambda p: p["ly"])
        for p in places[:30]:
            parts = [f"{p['ly']:.1f} ly", p["system"]]
            if p.get("ls"):
                parts.append(f"{int(p['ls']):,} ls")
            if p["carrier"]:
                parts.append("[magenta]DSSA[/magenta]" if p["dssa"] else "carrier")
                if p.get("age") is not None:
                    parts.append(f"seen {int(p['age'])} d ago")
            else:
                parts.append(p["type"])
            rows.append(("kv", p["name"] + (f" ({p['callsign']})" if p["callsign"]
                                            and p["callsign"] != p["name"] else ""),
                         " · ".join(x for x in parts if x)))
        if not rows:
            return ToolResult(f"[yellow]Nothing offering {service} found.[/yellow]")
        return ToolResult(f"[green]Nearest {service}: {rows[0][1]}[/green]", rows)
