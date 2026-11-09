"""core/windows/ship.py — the Ship window: the vessel's name, then Cargo,
Modules and Engineering.

Hull, shields and fuel live in the Commander window's Info tab.
"""
from __future__ import annotations

from core.windows import R, Tab, health_cls

#: Material grades, in the order the Engineering tab presents them.
GRADES = (
    ("raw",          "Raw"),
    ("manufactured", "Mfg"),
    ("encoded",      "Enc"),
    ("components",   "Comp"),
    ("items",        "Items"),
    ("consumables",  "Cons"),
    ("data",         "Data"),
)


def fmt_health(fraction: float) -> str:
    """A 0.0–1.0 health fraction. Wear accumulates slowly, so one decimal is
    kept below full health: 99.2% and 98.6% must not both read 99%."""
    pct = max(0.0, min(1.0, fraction)) * 100
    if pct >= 99.95:
        return "100%"
    return f"{pct:.1f}%"


def header(core) -> str:
    """Ship name, ident and type, on one line."""
    s = core.state
    parts = [p for p in ((getattr(s, "ship_name", "") or "").upper(),
                         (getattr(s, "ship_ident", "") or "").upper(),
                         (getattr(s, "pilot_ship", "") or "").upper()) if p]
    return " - ".join(parts) or "SHIP"


def srv_deployed(state) -> bool:
    return bool(getattr(state, "srv_type", "")
                or str(getattr(state, "vessel_mode", "")).lower() == "srv")


def price_source(core) -> tuple[str, str]:
    """(the market the manifest is priced at, the target market line)."""
    from core.ui_helpers import cargo_price_context
    s = core.state
    tgt = getattr(s, "cargo_target_market_name", "") or ""
    return (cargo_price_context(s)["source_label"],
            f"→ {tgt}" if tgt else "No target set")


def _hold(rows: list, items: dict, ctx: dict) -> int:
    from core.ui_helpers import cargo_manifest
    freight, limpets = cargo_manifest(items, ctx)
    total = 0
    for item in freight:
        line = item["price"] * item["count"]
        total += line
        name = ("⚠ " if item["stolen"] else "") + item["name"]
        rows.append(_cells(name, item["count"], item["price"], line))
    if limpets:
        rows.append(R.kv("", ""))
    for item in limpets:
        line = item["price"] * item["count"]
        total += line
        rows.append(_cells(item["name"], item["count"], item["price"], line))
    return total


def _cells(name, count, price, line):
    from core.ui_helpers import fmt_cargo_cr
    return R.cells(name, [f"{count} t", fmt_cargo_cr(price), fmt_cargo_cr(line)])


def _table():
    from core.ui_helpers import _CARGO_PRICE_W, _CARGO_QTY_W, _CARGO_VALUE_W
    return R.table("Commodity", (("Tons", _CARGO_QTY_W), ("Price", _CARGO_PRICE_W),
                                 ("Value", _CARGO_VALUE_W)))


def cargo(core) -> Tab:
    """The hold, cheapest per ton first so the jettison candidate leads,
    limpets last; and the SRV's while one is out."""
    from core.ui_helpers import cargo_price_context, fmt_cargo_cr, srv_tonnage
    from data.ships import srv_cargo_capacity
    s = core.state
    items = getattr(s, "cargo_items", {}) or {}
    cap = getattr(s, "cargo_capacity", 0) or 0
    used = sum(int(i.get("count", 0) or 0) for i in items.values())
    ctx = cargo_price_context(s)
    cap_str = f"{used}/{cap} t" if cap else (f"{used} t" if used else "—")

    rows: list = [R.hdr("Ship"), _table(), R.rule()]
    total = _hold(rows, items, ctx)
    rows.append(R.kv("", ""))
    rows.append(R.rule())
    rows.append(R.cells("Totals", [cap_str, "", fmt_cargo_cr(total)]))

    if srv_deployed(s):
        srv_items = getattr(s, "srv_cargo_items", None) or {}
        srv_used = int(getattr(s, "srv_cargo_count", 0) or 0)
        rows += [R.kv("", ""), R.hdr("SRV"), _table(), R.rule()]
        srv_total = _hold(rows, srv_items, ctx)
        tonnage = srv_tonnage(srv_used, srv_cargo_capacity(getattr(s, "srv_type", "")))
        if srv_items:
            rows.append(R.cells("Totals", [tonnage, "", fmt_cargo_cr(srv_total)]))
        else:
            # Count-only cargo event: tonnage is known, contents are not.
            rows.append(R.cells("Carrying", [tonnage, "", fmt_cargo_cr(0)]))
    return Tab("cargo", "Cargo", rows)


def modules(core) -> Tab:
    s = core.state
    plugin = (getattr(core, "_plugins", None) or {}).get("ship_health")
    if plugin is not None:
        mods = plugin.modules_sorted()
    else:
        mods = sorted(list(getattr(s, "ship_modules", []) or []),
                      key=lambda m: (int(m.get("priority", 0) or 0),
                                     float(m.get("health", 1.0) or 0.0),
                                     m.get("name_display", "")))
    damaged = sum(1 for m in mods if float(m.get("health", 1.0) or 0.0) < 1.0)
    if damaged:
        heading = f"MODULES — {damaged} damaged"
    elif mods:
        heading = f"MODULES — {len(mods)} all nominal"
    else:
        heading = "MODULES"
    if not mods:
        return Tab("modules", "Modules",
                   [R.text("No loadout data yet — dock or jump to populate.", "dim")], heading=heading)
    rows = []
    for m in mods:
        health = float(m.get("health", 1.0) or 0.0)
        key = f"{int(m.get('priority', 0) or 0) + 1}  {m.get('name_display') or m.get('slot') or '—'}"
        if not m.get("on", True):
            key += " (off)"
        cls = f"val {health_cls(int(health * 100))}" if health < 1.0 else "val dim"
        rows.append(R.kv(key, fmt_health(health), cls))
    return Tab("modules", "Modules", rows, heading=heading)


def engineering(core) -> Tab:
    s = core.state
    lk = getattr(s, "engineering_locker", {}) or {}
    buckets = {
        "raw":          getattr(s, "materials_raw", {}) or {},
        "manufactured": getattr(s, "materials_manufactured", {}) or {},
        "encoded":      getattr(s, "materials_encoded", {}) or {},
        "components":   lk.get("components", {}) or {},
        "items":        lk.get("items", {}) or {},
        "consumables":  lk.get("consumables", {}) or {},
        "data":         lk.get("data", {}) or {},
    }
    pages = []
    for key, label in GRADES:
        items = buckets[key]
        if not items:
            rows = [R.text("— none —", "dim")]
        else:
            rows = [R.kv(d.get("name_local", ""), str(d.get("count", 0)))
                    for _k, d in sorted(items.items(),
                                        key=lambda kv: kv[1].get("name_local", kv[0]).lower())]
        pages.append(Tab(key, label, rows))
    return Tab("engineering", "Engineering", pages=pages)


def tabs(core) -> list[Tab]:
    return [cargo(core), modules(core), engineering(core)]
