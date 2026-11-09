"""core/windows/mining.py — the Mining window: Ring Hotspots, Surface Sites.

Each row is a ``cells`` row with action ``edit:<id>``. ``editable`` appends an
``Edit ›`` cell (desktop and terminal); EDAM receives the tables without it.
"""
from __future__ import annotations

from core.windows import R, Tab

HOTSPOT_HEADINGS = ("BODY", "RING", "TYPE", "RESERVE", "COMMODITY", "OVERLAP", "NOTE")
SITE_HEADINGS = ("BODY", "G", "SITE", "COMMODITY", "AMOUNT", "DENSITY", "RIGS", "DEPLETED")
EDIT = "Edit ›"


def _plugin(core, name: str):
    return (getattr(core, "_plugins", None) or {}).get(name)


def _table(headings: tuple, rows: list, editable: bool) -> list:
    heads = list(headings[1:]) + ([""] if editable else [])
    cells = [r for r in rows if r[0] == "cells"]
    widths = [max(len(h), *(len(r[2][i]) for r in cells)) for i, h in enumerate(heads)]
    return [R.table(headings[0], tuple(zip(heads, widths)))] + rows


def hotspot_cells(h: dict) -> list[str]:
    return [h.get("ring", "") or "", h.get("ring_type", "") or "",
            h.get("reserve_level", "") or "",
            h.get("commodity_display") or h.get("commodity", ""),
            h.get("overlap", "") or "", h.get("note", "") or ""]


def hotspots(core, query: str = "", editable: bool = True) -> Tab:
    """Ring hotspots by system, body, ring, commodity. Filter matches any
    column and the system name."""
    plugin = _plugin(core, "ring_hotspots")
    records = plugin.records() if plugin is not None else []
    q = (query or "").strip().lower()
    rows: list = []
    for h in records:
        cells = hotspot_cells(h)
        body = h.get("body_name") or ""
        if q and q not in " ".join([body, h.get("system_name") or ""] + cells).lower():
            continue
        label = body + ("  (test)" if h.get("is_test") else "")
        rows.append(R.cells(label, cells + ([EDIT] if editable else []), "val",
                            action=f"edit:{h['hotspot_id']}"))
    if not rows:
        text = ("No hotspots match" if q and records else "No ring hotspots recorded")
        return Tab("hotspots", "Ring Hotspots", [R.text(text, "dim")])
    return Tab("hotspots", "Ring Hotspots", _table(HOTSPOT_HEADINGS, rows, editable))


def site_cells(d: dict) -> list[str]:
    g = d.get("gravity")
    return [f"{float(g):.2f}" if g not in (None, "") else "",
            "" if d.get("signal_no") in (None, "") else f"#{d['signal_no']}",
            d.get("commodity_display") or d.get("commodity", ""),
            d.get("amount", "") or "",
            d.get("density_observed", "") or d.get("density_claimed", "") or "",
            "" if d.get("rigs") in (None, "") else str(d["rigs"]),
            (d.get("depleted_on") or "")[:10]]


def surface_sites(core, query: str = "", editable: bool = True) -> Tab:
    """Surface survey deposits, as the shared sheet lists them; each deposit's
    first note line under its row. A depleted site's row is dim."""
    plugin = _plugin(core, "surface_mining")
    records = plugin.deposit_records() if plugin is not None else []
    q = (query or "").strip().lower()
    rows: list = []
    for d in records:
        body = d.get("body_name") or d.get("system_name") or f"Body {d.get('body_id')}"
        cells = site_cells(d)
        notes = (d.get("notes") or "").strip()
        if q and q not in " ".join([body, d.get("system_name") or "", notes] + cells).lower():
            continue
        label = body + ("  (test)" if d.get("is_test") else "")
        rows.append(R.cells(label, cells + ([EDIT] if editable else []),
                            "val dim" if cells[-1] else "val",
                            action=f"edit:{d['deposit_id']}"))
        if notes:
            rows.append(R.text(f"   {notes.splitlines()[0][:120]}", "dim subnote"))
    if not rows:
        text = ("No sites match" if q and records else "No surface sites recorded")
        return Tab("sites", "Surface Sites", [R.text(text, "dim")])
    return Tab("sites", "Surface Sites", _table(SITE_HEADINGS, rows, editable))
