"""core/survey.py — survey routes: Road to Riches, Exomastery, Earth-like, ammonia
and terraformable worlds, trade runs and a sweep through chosen systems, all
from Spansh's routers.

The routers and their parameters (Spansh's own names):

    riches      /api/riches/route      source, range, radius, max_results,
                                       max_distance, min_value,
                                       use_mapping_value, avoid_thargoids, loop
    elw/aw/tf   the same, with body_types (repeated) — Spansh has no endpoint
                for one body type; its Earth-like and ammonia pages ask Road
                to Riches this way
    exobiology  /api/exobiology/route  source, range, radius, max_results,
                                       max_distance, min_value, loop
    tourist     /api/tourist/route     source, range, loop, destination
                                       (repeated), final_destination
    trade       /api/trade/route       system, station, starting_capital,
                                       max_cargo, max_hops, max_hop_distance,
                                       max_system_distance, max_price_age (s),
                                       requires_large_pad, allow_planetary,
                                       allow_player_owned, allow_prohibited,
                                       permit, unique
"""
from __future__ import annotations

import math
from typing import Any

#: kind → (label, Spansh router)
KINDS: dict[str, tuple[str, str]] = {
    "riches":     ("Road to Riches",            "riches"),
    "exobiology": ("Exomastery",                "exobiology"),
    "elw":        ("Earth-like worlds",         "riches"),
    "aw":         ("Ammonia worlds",            "riches"),
    "tf":         ("Terraformable worlds",      "riches"),
    "trade":      ("Trade run",                 "trade"),
    "tourist":    ("Sweep: chosen systems",     "tourist"),
}
ENDPOINT = {k: v[1] for k, v in KINDS.items()}

BODY_TYPES = {
    "elw": ["Earth-like world"],
    "aw":  ["Ammonia world"],
    "tf":  ["Rocky body", "High metal content world"],
}


def params(kind: str, v: dict, plan_range: float | None, credits: int | None,
           cargo_capacity: int | None, docked: tuple[str, str] | None) -> dict:
    """The router's parameters from the Survey tab's values (strings), with
    what the commander's ship and position supply. Raises ValueError with a
    message for the form."""
    from core.tooltab import number
    if kind not in KINDS:
        raise ValueError("Choose a kind of route.")
    rng = number(v, "range", 1, 1000, plan_range)
    if kind == "trade":
        if not docked and not (v.get("from") and v.get("station")):
            raise ValueError("Dock at the station to start from, or give its system and name.")
        system = v.get("from") or (docked[0] if docked else "")
        station = v.get("station") or (docked[1] if docked else "")
        return {
            "system": system, "station": station,
            "starting_capital": number(v, "capital", 1, 1e13, credits or 1_000_000, True),
            "max_cargo": number(v, "cargo", 1, 5000, cargo_capacity or 100, True),
            "max_hops": number(v, "hops", 1, 20, 5, True),
            "max_hop_distance": rng,
            "max_system_distance": number(v, "max_ls", 1, 1_000_000, 5000, True),
            "max_price_age": number(v, "price_age_days", 1, 365, 14, True) * 86400,
            "requires_large_pad": 1 if v.get("large_pad") else 0,
            "allow_planetary": 1 if v.get("planetary") else 0,
            "allow_player_owned": 0, "allow_prohibited": 0, "permit": 0, "unique": 0,
        }
    source = (v.get("from") or "").strip()
    if not source:
        raise ValueError("From is required.")
    loop = 1 if v.get("loop") else 0
    if kind == "tourist":
        stops = [s.strip() for s in str(v.get("systems") or "").replace(";", ",").split(",")
                 if s.strip()]
        if not stops:
            raise ValueError("List the systems to visit, separated by commas.")
        p = {"source": source, "range": rng, "loop": loop, "destination": stops}
        if (v.get("to") or "").strip() and not loop:
            p["final_destination"] = v["to"].strip()
        return p
    p = {
        "source": source, "range": rng, "loop": loop,
        "radius": number(v, "radius", 1, 1000, 25),
        "max_results": number(v, "max_results", 1, 1000, 25, True),
        "max_distance": number(v, "max_ls", 1, 1_000_000, 50000, True),
    }
    if kind == "exobiology":
        p["min_value"] = number(v, "min_value", 0, 1e10, 1_000_000, True)
        return p
    p["avoid_thargoids"] = 1
    if kind == "riches":
        p["min_value"] = number(v, "min_value", 0, 1e10, 300_000, True)
        p["use_mapping_value"] = 1
    else:
        p["body_types"] = BODY_TYPES[kind]
        p["min_value"] = number(v, "min_value", 0, 1e10, 100_000 if kind == "tf" else 1, True)
    return p


def _num(x, typ=float):
    try:
        return typ(x)
    except (TypeError, ValueError):
        return None


def _dist(a: dict, b: dict) -> float | None:
    try:
        return math.dist((float(a["x"]), float(a["y"]), float(a["z"])),
                         (float(b["x"]), float(b["y"]), float(b["z"])))
    except (KeyError, TypeError, ValueError):
        return None


def _bodies(raw: list) -> list[dict]:
    out = []
    for b in raw or []:
        if not isinstance(b, dict) or not b.get("name"):
            continue
        species = [{"genus": l.get("type"), "species": l.get("subtype"),
                    "value": _num(l.get("value"), int) or 0}
                   for l in b.get("landmarks") or [] if isinstance(l, dict)]
        out.append({
            "name": str(b["name"]),
            "subtype": b.get("subtype") or "",
            "ls": _num(b.get("distance_to_arrival")),
            "map_value": _num(b.get("estimated_mapping_value"), int) or 0,
            "scan_value": _num(b.get("estimated_scan_value"), int) or 0,
            "terraformable": bool(b.get("is_terraformable")),
            "species": species,
            "bio_value": _num(b.get("landmark_value"), int) or sum(s["value"] for s in species),
        })
    return out


def shape(kind: str, result: Any, params: dict) -> dict:
    """Spansh's answer as a route every view and the follower read:
    ``system_jumps`` rows (system, id64, x, y, z, jumps, distance_jumped)
    carrying ``bodies`` or ``trade`` for each stop."""
    rows: list[dict] = []
    if kind == "trade":
        hops = result if isinstance(result, list) else (result or {}).get("result") or []
        for h in hops:
            if not isinstance(h, dict) or not isinstance(h.get("source"), dict):
                continue
            src, dst = h["source"], h.get("destination") or {}
            if not rows or rows[-1]["trade"]["market_id"] != src.get("market_id"):
                rows.append(_trade_stop(src, None, [], 0, 0))
            buys = [{"name": c.get("name"), "amount": _num(c.get("amount"), int) or 0,
                     "price": (c.get("source_commodity") or {}).get("buy_price"),
                     "sell_price": (c.get("destination_commodity") or {}).get("sell_price")}
                    for c in h.get("commodities") or [] if isinstance(c, dict)]
            rows[-1]["trade"]["buy"] = buys
            rows.append(_trade_stop(dst, _num(h.get("distance")), buys,
                                    _num(h.get("total_profit"), int) or 0,
                                    _num(h.get("cumulative_profit"), int) or 0))
    elif kind == "tourist":
        res = result if isinstance(result, dict) else {}
        for j in res.get("system_jumps") or []:
            rows.append({"system": j.get("system"), "id64": j.get("id64"),
                         "x": j.get("x"), "y": j.get("y"), "z": j.get("z"),
                         "jumps": _num(j.get("jumps"), int) or 0,
                         "distance_jumped": _num(j.get("distance")) or 0, "bodies": []})
    else:
        systems = result if isinstance(result, list) else (result or {}).get("result") or []
        prev = None
        for s in systems:
            if not isinstance(s, dict) or not s.get("name"):
                continue
            row = {"system": s["name"], "id64": _num(s.get("id64"), int),
                   "x": s.get("x"), "y": s.get("y"), "z": s.get("z"),
                   "jumps": _num(s.get("jumps"), int) or 0,
                   "bodies": _bodies(s.get("bodies"))}
            row["distance_jumped"] = (_dist(prev, row) or 0) if prev else 0
            rows.append(row)
            prev = row
    if not rows:
        raise ValueError("no stops")
    rows[0]["jumps"] = 0
    total_value = sum(b["map_value"] + b["scan_value"] + b["bio_value"]
                      for r in rows for b in r.get("bodies") or [])
    out = {
        "system_jumps": rows,
        "total_jumps": sum(int(r.get("jumps") or 0) for r in rows),
        "distance": sum(float(r.get("distance_jumped") or 0) for r in rows),
        "source_system": rows[0]["system"],
        "destination_system": rows[-1]["system"],
        "range": params.get("range") or params.get("max_hop_distance"),
        "survey": kind,
        "_source": f"Spansh {KINDS[kind][0]}",
    }
    if total_value:
        out["value"] = total_value
    if kind == "trade":
        out["profit"] = max((r["trade"]["cumulative"] for r in rows), default=0)
    return out


def _trade_stop(place: dict, distance, sells: list, profit: int, cumulative: int) -> dict:
    return {
        "system": place.get("system"), "id64": place.get("system_id64"),
        "x": place.get("x"), "y": place.get("y"), "z": place.get("z"),
        "jumps": 1, "distance_jumped": distance or 0, "bodies": [],
        "trade": {"station": place.get("station"), "market_id": place.get("market_id"),
                  "ls": _num(place.get("distance_to_arrival"), int),
                  "sell": [dict(c, price=c.get("sell_price")) for c in sells],
                  "buy": [], "profit": profit, "cumulative": cumulative},
    }


# ── What is left to do at a stop ──────────────────────────────────────────────

def _short(system: str, body: str) -> str:
    return body[len(system):].strip() if system and body.startswith(system) else body


def todo(core, system: str, address, stop: dict) -> dict:
    """What is still to do at one survey stop, from the commander's own
    journal: {"map": [(short, subtype, value)], "sample": [(short, species,
    value)], "done": int, "trade": {...}}. Bodies already mapped and species
    already analyzed there are counted as done."""
    out = {"map": [], "sample": [], "done": 0, "trade": stop.get("trade")}
    bodies = stop.get("bodies") or []
    if not bodies:
        return out
    mapped, analysed = set(), set()
    try:
        from core.bodies_db import get_db
        db = get_db()
        cid = core.plugin_call("explo_sync", "current_commander_id")
        sid = db.system_id_by_address(int(address)) if address else None
        if sid and cid:
            known = db.system_bodies(sid, cid)
            for p in known.get("planets") or []:
                if p.get("mapped"):
                    mapped.add(p.get("name"))
                for f in db.planet_flora(p["id"], cid) or []:
                    if f.get("logged"):
                        analysed.add((p.get("name"), (f.get("species") or "").lower()))
    except Exception:
        pass
    for b in bodies:
        if b.get("species"):
            for sp in b["species"]:
                if (b["name"], str(sp.get("species") or "").lower()) in analysed:
                    out["done"] += 1
                else:
                    out["sample"].append((_short(system, b["name"]), sp.get("species") or "",
                                          sp.get("value") or 0))
        elif b["name"] in mapped:
            out["done"] += 1
        else:
            out["map"].append((_short(system, b["name"]), b.get("subtype") or "",
                               (b.get("map_value") or 0) + (b.get("scan_value") or 0)))
    return out


def todo_text(t: dict) -> str:
    """One line for the Ahead list and the arrival callout."""
    from core.emit import fmt_credits
    parts = []
    if t["map"]:
        v = sum(x[2] for x in t["map"])
        parts.append(f"{len(t['map'])} to map ({fmt_credits(v)})")
    if t["sample"]:
        v = sum(x[2] for x in t["sample"])
        parts.append(f"{len(t['sample'])} to sample ({fmt_credits(v)})")
    if t.get("trade"):
        tr = t["trade"]
        if tr.get("sell"):
            parts.append("sell " + ", ".join(f"{c['amount']} {c['name']}" for c in tr["sell"]))
        if tr.get("buy"):
            parts.append("buy " + ", ".join(f"{c['amount']} {c['name']}" for c in tr["buy"]))
        if tr.get("station"):
            parts.insert(0, str(tr["station"]))
    if not parts and t["done"]:
        parts.append("all done")
    return " · ".join(parts)


def todo_detail(t: dict) -> list[str]:
    """The arrival callout's list, body by body."""
    from core.emit import fmt_credits
    lines = [f"{b} — {sub} ({fmt_credits(v)})" for b, sub, v in t["map"]]
    lines += [f"{b} — {sp} ({fmt_credits(v)})" for b, sp, v in t["sample"]]
    return lines


def system_status(rec: dict) -> str:
    """"done", "partial" or "star" for a Spansh system record."""
    count = rec.get("body_count")
    bodies = [b for b in rec.get("bodies") or []
              if isinstance(b, dict) and b.get("type") in ("Star", "Planet")]
    if isinstance(count, int) and count > 0 and len(bodies) >= count:
        return "done"
    return "partial" if len(bodies) > 1 else "star"
