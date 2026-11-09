"""core/windows/career.py — the Career / Session window, tab by tab.

Session leads: it is the tab wanted at a glance mid-flight, where the
lifetime figures change on a scale of weeks.
"""
from __future__ import annotations

from core.summary_model import career_sections, session_sections
from core.windows import R, Tab, cr as _fmt_credits, num as _fmt

#: (title, id), in the order the tabs are drawn.
TABS = [
    ("Session", "session"),
    ("Summary", "summary"),
    ("Combat",  "combat"),
    ("Explore", "explore"),
    ("Exobio",  "exobio"),
    ("Mining",  "mining"),
    ("Trade",   "trade"),
    ("Credits", "credits"),
    ("Carrier", "carrier"),
    ("PPlay",   "powerplay"),
]


def _fmt_distance(n) -> str:
    try:
        v = float(n)
    except (TypeError, ValueError):
        return "—"
    if v >= 1_000_000:
        return f"{v / 1_000_000:.2f}M ly"
    if v >= 1_000:
        return f"{v:,.0f} ly"
    return f"{v:.2f} ly"


def _fmt_pledged(iso_ts) -> str:
    """Render a pledge start as a date plus elapsed days."""
    if not iso_ts:
        return ""
    try:
        from datetime import datetime, timezone
        when = datetime.fromisoformat(str(iso_ts).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return ""
    days = (datetime.now(timezone.utc) - when).days
    stamp = when.strftime("%Y-%m-%d")
    if days < 0:
        return stamp
    if days == 0:
        return f"{stamp}  (today)"
    if days == 1:
        return f"{stamp}  (1 day)"
    return f"{stamp}  ({days} days)"


# ── Summary tab ───────────────────────────────────────────────────────────

def _sections_rows(sections) -> list:
    rows: list = []
    for section in sections:
        rows.append(R.hdr(section["title"]))
        for row in section["rows"]:
            if row["kind"] == "sub":
                rows.append(R.text(row["label"], "dim"))
                continue
            value = row["value"]
            if row.get("rate"):
                value = f"{value}  {row['rate']}"
            rows.append(R.kv(row["label"], value))
    return rows


def _summary(core) -> list:
    """Render the career-scoped summary from the shared summary model."""
    try:
        sections = career_sections(core)
    except Exception:
        sections = []

    if not sections:
        hist = core._plugins.get("journal_history")
        msg = ("Lifetime scan in progress…"
               if hist is not None and not hist.scan_done.is_set()
               else "No career data yet")
        return [R.text(msg, "dim")]

    widgets: list = []
    for section in sections:
        widgets.append(R.hdr(section["title"]))
        for row in section["rows"]:
            if row["kind"] == "sub":
                widgets.append(R.text(row["label"], "dim"))
                continue
            value = row["value"]
            if row.get("rate"):
                value = f"{value}  {row['rate']}"
            widgets.append(R.kv(row["label"], value))
    return widgets

# ── Combat ────────────────────────────────────────────────────────────────

def _combat(core, cmb, bank, combat, finance) -> list:
    rows = []
    kills = cmb.get("Bounties_Claimed", 0) or combat.get("kill_count", 0)
    if kills:
        rows.append(R.kv("Kills", _fmt(kills)))
    bp = _fmt_credits(cmb.get("Bounty_Hunting_Profit")
                      or combat.get("bounties_earned"))
    if bp != "—":
        rows.append(R.kv("Bounties earned", bp))
    cb = _fmt_credits(cmb.get("Combat_Bond_Profits")
                      or combat.get("bonds_earned"))
    if cb != "—":
        rows.append(R.kv("Combat bonds", cb))
    if cmb.get("Assassinations"):
        rows.append(R.kv("Assassinations", _fmt(cmb.get("Assassinations"))))
    if bank.get("Insurance_Claims"):
        rows.append(R.kv("Deaths", _fmt(bank.get("Insurance_Claims"))))
    if bank.get("Spent_On_Insurance"):
        rows.append(R.kv("Rebuy costs",
                            _fmt_credits(bank.get("Spent_On_Insurance"))))

    # Voucher status — issued vs redeemed.
    vouchers = finance.get("vouchers", {})
    bi = vouchers.get("bounty_issued",   0)
    br = vouchers.get("bounty_redeemed", 0)
    ki = vouchers.get("bonds_issued",    0)
    kr = vouchers.get("bonds_redeemed",  0)
    if bi or br or ki or kr:
        rows.append(R.hdr("Voucher status"))
        if bi:
            rows.append(R.kv("Bounties issued",   _fmt_credits(bi)))
            rows.append(R.kv("Bounties redeemed", _fmt_credits(br)))
            pending = max(bi - br, 0)
            if pending:
                rows.append(R.kv("Bounties unredeemed", _fmt_credits(pending)))
        if ki:
            rows.append(R.kv("Bonds issued",      _fmt_credits(ki)))
            rows.append(R.kv("Bonds redeemed",    _fmt_credits(kr)))
            pending = max(ki - kr, 0)
            if pending:
                rows.append(R.kv("Bonds unredeemed", _fmt_credits(pending)))

    if not rows:
        rows.append(R.text("No combat activity logged", "dim"))
    return rows

# ── Explore ───────────────────────────────────────────────────────────────

def _explore(core, expl, carto, career) -> list:
    # Journal-derived FSS/DSS counts are authoritative — the
    # Statistics Planets_Scanned_To_Level_2/3 fields are unreliable.
    fss = career.get("fss_scanned") or expl.get("Planets_Scanned_To_Level_2")
    dss = career.get("dss_mapped")  or expl.get("Planets_Scanned_To_Level_3")

    rows = [
        R.kv("Systems visited",  _fmt(expl.get("Systems_Visited"))),
        R.kv("Hyperspace jumps", _fmt(expl.get("Total_Hyperspace_Jumps"))),
        R.kv("Distance",
                _fmt_distance(expl.get("Total_Hyperspace_Distance"))),
        R.kv("Planets FSS-scanned", _fmt(fss)),
        R.kv("Planets DSS-mapped",  _fmt(dss)),
        R.kv("First discoveries", _fmt(career.get("first_discoveries"))),
        R.kv("First mapped",      _fmt(career.get("first_mapped"))),
        R.kv("Exploration profit",
                _fmt_credits(expl.get("Exploration_Profits")
                             or carto.get("sold_total"))),
        R.kv("Highest payout", _fmt_credits(expl.get("Highest_Payout"))),
    ]
    for key, label in (
        ("elw",           "Earth-likes"),
        ("water_world",   "Water worlds"),
        ("ammonia_world", "Ammonia worlds"),
        ("terraformable", "Terraformables"),
        ("neutron_star",  "Neutron stars"),
        ("black_hole",    "Black holes"),
    ):
        n = career.get(key)
        if n:
            rows.append(R.kv(label, _fmt(n)))
    return rows

# ── Exobiology ────────────────────────────────────────────────────────────

def _exobio(core, exo, exobio) -> list:
    rows = [
        R.kv("Samples analyzed",
                _fmt(exo.get("Organic_Data") or exobio.get("sample_count"))),
        R.kv("Species encountered", _fmt(exo.get("Organic_Species_Encountered"))),
        R.kv("Genera encountered",  _fmt(exo.get("Organic_Genus_Encountered"))),
        R.kv("Systems",  _fmt(exo.get("Organic_Systems"))),
        R.kv("Total sold",
                _fmt_credits(exo.get("Organic_Data_Profits")
                             or exobio.get("sold_total"))),
        R.kv("First-logged",       _fmt(exo.get("First_Logged"))),
        R.kv("First-logged profit", _fmt_credits(exo.get("First_Logged_Profits"))),
    ]
    by_genus = exobio.get("by_genus_value", {}) or exobio.get("by_genus", {})
    if by_genus:
        rows.append(R.hdr("Credits by genus"))
        for genus, val in list(by_genus.items())[:15]:
            rows.append(R.kv(genus, _fmt_credits(val)))
    return rows

# ── Mining ────────────────────────────────────────────────────────────────

def _mining(core, mine) -> list:
    qty    = mine.get("Quantity_Mined", 0)
    mats   = mine.get("Materials_Collected", 0)
    profit = mine.get("Mining_Profits", 0)
    rows = []
    if qty:
        rows.append(R.kv("Tons refined", f"{qty:,} t"))
    if mats:
        rows.append(R.kv("Materials collected", _fmt(mats)))
    if profit:
        rows.append(R.kv("Mining profit", _fmt_credits(profit)))
        if qty:
            rows.append(R.kv("Per ton", _fmt_credits(profit / qty)))
    if not rows:
        rows.append(R.text("No mining activity logged", "dim"))
    return rows

# ── Trade ─────────────────────────────────────────────────────────────────

def _trade(core, trd, smg, finance) -> list:
    # Journal-derived figures are authoritative. Statistics.Trading.
    ms = finance.get("market_sell", {})
    j_count   = ms.get("count",   0)
    j_revenue = ms.get("revenue", 0)
    j_profit  = ms.get("profit",  0)

    market_profit = max(trd.get("Market_Profits", 0), j_profit)
    markets       = trd.get("Markets_Traded_With", 0)
    resources     = max(trd.get("Resources_Traded", 0), j_count)
    highest       = trd.get("Highest_Single_Transaction", 0)
    avg           = trd.get("Average_Profit", 0)

    rows = []
    if markets:   rows.append(R.kv("Markets visited", _fmt(markets)))
    if resources: rows.append(R.kv("Tons sold",     f"{resources:,} t"))
    if j_revenue: rows.append(R.kv("Gross revenue",   _fmt_credits(j_revenue)))
    if market_profit:
        rows.append(R.kv("Net profit", _fmt_credits(market_profit)))
    if highest:
        rows.append(R.kv("Largest transaction", _fmt_credits(highest)))
    if avg:
        rows.append(R.kv("Average per trade", _fmt_credits(avg)))
    if resources and market_profit:
        rows.append(R.kv("Profit per ton",
                            _fmt_credits(market_profit / resources)))

    smg_profit  = smg.get("Black_Markets_Profits", 0)
    smg_markets = smg.get("Black_Markets_Traded_With", 0)
    if smg_profit or smg_markets:
        rows.append(R.hdr("Black market"))
        if smg_markets:
            rows.append(R.kv("Black markets used", _fmt(smg_markets)))
        if smg_profit:
            rows.append(R.kv("Smuggling profit", _fmt_credits(smg_profit)))

    if not rows:
        rows.append(R.text("No trade activity logged", "dim"))
    return rows

# ── Credits ───────────────────────────────────────────────────────────────

def _credits(core, finance, carrier_scan, state) -> list:
    """Earnings & spending ledger + carrier-bank flow + voucher
    reconciliation.
    """
    f_in     = finance.get("in",  {}) or {}
    f_out    = finance.get("out", {}) or {}
    vouchers = finance.get("vouchers", {})

    rows: list = []
    if not f_in and not f_out:
        rows.append(R.text("No financial events logged yet", "dim"))
        return rows

    total_in = sum(f_in.values())
    if f_in:
        rows.append(R.hdr("Lifetime earnings"))
        for k, v in f_in.items():
            pct = (f"  {v / total_in * 100:.1f}%" if total_in else "")
            rows.append(R.kv(k, f"{_fmt_credits(v)}{pct}"))
        rows.append(R.kv("[b]Total earnings[/b]",
                            f"[b]{_fmt_credits(total_in)}[/b]"))

    total_out = sum(f_out.values())
    if f_out:
        rows.append(R.hdr("Lifetime spending"))
        for k, v in f_out.items():
            pct = (f"  {v / total_out * 100:.1f}%" if total_out else "")
            rows.append(R.kv(k, f"{_fmt_credits(v)}{pct}"))
        rows.append(R.kv("[b]Total spending[/b]",
                            f"[b]{_fmt_credits(total_out)}[/b]"))

    # Carrier bank flow — live balance preferred.
    live_carrier = (getattr(state, "assets_carrier", None) or {}
                    if state else {})
    cbb = (live_carrier.get("balance") or carrier_scan.get("bank_balance", 0))
    cbr = carrier_scan.get("bank_reserve",     0)
    cba = carrier_scan.get("bank_available",   0)
    cbd = carrier_scan.get("bank_deposits",    0)
    cbw = carrier_scan.get("bank_withdrawals", 0)
    if cbb or cbd or cbw:
        rows.append(R.hdr("Carrier bank"))
        if cbb: rows.append(R.kv("Current balance",      _fmt_credits(cbb)))
        if cbr: rows.append(R.kv("Reserve (locked)",     _fmt_credits(cbr)))
        if cba: rows.append(R.kv("Available",            _fmt_credits(cba)))
        if cbd: rows.append(R.kv("Lifetime deposits",    _fmt_credits(cbd)))
        if cbw: rows.append(R.kv("Lifetime withdrawals", _fmt_credits(cbw)))

    # Voucher reconciliation.
    bi = vouchers.get("bounty_issued",   0)
    br = vouchers.get("bounty_redeemed", 0)
    ki = vouchers.get("bonds_issued",    0)
    kr = vouchers.get("bonds_redeemed",  0)
    if bi or br or ki or kr:
        rows.append(R.hdr("Voucher reconciliation"))
        if bi:
            rows.append(R.kv("Bounty vouchers issued",   _fmt_credits(bi)))
            rows.append(R.kv("Bounty vouchers redeemed", _fmt_credits(br)))
            pending = max(bi - br, 0)
            if pending:
                rows.append(R.kv("Bounty vouchers unredeemed",
                                    _fmt_credits(pending)))
        if ki:
            rows.append(R.kv("Combat bonds issued",   _fmt_credits(ki)))
            rows.append(R.kv("Combat bonds redeemed", _fmt_credits(kr)))
            pending = max(ki - kr, 0)
            if pending:
                rows.append(R.kv("Combat bonds unredeemed",
                                    _fmt_credits(pending)))

    return rows

# ── Carrier ───────────────────────────────────────────────────────────────

def _carrier(core, carrier, fc_stat, state) -> list:
    if not carrier.get("stats") and not fc_stat:
        return [R.text("No fleet carrier data", "dim")]

    rows: list = []
    cstats = carrier.get("stats", {}) or {}

    rows.append(R.hdr("Carrier"))
    if carrier.get("name"):
        rows.append(R.kv("Name", carrier.get("name")))
    if carrier.get("callsign"):
        rows.append(R.kv("Callsign", carrier.get("callsign")))
    ctype = carrier.get("type", "")
    if ctype:
        rows.append(R.kv(
            "Type",
            "Squadron carrier" if ctype.lower().startswith("squadron")
            else "Fleet carrier"))
    usage = cstats.get("SpaceUsage", {})
    if usage:
        used = usage.get("TotalCapacity", 0) - usage.get("FreeSpace", 0)
        rows.append(R.kv(
            "Capacity used",
            f"{used:,} / {usage.get('TotalCapacity', 0):,} t"))
    if carrier.get("fuel_level"):
        rows.append(R.kv("Tritium on board",
                            f"{int(carrier.get('fuel_level')):,} t"))
    if carrier.get("jump_range"):
        rows.append(R.kv("Current jump range",
                            _fmt_distance(carrier.get("jump_range"))))

    live_carrier = (getattr(state, "assets_carrier", None) or {}
                    if state else {})
    cbb = (live_carrier.get("balance") or carrier.get("bank_balance", 0))
    cbr = carrier.get("bank_reserve",     0)
    cba = carrier.get("bank_available",   0)
    cbd = carrier.get("bank_deposits",    0)
    cbw = carrier.get("bank_withdrawals", 0)
    if cbb or cbd or cbw:
        rows.append(R.hdr("Bank"))
        if cbb: rows.append(R.kv("Current balance",      _fmt_credits(cbb)))
        if cbr: rows.append(R.kv("Reserve (locked)",     _fmt_credits(cbr)))
        if cba: rows.append(R.kv("Available",            _fmt_credits(cba)))
        if cbd: rows.append(R.kv("Lifetime deposits",    _fmt_credits(cbd)))
        if cbw: rows.append(R.kv("Lifetime withdrawals", _fmt_credits(cbw)))

    jumps    = fc_stat.get("FLEETCARRIER_TOTAL_JUMPS") or 0
    distance = fc_stat.get("FLEETCARRIER_DISTANCE_TRAVELLED") or 0
    if jumps or distance:
        rows.append(R.hdr("Lifetime travel"))
        if jumps:    rows.append(R.kv("Total jumps", _fmt(jumps)))
        if distance: rows.append(R.kv("Total distance", _fmt_distance(distance)))
        if jumps and distance:
            rows.append(R.kv("Average jump", _fmt_distance(distance / jumps)))

    rearm   = fc_stat.get("FLEETCARRIER_REARM_TOTAL")   or 0
    refuel  = fc_stat.get("FLEETCARRIER_REFUEL_TOTAL")  or 0
    repairs = fc_stat.get("FLEETCARRIER_REPAIRS_TOTAL") or 0
    if rearm or refuel or repairs:
        rows.append(R.hdr("Services rendered"))
        if refuel:  rows.append(R.kv("Refuel services",  _fmt(refuel)))
        if rearm:   rows.append(R.kv("Rearm services",   _fmt(rearm)))
        if repairs: rows.append(R.kv("Repair services",  _fmt(repairs)))

    return rows

# ── PowerPlay ─────────────────────────────────────────────────────────────

def _pplay(core, pp) -> list:
    """PowerPlay tab, current pledge only. Pledge total: server TotalMerits.
    """
    from core import weekly
    state = core.state
    pledge_total = (getattr(state, "pp_merits_total", None)
                    or pp.get("total_merits", 0) or 0)
    cm = getattr(state, "pp_cycle", None)
    cycle_total = cm.cycle() if cm is not None else 0
    pp_power    = (getattr(state, "pp_power", None)
                   or pp.get("power") or "")
    pp_rank     = getattr(state, "pp_rank", None)

    rows = []
    if pp_power:
        rows.append(R.kv("Pledged to", pp_power))
        since = _fmt_pledged(pp.get("pledged_since"))
        if since:
            rows.append(R.kv("  Since", since))
    if pp_rank is not None:
        rows.append(R.kv("Rank", str(pp_rank)))
    if pp_power:
        rows.append(R.kv("Merits this cycle", _fmt(cycle_total)))
        rows.append(R.kv("Cycle resets", weekly.until_reset()))
    if pledge_total:
        rows.append(R.kv("Merits this pledge", _fmt(pledge_total)))

    by_act  = {a: m for a, m in (pp.get("by_activity", {}) or {}).items() if m}
    pledge  = sum(by_act.values())     # journal tally: percentages only

    if by_act:
        rows.append(R.hdr("Merits by activity"))
        for act, m in by_act.items():
            pct = f"  {m / pledge * 100:.0f}%" if pledge else ""
            rows.append(R.kv(act, f"{_fmt(m)}{pct}"))

    by_sys = pp.get("system_merits", {}) or pp.get("by_system", {})
    by_sys = {s: m for s, m in by_sys.items() if m}
    if by_sys:
        rows.append(R.hdr("Merits by system (top 20)"))
        sys_total = sum(by_sys.values())
        for sys_name, merits in list(by_sys.items())[:20]:
            pct = (f"  {merits / sys_total * 100:.0f}%" if sys_total else "")
            rows.append(R.kv(sys_name, f"{_fmt(merits)}{pct}"))

    if not rows:
        rows.append(R.text("Not pledged to a power", "dim"))
    return rows


def _session(core) -> list:
    """This session's running totals, at session scope."""
    try:
        sections = session_sections(core)
    except Exception:
        sections = []
    return _sections_rows(sections) or [R.text("No session activity yet", "dim")]


def tabs(core) -> list[Tab]:
    """Every tab, rows in order."""
    out = {"session": _session(core), "summary": _summary(core)}
    hist = (getattr(core, "_plugins", None) or {}).get("journal_history")
    state = getattr(core, "state", None)
    if hist is None or not hist.scan_done.is_set():
        wait = [R.text("Lifetime scan in progress…", "dim")]
        for _t, key in TABS:
            out.setdefault(key, list(wait))
    else:
        r = hist.results
        stats = r.get("statistics", {})
        bank, expl = stats.get("Bank_Account", {}), stats.get("Exploration", {})
        exo, cmb = stats.get("Exobiology", {}), stats.get("Combat", {})
        mine, trd = stats.get("Mining", {}), stats.get("Trading", {})
        smg, fc_stat = stats.get("Smuggling", {}), stats.get("FLEETCARRIER", {})
        career, combat = r.get("career", {}), r.get("combat", {})
        carto, exobio = r.get("cartography", {}), r.get("exobiology", {})
        finance, carrier, pp = r.get("finance", {}), r.get("carrier", {}), r.get("powerplay", {})
        out["combat"] = _combat(core, cmb, bank, combat, finance)
        out["explore"] = _explore(core, expl, carto, career)
        out["exobio"] = _exobio(core, exo, exobio)
        out["mining"] = _mining(core, mine)
        out["trade"] = _trade(core, trd, smg, finance)
        out["credits"] = _credits(core, finance, carrier, state)
        out["carrier"] = _carrier(core, carrier, fc_stat, state)
        out["powerplay"] = _pplay(core, pp)
    return [Tab(key, title, out.get(key) or [R.text("—", "dim")]) for title, key in TABS]
