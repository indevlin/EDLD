"""core/eng_trade.py — the nearest material traders of each kind.

Spansh is asked for the nearest stations with a Material Trader; each is
sorted into raw, manufactured or encoded by the trader it names, or failing
that by the station's economy, which decides the trader a station gets.
"""
from __future__ import annotations

#: Economy → trader kind.
_ECONOMY = {"extraction": "raw", "refinery": "raw", "industrial": "mfc",
            "high tech": "enc", "military": "enc"}
_NAMED = {"raw": "raw", "manufactured": "mfc", "encoded": "enc"}


def trader_kind(rec: dict) -> str:
    """"raw", "mfc", "enc", or "" for a station record from Spansh."""
    named = str(rec.get("material_trader") or "").strip().lower()
    if named in _NAMED:
        return _NAMED[named]
    for key in ("primary_economy", "economy"):
        kind = _ECONOMY.get(str(rec.get(key) or "").strip().lower())
        if kind:
            return kind
    return ""


def _here(core):
    try:
        x, y, z = (float(v) for v in getattr(core.state, "pilot_star_pos", None))
        return {"x": x, "y": y, "z": z}
    except (TypeError, ValueError):
        return None


def nearest_traders(core, kinds, per_kind: int = 3) -> dict:
    """{kind: [{system, station, ly, ls}]}, nearest first; {} when the
    commander's position or Spansh is not to be had."""
    want = [k for k in kinds if k in ("raw", "mfc", "enc")]
    sp = (getattr(core, "_plugins", None) or {}).get("spansh")
    here = _here(core)
    if not want or sp is None or here is None:
        return {}
    out: dict[str, list] = {k: [] for k in want}
    found = sp.stations_near(here, "Material Trader", size=60) or []
    for rec in found:
        kind = trader_kind(rec)
        if kind in out and len(out[kind]) < per_kind:
            out[kind].append({
                "system": str(rec.get("system_name") or rec.get("system") or ""),
                "station": str(rec.get("name") or ""),
                "ly": rec.get("distance"),
                "ls": rec.get("distance_to_arrival"),
            })
    return out
