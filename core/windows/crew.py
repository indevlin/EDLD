"""
core/windows/crew.py — the Crew pane: the NPC crew member, their fighter,
and what they have been paid.

The pane is a fixed set of lines — a name line with the fighter's type
beside it, the crew member's combat rank, then SLF, Hired, Active and Paid —
so ``crew`` returns them by name and both interfaces fill their own widgets;
``tab`` gives the same as rows for EDAM.

Paid is a floor, always shown "≥": the game pays wages it writes no event
for, so the journal's total is never the whole of it.
"""
from __future__ import annotations

from datetime import datetime, timezone

from core.windows import R, Tab, cr, health_cls

COMBAT_RANKS = [
    "Harmless", "Mostly Harmless", "Novice", "Competent", "Expert",
    "Master", "Dangerous", "Deadly", "Elite",
    "Elite I", "Elite II", "Elite III", "Elite IV", "Elite V",
]


def crew(core) -> dict:
    """{"name", "type", "rank", "slf": (value, classes) or None when there
    is no fighter bay, "hired", "active", "paid"}."""
    from core.ui_helpers import fmt_crew_active
    s = core.state
    if not (getattr(s, "crew_name", None) and getattr(s, "crew_active", False)):
        return {"name": "No NPC crew", "type": "", "rank": "", "slf": ("—", "val"),
                "hired": "—", "active": "—", "paid": "—", "none": True}

    full = (getattr(s, "slf_type", "") or "").strip()
    if "(" in full and full.endswith(")"):
        i = full.index("(")
        base, variant = full[:i].strip(), full[i + 1:-1].strip()
    else:
        base, variant = full, ""
    slf_label = f"{base} ({variant})" if base and variant else (base or variant)

    name = f"CREW: {s.crew_name or 'NPC'}" + ("  [IN FIGHTER]" if s.cmdr_in_slf else "")
    rank = ""
    if s.crew_rank is not None and 0 <= s.crew_rank < len(COMBAT_RANKS):
        rank = f"Combat Rank: {COMBAT_RANKS[s.crew_rank]}"

    slf = None
    if s.has_fighter_bay:
        spent = (s.slf_stock_total > 0 and s.slf_destroyed_count >= s.slf_stock_total
                 and not s.slf_docked and not s.slf_deployed)
        if s.cmdr_in_slf:
            hull = f"{s.slf_hull}%" if s.slf_hull is not None else "—"
            slf = (f"CMDR Aboard  |  Hull {hull}", "val health-good")
        elif s.slf_docked:
            slf = ("SLF Docked", "val health-good")
        elif s.slf_deployed:
            hull = f"Hull {s.slf_hull}%" if s.slf_hull is not None else "Hull —"
            slf = (hull, f"val {health_cls(s.slf_hull)}" if s.slf_hull is not None
                   else "val health-good")
        elif spent:
            slf = ("All Spent", "val health-crit")
        else:
            slf = ("Destroyed", "val health-crit")

    hired = s.crew_hire_time.strftime("%d %b %Y") if s.crew_hire_time else "Unknown"
    active = (fmt_crew_active(datetime.now(timezone.utc) - s.crew_hire_time)
              if s.crew_hire_time else "—")
    paid = f"≥ {cr(s.crew_total_paid)}" if s.crew_total_paid and s.crew_total_paid > 0 else "—"
    return {"name": name, "type": slf_label, "rank": rank, "slf": slf,
            "hired": hired, "active": active, "paid": paid, "none": False}


def tab(core) -> Tab:
    c = crew(core)
    rows = [R.hdr(c["name"] + (f"  ·  {c['type']}" if c["type"] else ""))]
    if c["rank"]:
        rows.append(R.text(c["rank"], "dim"))
    if c["slf"] is not None:
        rows.append(R.kv("SLF", *c["slf"]))
    rows += [R.kv("Hired", c["hired"]), R.kv("Active", c["active"]), R.kv("Paid", c["paid"])]
    return Tab("crew", "Crew", rows)
