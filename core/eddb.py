"""core/eddb.py — EDSY's reference tables, read from its eddb.js.

Ships and their slot layouts, every module with its type, class and rating,
the blueprints with the materials each grade costs, the experimental effects,
and the materials themselves. The ENGINEERING window reads a build from an
EDSY link with them and prices what a planned build still needs.

The file is downloaded on first use and kept in the shared data directory; it
is not shipped with EDLD. ``load()`` answers from the cache and refreshes it in
the background once it is a week old.
"""
from __future__ import annotations

import re
import threading
import time
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

URL = "https://raw.githubusercontent.com/taleden/EDSY/master/eddb.js"
CACHE_NAME = "eddb.js"
MAX_AGE_S = 7 * 86400


# ── A reader for the object literal eddb.js holds ────────────────────────────

class JsError(ValueError):
    pass


class _Js:
    """Recursive descent over a JavaScript object literal: objects with bare
    or quoted keys, arrays, strings, numbers, true/false/null, comments and
    trailing commas."""

    _NUM = re.compile(r"-?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?")
    _IDENT = re.compile(r"[A-Za-z_$][\w$]*")

    def __init__(self, text: str, pos: int = 0) -> None:
        self.t = text
        self.i = pos
        self.n = len(text)

    def skip(self) -> None:
        t, n = self.t, self.n
        while self.i < n:
            c = t[self.i]
            if c in " \t\r\n":
                self.i += 1
            elif t.startswith("//", self.i):
                j = t.find("\n", self.i)
                self.i = n if j < 0 else j + 1
            elif t.startswith("/*", self.i):
                j = t.find("*/", self.i + 2)
                self.i = n if j < 0 else j + 2
            else:
                return

    def value(self) -> Any:
        self.skip()
        if self.i >= self.n:
            raise JsError("unexpected end")
        c = self.t[self.i]
        if c == "{":
            return self._object()
        if c == "[":
            return self._array()
        if c in "'\"":
            return self._string()
        m = self._NUM.match(self.t, self.i)
        if m:
            self.i = m.end()
            s = m.group(0)
            num = float(s) if any(ch in s for ch in ".eE") else int(s)
            return self._arith(num)
        m = self._IDENT.match(self.t, self.i)
        if m:
            self.i = m.end()
            word = m.group(0)
            return {"true": True, "false": False, "null": None,
                    "undefined": None, "Infinity": float("inf")}.get(word)
        raise JsError(f"unexpected {c!r} at {self.i}")

    def _arith(self, num):
        """A number followed by * or / and another: "rof: 1/0"."""
        while True:
            j = self.i
            while j < self.n and self.t[j] in " \t":
                j += 1
            op = self.t[j:j + 1]
            if op not in ("*", "/") or self.t.startswith(("//", "/*"), j):
                return num
            self.i = j + 1
            self.skip()
            m = self._NUM.match(self.t, self.i)
            if not m:
                raise JsError(f"bad operand at {self.i}")
            self.i = m.end()
            rhs = float(m.group(0))
            if op == "*":
                num = num * rhs
            else:
                num = num / rhs if rhs else float("inf")

    def _string(self) -> str:
        q = self.t[self.i]
        self.i += 1
        out = []
        t = self.t
        while self.i < self.n:
            c = t[self.i]
            if c == "\\":
                nxt = t[self.i + 1:self.i + 2]
                out.append({"n": "\n", "t": "\t"}.get(nxt, nxt))
                self.i += 2
                continue
            if c == q:
                self.i += 1
                return "".join(out)
            out.append(c)
            self.i += 1
        raise JsError("unterminated string")

    def _key(self) -> str:
        self.skip()
        c = self.t[self.i]
        if c in "'\"":
            return self._string()
        m = self._NUM.match(self.t, self.i) or self._IDENT.match(self.t, self.i)
        if not m:
            raise JsError(f"bad key at {self.i}")
        self.i = m.end()
        return m.group(0)

    def _object(self) -> dict:
        self.i += 1
        out: dict = {}
        while True:
            self.skip()
            if self.t[self.i] == "}":
                self.i += 1
                return out
            k = self._key()
            self.skip()
            if self.t[self.i] != ":":
                raise JsError(f"expected ':' at {self.i}")
            self.i += 1
            out[k] = self.value()
            self.skip()
            if self.t[self.i] == ",":
                self.i += 1

    def _array(self) -> list:
        self.i += 1
        out: list = []
        while True:
            self.skip()
            if self.t[self.i] == "]":
                self.i += 1
                return out
            out.append(self.value())
            self.skip()
            if self.t[self.i] == ",":
                self.i += 1


def parse_eddb(text: str) -> dict:
    """The ``eddb`` object of eddb.js as Python data."""
    m = re.search(r"\bvar\s+eddb\s*=\s*\{", text)
    if not m:
        raise JsError("no 'var eddb' in the file")
    return _Js(text, m.end() - 1).value()


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

_lock = threading.Lock()
_loaded: Optional[Eddb] = None
_loaded_mtime = 0.0
_fetching = False
_last_error = ""


def cache_path() -> Path:
    from core.state import shared_data_dir
    return shared_data_dir() / CACHE_NAME


def last_error() -> str:
    return _last_error


def _download(path: Path) -> None:
    global _last_error
    from core import debug as _dbg
    try:
        req = urllib.request.Request(URL, headers={"User-Agent": "EDLD"})
        with urllib.request.urlopen(req, timeout=60) as resp:
            data = resp.read()
        parse_eddb(data.decode("utf-8-sig"))            # refuse a broken file
        tmp = path.with_suffix(".tmp")
        tmp.write_bytes(data)
        tmp.replace(path)
        _last_error = ""
        _dbg.log(f"  [eddb] downloaded {len(data):,} bytes")
    except Exception as exc:
        _last_error = f"{type(exc).__name__}: {exc}"
        _dbg.log(f"  [eddb] download failed: {_last_error}")


def _fetch_async(path: Path, on_done=None) -> None:
    global _fetching
    if _fetching:
        return
    _fetching = True

    def run():
        global _fetching
        try:
            _download(path)
        finally:
            _fetching = False
        if on_done is not None:
            try:
                on_done()
            except Exception:
                pass
    threading.Thread(target=run, name="eddb-fetch", daemon=True).start()


def fetching() -> bool:
    return _fetching


def load(fetch: bool = True, on_fetched=None, path: Optional[Path] = None) -> Optional[Eddb]:
    """The tables, from the cache; None until a first download has landed.
    A missing or week-old cache is fetched in the background when ``fetch``,
    and ``on_fetched`` called when it arrives."""
    global _loaded, _loaded_mtime, _last_error
    if _loaded is not None and _loaded_mtime < 0:
        return _loaded
    p = path or cache_path()
    try:
        mtime = p.stat().st_mtime
    except OSError:
        mtime = 0.0
    if fetch and (not mtime or time.time() - mtime > MAX_AGE_S):
        _fetch_async(p, on_fetched)
    if not mtime:
        return None
    with _lock:
        if _loaded is not None and _loaded_mtime == mtime:
            return _loaded
        try:
            _loaded = Eddb(parse_eddb(p.read_text(encoding="utf-8-sig")))
            _loaded_mtime = mtime
        except Exception as exc:
            _last_error = f"cached eddb.js unreadable: {exc}"
            from core import debug as _dbg
            _dbg.log(f"  [eddb] {_last_error}")
            return _loaded
    return _loaded


def use(db: Optional[Eddb]) -> None:
    """Install tables directly (tests)."""
    global _loaded, _loaded_mtime
    with _lock:
        _loaded = db
        _loaded_mtime = -1.0 if db is not None else 0.0
