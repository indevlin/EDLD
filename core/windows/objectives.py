"""core/windows/objectives.py — the Objectives window: the mission board and
colonization construction sites.

Missions: every active mission, one table per kind, then the community goals
signed up for or open to join.
"""
from __future__ import annotations

from datetime import datetime, timezone

from core.windows import R, Tab, cr, num


def fmt_reward(v: int) -> str:
    """Compact reward: 103.3M / 1.2B — no 'cr' suffix, one width."""
    if not v:                          return "—"
    if v >= 1_000_000_000:             return f"{v/1_000_000_000:.1f}B"
    if v >= 1_000_000:                 return f"{v/1_000_000:.1f}M"
    if v >= 1_000:                     return f"{v/1_000:.0f}k"
    return str(v)


def strip_target_type(raw: str) -> str:
    s = raw or ""
    if s.startswith("$") and s.endswith(";"):
        inner = s[1:-1]
        if "_" in inner:
            s = inner.rsplit("_", 1)[-1]
    return s.strip()


def missions_cell(done: int, held: int) -> str:
    """Missions complete of missions held, two digits each: 01 / 20."""
    return f"{int(done):02d} / {int(held):02d}"


def time_left(expiry: str, now: datetime | None = None) -> str:
    """6d 21h · 21h 02m · 45m · EXPIRED; blank when there is no deadline."""
    if not expiry:
        return ""
    try:
        end = datetime.fromisoformat(str(expiry).replace("Z", "+00:00"))
    except ValueError:
        return ""
    secs = int((end - (now or datetime.now(timezone.utc))).total_seconds())
    if secs <= 0:
        return "EXPIRED"
    d, h, m = secs // 86400, secs % 86400 // 3600, secs % 3600 // 60
    if d:
        return f"{d}d {h:02d}h"
    if h:
        return f"{h}h {m:02d}m"
    return f"{m}m"


def _tons(m: dict) -> str:
    """Delivered of asked for: 0120 / 2890. Nothing is delivered until a
    cargo depot says so."""
    asked = int(m.get("total") or m.get("count") or 0)
    if not asked:
        return ""
    return f"{int(m.get('delivered', 0) or 0):0{len(str(asked))}d} / {asked}"


def _destination(m: dict) -> str:
    station, system = m.get("dest_station", ""), m.get("dest_system", "")
    if station and system and station != system:
        return f"{station} · {system}"
    return station or system or m.get("name") or "Mission"


#: Kind → (heading: what each row is, the asked-for column, what labels a row,
#: what fills the asked-for column). Kinds not here get the name and no asked-
#: for column.
_KINDS = {
    "Delivery":      ("DELIVERY COMMODITY", "TONS",
                      lambda m: m.get("commodity") or m.get("name"), _tons),
    "Collection":    ("COLLECTION COMMODITY", "TONS",
                      lambda m: m.get("commodity") or m.get("name"), _tons),
    "Mining":        ("MINING COMMODITY", "TONS",
                      lambda m: m.get("commodity") or m.get("name"), _tons),
    "Salvage":       ("SALVAGE COMMODITY", "UNITS",
                      lambda m: m.get("commodity") or m.get("name"),
                      lambda m: str(m.get("count", "")) if m.get("count") else ""),
    "Smuggling":     ("SMUGGLING COMMODITY", "TONS",
                      lambda m: m.get("commodity") or m.get("name"), _tons),
    "Courier":       ("COURIER DESTINATION", None, _destination, None),
    "Passenger":     ("PASSENGER DESTINATION", "PAX", _destination,
                      lambda m: str(m.get("passengers", "")) if m.get("passengers") else ""),
    "Rescue":        ("RESCUE DESTINATION", None, _destination, None),
    "Scan":          ("SCAN DESTINATION", None, _destination, None),
    "Assassination": ("ASSASSINATION TARGET", None,
                      lambda m: m.get("target") or m.get("name"), None),
    "Donation":      ("DONATION FACTION", "CREDITS",
                      lambda m: m.get("faction") or m.get("name"),
                      lambda m: fmt_reward(int(m.get("donation", 0) or 0))),
}


def _ore_held(core, ms: list) -> list:
    """Mining missions' commodities held: ship hold + own carrier (not the
    squadron carrier). Green when held covers what is still to deliver."""
    s = core.state
    ship = getattr(s, "cargo_items", {}) or {}
    carrier = getattr(s, "assets_carrier_hold", None) or {}
    need: dict[str, list] = {}
    for m in ms:
        key = m.get("commodity_key")
        if not key:
            continue
        rec = need.setdefault(key, [m.get("commodity") or key, 0])
        rec[1] += max(0, int(m.get("total") or m.get("count") or 0) - int(m.get("delivered", 0) or 0))
    if not need:
        return []
    def count(hold, key):
        c = hold.get(key, 0)
        return int(c.get("count", 0) if isinstance(c, dict) else c or 0)
    rows = [R.text(""), R.table("MINING ORE HELD", (("SHIP", 5), ("CARRIER", 7), ("HELD", 5)))]
    for key, (name, still) in sorted(need.items(), key=lambda kv: kv[1][0]):
        a, b = count(ship, key), count(carrier, key)
        rows.append(R.cells(name, [str(a), str(b) if carrier else "—", str(a + b)],
                            "val health-good" if a + b >= still > 0 else "val"))
    return rows


def _kind_table(category: str, ms: list, now) -> list:
    heading, qty_head, label_of, qty_of = _KINDS.get(
        category, (f"{category.upper()} MISSION", None, lambda m: m.get("name") or "Mission", None))
    ready = [m.get("status") == "Ready" for m in ms]
    qty = [qty_of(m) if qty_of else "" for m in ms]
    left = ["READY" if r else time_left(m.get("expiry", ""), now) for m, r in zip(ms, ready)]
    cols = []
    if qty_head:
        cols.append((qty_head, max([len(qty_head)] + [len(q) for q in qty])))
    cols.append(("EXPIRES", 7))
    cols.append(("REWARD", 6))
    rows = [R.table(heading, tuple(cols))]
    for m, r, q, t in zip(ms, ready, qty, left):
        # Not "[W]": the terminal dashboard reads that as markup and drops it.
        label = str(label_of(m) or "Mission") + ("  (Wing)" if m.get("wing") else "")
        values = ([q] if qty_head else []) + [t, fmt_reward(int(m.get("reward", 0) or 0))]
        rows.append(R.cells(label, values, "val health-good" if r else "val"))
    if len(ms) > 1:
        rows.append(R.rule())
        total = sum(int(m.get("reward", 0) or 0) for m in ms)
        tq = ""
        if qty_head in ("TONS", "UNITS", "PAX"):
            asked = sum(int(m.get("total") or m.get("count") or m.get("passengers") or 0) for m in ms)
            if qty_head == "TONS" and asked:
                tq = f"{sum(int(m.get('delivered', 0) or 0) for m in ms):0{len(str(asked))}d} / {asked}"
            else:
                tq = str(asked) if asked else ""
        elif qty_head == "CREDITS":
            tq = fmt_reward(sum(int(m.get("donation", 0) or 0) for m in ms))
        rows.append(R.cells("Totals", ([tq] if qty_head else []) + ["", fmt_reward(total)]))
    return rows


def missions(core, now: datetime | None = None) -> Tab:
    s = core.state
    detail = getattr(s, "mission_detail_map", {}) or {}
    rows: list = []
    if detail:
        # Done is redirects only. Kills made are not shown: the journal
        # records only about seven in ten of the kills the game credits, so
        # a running count always fell behind the mission screen.
        finished = getattr(s, "massacre_redirected", set()) or set()
        factions: dict[str, dict] = {}
        target_factions, target_types = set(), set()
        for mid, info in detail.items():
            src = info.get("faction", "Unknown")
            f = factions.setdefault(src, {"kill_count": 0, "reward": 0, "held": 0, "done": 0})
            f["kill_count"] += int(info.get("kill_count", 0))
            f["reward"] += int(info.get("reward", 0))
            f["held"] += 1
            f["done"] += mid in finished
            if info.get("target_faction"):
                target_factions.add(info["target_faction"])
            tt = strip_target_type(info.get("target_type", ""))
            if tt:
                target_types.add(tt)
        kills_w = max(5, len(str(sum(f["kill_count"] for f in factions.values()))))
        rows.append(R.table("MASSACRE SOURCE FACTION",
                            (("KILLS", kills_w), ("MISSIONS", 8), ("REWARD", 6))))
        for name in sorted(factions, key=lambda k: -factions[k]["kill_count"]):
            f = factions[name]
            rows.append(R.cells(name, [str(f["kill_count"]), missions_cell(f["done"], f["held"]),
                                       fmt_reward(f["reward"])],
                                "val health-good" if f["done"] == f["held"] else "val"))
        rows.append(R.rule())
        done = sum(f["done"] for f in factions.values())
        held = sum(f["held"] for f in factions.values())
        rows.append(R.cells("Totals", [str(max(f["kill_count"] for f in factions.values())),
                                       missions_cell(done, held),
                                       fmt_reward(sum(f["reward"] for f in factions.values()))],
                            "val health-good" if done == held else "val"))
        if len(target_factions) > 1:
            rows.append(R.text(f"[yellow]⚠ Mixed targets: {', '.join(sorted(target_factions))}[/yellow]"))
        if len(target_types) > 1:
            rows.append(R.text(f"[yellow]⚠ Mixed types: {', '.join(sorted(target_types))}[/yellow]"))

    # Every other mission, a table per kind.
    board = getattr(s, "all_missions", {}) or {}
    by_kind: dict[str, list] = {}
    for mid, m in board.items():
        if m.get("category") == "Massacre" or mid in detail:
            continue
        by_kind.setdefault(m.get("category") or "Other", []).append(m)
    order = [k for k in _KINDS if k in by_kind] + sorted(k for k in by_kind if k not in _KINDS)
    for kind in order:
        if rows:
            rows.append(R.text(""))
        ms = sorted(by_kind[kind], key=lambda m: -int(m.get("reward", 0) or 0))
        rows.extend(_kind_table(kind, ms, now))
        if kind == "Mining":
            rows.extend(_ore_held(core, ms))
    if not rows:
        rows = [R.text("No active missions", "dim")]
    goals = community_goals(core, now)
    if goals:
        rows.append(R.text(""))
        rows.extend(goals)
    return Tab("missions", "Missions", rows)


def _goal_rows(g: dict, now) -> list:
    from core.community_goals import finished
    rows = [R.text(f"[bold cyan]{g.get('title') or 'Community goal'}[/bold cyan]")]
    where = " · ".join(x for x in (g.get("station"), g.get("system")) if x)
    if where:
        rows.append(R.kv("Where", where))
    if g.get("objective"):
        rows.append(R.text(g["objective"], "dim"))
    if g.get("joined") and finished(g, now):
        rows.append(R.kv("Status", "Finished — hand in to claim", "val health-good"))
    elif g.get("expiry"):
        rows.append(R.kv("Ends in", time_left(g["expiry"], now)))
    if g.get("tier") is not None:
        rows.append(R.kv("Tier", f"{g['tier']} of {g['top_tier']}" if g.get("top_tier") else str(g["tier"])))
    if g.get("contributors"):
        rows.append(R.kv("Contributors", num(g["contributors"])))
    if g.get("joined"):
        rows.append(R.kv("Your contribution", f"{int(g.get('contribution') or 0):,}"))
        # The game gives a band and its reward before anything is handed in.
        if not g.get("contribution"):
            return rows
        if g.get("percentile"):
            band = f"Top {g['percentile']}%"
            if g.get("top_rank"):
                band += " · top commanders"
            rows.append(R.kv("Your band", band))
        if g.get("reward"):
            rows.append(R.kv("Reward", cr(g["reward"])))
    else:
        rows.append(R.kv("Signed up", "No", "val dim"))
    return rows


def community_goals(core, now: datetime | None = None) -> list:
    """Goals signed up for — running, then finished and waiting to be handed
    in — then those running that are open to join; nothing when there are
    none."""
    from core import community_goals as CG
    s = core.state
    goals = CG.merged(getattr(s, "cg_joined", {}) or {},
                      getattr(s, "capi_community_goals", None),
                      CG.from_inara(getattr(s, "inara_community_goals", None)), now)
    if not goals:
        return []
    rows = [R.hdr("Community Goals")]
    for i, g in enumerate(goals):
        if i:
            rows.append(R.text(""))
        rows.extend(_goal_rows(g, now))
    return rows


def colonisation(core, expanded: dict | None = None, expanded_sys: dict | None = None) -> Tab:
    """Sites by system. ``expanded`` (market id → bool) and ``expanded_sys``
    (system → bool) are the interface's own collapse state; a group not in
    them is open.
    """
    expanded = {} if expanded is None else expanded
    expanded_sys = {} if expanded_sys is None else expanded_sys
    s = core.state
    sites = getattr(s, "colonisation_sites", []) or []
    cargo = getattr(s, "cargo_items", {}) or {}
    docked = getattr(s, "colonisation_docked", False)
    cur_mid = getattr(s, "_colonisation_current_market_id", None)
    if not sites:
        return Tab("colonisation", "Colonization",
                   [R.text("No recent colonization activity", "dim")])
    rows: list = []
    active = [x for x in sites if not x.get("complete") and not x.get("failed")]
    order: list[str] = []
    by_sys: dict[str, list] = {}
    for site in active:
        name = site.get("system") or "Unknown"
        if name not in by_sys:
            order.append(name)
            by_sys[name] = []
        by_sys[name].append(site)
    for sys_name in order:
        open_sys = expanded_sys.setdefault(sys_name, True)
        rows.append(("toggle", f"{'▼' if open_sys else '▶'} {sys_name}", "system", sys_name))
        if not open_sys:
            continue
        for site in by_sys[sys_name]:
            mid = site.get("market_id")
            current = docked and mid == cur_mid
            name = site.get("station") or site.get("system", "Unknown")
            pct = round(site.get("progress", 0.0) * 100)
            is_open = expanded.setdefault(mid, True)
            pfx = "[bold cyan]▶ [/bold cyan]" if current else ""
            rows.append(("toggle", f"  {'▼' if is_open else '▶'} {pfx}[bold cyan]{name}[/bold cyan]  {pct}%",
                         "site", mid))
            if not is_open:
                continue
            resources = site.get("resources", {}) or {}
            hold = cargo if current else {}
            clear = R.kv("   Stop tracking", "Clear  ›", "val dim", action=f"clear:{mid}")
            if not resources:
                rows.append(R.text("     (dock to load requirements)"))
                rows.append(clear)
                continue
            remaining = [(k, inf) for k, inf in resources.items() if inf["provided"] < inf["required"]]
            if not remaining:
                rows.append(R.text("     [green]All resources delivered![/green]"))
                rows.append(clear)
                continue
            remaining.sort(key=lambda x: -(x[1]["required"] - x[1]["provided"]))
            total = 0
            for key, inf in remaining:
                needed = inf["required"] - inf["provided"]
                total += needed
                c = hold.get(key, {})
                have = c.get("count", 0) if isinstance(c, dict) else int(c)
                text = f"{needed:,} needed" + (f" ({min(have, needed):,} in hold)" if have > 0 else "")
                if have >= needed:
                    text = f"[green]{text}[/green]"
                elif have > 0:
                    text = f"[yellow]{text}[/yellow]"
                rows.append(R.kv(f"   {inf.get('name') or key}", text))
            rows.append(R.kv("   Total remaining", f"{total:,} t"))
            rows.append(clear)
    for site in (x for x in sites if x.get("complete")):
        rows.append(R.text(f"[green]✓ {site.get('station') or site.get('system', 'Unknown')} — complete[/green]"))
    for site in (x for x in sites if x.get("failed")):
        rows.append(R.text(f"[red]✗ {site.get('station') or site.get('system', 'Unknown')} — failed[/red]"))
    return Tab("colonisation", "Colonization", rows)
