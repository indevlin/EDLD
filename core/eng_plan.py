"""core/eng_plan.py — what stands between a ship and the build planned for it.

``delta(current, target, stored, db)`` compares a fitting with a target build
slot by slot: the modules to buy or take out of storage, the blueprint grades
still to roll and the experimental effects still to apply. ``materials()``
totals what that work costs, and ``shortfall()`` sets it against what the
commander holds.

A grade takes as many rolls as its number — G1 one, G5 five, fifteen from
nothing to a full G5 — and a grade the target wants only part of takes that
share of its rolls, rounded up.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Optional

#: Kinds of material, in the order the windows list them.
KINDS = (("raw", "Raw"), ("mfc", "Manufactured"), ("enc", "Encoded"))
KIND_LABEL = dict(KINDS)
#: The most of one material a commander can hold, by grade.
CAPS = {1: 300, 2: 250, 3: 200, 4: 150, 5: 100}


def rolls_for(grade: int, fraction: float = 1.0) -> int:
    """Rolls to take ``grade`` from nothing to ``fraction`` complete."""
    if grade <= 0 or fraction <= 0:
        return 0
    return max(1, math.ceil(grade * min(1.0, fraction) - 1e-9))


def _eng(m: Optional[dict]) -> dict:
    return dict((m or {}).get("engineering") or {})


def _bp(e: dict) -> str:
    return str(e.get("BlueprintName") or "").lower()


def _fx(e: dict) -> str:
    return str(e.get("ExperimentalEffect") or "").lower()


@dataclass
class Step:
    """The work left on one slot."""
    slot: str
    item: str                          # the target module
    current: str = ""                  # what is fitted there now
    module: str = ""                   # "" | "purchase" | "stored"
    blueprint: str = ""                # journal BlueprintName
    grades: list = field(default_factory=list)   # [(grade, rolls)]
    effect: str = ""                   # journal ExperimentalEffect
    remove: bool = False               # fitted now, empty in the target

    @property
    def idle(self) -> bool:
        return not (self.module or self.grades or self.effect or self.remove)


def _index(mods) -> dict:
    out = {}
    for m in mods or []:
        slot = str(m.get("slot") or "").lower()
        if slot:
            out[slot] = m
    return out


def _item(m: Optional[dict]) -> str:
    """The module, the free variant a ship comes with counting as the same."""
    i = str((m or {}).get("item") or (m or {}).get("name_internal") or "").lower()
    return i[:-5] if i.endswith("_free") else i


def _stored_match(item: str, want_bp: str, stored: list, used: set) -> Optional[dict]:
    """The stored module of this kind that is furthest along the wanted
    blueprint, not already promised to another slot."""
    best, best_key = None, None
    for i, s in enumerate(stored or []):
        if i in used or _item(s) != item:
            continue
        e = _eng(s)
        key = ((_bp(e) == want_bp) if want_bp else not _bp(e),
               int(e.get("Level") or 0) if _bp(e) == want_bp else 0,
               float(e.get("Quality") or 0))
        if best_key is None or key > best_key:
            best, best_key = (i, s), key
    if best is None:
        return None
    used.add(best[0])
    return best[1]


def delta(current: list, target: dict, stored: Optional[list] = None) -> list[Step]:
    """The work left, slot by slot, in the target's order; slots already as
    planned are left out."""
    cur = _index(current)
    used: set = set()
    steps: list[Step] = []
    seen: set = set()
    for t in (target or {}).get("modules") or []:
        slot = str(t.get("slot") or "")
        key = slot.lower()
        seen.add(key)
        titem = _item(t)
        c = cur.get(key)
        step = Step(slot=slot, item=titem, current=_item(c))
        te = _eng(t)
        if _item(c) == titem:
            base = _eng(c)
        else:
            hit = _stored_match(titem, _bp(te), stored or [], used)
            step.module = "stored" if hit is not None else "purchase"
            base = _eng(hit)
        want = _bp(te)
        if want:
            step.blueprint = str(te.get("BlueprintName"))
            lt = int(te.get("Level") or 0)
            qt = float(te.get("Quality") if te.get("Quality") is not None else 1.0) or 1.0
            if _bp(base) == want:
                lb = int(base.get("Level") or 0)
                qb = float(base.get("Quality") or 0)
            else:
                lb, qb = 0, 1.0
            for g in range(1, lt + 1):
                if g < lb:
                    continue
                if g == lb:
                    goal = qt if g == lt else 1.0
                    if qb + 1e-6 < goal:
                        r = max(1, math.ceil(g * (goal - qb) - 1e-9))
                        step.grades.append((g, r))
                    continue
                step.grades.append((g, rolls_for(g, qt if g == lt else 1.0)))
        if _fx(te) and _fx(te) != _fx(base):
            step.effect = str(te.get("ExperimentalEffect"))
        if not step.idle:
            steps.append(step)
    for key, c in cur.items():
        if key not in seen and _removable(key):
            steps.append(Step(slot=str(c.get("slot") or key), item="", current=_item(c),
                              remove=True))
    return steps


#: Slots a build tool leaves out though the game always fills them.
_KEEP = ("cargohatch", "planetaryapproachsuite", "paintjob", "decal", "shipname",
         "shipid", "shipkit", "weaponcolour", "enginecolour", "vesselvoice",
         "bobble", "stringlights", "nameplate", "datalinkscanner", "codexscanner",
         "discoveryscanner", "colonisation", "shipcockpit", "cargobaydoor")


def _removable(slot: str) -> bool:
    s = slot.lower()
    return not any(s.startswith(k.lower()) for k in _KEEP)


# ── Materials ─────────────────────────────────────────────────────────────────

@dataclass
class Need:
    key: str           # journal name, lower case
    name: str
    kind: str          # raw | mfc | enc | ""
    grade: int
    group: int
    need: int = 0
    have: int = 0

    @property
    def short(self) -> int:
        return max(0, self.need - self.have)


def materials(steps: list[Step], db) -> tuple[dict[str, Need], list[str]]:
    """{material: Need} for every step, and what could not be priced."""
    out: dict[str, Need] = {}
    unknown: list[str] = []

    def add(matkey: str, count: float) -> None:
        mat = db.material(matkey)
        if mat is None:
            unknown.append(matkey)
            return
        k = mat.fdname.lower()
        n = out.get(k)
        if n is None:
            n = out[k] = Need(k, mat.name, mat.kind, mat.grade, mat.group)
        n.need += int(round(count))

    for st in steps:
        if st.blueprint and st.grades:
            bp = db.blueprint(st.blueprint, st.item)
            if bp is None:
                unknown.append(st.blueprint)
            else:
                for g, rolls in st.grades:
                    recipe = bp.mats[g - 1] if 0 < g <= len(bp.mats) else {}
                    for mk, cnt in recipe.items():
                        add(mk, cnt * rolls)
        if st.effect:
            fx = db.effect(st.effect)
            if fx is None:
                unknown.append(st.effect)
            else:
                for mk, cnt in fx.mats.items():
                    add(mk, cnt)
    return out, sorted(set(unknown))


def holdings(state) -> dict[str, int]:
    """Every ship material the commander holds, by journal name."""
    out: dict[str, int] = {}
    for bucket in ("materials_raw", "materials_manufactured", "materials_encoded"):
        for k, d in (getattr(state, bucket, None) or {}).items():
            out[str(k).lower()] = int((d or {}).get("count", 0) or 0)
    return out


def shortfall(needs: dict[str, Need], held: dict[str, int]) -> list[Need]:
    """The needs with what is held filled in: kind, then grade, then name."""
    order = {k: i for i, (k, _l) in enumerate(KINDS)}
    rows = []
    for n in needs.values():
        n.have = int(held.get(n.key, 0))
        rows.append(n)
    rows.sort(key=lambda n: (order.get(n.kind, 9), n.group, n.grade, n.name.lower()))
    return rows


# ── Trading ──────────────────────────────────────────────────────────────────

@dataclass
class Trade:
    give: str          # journal name
    give_name: str
    give_count: int
    get: str
    get_name: str
    get_count: int
    kind: str


def trade_ratio(src, dst) -> tuple[int, int]:
    """(give, get) for one exchange at a material trader: within a column
    six of a grade buy one of the next and one buys three of the grade below;
    across columns everything costs six times as much."""
    d = dst.grade - src.grade
    if src.group == dst.group:
        return (6 ** d, 1) if d > 0 else (1, 3 ** (-d)) if d < 0 else (1, 1)
    if d > 0:
        return 6 ** (d + 1), 1
    if d == 0:
        return 6, 1
    num = 3 ** (-d)
    g = math.gcd(num, 6)
    return 6 // g, num // g


def plan_trades(rows: list[Need], held: dict[str, int], db) -> tuple[list[Trade], list[Need]]:
    """Trades that cover the shortfall from what is held beyond the plan's
    own needs, cheapest in trade value first, and what trading cannot cover.
    Every shortfall is tried within its column before any across columns."""
    need_of = {n.key: n.need for n in rows}
    spare: dict[str, int] = {k: max(0, v - need_of.get(k, 0)) for k, v in held.items()}
    trades: list[Trade] = []
    short_of = {n.key: n.short for n in rows}
    for same_column in (True, False):
        for n in sorted(rows, key=lambda r: -r.grade):
            short_of[n.key] = _cover(n, short_of[n.key], spare, trades, db, same_column)
    left = [Need(n.key, n.name, n.kind, n.grade, n.group, need=short_of[n.key], have=0)
            for n in rows if short_of[n.key] > 0]
    return _merge(trades), left


def _cover(n: Need, short: int, spare: dict, trades: list, db, same_column: bool) -> int:
    """Trade toward one shortfall; what is still short after."""
    dst = db.material(n.key)
    if short <= 0 or dst is None or dst.group == 0 or dst.kind not in KIND_LABEL:
        return short
    while short > 0:
        best = None
        for k, avail in spare.items():
            if avail <= 0 or k == n.key:
                continue
            src = db.material(k)
            if src is None or src.kind != dst.kind or src.group == 0:
                continue
            if same_column and src.group != dst.group:
                continue
            give, get = trade_ratio(src, dst)
            times = math.ceil(short / get)
            if avail < give:
                continue
            times = min(times, avail // give)
            cost = give * times * (6 ** (src.grade - 1)) / max(1, get * times)
            cand = (cost, -times, k, src, give, get, times)
            if best is None or cand[:2] < best[:2]:
                best = cand
        if best is None:
            break
        _c, _t, k, src, give, get, times = best
        spare[k] -= give * times
        got = get * times
        trades.append(Trade(k, src.name, give * times, n.key, dst.name, got, dst.kind))
        short -= got
    return max(0, short)


def _merge(trades: list[Trade]) -> list[Trade]:
    out: dict[tuple, Trade] = {}
    for t in trades:
        k = (t.give, t.get)
        if k in out:
            out[k].give_count += t.give_count
            out[k].get_count += t.get_count
        else:
            out[k] = Trade(**t.__dict__)
    return list(out.values())


# ── Names ────────────────────────────────────────────────────────────────────

def blueprint_name(fdname: str, db=None, item: str = "") -> str:
    if db is not None:
        bp = db.blueprint(fdname, item)
        if bp is not None:
            return bp.name
    from data.engineering import normalise_eng_name
    return normalise_eng_name(fdname)


def effect_name(fdname: str, db=None) -> str:
    if db is not None:
        fx = db.effect(fdname)
        if fx is not None:
            return fx.name
    from data.engineering import normalise_eng_name
    return normalise_eng_name(fdname)


def grade_span(grades: list) -> str:
    """G1–G5, G4, or G2, G4 — the grades still to roll."""
    gs = [g for g, _r in grades]
    if not gs:
        return ""
    if gs == list(range(gs[0], gs[-1] + 1)) and len(gs) > 1:
        return f"G{gs[0]}–G{gs[-1]}"
    return ", ".join(f"G{g}" for g in gs)
