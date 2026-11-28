"""core/windows/squad.py — the Squad Goals window: the events of your squadron,
and those you were invited to, from ED Commanders.

Shown only to a commander signed in to Frontier (EDLD's Frontier CAPI sign-in)
who is in a squadron or holds an invitation (``access``); its leader tab only to
the squadron's verified leader. The desktop window, the terminal screen and
EDAM all draw ``events_tab``.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone

from core.windows import R, Tab, cr
from core.windows.objectives import fmt_reward, time_left

#: Measures: label, unit.
METRICS = {
    "mined_tons": ("Tons refined", "t"), "bounty_value": ("Bounty value earned", "cr"),
    "bond_value": ("Combat bond value earned", "cr"), "sold_tons": ("Tons sold", "t"),
    "sold_value": ("Credits from sales", "cr"), "construction_tons": ("Tons delivered to construction", "t"),
}

_STATE = {"upcoming": "Starts in", "open": "Ends in", "settling": "Ended: reading late journal days",
          "closing": "Ended: results being made final", "closed": "Final", "cancelled": "Cancelled"}


def plugin(core):
    return (getattr(core, "_plugins", None) or {}).get("edcmdr")


def access(core) -> dict:
    """{"show": the window, "lead": its leader tab, "why": what is missing}."""
    p = plugin(core)
    if p is None or not hasattr(p, "squad_access"):
        return {"show": False, "lead": False, "why": "ED Commanders is off."}
    try:
        return p.squad_access()
    except Exception:
        return {"show": False, "lead": False, "why": ""}


def amount(v, unit: str) -> str:
    return cr(v) if unit == "cr" else f"{int(v or 0):,} t"


def _iso(ts) -> str:
    return datetime.fromtimestamp(int(ts), timezone.utc).isoformat()


def _day(ts) -> str:
    return datetime.fromtimestamp(int(ts), timezone.utc).strftime("%d %b %Y")


def event_rows(ev: dict, me_pub: str | None, now=None) -> list:
    unit = ev.get("unit") or ""
    f = ev.get("filters") or {}
    rows = [R.text(f"[bold cyan]{ev.get('title') or 'Squad Goal'}[/bold cyan]")]
    if ev.get("note"):
        rows.append(R.text(ev["note"], "dim"))
    rows.append(R.kv("Measure", ev.get("metric_label") or ev.get("metric") or ""))
    where = ", ".join(s.get("name", "") for s in f.get("systems") or [])
    if where:
        rows.append(R.kv("Where", where))
    names = f.get("commodity_names") or f.get("commodities") or []
    if names:
        rows.append(R.kv("Commodities", ", ".join(names)))
    rows.append(R.kv("Days (UTC)", f"{_day(ev['starts'])} to {_day(ev['ends'])}" if ev.get("starts") else ""))
    state = ev.get("state") or ""
    if state == "upcoming":
        rows.append(R.kv(_STATE[state], time_left(_iso(ev["starts"]), now)))
    elif state == "open":
        rows.append(R.kv(_STATE[state], time_left(_iso(int(ev["ends"]) + 1), now)))
    else:
        rows.append(R.kv("Status", _STATE.get(state, state),
                         "val health-good" if state == "closed" else "val dim"))
        if state == "settling" and ev.get("finalizes"):
            rows.append(R.text("Results are final " + time_left(_iso(ev["finalizes"]), now)
                               + " from now: keep EDLD running so your journal is read in.", "dim"))
    rows.append(R.kv("Squadron total", amount(ev.get("total"), unit)))
    payout = ev.get("payout") or {}
    if payout.get("pool"):
        tiers = payout.get("tiers") or []
        pool = cr(ev.get("pool"))
        if tiers:
            reached = ev.get("tier")
            nxt = tiers[0 if reached is None else reached + 1] if reached is None or reached + 1 < len(tiers) else None
            pool += f" of {cr(payout['pool'])}"
            if nxt:
                pool += f" · next at {amount(nxt['target'], unit)}"
        rows.append(R.kv("Prize pool", pool))
    standings = ev.get("standings") or []
    if not standings:
        rows.append(R.text("No one has scored yet.", "dim"))
        return rows
    w = max(5, max(len(amount(r.get("value"), unit)) for r in standings))
    rows.append(R.table("COMMANDER", (("#", 3), ("AMOUNT", w), ("PAYOUT", 8))))
    shown = standings[:10]
    me = ev.get("me")
    if me and me not in shown:
        shown = shown + [me]
    for r in shown:
        mine = me_pub is not None and r.get("pub_id") == me_pub
        rows.append(R.cells(f"CMDR {r.get('name', '')}",
                            [str(r.get("rank", "")), amount(r.get("value"), unit),
                             fmt_reward(int(r.get("credits") or 0))],
                            "val highlight" if mine else "val"))
    return rows


BETA_NOTE = ("[bold yellow]BETA[/bold yellow] · Squad Goals is new and still being tested: check standings and payouts before "
             "paying anyone. Feedback and bug reports are welcome on the Indevlin Discord (discord.indevlin.com).")


def events_tab(core, now: datetime | None = None, beta: bool = True) -> Tab:
    """The events, under the beta notice unless ``beta`` is off (the desktop panel shows its own)."""
    p = plugin(core)
    view = p.squad_view() if p is not None and hasattr(p, "squad_view") else {"state": "off"}
    st = view.get("state")
    if st == "off":
        rows = [R.text("Switch on Options › ED Commanders to see your squadron's events.", "dim")]
    elif st == "none":
        rows = [R.text("Waiting for EDLD to read your journals.", "dim")]
    elif st == "switched-off":
        rows = [R.text("You are not taking part in your squadron's events: switch on "
                       "\"Take part in my squadron's events\" under Options › ED Commanders.", "dim")]
    elif st == "unverified":
        rows = [R.text(f"Verifying CMDR {view.get('name', '')} with your Frontier sign-in…", "dim")]
    else:
        rows = []
        if view.get("note"):
            rows.append(R.text(f"[yellow]{view['note']}[/yellow]"))
        events = view.get("events")
        if events is None:
            rows.append(R.text("Reading your squadron's events…", "dim"))
        elif not events:
            rows.append(R.text("No events running for your squadron.", "dim"))
        for i, ev in enumerate(events or []):
            if i or rows:
                rows.append(R.text(""))
            rows.extend(event_rows(ev, view.get("pub_id"), now))
    if beta:
        rows = [R.text(BETA_NOTE), R.text("")] + rows
    return Tab("squad", "Squad Goals · Beta", rows)


# ── The leader's payout preview ─────────────────────────────────────────────

def payouts(values: dict, p: dict) -> dict:
    """The server's payout rule (lib/SquadGoals.php payouts), for the leader's preview."""
    vals = {k: v for k, v in values.items() if v > 0}
    order = sorted(vals, key=lambda k: -vals[k])
    total = sum(vals.values())
    tiers = p.get("tiers") or []
    tier, pct = None, (0 if tiers else 100)
    for i, t in enumerate(tiers):
        if total >= int(t["target"]):
            tier, pct = i, int(t["pct"])
    pool = int(p.get("pool") or 0) * pct // 100
    floor = max(1, int(p.get("min") or 0))
    places = [float(x) for x in p.get("places") or []]
    bands = p.get("bands") or []
    n = sum(1 for k in order if vals[k] >= floor)
    w = []
    for i in range(n):
        if not places and not bands:
            w.append(float(vals[order[i]]))
        elif i < len(places):
            w.append(places[i])
        else:
            at = (i - len(places) + 1) / max(1, n - len(places)) * 100
            w.append(next((float(b["w"]) for b in bands if at <= float(b["pct"]) + 1e-9), 0.0))
    rows, i = [], 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and vals[order[j + 1]] == vals[order[i]]:
            j += 1
        span = range(i, j + 1)
        q = [k for k in span if k < n]
        avg = sum(w[k] for k in q) / len(span) if q else 0.0
        for k in span:
            rows.append({"cid": order[k], "value": vals[order[k]], "rank": i + 1, "weight": avg if k < n else 0.0})
        i = j + 1
    s = sum(r["weight"] for r in rows)
    for r in rows:
        r["credits"] = int(pool * r["weight"] // s) if s > 0 else 0
    return {"total": total, "tier": tier, "pool": pool, "standings": rows,
            "remainder": pool - sum(r["credits"] for r in rows)}


def preview(p: dict, people: int = 10) -> str:
    """What each place would be paid with ``people`` commanders who all reach the floor, one apart, the squadron
    having reached every tier: plain words for the leader's form."""
    if not int(p.get("pool") or 0):
        return "No prize pool: standings only."
    floor = max(1, int(p.get("min") or 0))
    vals = {f"#{i + 1}": floor + (people - i) * 1000 for i in range(people)}
    full = dict(p, tiers=[])
    res = payouts(vals, full)
    by_place = [r["credits"] for r in res["standings"]]
    paid = [c for c in by_place if c > 0]
    parts = [f"{_ordinal(i + 1)} {fmt_reward(c)}" for i, c in enumerate(paid[:5])]
    if len(paid) > 5:
        rest = sorted(set(paid[5:]), reverse=True)
        parts.append(f"{_ordinal(6)} to {_ordinal(len(paid))} "
                     + (fmt_reward(rest[0]) if len(rest) == 1 else f"{fmt_reward(rest[-1])} to {fmt_reward(rest[0])}")
                     + " each")
    line = f"With {people} commanders taking part: " + ", ".join(parts) + "."
    if len(paid) < len(by_place):
        line += " Nobody below " + _ordinal(len(paid)) + " is paid." if paid else " Nobody is paid."
    tiers = p.get("tiers") or []
    if tiers:
        line += " That is the full pool; " + "; ".join(
            f"{int(t['pct'])}% of it once the squadron reaches {int(t['target']):,}" for t in tiers) + "."
    return line


def _ordinal(n: int) -> str:
    return f"{n}{'th' if 10 <= n % 100 <= 20 else {1: 'st', 2: 'nd', 3: 'rd'}.get(n % 10, 'th')}"


# ── What the leader types ───────────────────────────────────────────────────

def parse_credits(s) -> int:
    """'100M', '1.5B', '250k', '100,000', '25000 t' or blank (0): credits or tons."""
    t = str(s or "").strip().replace(",", "").replace(" ", "").lower().removesuffix("cr").removesuffix("t")
    if not t:
        return 0
    m = re.fullmatch(r"(\d+(?:\.\d+)?)([kmb]?)", t)
    if not m:
        raise ValueError(f"'{s}' is not an amount such as 100M or 25,000.")
    return int(float(m.group(1)) * {"": 1, "k": 1e3, "m": 1e6, "b": 1e9}[m.group(2)])


def parse_weights(s) -> list[float]:
    """'50, 30, 20' as shares."""
    try:
        return [float(x) for x in str(s or "").replace(";", ",").split(",") if x.strip()]
    except ValueError:
        raise ValueError(f"'{s}' should be numbers with commas, such as 50, 30, 20.") from None
