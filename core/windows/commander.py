"""core/windows/commander.py — the Commander window: who the commander is (Info,
Ranks, Wallet) and what they own (Ships, Modules, Carrier, S. Carrier).

EDCARS splits the window: the identity tabs stay in Command, the fleet tabs go
to Fleet.
"""
from __future__ import annotations

from core.windows import R, Tab, cr as _credits, health_cls
from core.windows.ship import fmt_health


def headers(core) -> tuple[str, str]:
    """The two lines over the tabs: the commander and what they are in, and
    the squadron."""
    s = core.state
    name = getattr(s, "pilot_name", "") or ""
    mode = getattr(s, "vessel_mode", "ship")
    if name:
        if mode == "on_foot":
            suit = (getattr(s, "suit_name", "") or "").upper() or "ON FOOT"
            detail = (getattr(s, "suit_loadout", "") or "").upper()
            hdr1 = f"CMDR {name} - {detail} ({suit})" if detail else f"CMDR {name} - {suit}"
        elif mode == "srv":
            hdr1 = f"CMDR {name} - {(getattr(s, 'srv_type', '') or '').upper() or 'SRV'}"
        else:
            hdr1 = f"CMDR {name}" + (" [IN FIGHTER]" if getattr(s, "cmdr_in_slf", False) else "")
    else:
        hdr1 = "COMMANDER"
    sq_rank = getattr(s, "pilot_squadron_rank", "") or ""
    sq_name = getattr(s, "pilot_squadron_name", "") or ""
    sq_tag = getattr(s, "pilot_squadron_tag", "") or ""
    hdr2 = ""
    if sq_name:
        hdr2 = (f"{sq_rank.upper()} - " if sq_rank else "") + sq_name.upper() + \
               (f" [{sq_tag.upper()}]" if sq_tag else "")
    return hdr1, hdr2


from core.ui_helpers import pp_rank_progress  # noqa: E402


def _shields(s) -> tuple[str, str]:
    up = getattr(s, "ship_shields", None)
    if up is None:
        return "—", "val dim"
    if up:
        return "Up", "val health-good"
    if getattr(s, "ship_shields_recharging", False):
        return "Recharging", "val health-warn"
    return "Down", "val health-crit"


def _hull(s) -> tuple[str, str]:
    exact = getattr(s, "ship_hull_exact", None)
    if exact is not None:
        return fmt_health(exact), f"val {health_cls(int(exact * 100))}"
    pct = getattr(s, "ship_hull", None)
    if pct is None:
        return "—", "val dim"
    return f"{pct}%", f"val {health_cls(pct)}"


def _fuel(s) -> tuple[str, str]:
    from core.state import FUEL_CRIT_THRESHOLD, FUEL_WARN_THRESHOLD
    current = getattr(s, "fuel_current", None)
    tank = getattr(s, "fuel_tank_size", None)
    if current is None or not tank or tank <= 0:
        return "—", "val dim"
    text = f"{current / tank * 100:.0f}%"
    burn = getattr(s, "fuel_burn_rate", None)
    if burn and burn > 0:
        secs = (current / burn) * 3600
        hours, mins = int(secs // 3600), int((secs % 3600) // 60)
        text += f"  (~{hours}h {mins}m)" if hours else f"  (~{mins}m)"
    if current < tank * FUEL_CRIT_THRESHOLD:
        return text, "val health-crit"
    if current < tank * FUEL_WARN_THRESHOLD:
        return text, "val health-warn"
    return text, "val health-good"


def home_line(core) -> tuple[str, str]:
    """(Home System row value, "→ name")."""
    s = core.state
    cmdr = (getattr(core, "_plugins", None) or {}).get("commander")
    if not cmdr:
        return "—", ""
    home = cmdr.get_home_location()
    if not home:
        return "unknown", ""
    name = home["name"]
    system = home.get("system", name)
    is_stn = home.get("is_station", name != system and bool(system))
    display = f"{name}  ({system})" if is_stn and system and system != name else name
    dist = cmdr.home_distance_ly(getattr(s, "pilot_star_pos", None))
    if dist is not None:
        display += f"  |  {dist:,.0f} ly"
    return display, f"→ {name}"


def _home_row(core) -> tuple:
    """Home System; pressable (panel action "home") when search is available."""
    value = home_line(core)[0]
    plugins = getattr(core, "_plugins", None) or {}
    if plugins.get("spansh") is None or plugins.get("commander") is None:
        return R.kv("Home System", value)
    if value in ("unknown", "—"):
        value = "Set…"
    return R.kv("Home System", f"{value}  ›", "val", action="home")


def info(core) -> Tab:
    s = core.state
    body = "—"
    if getattr(s, "pilot_body", None):
        body = s.pilot_body
        if s.pilot_system and body.startswith(s.pilot_system):
            body = body[len(s.pilot_system):].lstrip()
        body = body or "—"
    pprank = "—"
    if getattr(s, "pp_rank", None):
        merits = getattr(s, "pp_merits_total", None)
        if merits is not None:
            frac = pp_rank_progress(s.pp_rank, merits)[0]
            pprank = f"Rank {s.pp_rank}  {int(frac * 100)}%"
        else:
            pprank = f"Rank {s.pp_rank}"
    rows = [R.rule(),
            R.kv("Mode", getattr(s, "pilot_mode", None) or "—"),
            _home_row(core),
            R.kv("Current System", getattr(s, "pilot_system", None) or "—"),
            R.kv("Location", body),
            R.rule(),
            R.kv("Power", getattr(s, "pp_power", None) or "—"),
            R.kv("PP Rank", pprank),
            R.rule(),
            R.kv("Shields", *_shields(s)),
            R.kv("Hull", *_hull(s)),
            R.kv("Fuel", *_fuel(s))]
    return Tab("info", "Info", rows)


def ranks(core) -> Tab:
    from core import ranks as RK
    rows = [R.kv(label, value) for label, value in RK.rows(core.state)]
    return Tab("ranks", "Ranks", rows or [R.text("No ranks yet — they come with the next login.", "dim")])


def _all_ships(s) -> list:
    current = getattr(s, "assets_current_ship", None)
    stored = list(getattr(s, "assets_stored_ships", []) or [])
    cid = (current or {}).get("ship_id")
    if cid:
        stored = [x for x in stored if x.get("ship_id") != cid]
    return [x for x in ([current] if current else []) + stored if x]


def wallet(core) -> Tab:
    from core.ui_helpers import normalise_carrier
    s = core.state
    bal = getattr(s, "assets_balance", None)
    ships_val = sum(x.get("value", 0) for x in _all_ships(s))
    mods_val = sum(m.get("value", 0) for m in getattr(s, "assets_stored_modules", []) or [])
    carrier = getattr(s, "assets_carrier", None)
    fc_mats = getattr(s, "assets_fc_materials", None) or []
    cargo_val = sum(m.get("price", 0) * m.get("stock", 0) for m in fc_mats)
    hull_val = normalise_carrier(carrier)["hull_value"] if carrier else 0
    h = {k: getattr(s, a, 0) or 0 for k, a in (
        ("bounties", "holdings_bounties"), ("bonds", "holdings_bonds"),
        ("trade", "holdings_trade"), ("carto", "holdings_cartography"),
        ("exobio", "holdings_exobiology"))}
    risk = sum(h.values())
    total_wealth = getattr(s, "assets_total_wealth", None)
    if total_wealth is not None:
        nw = int(total_wealth) + cargo_val + risk + hull_val
    else:
        nw = (bal or 0) + ships_val + mods_val + hull_val + cargo_val + risk
    rows = [R.hdr("Currencies"), R.kv("Credits", _credits(bal)),
            R.hdr("Fleet"), R.kv("Ships", _credits(ships_val)), R.kv("Modules", _credits(mods_val)),
            R.hdr("Fleet Carrier"),
            R.kv("Balance", _credits(carrier.get("balance")) if carrier and carrier.get("balance") else "—"),
            R.kv("Hull (decom.)", _credits(hull_val) if carrier else "—"),
            R.kv("Market listings", _credits(cargo_val) if carrier and cargo_val else "—"),
            R.hdr("Assets at Risk"),
            R.kv("Bounties", _credits(h["bounties"])), R.kv("Combat bonds", _credits(h["bonds"])),
            R.kv("Trade vouchers", _credits(h["trade"])),
            R.kv("Cartography (est.)", _credits(h["carto"])),
            R.kv("Exobiology (est.)", _credits(h["exobio"])),
            R.hdr("Net Worth"), R.kv("Total", _credits(nw) if nw else "—")]
    return Tab("wallet", "Wallet", rows)


def ships(core) -> Tab:
    rows = []
    for i, ship in enumerate(_all_ships(core.state)):
        name = ship.get("type_display") or ship.get("type", "Unknown")
        ident = ship.get("name", "")
        station = ship.get("station") or ""
        system = ship.get("system") or ""
        tag = "[green]▶[/green] " if i == 0 else "  "
        label = f"{tag}[bold]{name}[/bold]" + (f"  {ident}" if ident else "")
        loc = (f"{station}  ({system})" if station and system and station != system
               else system or "—")
        rows.append(R.kv(label, loc))
    return Tab("ships", "Ships", rows or [R.text("No ship data", "dim")])


def modules(core) -> Tab:
    mods = getattr(core.state, "assets_stored_modules", []) or []
    if not mods:
        return Tab("stored-modules", "Modules", [R.text("No stored modules", "dim")])
    by_system: dict[str, list] = {}
    for m in mods:
        by_system.setdefault(m.get("system") or "Unknown", []).append(m)
    rows = []
    for system in sorted(by_system):
        rows.append(R.hdr(system))
        for m in sorted(by_system[system], key=lambda x: x.get("name_display", "").lower()):
            name = m.get("name_display") or m.get("name_internal", "Unknown")
            eng = m.get("engineering", {}) or {}
            eng_tag = f"  G{eng.get('Level')}" if eng.get("BlueprintName") and eng.get("Level") else ""
            hot = "[red]⚠[/red] " if m.get("hot") else ""
            rows.append(R.kv(f"{hot}{name}{eng_tag}", _credits(m.get("value", 0))))
    return Tab("stored-modules", "Modules", rows)


def _carrier_rows(carrier, mats, hold, squadron) -> list:
    from core.ui_helpers import carrier_display_sections
    rows = []
    for title, entries in carrier_display_sections(carrier, mats, hold, squadron):
        rows.append(R.hdr(title))
        rows += [R.kv(label, value) for label, value in entries]
    return rows


def carrier(core) -> Tab | None:
    s = core.state
    if not getattr(s, "assets_carrier", None):
        return None
    return Tab("carrier", "Carrier", _carrier_rows(
        s.assets_carrier, getattr(s, "assets_fc_materials", None),
        getattr(s, "assets_carrier_hold", None), getattr(s, "pilot_squadron_name", "") or ""))


def squadron_carrier(core) -> Tab | None:
    s = core.state
    sq = getattr(s, "assets_squadron_carrier", None)
    if not sq:
        return None
    return Tab("squadron-carrier", "S. Carrier", _carrier_rows(
        sq, getattr(s, "assets_squadron_fc_materials", None),
        getattr(s, "assets_squadron_carrier_hold", None),
        getattr(s, "pilot_squadron_name", "") or ""))


def identity_tabs(core) -> list[Tab]:
    return [info(core), ranks(core), wallet(core)]


def fleet_tabs(core) -> list[Tab]:
    return [t for t in (ships(core), modules(core), carrier(core), squadron_carrier(core)) if t]
