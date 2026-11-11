"""core/eng_trade.py — the nearest material traders of each kind.

The journals first: every station docked at that has a Material Trader, its
system's position, and — once a trade has been made there — the trader's kind
(MaterialTrade's TraderType). Spansh fills a kind the journals have too few
of, and only with stations it names the trader of; a trader is never guessed
from the station's economy.
"""
from __future__ import annotations

import math
from pathlib import Path

#: TraderType / Spansh's material_trader → kind.
_KIND = {"raw": "raw", "manufactured": "mfc", "encoded": "enc"}


def trader_kind(rec: dict) -> str:
    """"raw", "mfc", "enc", or "" for a station record Spansh does not name
    the trader of."""
    return _KIND.get(str(rec.get("material_trader") or "").strip().lower(), "")


def journal_traders(journal_dir) -> list[dict]:
    """[{market_id, station, system, ls, kind, pos}] for every station with a
    Material Trader docked at; kind "" until a trade there shows it, pos None
    when no jump into its system is in the journals."""
    from core.journal_index import index_for
    idx = index_for(Path(journal_dir))
    stations: dict[int, dict] = {}
    kinds: dict[int, str] = {}
    for _f, ev in idx.events(("Docked", "MaterialTrade")):
        mid = ev.get("MarketID")
        if mid is None:
            continue
        if ev.get("event") == "MaterialTrade":
            kind = _KIND.get(str(ev.get("TraderType") or "").lower())
            if kind:
                kinds[int(mid)] = kind
            continue
        services = {str(s).lower() for s in ev.get("StationServices") or []}
        if "materialtrader" in services:
            stations[int(mid)] = {"market_id": int(mid),
                                  "station": str(ev.get("StationName") or ""),
                                  "system": str(ev.get("StarSystem") or ""),
                                  "ls": ev.get("DistFromStarLS")}
        else:
            stations.pop(int(mid), None)
    want = {s["system"] for s in stations.values()}
    pos: dict[str, list] = {}
    if want:
        for _f, ev in idx.events(("FSDJump", "Location", "CarrierJump")):
            name = ev.get("StarSystem")
            if name in want and ev.get("StarPos"):
                pos[name] = ev["StarPos"]
    out = []
    for mid, st in stations.items():
        st = dict(st, kind=kinds.get(mid, ""), pos=pos.get(st["system"]))
        out.append(st)
    return out


def _here(core):
    try:
        x, y, z = (float(v) for v in getattr(core.state, "pilot_star_pos", None))
        return {"x": x, "y": y, "z": z}
    except (TypeError, ValueError):
        return None


def _ly(here, pos):
    if here is None or not pos:
        return None
    return math.dist((here["x"], here["y"], here["z"]), [float(v) for v in pos])


def nearest_traders(core, kinds, per_kind: int = 3) -> dict:
    """{kind: [{system, station, ly, ls, seen}]}, nearest first; ``seen`` is
    True for a trader the journals know."""
    want = [k for k in kinds if k in ("raw", "mfc", "enc")]
    if not want:
        return {}
    here = _here(core)
    out: dict[str, list] = {k: [] for k in want}
    known: set = set()
    try:
        mine = journal_traders(core.journal_dir)
    except Exception as exc:
        from core import debug as _dbg
        _dbg.log(f"  [eng_trade] traders not read from the journals: {type(exc).__name__}: {exc}")
        mine = []
    for st in sorted(mine, key=lambda s: (_ly(here, s["pos"]) is None,
                                           _ly(here, s["pos"]) or 0.0)):
        if st["kind"] in out and len(out[st["kind"]]) < per_kind:
            out[st["kind"]].append({"system": st["system"], "station": st["station"],
                                    "ly": _ly(here, st["pos"]), "ls": st["ls"], "seen": True})
            known.add(st["market_id"])
    short = [k for k in want if len(out[k]) < per_kind]
    sp = (getattr(core, "_plugins", None) or {}).get("spansh")
    if short and sp is not None and here is not None:
        for rec in sp.stations_near(here, "Material Trader", size=60) or []:
            kind = trader_kind(rec)
            mid = rec.get("market_id")
            if kind in short and len(out[kind]) < per_kind and mid not in known:
                out[kind].append({"system": str(rec.get("system_name") or ""),
                                  "station": str(rec.get("name") or ""),
                                  "ly": rec.get("distance"),
                                  "ls": rec.get("distance_to_arrival"), "seen": False})
        for k in out:
            out[k].sort(key=lambda s: (s["ly"] is None, s["ly"] or 0.0))
    return out
