"""
core/windows/exploration.py — the Exploration window: the system the
commander is in, each body's value as scanned and if mapped, and each body's
biology nested beneath it.

A heading names the system, a summary line counts what is known, and the
rows follow: one per body with its type and markers (★ worth mapping, T
terraformable, ◆n biological signals, ✓ mapped, FD first discovery, FF
first footfall), then for a body with biology its signals, its sampled
species with the clonal-distance aid while sampling, and the genera still to
find (✦ new in the codex for this region).
"""
from __future__ import annotations

from core.windows import R, cr

_TYPE_ABBR = {
    "earthlike body": "ELW", "water world": "WW", "ammonia world": "AW",
    "high metal content body": "HMC", "metal rich body": "MR",
    "rocky body": "Rocky", "rocky ice body": "RkIce", "icy body": "Icy",
    "sudarsky class i gas giant": "GGc1", "sudarsky class ii gas giant": "GGc2",
    "sudarsky class iii gas giant": "GGc3", "sudarsky class iv gas giant": "GGc4",
    "sudarsky class v gas giant": "GGc5",
}


def abbr(b: dict) -> str:
    if b["is_star"]:
        return f"*{b['type']}" if b["type"] else "*"
    return _TYPE_ABBR.get((b["type"] or "").lower(), (b["type"] or "?")[:5])


def markers(b: dict) -> str:
    m = []
    if b["high_value"]:
        m.append("★")
    if b["terraformable"]:
        m.append("T")
    if b["bio_signals"]:
        m.append(f"◆{b['bio_signals']}")
    if b["mapped"]:
        m.append("✓")
    if b.get("first_discovery"):
        m.append("FD")
    if b.get("first_footfall"):
        m.append("FF")
    return " ".join(m)


def short(n: int) -> str:
    if not n:
        return "—"
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M"
    if n >= 1_000:
        return f"{n / 1_000:.0f}K"
    return str(n)


def value_range(g: dict) -> str:
    lo, hi = g.get("value_min", 0), g.get("value_max", 0)
    if not hi:
        return ""
    return short(lo) if lo == hi else f"{short(lo)}–{short(hi)}"


def arrow(rel: float) -> str:
    return "↑↗→↘↓↙←↖"[int(((rel % 360) + 22.5) // 45) % 8]


def position(core) -> dict | None:
    """Surface position, for the exobiology clonal-distance aid."""
    st = getattr(core, "state", None)
    if st is None:
        return None
    return {"lat": getattr(st, "surface_latitude", None),
            "lon": getattr(st, "surface_longitude", None),
            "radius": getattr(st, "planet_radius", None),
            "heading": getattr(st, "surface_heading", None),
            "on_foot": getattr(st, "on_foot", False),
            "body": getattr(st, "current_body_name", "") or ""}


def bio_rows(b: dict) -> list:
    """A body's biology, indented under its own row."""
    rows: list = []
    done = "✓" if b["complete"] else f"{b['analysed']}/{b['bio_signals']}"
    focus = "▸ " if b.get("current") else ""
    rows.append(R.hdr(f"  {focus}{b['bio_signals']} bio · {done}"))
    if b["bio_signals"] and (b["value_min"] or b["value_max"]):
        vtxt = f"est. {short(b['value_min'])}–{short(b['value_max'])}"
        if b.get("value_max_possible", 0) > b["value_max"]:
            vtxt += f" (↑{short(b['value_max_possible'])})"
        ff = f"  [b]✦ first footfall ×{b['first_footfall_mult']}[/b]" if b["first_footfall"] else ""
        rows.append(R.text(f"    {vtxt}{ff}"))
    sampled = {f["genus"] for f in b["flora"]}
    for f in b["flora"]:
        stage = "✓" if f["logged"] else f"{f['stage']}/3"
        extra = "" if f["logged"] else f"  ≥{f['clonal']}m"
        rows.append(R.kv(f"    {f['name']}  {stage}", short(f["value"]) + extra,
                         "val" if f["logged"] else "val highlight"))
        aid = f.get("aid")
        if aid:
            cue = ""
            if aid.get("heading") is not None and aid.get("bearing") is not None:
                cue = arrow(aid["bearing"] - aid["heading"]) + " "
            status = "[green]clear ✓[/green]" if aid["ok"] else "[b]too close — move away[/b]"
            rows.append(R.text(f"        {cue}{aid['distance']} m to last · ≥{aid['clonal']} m · {status}"))
    for g in (b["predicted_genera"] if b["predicting"] else b["genera"]):
        if g["genus"] not in sampled:
            label = (f"    {g['genus']}" + ("  (cond.)" if g.get("gated") else "")
                     + ("  [cyan]✦ new in codex[/cyan]" if g.get("codex_new") else ""))
            rows.append(R.kv(label, value_range(g), "val dim"))
    return rows


def view(core) -> dict:
    """{"title", "summary", "rows"}: the heading, the summary line beneath
    it, and the bodies."""
    from core.explo_view import build_system_view
    from core.exobio_view import build_exobio_view
    from core.ui_helpers import explo_fault
    v = bio = err = None
    sync = (getattr(core, "_plugins", None) or {}).get("explo_sync")
    if sync is not None:
        try:
            v = build_system_view(sync.current_system_address(), sync.current_commander_id())
        except Exception as e:
            err = e
        # Biology is best-effort: a fault here must not blank the
        # cartographic view, which is the more commonly useful half.
        try:
            bio = build_exobio_view(sync.current_system_address(), sync.current_commander_id(),
                                    position=position(core))
        except Exception:
            bio = None
    if not v:
        return {"title": "—", "rows": [],
                "summary": explo_fault(core, err) or "No system data yet — honk to populate."}
    by_body: dict = {}
    for b in (bio or {}).get("bodies") or []:
        for key in (b.get("name"), b.get("short")):
            if key:
                by_body[str(key)] = b
    sysd, tot = v["system"], v["totals"]
    bits = [f"{tot['scanned']}/{sysd['body_count'] or tot['bodies']} bodies"]
    if tot["high_value"]:
        bits.append(f"{tot['high_value']} worth mapping")
    if tot["bio_bodies"]:
        bits.append(f"{tot['bio_bodies']} bio")
    bt = (bio or {}).get("totals") or {}
    if bt.get("total_signals"):
        bits.append(f"{bt.get('analysed', 0)}/{bt['total_signals']} sampled")
    if tot.get("first_discovery"):
        bits.append(f"{tot['first_discovery']} undiscovered")
    if tot.get("first_footfall"):
        bits.append(f"{tot['first_footfall']} footfall")
    bits.append(f"{cr(tot['value_now'])} / {cr(tot['value_max'])}")
    rows = []
    for b in v["bodies"]:
        key = f"{(b['short'] or b['name']):<8} {abbr(b):<6} {markers(b)}"
        if not b["is_star"] and not b["mapped"] and b["mapping_gain"] > 0:
            val = f"{cr(b['value_now'])} → {cr(b['value_max'])}"
        else:
            val = cr(b["value_now"])
        rows.append(R.kv(key, val, "val highlight" if b["high_value"]
                         else ("val dim" if b["mapped"] else "val")))
        biob = by_body.get(str(b.get("name"))) or by_body.get(str(b.get("short")))
        if biob:
            rows += bio_rows(biob)
    return {"title": sysd["name"] or "—", "summary": "  ·  ".join(bits), "rows": rows}
