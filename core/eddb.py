"""core/eddb.py — the ship, module, blueprint and material tables, from
data/eddb.sqlite.

Ships and their slot layouts, every module with its type, class and rating,
the blueprints with the materials each grade costs, the experimental effects,
and the materials themselves. The Engineering window reads EDSY links and
EDOMH ships with them and prices what a planned build still needs.

data/eddb.sqlite is built from EDSY's eddb.js by the eddb2sqlite tool, outside
the program, and shipped with it. Recipes the journal shows (EngineerCraft)
are kept in ``OBSERVED`` and win over the table's: ``observe_craft``.
"""
from __future__ import annotations

import json
import sqlite3
import sys
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


# ── The tables ────────────────────────────────────────────────────────────────

@dataclass
class Module:
    id: int
    fdname: str
    mtype: str = ""
    cls: Optional[int] = None
    rating: str = ""
    name: str = ""
    mount: str = ""


@dataclass
class Ship:
    id: int
    fdname: str
    name: str
    slots: dict = field(default_factory=dict)       # group → [size, …]
    slotnames: dict = field(default_factory=dict)   # group → [journal slot, …]
    #: Hull-only modules (bulkheads), by EDSY id: the same ids recur per hull.
    modules: dict = field(default_factory=dict)


@dataclass
class Blueprint:
    key: str
    fdname: str
    name: str
    maxgrade: int
    #: One {material key: count} per grade, grade 1 first.
    mats: list = field(default_factory=list)


@dataclass
class Effect:
    key: str
    fdname: str
    name: str
    mats: dict = field(default_factory=dict)


@dataclass
class Material:
    key: str
    fdname: str
    name: str
    kind: str          # raw | mfc | enc
    group: int         # the trader's column; 0 cannot be traded
    grade: int         # rarity, 1–5


#: The core slots, in EDSY's component order.
CORE_SLOTS = ("Armour", "PowerPlant", "MainEngines", "FrameShiftDrive",
              "LifeSupport", "PowerDistributor", "Radar", "FuelTank")
SLOT_GROUPS = ("hardpoint", "utility", "component", "military", "internal")
_HP_SIZE = ("Tiny", "Small", "Medium", "Large", "Huge")


class Eddb:
    """EDSY's reference data, indexed for EDLD's lookups."""

    def __init__(self, raw: dict) -> None:
        self.version = raw.get("version")
        self.ships: dict[int, Ship] = {}
        self.ship_by_fd: dict[str, Ship] = {}
        self.modules: dict[int, Module] = {}
        self.module_by_fd: dict[str, Module] = {}
        self.blueprints: dict[str, Blueprint] = {}
        self.effects: dict[str, Effect] = {}
        self.mtypes: dict[str, dict] = {}
        self.materials: dict[str, Material] = {}
        self.material_by_fd: dict[str, Material] = {}

        for mid, rec in (raw.get("module") or {}).items():
            self._add_module(mid, rec)
        for sid, rec in (raw.get("ship") or {}).items():
            if not isinstance(rec, dict) or not rec.get("fdname"):
                continue
            ship = Ship(int(sid), rec["fdname"], rec.get("name") or rec["fdname"],
                        {g: list(v or []) for g, v in (rec.get("slots") or {}).items()},
                        {g: list(v or []) for g, v in (rec.get("slotnames") or {}).items()})
            self.ships[ship.id] = ship
            self.ship_by_fd[ship.fdname.lower()] = ship
            for mid, mrec in (rec.get("module") or {}).items():
                self._add_module(mid, mrec, mtype="cbh", ship=ship)
        for key, rec in (raw.get("blueprint") or {}).items():
            if isinstance(rec, dict) and rec.get("fdname"):
                self.blueprints[key] = Blueprint(
                    key, rec["fdname"], rec.get("name") or key,
                    int(rec.get("maxgrade") or 0),
                    [dict(g or {}) for g in (rec.get("mats") or [])])
        for key, rec in (raw.get("expeffect") or {}).items():
            if isinstance(rec, dict) and rec.get("fdname"):
                self.effects[key] = Effect(key, rec["fdname"], rec.get("name") or key,
                                           dict(rec.get("mats") or {}))
        for key, rec in (raw.get("mtype") or {}).items():
            if isinstance(rec, dict):
                self.mtypes[key] = {"name": rec.get("name") or key,
                                    "blueprints": list(rec.get("blueprints") or []),
                                    "expeffects": list(rec.get("expeffects") or [])}
        for key, rec in (raw.get("material") or {}).items():
            if isinstance(rec, dict) and rec.get("fdname"):
                mat = Material(key, rec["fdname"], (rec.get("name") or key).strip(),
                               rec.get("mattype") or "", int(rec.get("matgrp") or 0),
                               int(rec.get("rarity") or 0))
                self.materials[key] = mat
                self.material_by_fd[mat.fdname.lower()] = mat

    def _add_module(self, mid, rec, mtype: str = "", ship: Optional[Ship] = None) -> None:
        if not isinstance(rec, dict) or not rec.get("fdname"):
            return
        try:
            num = int(mid)
        except ValueError:
            return
        mod = Module(num, rec["fdname"], rec.get("mtype") or mtype,
                     rec.get("class"), rec.get("rating") or "", rec.get("name") or "",
                     rec.get("mount") or "")
        if ship is not None:
            ship.modules[num] = mod
        else:
            self.modules.setdefault(num, mod)
        self.module_by_fd.setdefault(mod.fdname.lower(), mod)

    # ── Lookups ───────────────────────────────────────────────────────────────

    def module(self, item: str) -> Optional[Module]:
        return self.module_by_fd.get((item or "").lower())

    def ship(self, fdname: str) -> Optional[Ship]:
        return self.ship_by_fd.get((fdname or "").lower())

    def blueprint(self, fdname: str, item: str = "") -> Optional[Blueprint]:
        """The blueprint a journal BlueprintName names; where several module
        types share the name, the one legal for ``item``."""
        want = (fdname or "").lower()
        hits = [b for b in self.blueprints.values() if b.fdname.lower() == want]
        if len(hits) > 1 and item:
            mod = self.module(item)
            legal = set(self.mtypes.get(mod.mtype if mod else "", {}).get("blueprints", []))
            hits = [b for b in hits if b.key in legal] or hits
        return hits[0] if hits else None

    def effect(self, fdname: str) -> Optional[Effect]:
        want = (fdname or "").lower()
        return next((e for e in self.effects.values() if e.fdname.lower() == want), None)

    def material(self, key: str) -> Optional[Material]:
        return self.materials.get(key) or self.material_by_fd.get((key or "").lower())

    def slot_name(self, ship: Ship, group: str, num: int) -> str:
        """The journal's name for slot ``num`` of a slot group."""
        names = ship.slotnames.get(group) or []
        if num < len(names) and names[num]:
            return names[num]
        sizes = ship.slots.get(group) or []
        size = sizes[num] if num < len(sizes) else 0
        if group == "hardpoint":
            n = sum(1 for s in sizes[:num + 1] if s == size)
            return f"{_HP_SIZE[size] if size < len(_HP_SIZE) else 'Unknown'}Hardpoint{n}"
        if group == "utility":
            return f"TinyHardpoint{num + 1}"
        if group == "component":
            return CORE_SLOTS[num] if num < len(CORE_SLOTS) else f"Core{num + 1}"
        if group == "military":
            return f"Military{num + 1:02d}"
        return f"Slot{num + 1:02d}_Size{size}"

    def ship_types(self) -> list[tuple[str, str]]:
        """(journal id, name) for every hull, by name."""
        return sorted(((s.fdname.lower(), s.name) for s in self.ships.values()),
                      key=lambda p: p[1].lower())


# ── Loading ──────────────────────────────────────────────────────────────────

def db_path() -> Path:
    base = getattr(sys, "_MEIPASS", None)
    return (Path(base) if base else Path(__file__).resolve().parents[1]) / "data" / "eddb.sqlite"


def raw_from_sqlite(path: Path) -> dict:
    """The tables as the nested shape ``Eddb`` takes."""
    con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        q = con.execute
        raw: dict = {"version": dict(q("SELECT key, value FROM meta")).get("eddb_version"),
                     "module": {}, "ship": {}, "blueprint": {}, "expeffect": {},
                     "mtype": {}, "material": {}}
        for sid, fd, name, slots, slotnames in q("SELECT * FROM ships"):
            raw["ship"][str(sid)] = {"fdname": fd, "name": name, "slots": json.loads(slots),
                                     "slotnames": json.loads(slotnames), "module": {}}
        for mid, ship, fd, mtype, cls, rating, name, mount in q("SELECT * FROM modules"):
            rec = {"fdname": fd, "mtype": mtype, "class": cls, "rating": rating,
                   "name": name, "mount": mount}
            if ship:
                raw["ship"][str(ship)]["module"][str(mid)] = rec
            else:
                raw["module"][str(mid)] = rec
        for key, name in q("SELECT * FROM mtypes"):
            raw["mtype"][key] = {"name": name, "blueprints": [], "expeffects": []}
        for mtype, _pos, bp in q("SELECT * FROM mtype_blueprints ORDER BY mtype, pos"):
            raw["mtype"][mtype]["blueprints"].append(bp)
        for mtype, _pos, fx in q("SELECT * FROM mtype_effects ORDER BY mtype, pos"):
            raw["mtype"][mtype]["expeffects"].append(fx)
        for key, fd, name, maxgrade in q("SELECT * FROM blueprints"):
            raw["blueprint"][key] = {"fdname": fd, "name": name, "maxgrade": maxgrade,
                                     "mats": [{} for _ in range(maxgrade)]}
        for bp, grade, mat, cnt in q("SELECT * FROM blueprint_mats"):
            mats = raw["blueprint"][bp]["mats"]
            while len(mats) < grade:
                mats.append({})
            mats[grade - 1][mat] = cnt
        for key, fd, name in q("SELECT * FROM effects"):
            raw["expeffect"][key] = {"fdname": fd, "name": name, "mats": {}}
        for fx, mat, cnt in q("SELECT * FROM effect_mats"):
            raw["expeffect"][fx]["mats"][mat] = cnt
        for key, fd, name, kind, grp, grade in q("SELECT * FROM materials"):
            raw["material"][key] = {"fdname": fd, "name": name, "mattype": kind,
                                    "matgrp": grp, "rarity": grade}
        return raw
    finally:
        con.close()


_lock = threading.Lock()
_loaded: Optional[Eddb] = None
_tried = False
_error = ""


def last_error() -> str:
    """Why the tables could not be read, or ""."""
    return _error


def load() -> Optional[Eddb]:
    """The tables, read once; None when data/eddb.sqlite cannot be read."""
    global _loaded, _tried, _error
    with _lock:
        if _loaded is None and not _tried:
            _tried = True
            try:
                _loaded = Eddb(raw_from_sqlite(db_path()))
            except Exception as exc:
                _error = f"{type(exc).__name__}: {exc}"
                from core import debug as _dbg
                _dbg.log(f"  [eddb] {db_path()} unreadable: {_error}", level="WARN", echo=True)
        return _loaded


def use(db: Optional[Eddb]) -> None:
    """Install tables directly (tests); None reads the file again."""
    global _loaded, _tried
    with _lock:
        _loaded = db
        _tried = db is not None


# ── Recipes the journal shows ────────────────────────────────────────────────

#: (blueprint fdname lower, grade) → {material: count}, and
#: ("fx", effect fdname lower) → {material: count}, from EngineerCraft.
OBSERVED: dict[tuple, dict[str, int]] = {}
_reported: set = set()


def _table_recipe(db: Eddb, key: tuple, item: str) -> Optional[dict]:
    if key[0] == "fx":
        fx = db.effect(key[1])
        mats = fx.mats if fx else None
    else:
        bp = db.blueprint(key[0], item)
        mats = bp.mats[key[1] - 1] if bp and 0 < key[1] <= len(bp.mats) else None
    if mats is None:
        return None
    out = {}
    for k, v in mats.items():
        m = db.material(k)
        out[m.fdname.lower() if m else k] = int(v)
    return out


def observe_craft(event: dict, db: Optional[Eddb] = None) -> None:
    """Keep the recipe an EngineerCraft shows, and log once where the table
    disagrees with it."""
    ing = {str(i.get("Name") or "").lower(): int(i.get("Count") or 0)
           for i in event.get("Ingredients") or [] if i.get("Name")}
    if not ing:
        return
    fx = str(event.get("ApplyExperimentalEffect") or "")
    if fx:
        key = ("fx", fx.lower())
    elif event.get("BlueprintName") and event.get("Level"):
        key = (str(event["BlueprintName"]).lower(), int(event["Level"]))
    else:
        return
    OBSERVED[key] = ing
    db = db or load()
    if db is None or key in _reported:
        return
    table = _table_recipe(db, key, str(event.get("Module") or ""))
    if table is not None and table != ing:
        _reported.add(key)
        from core import debug as _dbg
        _dbg.log(f"  [eddb] journal recipe for {key} is {ing}; the table says {table}. "
                 "The journal's is used.", level="WARN")


def recipe(db: Eddb, blueprint: str, grade: int, item: str = "") -> Optional[dict]:
    """{material fdname lower: count} for one roll: the journal's when seen."""
    key = (blueprint.lower(), grade)
    return OBSERVED.get(key) or _table_recipe(db, key, item)


def effect_recipe(db: Eddb, effect: str) -> Optional[dict]:
    key = ("fx", effect.lower())
    return OBSERVED.get(key) or _table_recipe(db, key, "")
