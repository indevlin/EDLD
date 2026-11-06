"""
core/windows/objectives.py — the Objectives window: the mission board and
colonisation construction sites.

Missions: the massacre stack summarised by source faction — kills and reward
in two columns — with its height and any mixed targets, then every other
mission grouped by category. Colonisation: active sites grouped by system,
each with what it still needs and how much of that is in the hold; a system
or a site can be collapsed by clicking its heading.
"""
from __future__ import annotations

from core.windows import R, Tab


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


def missions(core) -> Tab:
    s = core.state
    detail = getattr(s, "mission_detail_map", {}) or {}
    rows: list = []
    if detail:
        factions: dict[str, dict] = {}
        target_factions, target_types = set(), set()
        total_reward = 0
        for info in detail.values():
            src = info.get("faction", "Unknown")
            f = factions.setdefault(src, {"kill_count": 0, "reward": 0})
            f["kill_count"] += int(info.get("kill_count", 0))
            f["reward"] += int(info.get("reward", 0))
            total_reward += int(info.get("reward", 0))
            if info.get("target_faction"):
                target_factions.add(info["target_faction"])
            tt = strip_target_type(info.get("target_type", ""))
            if tt:
                target_types.add(tt)
        heights = sorted((v["kill_count"] for v in factions.values()), reverse=True)
        n = len(getattr(s, "active_missions", []) or [])
        done = getattr(s, "missions_complete", 0)
        full = (getattr(core, "app_settings", None) or {}).get("FullStackSize", 20)
        rows.append(R.table("", (("Kills", 5), ("Reward", 8))))
        rows.append(R.cells("Active", [f"{n}/{full}", ""]))
        if done > 0:
            rows.append(R.cells("Redirected", [f"{done}/{n}", ""]))
        rows.append(R.hdr("By Source Faction"))
        for name in sorted(factions, key=lambda k: -factions[k]["kill_count"]):
            rows.append(R.cells(name, [str(factions[name]["kill_count"]),
                                       fmt_reward(factions[name]["reward"])]))
        rows.append(R.rule())
        rows.append(R.cells("Stack height", [str(heights[0] if heights else 0),
                                             fmt_reward(total_reward)]))
        if len(target_factions) > 1:
            rows.append(R.text(f"[yellow]⚠ Mixed targets: {', '.join(sorted(target_factions))}[/yellow]"))
        if len(target_types) > 1:
            rows.append(R.text(f"[yellow]⚠ Mixed types: {', '.join(sorted(target_types))}[/yellow]"))

    # Every other mission. Massacres are summarised above, so listing them
    # again would repeat the stack.
    board = getattr(s, "all_missions", {}) or {}
    others = {mid: m for mid, m in board.items() if m.get("category") != "Massacre"}
    if others:
        by_category: dict = {}
        for m in others.values():
            by_category.setdefault(m.get("category", "Other"), []).append(m)
        rows.append(R.hdr(f"Other Missions ({len(others)})"))
        for category in sorted(by_category):
            rows.append(R.text(category, "dim"))
            for m in sorted(by_category[category], key=lambda m: -int(m.get("reward", 0) or 0)):
                label = f"  {m.get('name') or 'Mission'}" + ("  [W]" if m.get("wing") else "")
                rows.append(R.kv(label, fmt_reward(int(m.get("reward", 0) or 0))))
                bits = []
                if m.get("count"):
                    bits.append(f"x{m['count']}")
                for key in ("commodity", "target", "target_faction"):
                    if m.get(key):
                        bits.append(str(m[key]))
                if m.get("passengers"):
                    bits.append(f"{m['passengers']} pax")
                if m.get("destination"):
                    bits.append(f"→ {m['destination']}")
                if m.get("status") and m["status"] != "Active":
                    bits.append(f"[green]{m['status']}[/green]")
                if bits:
                    rows.append(R.text("      " + "  ·  ".join(bits), "dim"))
    if not rows:
        rows = [R.text("No active missions", "dim")]
    return Tab("missions", "Missions", rows)


def colonisation(core, expanded: dict | None = None, expanded_sys: dict | None = None) -> Tab:
    """Sites by system. ``expanded`` (market id → bool) and ``expanded_sys``
    (system → bool) are the interface's own collapse state; a group not in
    them is open. Headings are ("toggle", text, "system" | "site", key)."""
    expanded = {} if expanded is None else expanded
    expanded_sys = {} if expanded_sys is None else expanded_sys
    s = core.state
    sites = getattr(s, "colonisation_sites", []) or []
    cargo = getattr(s, "cargo_items", {}) or {}
    docked = getattr(s, "colonisation_docked", False)
    cur_mid = getattr(s, "_colonisation_current_market_id", None)
    if not sites:
        return Tab("colonisation", "Colonisation",
                   [R.text("No construction sites tracked.\nDock at a depot to begin.", "dim")])
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
            if not resources:
                rows.append(R.text("     (dock to load requirements)"))
                continue
            remaining = [(k, inf) for k, inf in resources.items() if inf["provided"] < inf["required"]]
            if not remaining:
                rows.append(R.text("     [green]All resources delivered![/green]"))
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
    for site in (x for x in sites if x.get("complete")):
        rows.append(R.text(f"[green]✓ {site.get('station') or site.get('system', 'Unknown')} — complete[/green]"))
    for site in (x for x in sites if x.get("failed")):
        rows.append(R.text(f"[red]✗ {site.get('station') or site.get('system', 'Unknown')} — failed[/red]"))
    return Tab("colonisation", "Colonisation", rows)
