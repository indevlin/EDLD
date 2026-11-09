"""components/discoveries.py — first discoveries not yet sold, what a death lost,
and the commander's firsts.

Unsold firsts   Every body scanned that no one had discovered, from its Scan
                until the system's data is sold. Selling first is what puts
                the commander's name on it, so these are watched on Spansh:
                a body there reported well after the commander's own scan was
                scanned by someone else, who could sell it first.
Rescan list     A death loses every unsold scan. What was unsold then is kept
                here, system by system, as the list to go back to; a body
                scanned again comes off it, and the system with its last body.
My firsts       Bodies first discovered, first mapped and first walked on,
                from the body database.
"""
from __future__ import annotations

import json
import threading
import time
from datetime import datetime, timezone

from core.plugin_loader import BasePlugin
from core.tooltab import Field, ToolResult, ToolTab, number

#: A report on Spansh this long after the commander's own scan is someone
#: else's: the commander's own upload, through EDDN, reaches it in minutes.
OTHERS_AFTER_S = 3600
#: Systems looked up on Spansh in one check, oldest scans first.
CHECK_MAX = 25
#: Automatic checks this far apart.
CHECK_EVERY_S = 3 * 3600


def _epoch(ts) -> float | None:
    s = str(ts or "").strip().replace("Z", "+00:00").replace(" ", "T", 1)
    if not s:
        return None
    if s.endswith("+00"):
        s += ":00"
    try:
        t = datetime.fromisoformat(s)
    except ValueError:
        return None
    if t.tzinfo is None:
        t = t.replace(tzinfo=timezone.utc)
    return t.timestamp()


class Ledger:
    """The unsold firsts and the rescan list, and the events that move them."""

    def __init__(self, data: dict | None = None) -> None:
        data = data or {}
        self.unsold: dict[str, dict] = data.get("unsold") or {}
        self.lost: dict[str, dict] = data.get("lost") or {}
        self.others: dict[str, dict] = data.get("others") or {}
        self._system = ("", "")            # (address, name) the commander is in

    def as_dict(self) -> dict:
        return {"unsold": self.unsold, "lost": self.lost, "others": self.others}

    def apply(self, ev: dict) -> bool:
        """Apply one journal event; True when anything changed."""
        name = ev.get("event")
        if name in ("FSDJump", "Location", "CarrierJump"):
            self._system = (str(ev.get("SystemAddress") or ""), str(ev.get("StarSystem") or ""))
            return False
        if name == "Scan":
            return self._scan(ev)
        if name == "SAAScanComplete":
            sysrec = self.unsold.get(str(ev.get("SystemAddress") or self._system[0]))
            body = (sysrec or {}).get("bodies", {}).get(str(ev.get("BodyName") or ""))
            if body is not None and not body.get("mapped"):
                body["mapped"] = True
                return True
            return False
        if name in ("SellExplorationData", "MultiSellExplorationData"):
            return self._sold(ev)
        if name == "Died":
            if not self.unsold:
                return False
            when = str(ev.get("timestamp") or "")
            for addr, rec in self.unsold.items():
                kept = self.lost.setdefault(addr, {"name": rec["name"], "bodies": {}})
                kept["lost_at"] = when
                kept["bodies"].update(rec["bodies"])
            self.unsold = {}
            self.others = {}
            return True
        return False

    def _scan(self, ev: dict) -> bool:
        body = str(ev.get("BodyName") or "")
        if not body or ev.get("ScanType") == "NavBeaconDetail" or "Belt Cluster" in body:
            return False
        addr = str(ev.get("SystemAddress") or self._system[0] or "")
        if not addr:
            return False
        changed = False
        lost = self.lost.get(addr)
        if lost and body in lost["bodies"]:
            del lost["bodies"][body]
            if not lost["bodies"]:
                del self.lost[addr]
            changed = True
        if ev.get("WasDiscovered"):
            return changed
        sysname = (self._system[1] if self._system[0] == addr else "") or \
            str(ev.get("StarSystem") or "") or body
        rec = self.unsold.setdefault(addr, {"name": sysname, "bodies": {}})
        if body not in rec["bodies"]:
            rec["bodies"][body] = {"scanned_at": str(ev.get("timestamp") or ""),
                                   "kind": "star" if ev.get("StarType") else "planet",
                                   "type": ev.get("StarType") or ev.get("PlanetClass") or "",
                                   "mapped": False}
            changed = True
        return changed

    def _sold(self, ev: dict) -> bool:
        names = set()
        for d in ev.get("Discovered") or []:
            names.add(str(d.get("SystemName") if isinstance(d, dict) else d).lower())
        for s in ev.get("Systems") or []:
            names.add(str(s).lower())
        gone = [a for a, r in self.unsold.items() if str(r.get("name") or "").lower() in names]
        for a in gone:
            del self.unsold[a]
            self.others.pop(a, None)
        return bool(gone)

    # ── reading ──────────────────────────────────────────────────────────────

    def unsold_bodies(self) -> int:
        return sum(len(r["bodies"]) for r in self.unsold.values())

    def lost_bodies(self) -> int:
        return sum(len(r["bodies"]) for r in self.lost.values())


#: The events Ledger.apply reads.
LEDGER_EVENTS = ("FSDJump", "Location", "CarrierJump", "Scan", "SAAScanComplete",
                 "SellExplorationData", "MultiSellExplorationData", "Died")


def rebuild(journal_dir) -> Ledger:
    """The ledger from every journal, oldest first."""
    from core.journal_index import index_for
    led = Ledger()
    for _f, ev in index_for(journal_dir).events(LEDGER_EVENTS):
        led.apply(ev)
    return led


def check_others(led: Ledger, dump, limit: int = CHECK_MAX) -> dict[str, dict]:
    """Look the unsold systems up on Spansh (``dump(id64)`` → its system
    dump, {} when it has none, None when it cannot be asked) and return those
    where a body the commander discovered was reported well after the
    commander's own scan: {address: {"name", "bodies": [...], "checked"}}."""
    found: dict[str, dict] = {}
    oldest = sorted(led.unsold.items(),
                    key=lambda kv: min((b["scanned_at"] for b in kv[1]["bodies"].values()),
                                       default=""))
    for addr, rec in oldest[:limit]:
        d = dump(int(addr))
        if d is None:
            break
        bodies = {str(b.get("name") or ""): b for b in ((d or {}).get("system") or {}).get("bodies") or []
                  if isinstance(b, dict)}
        hit = []
        for name, mine in rec["bodies"].items():
            theirs = bodies.get(name)
            if not theirs:
                continue
            t_mine, t_theirs = _epoch(mine["scanned_at"]), _epoch(theirs.get("updateTime"))
            if t_mine and t_theirs and t_theirs - t_mine > OTHERS_AFTER_S:
                hit.append(name)
        if hit:
            found[addr] = {"name": rec["name"], "bodies": hit, "checked": time.time()}
    return found


class DiscoveriesPlugin(BasePlugin):
    PLUGIN_NAME = "discoveries"
    PLUGIN_DISPLAY = "Discoveries"
    PLUGIN_VERSION = "1.0.0"
    PLUGIN_DESCRIPTION = ("Unsold first discoveries watched on Spansh, the rescan list a "
                          "death leaves, and your firsts.")
    SUBSCRIBED_EVENTS = ["FSDJump", "Location", "CarrierJump", "Scan", "SAAScanComplete",
                         "SellExplorationData", "MultiSellExplorationData", "Died"]

    def on_load(self, core) -> None:
        super().on_load(core)
        self._lock = threading.Lock()
        self._ready = False
        self._pending: list[dict] = []
        self._checked_at = 0.0
        try:
            saved = self.storage.read_json("ledger") or {}
        except Exception:
            saved = {}
        if saved:
            self.ledger = Ledger(saved)
            self._ready = True
        else:
            self.ledger = Ledger()
            threading.Thread(target=self._rebuild, daemon=True, name="discoveries-build").start()
        threading.Thread(target=self._check_loop, daemon=True, name="discoveries-check").start()

    def _rebuild(self) -> None:
        jdir = getattr(self.core, "journal_dir", None)
        led = rebuild(jdir) if jdir else Ledger()
        with self._lock:
            # Events that arrived while the journals were read are later than
            # all of them; apply them on top.
            for ev in self._pending:
                led.apply(ev)
            self._pending = []
            self.ledger = led
            self._ready = True
        self._save()

    def _save(self) -> None:
        try:
            with self._lock:
                data = json.loads(json.dumps(self.ledger.as_dict()))
            self.storage.write_json(data, "ledger")
        except Exception:
            pass

    def on_event(self, event: dict, state) -> None:
        if getattr(state, "in_preload", False):
            # Already in the saved ledger, or in the rebuild; only the
            # location matters, for scans that follow.
            if event.get("event") in ("FSDJump", "Location", "CarrierJump"):
                with self._lock:
                    self.ledger.apply(event)
            return
        with self._lock:
            if not self._ready:
                self._pending.append(event)
                return
            changed = self.ledger.apply(event)
        if changed:
            self._save()
            if event.get("event") == "Died" and self.ledger.lost:
                from core import callout
                callout.say(self.core, "FirstsWatch", "🔁",
                            f"Unsold data lost: {len(self.ledger.lost)} systems are on the rescan list",
                            sigil="!  EXPL", alert=True)

    # ── Spansh ───────────────────────────────────────────────────────────────

    def check_now(self) -> tuple[int, str]:
        sp = (getattr(self.core, "_plugins", None) or {}).get("spansh")
        if sp is None:
            return 0, "The Spansh component is not loaded."
        with self._lock:
            led = Ledger(json.loads(json.dumps(self.ledger.as_dict())))
        found = check_others(led, sp.system_dump)
        with self._lock:
            new = [a for a in found if a not in self.ledger.others and a in self.ledger.unsold]
            for a, v in found.items():
                if a in self.ledger.unsold:
                    self.ledger.others[a] = v
        self._checked_at = time.time()
        self._save()
        if new:
            from core import callout
            names = ", ".join(found[a]["name"] for a in new[:3])
            callout.say(self.core, "FirstsWatch", "⚠",
                        f"Someone else has scanned your unsold discoveries in {names}"
                        + (f" and {len(new) - 3} more" if len(new) > 3 else "")
                        + " — sell them first", sigil="!  EXPL", alert=True, sound="attention")
        return len(found), ""

    def _check_loop(self) -> None:
        time.sleep(120)
        while True:
            if self._ready and self.ledger.unsold and \
                    time.time() - self._checked_at > CHECK_EVERY_S:
                try:
                    self.check_now()
                except Exception as exc:
                    from core import debug as _dbg
                    _dbg.log(f"  [Discoveries] check failed: {type(exc).__name__}: {exc}")
            time.sleep(300)

    # ── the tab, and EDAM ────────────────────────────────────────────────────

    def navigation_tool_tabs(self) -> list[ToolTab]:
        return [ToolTab(
            id="discoveries", title="Discoveries", button="Show",
            fields=(
                Field("kind", "Show", "choice", (("unsold", "Unsold first discoveries"),
                                                 ("rescan", "Rescan list"),
                                                 ("firsts", "My firsts")), "unsold"),
                Field("check", "Check them on Spansh", "check", default=False, only_for=("unsold",)),
                Field("first", "Firsts", "choice", (("all", "All"), ("discovered", "Discovered"),
                                                    ("mapped", "Mapped"), ("footfall", "Footfall")),
                      "all", only_for=("firsts",)),
                Field("limit", "Most rows (50)", only_for=("firsts",)),
            ),
            run=self._run_tab, intro=self._intro)]

    def _intro(self, core) -> str:
        if not self._ready:
            return "[dim]Reading the journals…[/dim]"
        led = self.ledger
        return (f"[dim]{led.unsold_bodies()} unsold first discoveries in {len(led.unsold)} "
                f"systems · {len(led.lost)} systems to rescan[/dim]")

    def _run_tab(self, core, v: dict) -> ToolResult:
        kind = v.get("kind") or "unsold"
        if not self._ready:
            return ToolResult("[yellow]Still reading the journals — try again in a moment.[/yellow]")
        if kind == "firsts":
            return self._firsts(v)
        if kind == "unsold" and v.get("check"):
            n, err = self.check_now()
            if err:
                return ToolResult(f"[red]{err}[/red]")
        with self._lock:
            src = self.ledger.unsold if kind == "unsold" else self.ledger.lost
            others = dict(self.ledger.others)
            items = sorted(src.items(), key=lambda kv: kv[1]["name"])
        rows = []
        for addr, rec in items:
            bodies = rec["bodies"]
            mapped = sum(1 for b in bodies.values() if b.get("mapped"))
            parts = [f"{len(bodies)} bod{'ies' if len(bodies) != 1 else 'y'}"]
            if mapped:
                parts.append(f"{mapped} mapped")
            if kind == "rescan" and rec.get("lost_at"):
                parts.append(f"lost {str(rec['lost_at'])[:10]}")
            if addr in others:
                parts.append(f"[red]scanned since by someone else: "
                             f"{len(others[addr]['bodies'])}[/red]")
            rows.append(("kv", rec["name"], " · ".join(parts)))
        if not rows:
            return ToolResult("[green]Nothing unsold.[/green]" if kind == "unsold"
                              else "[green]Nothing to rescan.[/green]")
        what = "unsold first discoveries" if kind == "unsold" else "systems to rescan"
        total = sum(len(r["bodies"]) for _a, r in items)
        return ToolResult(f"[green]{len(rows)} systems, {total} bodies: {what}[/green]", rows)

    def _firsts(self, v: dict) -> ToolResult:
        rows = my_firsts(self.core, v.get("first") or "all", number(v, "limit", 1, 1000, 50, True))
        if rows is None:
            return ToolResult("[yellow]The body database is not ready.[/yellow]")
        counts, items = rows
        status = (f"{counts['discovered']} discovered first · {counts['mapped']} mapped first · "
                  f"{counts['footfall']} first footfalls")
        return ToolResult(f"[green]{status}[/green]",
                          [("kv", name, " · ".join(tags)) for name, tags in items])

    def summary_rows(self) -> list[tuple[str, str]]:
        """For EDAM's Exploration page."""
        if not self._ready:
            return []
        led = self.ledger
        out = [("Unsold firsts", f"{led.unsold_bodies()} in {len(led.unsold)} systems")]
        if led.others:
            out.append(("Scanned by others", ", ".join(r["name"] for r in list(led.others.values())[:3])))
        if led.lost:
            out.append(("To rescan", f"{len(led.lost)} systems"))
            for rec in sorted(led.lost.values(), key=lambda r: str(r.get("lost_at") or ""),
                              reverse=True)[:5]:
                out.append(("  " + rec["name"], f"{len(rec['bodies'])} bodies"))
        return out


def my_firsts(core, which: str = "all", limit: int = 50):
    """(counts, [(body, [tags])]) newest first, from the body database."""
    try:
        from core.bodies_db import get_db
        db = get_db()
        cid = core.plugin_call("explo_sync", "current_commander_id")
    except Exception:
        return None
    if not cid:
        return None
    q = ("SELECT p.name, ps.was_discovered, ps.mapped, ps.was_mapped, ps.footfall, "
         "ps.was_footfalled, COALESCE(ps.mapped_at, ps.scanned_at) AS at "
         "FROM planet_status ps JOIN planets p ON p.id = ps.planet_id "
         "WHERE ps.commander_id = ? AND ps.discovered = 1 AND (ps.was_discovered = 0 "
         "OR (ps.mapped = 1 AND ps.was_mapped = 0) OR (ps.footfall = 1 AND ps.was_footfalled = 0))")
    rows = [dict(r) for r in db._c.execute(q, (cid,))]
    stars = [dict(r) for r in db._c.execute(
        "SELECT s.name, ss.scanned_at AS at FROM star_status ss JOIN stars s ON s.id = ss.star_id "
        "WHERE ss.commander_id = ? AND ss.discovered = 1 AND ss.was_discovered = 0", (cid,))]
    counts = {"discovered": len(stars) + sum(1 for r in rows if not r["was_discovered"]),
              "mapped": sum(1 for r in rows if r["mapped"] and not r["was_mapped"]),
              "footfall": sum(1 for r in rows if r["footfall"] and r["was_footfalled"] == 0)}
    items = []
    for r in rows:
        tags = []
        if not r["was_discovered"]:
            tags.append("discovered")
        if r["mapped"] and not r["was_mapped"]:
            tags.append("mapped")
        if r["footfall"] and r["was_footfalled"] == 0:
            tags.append("footfall")
        if which == "all" or which in tags:
            items.append((r["at"] or "", r["name"], tags))
    if which in ("all", "discovered"):
        items += [(s["at"] or "", s["name"], ["discovered"]) for s in stars]
    items.sort(key=lambda t: t[0], reverse=True)
    return counts, [(name, tags + ([at[:10]] if at else [])) for at, name, tags in items[:limit]]
