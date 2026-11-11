"""core/windows/engineering.py — the Engineering window: Fitting and Materials.

Fitting   one ship at a time, owned or planned: what is fitted beside the build
          planned for it, the work still to do, and the materials that work
          takes against what is held. Planned builds are for hulls not yet
          owned, and can be moved onto an owned hull of the same type.
Materials every material held, by kind: they travel with every ship, so they
          are not the Ship window's.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional

from core.windows import R, Tab

#: Material kinds, in the order the Materials tab presents them.
GRADES = (
    ("raw",          "Raw"),
    ("manufactured", "Mfg"),
    ("encoded",      "Enc"),
    ("components",   "Comp"),
    ("items",        "Items"),
    ("consumables",  "Cons"),
    ("data",         "Data"),
)

#: What the build dialog takes, worded once for both front ends.
IMPORT_HINT = ("Paste an EDSY or Coriolis link (long or short), an EDOMH link, "
               "or SLEF JSON exported by EDSY, Coriolis or EDSX.")

#: The choice at the foot of the ship list that starts a planned build.
NEW_PLAN = "new"
NEW_PLAN_LABEL = "New (Planned)…"


def _plugin(core, name: str):
    return (getattr(core, "_plugins", None) or {}).get(name)


# ── Materials ────────────────────────────────────────────────────────────────

def materials(core) -> Tab:
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
    return Tab("materials", "Materials", pages=pages)


# ── Ships ────────────────────────────────────────────────────────────────────

def _ship_type_name(ship_type: str) -> str:
    """A hull's name: EDSY's, once its tables are here, else EDLD's own."""
    return hull_name(ship_type)


def hull_name(ship_type: str) -> str:
    from core import eddb
    db = eddb.load(fetch=False)
    hull = db.ship(ship_type) if db is not None else None
    if hull is not None:
        return hull.name
    from data.ships import normalise_ship_name
    return normalise_ship_name(ship_type) or ship_type


def owned_ships(core) -> list[dict]:
    from core.windows.commander import _all_ships
    return [s for s in _all_ships(core.state) if s.get("ship_id") is not None]


def ship_label(ship: dict) -> str:
    name = str(ship.get("name") or "").strip()
    ident = str(ship.get("ident") or "").strip()
    kind = ship.get("type_display") or _ship_type_name(str(ship.get("type") or ""))
    named = f"{name} ({ident})" if name and ident else (name or ident)
    return f"{named} · {kind}" if named else str(kind)


def plan_labels(planned: dict) -> dict[str, str]:
    """"<type> (planned)" for each plan, numbered where a type repeats."""
    out: dict[str, str] = {}
    seen: dict[str, int] = {}
    for pid in sorted(planned, key=lambda k: int(k) if str(k).isdigit() else 0):
        t = _ship_type_name(str((planned[pid] or {}).get("ship") or ""))
        seen[t] = seen.get(t, 0) + 1
        out[pid] = f"{t} (planned)" if seen[t] == 1 else f"{t} (planned {seen[t]})"
    return out


def choices(core) -> list[tuple[str, str]]:
    """(key, label) for the ship list: owned ships, planned builds, then the
    choice that starts a new plan."""
    out = [(f"ship:{s['ship_id']}", ship_label(s)) for s in owned_ships(core)]
    eng = _plugin(core, "engineering")
    if eng is not None:
        labels = plan_labels(eng.planned())
        out += [(f"plan:{pid}", labels[pid]) for pid in labels]
    out.append((NEW_PLAN, NEW_PLAN_LABEL))
    return out


def ship_types(core) -> list[tuple[str, str]]:
    """(journal id, name) for every hull a plan can be for: EDSY's list once
    downloaded, EDLD's own names until then."""
    from core import eddb
    db = eddb.load(fetch=False)
    if db is not None and db.ships:
        return db.ship_types()
    from data.ships import SHIP_NAME_MAP
    seen: dict[str, str] = {}
    for key, name in SHIP_NAME_MAP.items():
        if " " in key or "fighter" in key or name in ("SRV", "Nomad") or name in seen:
            continue
        seen[name] = key
    return sorted(((k, n) for n, k in seen.items()), key=lambda p: p[1].lower())


def current_fit(core, ship_id) -> list[dict]:
    """A ship's fitted modules: the live ones for the ship flown, the last
    Loadout seen for any other."""
    cur = getattr(core.state, "assets_current_ship", None) or {}
    try:
        flown = cur.get("ship_id") is not None and int(cur["ship_id"]) == int(ship_id)
    except (TypeError, ValueError):
        flown = False
    if flown:
        live = list(getattr(core.state, "ship_modules", None) or [])
        if live:
            return live
    assets = _plugin(core, "assets")
    if assets is not None and hasattr(assets, "loadout_for"):
        lo = assets.loadout_for(ship_id)
        if lo:
            return lo
    for s in owned_ships(core):
        if str(s.get("ship_id")) == str(ship_id):
            return list(s.get("loadout") or [])
    return []


# ── Slots ────────────────────────────────────────────────────────────────────

_CORE = {"armour": ("Bulkheads", 0), "powerplant": ("Power Plant", 1),
         "mainengines": ("Thrusters", 2), "frameshiftdrive": ("Frame Shift Drive", 3),
         "lifesupport": ("Life Support", 4), "powerdistributor": ("Power Distributor", 5),
         "radar": ("Sensors", 6), "fueltank": ("Fuel Tank", 7)}
_HP = re.compile(r"^(tiny|small|medium|large|huge)(mining)?hardpoint(\d+)$")
_HP_SIZE = {"huge": 4, "large": 3, "medium": 2, "small": 1}
_OPT = re.compile(r"^slot(\d+)_size(\d+)$")
_MIL = re.compile(r"^military(\d+)$")


def slot_label(slot: str) -> str:
    s = (slot or "").lower()
    if s in _CORE:
        return _CORE[s][0]
    m = _HP.match(s)
    if m:
        if m.group(1) == "tiny":
            return f"Utility {int(m.group(3))}"
        return (f"{m.group(1).title()}{' Mining' if m.group(2) else ''} "
                f"{int(m.group(3))}")
    m = _OPT.match(s)
    if m:
        return f"Optional {int(m.group(1))} ({m.group(2)})"
    m = _MIL.match(s)
    if m:
        return f"Military {int(m.group(1))}"
    words = re.sub(r"(?<=[a-z])(?=[A-Z0-9])", " ", slot or "").replace("_", " ")
    return re.sub(r"\s*0*(\d+)$", r" \1", words).strip() or slot


def slot_order(slot: str) -> tuple:
    s = (slot or "").lower()
    if s in _CORE:
        return (0, _CORE[s][1], 0)
    m = _HP.match(s)
    if m:
        if m.group(1) == "tiny":
            return (2, 0, int(m.group(3)))
        return (1, 4 - _HP_SIZE[m.group(1)], int(m.group(3)) + (100 if m.group(2) else 0))
    m = _OPT.match(s)
    if m:
        return (3, int(m.group(1)), 0)
    m = _MIL.match(s)
    if m:
        return (4, int(m.group(1)), 0)
    return (3, 50, 0, s)


#: Slots the game fills itself, which build tools leave out.
_BUILT_IN = ("cargohatch", "planetaryapproachsuite", "paintjob", "decal", "shipname",
             "shipid", "shipkit", "weaponcolour", "enginecolour", "vesselvoice", "bobble",
             "stringlights", "nameplate", "datalinkscanner", "codexscanner",
             "discoveryscanner", "colonisationsuite", "shipcockpit", "cockpit")


def fitted(mods) -> list[dict]:
    """The modules a fitting is compared on: no cosmetics or built-ins."""
    from data.modules import is_cosmetic_module
    out = []
    for m in mods or []:
        slot = str(m.get("slot") or "")
        item = str(m.get("item") or m.get("name_internal") or "")
        if not slot or not item or slot.lower().startswith(_BUILT_IN) \
                or is_cosmetic_module(item.lower()):
            continue
        out.append(m)
    return out


def _item(m: Optional[dict]) -> str:
    i = str((m or {}).get("item") or (m or {}).get("name_internal") or "").lower()
    return i[:-5] if i.endswith("_free") else i


def module_name(item: str) -> str:
    from data.modules import normalise_module_name
    return str(normalise_module_name(item)) if item else ""


def eng_line(eng: Optional[dict]) -> str:
    """The Ship window's engineering line, with the share of the grade
    rolled when it is not all of it."""
    from core.windows.ship import engineering_line
    text = engineering_line(eng)
    q = (eng or {}).get("Quality")
    if text and (eng or {}).get("BlueprintName") and q is not None and 0 < float(q) < 0.999:
        text = text.replace(f"G{int(eng.get('Level') or 0)} ",
                            f"G{int(eng.get('Level') or 0)} {float(q) * 100:.0f}% ", 1)
    return text


# ── The Fitting view ─────────────────────────────────────────────────────────

@dataclass
class SlotRow:
    slot: str
    label: str
    current: str = ""
    current_eng: str = ""
    target: str = ""
    target_eng: str = ""
    #: "" the same; "eng" the module matches, its engineering does not;
    #: "module" a different module; "added" only in the target; "removed"
    #: only fitted now.
    state: str = ""


@dataclass
class FittingView:
    key: str = ""
    label: str = ""
    planned: bool = False
    ship_type: str = ""
    has_target: bool = False
    target_source: str = ""
    target_url: str = ""
    slots: list = field(default_factory=list)       # [SlotRow]
    work: list = field(default_factory=list)        # model rows
    needs: list = field(default_factory=list)       # model rows
    short: int = 0                                  # materials short, units
    apply_to: list = field(default_factory=list)    # [(key, label)]
    status: str = ""


def _eng_state(c: dict, t: dict) -> bool:
    ce, te = (c or {}).get("engineering") or {}, (t or {}).get("engineering") or {}
    if str(te.get("BlueprintName") or "").lower() != str(ce.get("BlueprintName") or "").lower():
        return bool(te.get("BlueprintName"))
    if te.get("BlueprintName") and (
            int(ce.get("Level") or 0) < int(te.get("Level") or 0)
            or (int(ce.get("Level") or 0) == int(te.get("Level") or 0)
                and float(ce.get("Quality") or 0) + 1e-6 < float(te.get("Quality") or 1))):
        return True
    tf = str(te.get("ExperimentalEffect") or "").lower()
    return bool(tf) and tf != str(ce.get("ExperimentalEffect") or "").lower()


def compare(current: list, target: Optional[dict]) -> list[SlotRow]:
    cur = {str(m.get("slot")).lower(): m for m in fitted(current)}
    tgt = {str(m.get("slot")).lower(): m for m in fitted((target or {}).get("modules"))}
    names = {}
    for m in fitted(current) + fitted((target or {}).get("modules")):
        names.setdefault(str(m.get("slot")).lower(), str(m.get("slot")))
    rows = []
    for key in sorted(names, key=lambda k: slot_order(names[k])):
        c, t = cur.get(key), tgt.get(key)
        row = SlotRow(names[key], slot_label(names[key]),
                      module_name(str((c or {}).get("item") or (c or {}).get("name_internal") or "")),
                      eng_line((c or {}).get("engineering")),
                      module_name(str((t or {}).get("item") or "")),
                      eng_line((t or {}).get("engineering")))
        if target is None:
            row.state = ""
        elif c is None:
            row.state = "added"
        elif t is None:
            row.state = "removed"
        elif _item(c) != _item(t):
            row.state = "module"
        elif _eng_state(c, t):
            row.state = "eng"
        rows.append(row)
    return rows


def _resolve_key(core, key: Optional[str]) -> str:
    eng = _plugin(core, "engineering")
    keys = [k for k, _l in choices(core) if k != NEW_PLAN]
    want = key or (eng.selected() if eng is not None else "")
    if want in keys:
        return want
    cur = getattr(core.state, "assets_current_ship", None) or {}
    if cur.get("ship_id") is not None and f"ship:{cur['ship_id']}" in keys:
        return f"ship:{cur['ship_id']}"
    return keys[0] if keys else ""


def fitting(core, key: Optional[str] = None) -> FittingView:
    """The Fitting tab for ``key`` (the remembered choice when None)."""
    from core import eddb
    from core import eng_plan as P
    view = FittingView()
    key = _resolve_key(core, key)
    view.key = key
    labels = dict(choices(core))
    view.label = labels.get(key, "")
    eng = _plugin(core, "engineering")
    if not key:
        view.status = "No ships yet: they come with the first Loadout."
        return view
    kind, _, ident = key.partition(":")
    target = eng.target(key) if eng is not None else None
    view.has_target = bool(target)
    if target:
        view.target_source = str(target.get("source") or "")
        view.target_url = str(target.get("url") or "")
    if kind == "plan":
        view.planned = True
        plan = (eng.planned() if eng is not None else {}).get(ident) or {}
        view.ship_type = str(plan.get("ship") or "")
        current: list = []
        view.apply_to = [(f"ship:{s['ship_id']}", ship_label(s)) for s in owned_ships(core)
                         if str(s.get("type") or "").lower() == view.ship_type]
    else:
        ship = next((s for s in owned_ships(core) if str(s["ship_id"]) == ident), {})
        view.ship_type = str(ship.get("type") or "").lower()
        current = current_fit(core, ident)
    view.slots = compare(current, target)
    if not target:
        view.status = ("No build yet. Add one with Build…" if view.planned
                       else "No target build. Add one with Target…")
        return view
    if not current and not view.planned:
        view.status = "No Loadout seen for this ship yet: board it once to read its fitting."
    stored = list(getattr(core.state, "assets_stored_modules", None) or [])
    steps = P.delta(fitted(current), {"modules": fitted(target.get("modules"))}, stored)
    db = eddb.load(on_fetched=lambda: _refresh(core))
    view.work = work_rows(steps, db)
    if db is None:
        why = eddb.last_error()
        if why and not eddb.fetching():
            view.status = f"EDSY's tables could not be downloaded ({why}); materials need them."
        else:
            view.status = "Downloading EDSY's tables; materials follow when they land."
        return view
    needs, unknown = P.materials(steps, db)
    rows = P.shortfall(needs, P.holdings(core.state))
    view.needs = need_rows(rows)
    view.short = sum(n.short for n in rows)
    if unknown:
        view.status = "Not priced: " + ", ".join(unknown)
    return view


def _refresh(core) -> None:
    gq = getattr(core, "gui_queue", None)
    if gq is not None:
        gq.put(("plugin_refresh", "engineering"))


def work_rows(steps, db) -> list:
    from core import eng_plan as P
    rows: list = []
    if not steps:
        return [R.text("Nothing left: the ship matches its build.", "dim")]
    for st in steps:
        label = slot_label(st.slot)
        if st.remove:
            rows.append(R.kv(f"{label}: {module_name(st.current)}", "remove", "val dim"))
            continue
        tag = {"purchase": "purchase", "stored": "stored"}.get(st.module, "")
        rows.append(R.kv(f"{label}: {module_name(st.item)}", tag,
                         "val health-warn" if tag == "purchase" else "val"))
        if st.grades:
            rolls = sum(r for _g, r in st.grades)
            rows.append(R.note(f"{P.grade_span(st.grades)} "
                               f"{P.blueprint_name(st.blueprint, db, st.item)}  ·  "
                               f"{rolls} roll{'s' if rolls != 1 else ''}", "  "))
        if st.effect:
            rows.append(R.note(f"Experimental: {P.effect_name(st.effect, db)}", "  "))
    return rows


def need_rows(needs) -> list:
    from core import eng_plan as P
    if not needs:
        return [R.text("No materials needed.", "dim")]
    rows: list = [R.table("Material", (("Grade", 5), ("Need", 5), ("Have", 5), ("Short", 5)))]
    kind = None
    for n in needs:
        if n.kind != kind:
            kind = n.kind
            rows.append(R.hdr(P.KIND_LABEL.get(kind, "Other")))
        cls = "val health-crit" if n.short else "val health-good"
        rows.append(R.cells(n.name, [f"G{n.grade}", str(n.need), str(n.have),
                                     str(n.short) if n.short else "—"], cls))
    need = sum(n.need for n in needs)
    short = sum(n.short for n in needs)
    rows.append(R.rule())
    rows.append(R.cells("Total", ["", str(need), "", str(short) if short else "—"],
                        "val health-crit" if short else "val health-good"))
    return rows


# ── Shopping list ────────────────────────────────────────────────────────────

def shopping(core, key: Optional[str] = None, traders: Optional[dict] = None) -> list:
    """Trades that cover what is short from what is spare, what no trade can
    cover, and where the nearest traders of each kind are."""
    from core import eddb
    from core import eng_plan as P
    key = _resolve_key(core, key)
    eng = _plugin(core, "engineering")
    target = eng.target(key) if eng is not None and key else None
    db = eddb.load(fetch=False)
    if not target or db is None:
        return [R.text("Nothing to plan: no target build, or EDSY's tables not yet here.", "dim")]
    kind, _, ident = key.partition(":")
    current = current_fit(core, ident) if kind == "ship" else []
    steps = P.delta(fitted(current), {"modules": fitted(target.get("modules"))},
                    list(getattr(core.state, "assets_stored_modules", None) or []))
    needs, _unknown = P.materials(steps, db)
    held = P.holdings(core.state)
    rows_n = P.shortfall(needs, held)
    if not any(n.short for n in rows_n):
        return [R.text("Nothing is short: everything the build needs is held.", "health-good")]
    trades, left = P.plan_trades(rows_n, held, db)
    rows: list = []
    by_kind: dict[str, list] = {}
    for t in trades:
        by_kind.setdefault(t.kind, []).append(t)
    for k, label in P.KINDS:
        ts = by_kind.get(k)
        if not ts:
            continue
        rows.append(R.hdr(f"{label} trader"))
        for t in ts:
            rows.append(R.kv(f"{t.give_count} {t.give_name}", f"→ {t.get_count} {t.get_name}"))
        for st in (traders or {}).get(k, []) or []:
            ly = st.get("ly")
            where = f"{st.get('station')}, {st.get('system')}"
            rows.append(R.note(f"{where}" + (f"  ·  {float(ly):,.1f} ly" if ly is not None else ""),
                               "  "))
        if traders is not None and not (traders or {}).get(k):
            rows.append(R.note("No trader found nearby (or Spansh not reachable).", "  "))
    if left:
        rows.append(R.hdr("Still to collect"))
        for n in left:
            rows.append(R.kv(n.name, str(n.need), "val health-crit"))
    return rows


def trade_kinds(core, key: Optional[str] = None) -> list[str]:
    """The trader kinds the shopping list for ``key`` sends the commander to."""
    rows = shopping(core, key)
    kinds = []
    for kind, label in (("raw", "Raw"), ("mfc", "Manufactured"), ("enc", "Encoded")):
        if any(r[0] == "hdr" and r[1] == f"{label} trader" for r in rows):
            kinds.append(kind)
    return kinds


# ── For the wire, and the terminal ───────────────────────────────────────────

def fitting_tab(core) -> Tab:
    """The Fitting tab as rows, for a device: the ship, each slot fitted and
    planned, the work left and the materials it takes."""
    v = fitting(core)
    rows: list = []
    if v.label:
        rows.append(R.hdr(v.label))
    if v.status:
        rows.append(R.text(v.status, "dim"))
    if v.has_target:
        rows.append(R.text(f"Target: {v.target_source or 'build'}", "dim"))
    if v.planned and v.has_target and not v.apply_to:
        rows.append(R.text(f"No {_ship_type_name(v.ship_type)} owned to apply it to yet.",
                           "dim"))
    for s in v.slots:
        if v.planned:
            rows.append(R.kv(s.label, s.target or "—", "val"))
            if s.target_eng:
                rows.append(R.note(s.target_eng, "  "))
            continue
        cls = {"": "val dim", "eng": "val health-warn", "module": "val health-crit",
               "added": "val health-crit", "removed": "val dim"}.get(s.state, "val")
        cur = s.current or "—"
        rows.append(R.kv(f"{s.label}: {cur}", s.target if v.has_target else "", cls))
        if s.current_eng:
            rows.append(R.note(s.current_eng, "  "))
        if v.has_target and s.target_eng and s.target_eng != s.current_eng:
            rows.append(R.note(f"→ {s.target_eng}", "  ", "health-warn"))
    if v.has_target and v.work:
        rows += [R.rule(), R.hdr("Work left")] + v.work
    if v.needs:
        rows += [R.rule(), R.hdr("Materials")] + v.needs
    return Tab("fitting", "Fitting", rows)


def tabs(core) -> list[Tab]:
    return [fitting_tab(core), materials(core)]
