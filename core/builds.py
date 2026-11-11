"""core/builds.py — ship builds read from wherever they are kept.

    EDSY        https://edsy.org/#/L=…  and its short links, edsy.org/s/…
    Coriolis    https://coriolis.io/import?data=…  and sh.orbis.zone/… links
    EDOMH       https://link.edomh.nl/…  and the edomh://ship/?… it leads to
    SLEF        the JSON EDSY and Coriolis export, and EDSX writes
    Loadout     a journal Loadout event, or EDOMH's own ship JSON

Every one becomes the same thing, a build:

    {"ship": journal ship id, "name": …, "ident": …, "source": …, "url": …,
     "modules": [{"slot", "item", "on", "priority",
                  "engineering": {"BlueprintName", "Level", "Quality",
                                  "ExperimentalEffect"}}]}

Short links are followed with ``fetch(url)``, which returns the address the
link redirects to. EDSY hashes and EDOMH ships need EDSY's tables
(core/eddb.py); SLEF and Loadout JSON need nothing.
"""
from __future__ import annotations

import base64
import gzip
import json
import re
import urllib.parse
import zlib
from typing import Any, Callable, Optional


class BuildError(ValueError):
    """Text that is not a build this module can read, said plainly."""


Fetch = Callable[[str], str]


# ── Entry point ──────────────────────────────────────────────────────────────

def parse(text: str, fetch: Optional[Fetch] = None, db=None) -> tuple[dict, list[str]]:
    """(build, warnings) from a link or JSON. Raises BuildError."""
    raw = (text or "").strip()
    if not raw:
        raise BuildError("Nothing to import.")
    warnings: list[str] = []
    if raw[0] in "[{":
        try:
            obj = json.loads(raw)
        except ValueError as exc:
            raise BuildError(f"Not valid JSON: {exc}") from None
        return _from_json(obj, db, warnings), warnings
    url = raw.split()[0]
    return _from_url(url, fetch, db, warnings, hops=0), warnings


def _from_url(url: str, fetch, db, warnings, hops: int) -> dict:
    if hops > 3:
        raise BuildError("The link redirects too many times.")
    low = url.lower()
    if low.startswith("edomh://"):
        return from_edomh(decode_edomh_uri(url), db, warnings, url)
    parsed = urllib.parse.urlparse(url if "://" in url else "https://" + url)
    host = (parsed.netloc or "").lower()
    if host.endswith("edsy.org"):
        frag = parsed.fragment or ""
        m = re.search(r"(?:^|/)L=([^/&]+)", frag)
        if m:
            build = from_edsy_hash(urllib.parse.unquote(m.group(1)), db, warnings)
            build["url"] = url
            return build
        if parsed.path.startswith("/s/"):
            return _from_url(_follow(url, fetch), fetch, db, warnings, hops + 1)
        raise BuildError("That EDSY link has no build in it (no #/L=…).")
    if host.endswith("coriolis.io") or host.endswith("coriolis.edcd.io"):
        data = urllib.parse.parse_qs(parsed.query).get("data")
        if data:
            build = _from_json(decode_coriolis(data[0]), db, warnings)
            build["source"] = "Coriolis"
            build["url"] = url
            return build
        raise BuildError("That Coriolis link has no build in it (no import?data=…). "
                         "Use Coriolis's Export → SLEF, or its share link.")
    if host.endswith("orbis.zone"):
        return _from_url(_follow(url, fetch), fetch, db, warnings, hops + 1)
    if host.endswith("edomh.nl"):
        target = _follow(url, fetch)
        if not target.lower().startswith("edomh://"):
            raise BuildError("That EDOMH link did not lead to a ship.")
        return _from_url(target, fetch, db, warnings, hops + 1)
    raise BuildError("Not a link EDLD reads: EDSY, Coriolis, EDOMH, or SLEF/Loadout JSON.")


def _follow(url: str, fetch: Optional[Fetch]) -> str:
    if fetch is None:
        raise BuildError("Short links need the network to follow.")
    try:
        target = fetch(url)
    except BuildError:
        raise
    except Exception as exc:
        raise BuildError(f"Could not follow {url}: {type(exc).__name__}: {exc}") from None
    if not target:
        raise BuildError(f"{url} did not redirect anywhere.")
    return target


def redirect_target(url: str, timeout: float = 20) -> str:
    """Where a short link points, read from its redirect without following
    it (edomh:// is not a scheme urllib opens)."""
    import urllib.error
    import urllib.request

    class _Stop(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *a, **k):
            return None

    opener = urllib.request.build_opener(_Stop)
    req = urllib.request.Request(url, headers={"User-Agent": "EDLD"})
    try:
        with opener.open(req, timeout=timeout) as resp:
            body = resp.read(65536).decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        if exc.code in (301, 302, 303, 307, 308) and exc.headers.get("Location"):
            return urllib.parse.urljoin(url, exc.headers["Location"])
        raise
    m = re.search(r"""(?:url=|location\.(?:href|replace)\(?\s*=?\s*)['"]?([^'"\s>)]+)""",
                  body, re.I)
    if m:
        return urllib.parse.urljoin(url, m.group(1))
    raise BuildError(f"{url} did not redirect anywhere.")


# ── JSON: SLEF, Loadout, EDOMH ───────────────────────────────────────────────

def _from_json(obj: Any, db, warnings: list[str]) -> dict:
    if isinstance(obj, list):
        if not obj:
            raise BuildError("The SLEF list is empty.")
        if len(obj) > 1:
            warnings.append(f"The SLEF holds {len(obj)} ships; the first was read.")
        obj = obj[0]
    if not isinstance(obj, dict):
        raise BuildError("Not a ship build.")
    if obj.get("event") == "ship" and "shipConfiguration" in obj:
        return from_edomh(obj, db, warnings)
    if "data" in obj and isinstance(obj["data"], dict):
        header = obj.get("header") or {}
        build = from_loadout(obj["data"])
        build["source"] = str(header.get("appName") or "SLEF")
        if header.get("appURL"):
            build["url"] = str(header["appURL"])
        return build
    if "Modules" in obj and "Ship" in obj:
        return from_loadout(obj)
    raise BuildError("JSON, but not SLEF, a Loadout event or an EDOMH ship.")


def from_loadout(ev: dict, source: str = "Loadout") -> dict:
    """A build from a journal Loadout event (or SLEF's data)."""
    ship = str(ev.get("Ship") or "").strip().lower()
    if not ship:
        raise BuildError("The build names no ship.")
    mods = []
    for m in ev.get("Modules") or []:
        slot = str(m.get("Slot") or "")
        item = str(m.get("Item") or "").strip().lower()
        if not slot or not item:
            continue
        eng = m.get("Engineering") or {}
        out = {"slot": slot, "item": item, "on": bool(m.get("On", True)),
               "priority": int(m.get("Priority") or 0)}
        if eng.get("BlueprintName") or eng.get("ExperimentalEffect"):
            e = {}
            if eng.get("BlueprintName"):
                e["BlueprintName"] = str(eng["BlueprintName"])
                e["Level"] = int(eng.get("Level") or 0)
                e["Quality"] = float(eng.get("Quality") or 0)
            if eng.get("ExperimentalEffect"):
                e["ExperimentalEffect"] = str(eng["ExperimentalEffect"])
            out["engineering"] = e
        mods.append(out)
    return {"ship": ship, "name": str(ev.get("ShipName") or ""),
            "ident": str(ev.get("ShipIdent") or ""), "source": source, "url": "",
            "modules": mods}


def decode_coriolis(data: str) -> Any:
    """Coriolis's import data: base64 of gzipped SLEF JSON."""
    # parse_qs has already unquoted it, and read a bare "+" as a space.
    s = urllib.parse.unquote(data).replace(" ", "+")
    s += "=" * (-len(s) % 4)
    try:
        raw = base64.b64decode(s.replace("-", "+").replace("_", "/"))
        return json.loads(gzip.decompress(raw).decode("utf-8"))
    except Exception as exc:
        raise BuildError(f"The Coriolis link's data could not be read: {exc}") from None


# ── EDSY build hashes ────────────────────────────────────────────────────────

_HASH = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz_-"
_HASH_NUM = {c: i for i, c in enumerate(_HASH)}
_HASHT = " !\"#$%&'()*+,-./:;<=>?@[\\]^_`{|}~"


def _dec(h: str) -> int:
    n = 0
    for c in h:
        n = (n << 6) | _HASH_NUM.get(c, 0)
    return n


def _dec_text(h: str) -> str:
    out, i = [], 0
    while i < len(h):
        c1 = _HASH_NUM.get(h[i])
        i += 1
        if c1 is None:
            continue
        if c1 < 62:
            out.append(_HASH[c1])
        elif c1 == 62:
            c2 = _HASH_NUM.get(h[i:i + 1], 0) if i < len(h) else 0
            i += 1
            out.append(_HASHT[c2] if c2 < len(_HASHT) else "")
        else:
            a = _HASH_NUM.get(h[i:i + 1], 0) if i < len(h) else 0
            b = _HASH_NUM.get(h[i + 1:i + 2], 0) if i + 1 < len(h) else 0
            i += 2
            out.append(chr(((a << 6) | b) + 0x7F))
    return "".join(out)


#: The oldest build hash read here; older ones are re-saved by EDSY itself.
EDSY_MIN_VERSION = 15


def _edsy_maps(version: int) -> dict:
    """EDSY's id and slot renumberings for a hash older than its current one."""
    slotnum: dict = {}
    module: dict = {}
    if version <= 16:
        module.update({86220: 86250, 86222: 86262, 86310: 86330, 86312: 86352})
    if version <= 18:
        slotnum.setdefault(46, {})["hardpoint"] = [4, 5, 0, 1, 2, 3]
    if version <= 19:
        slotnum.setdefault(32, {})["internal"] = list(range(1, 10))
        slotnum.setdefault(33, {})["internal"] = list(range(2, 12))
        slotnum.setdefault(3, {})["internal"] = list(range(1, 10))
        slotnum.setdefault(4, {})["internal"] = list(range(1, 10))
    return {"slotnum": slotnum, "module": module}


def _need_db(db, what: str):
    if db is None:
        raise BuildError(f"{what} needs EDSY's reference data, which has not been "
                         "downloaded yet. Try again in a moment.")
    return db


def from_edsy_hash(buildhash: str, db, warnings: list[str]) -> dict:
    """A build from the L= part of an EDSY link."""
    db = _need_db(db, "An EDSY link")
    h = buildhash.strip()
    if not h:
        raise BuildError("The EDSY link is empty.")
    version = _dec(h[0])
    if version < EDSY_MIN_VERSION:
        raise BuildError("That EDSY link is from an old version of EDSY. Open it in "
                         "EDSY and copy the link again.")
    maps = _edsy_maps(version)
    chunks = h[1:].split(",")
    chunks += [""] * (8 - len(chunks))
    groups = dict(zip(("ship", "hardpoint", "utility", "component", "military",
                       "internal", "name", "nametag"), chunks))
    ship_chunk = groups["ship"]
    i = 0
    shipid = _dec(ship_chunk[i:i + 1]); i += 1
    ship = db.ships.get(shipid)
    if ship is None:
        raise BuildError(f"EDSY ship #{shipid} is not in EDSY's tables. Try again "
                         "after the tables refresh.")
    i += 1                                        # discounts
    costbits = _dec(ship_chunk[i:i + 1]); i += 1
    i += ((costbits >> 4) & 0x3) + 2              # hull cost
    i += 1 + 2                                    # crew and distributor
    mods: list[dict] = []
    hatch = ship_chunk[i:]
    if hatch:
        m = _edsy_module(hatch, None, ship, db, maps, warnings, "CargoHatch")
        if m:
            m["slot"] = "CargoHatch"
            mods.append(m)
    for group in ("hardpoint", "utility", "component", "military", "internal"):
        chunk = groups[group]
        j = n = 0
        remap = (maps["slotnum"].get(shipid) or {}).get(group)
        while j < len(chunk):
            start = j
            modid = _dec(chunk[j:j + 3]); j += 3
            if modid >= 199900:
                n += modid - 199900
                continue
            slotbits = _dec(chunk[j:j + 1]); j += 1
            if slotbits & 0x20:
                cb = _dec(chunk[j:j + 1]); j += 1
                j += ((cb >> 4) & 0x3) + 2
            else:
                j += 1
            if slotbits & 0x10:
                j += 2 + 2
                nummods = _dec(chunk[j:j + 1]); j += 1
                j += nummods * 4
            slotnum = remap[n] if remap and n < len(remap) else n
            n += 1
            slot = db.slot_name(ship, group, slotnum)
            m = _edsy_module(chunk[start:j], group, ship, db, maps, warnings, slot)
            if m:
                m["slot"] = slot
                mods.append(m)
    return {"ship": ship.fdname.lower(),
            "name": _dec_text(groups["name"]) if groups["name"] else "",
            "ident": _dec_text(groups["nametag"]) if groups["nametag"] else "",
            "source": "EDSY", "url": "", "modules": mods}


def _edsy_module(h: str, group, ship, db, maps, warnings, slot) -> Optional[dict]:
    i = 0
    modid = _dec(h[i:i + 3]); i += 3
    modid = max(0, maps["module"].get(modid, modid)) & 0x1FFFF
    mod = ship.modules.get(modid) or db.modules.get(modid)
    if mod is None:
        warnings.append(f"{slot}: EDSY module #{modid} is unknown; left out.")
        return None
    slotbits = _dec(h[i:i + 1]); i += 1
    out = {"item": mod.fdname.lower(), "on": not (slotbits & 0x8),
           "priority": slotbits & 0x7}
    if slotbits & 0x20:
        cb = _dec(h[i:i + 1]); i += 1
        i += ((cb >> 4) & 0x3) + 2
    else:
        i += 1
    if slotbits & 0x10:
        engbits = _dec(h[i:i + 2]); i += 2
        roll = _dec(h[i:i + 2]) / 4000.0; i += 2
        mtype = db.mtypes.get(mod.mtype) or {}
        bpidx = (engbits >> 7) & 0xF
        grade = (engbits >> 4) & 0x7
        expidx = engbits & 0xF
        eng: dict = {}
        bps = mtype.get("blueprints") or []
        if bpidx and bpidx <= len(bps):
            bp = db.blueprints.get(bps[bpidx - 1])
            if bp is not None:
                eng.update({"BlueprintName": bp.fdname, "Level": grade,
                            "Quality": round(min(1.0, roll), 4)})
        exps = mtype.get("expeffects") or []
        if expidx and expidx <= len(exps):
            ex = db.effects.get(exps[expidx - 1])
            if ex is not None:
                eng["ExperimentalEffect"] = ex.fdname
        if eng:
            out["engineering"] = eng
    return out


# ── EDOMH ships ──────────────────────────────────────────────────────────────

_EDOMH_PREFIX = "edomh://ship/?"


def decode_edomh_uri(uri: str) -> dict:
    """edomh://ship/?<base64url(zlib(json))> as EDOMH's ship JSON."""
    if not uri.lower().startswith(_EDOMH_PREFIX):
        raise BuildError("Not an EDOMH ship address.")
    enc = uri[len(_EDOMH_PREFIX):]
    enc += "=" * (-len(enc) % 4)
    try:
        obj = json.loads(zlib.decompress(base64.urlsafe_b64decode(enc)).decode("utf-8"))
    except Exception as exc:
        raise BuildError(f"The EDOMH ship could not be read: {exc}") from None
    if obj.get("event") != "ship" or "shipConfiguration" not in obj:
        raise BuildError("The EDOMH link holds no ship.")
    return obj


def _norm(s: str) -> str:
    return re.sub(r"[^A-Z0-9]+", "", (s or "").upper())


#: EDOMH hull names that do not normalize onto the journal's.
_EDOMH_SHIPS = {
    "LYNX_HIGHLINER": "mediumtransport01", "KESTREL_MK_II": "smallcombat01_nx",
    "PANTHER_CLIPPER_MK_II": "panthermkii", "TYPE_9_MILITARY": "type9_military",
}

#: EDOMH module names that differ from the game's.
_EDOMH_NAMES = {
    "FRAMESHIFTDRIVEBOOSTER": ["Guardian Frame Shift Drive Booster"],
    "FRAMESHIFTDRIVEOVERCHARGE": ["Frame Shift Drive (SCO)"],
    "FIGHTERHANGAR": ["Vessel Hangar"],
    "MKIIFIGHTERHANGAR": ["Mk II Vessel Hangar"],
    "LARGECARGORACK": ["Mk II Cargo Rack"],
    "GUARDIANSHIELDREINFORCEMENTPACKAGE": ["Guardian Shield Reinforcement Package",
                                           "Guardian Shield Reinforcement"],
    "HULLREINFORCEMENTPACKAGE": ["Hull Reinforcement Package", "Hull Reinforcement"],
    "MODULEREINFORCEMENTPACKAGE": ["Module Reinforcement Package", "Module Reinforcement"],
    "GUARDIANMODULEREINFORCEMENTPACKAGE": ["Guardian Module Reinforcement Package",
                                           "Guardian Module Reinforcement"],
    "GUARDIANHULLREINFORCEMENTPACKAGE": ["Guardian Hull Reinforcement Package",
                                         "Guardian Hull Reinforcement"],
}
_EDOMH_MKII = {
    "THRUSTERS": ["Mk II Agile Boost Thrusters", "Mk II Gravity Optimised Thrusters",
                  "Mk II Enhanced Performance Thrusters"],
    "FRAMESHIFTDRIVEOVERCHARGE": ["Mk II Supercharge Optimised FSD (SCO)",
                                  "Mk II Supercharge Optimised Frame Shift Drive (SCO)"],
}
_EDOMH_BLUEPRINTS = {
    "DIRTY_DRIVE_TUNING": "Dirty Tuning", "CLEAN_DRIVE_TUNING": "Clean Tuning",
    "DRIVE_STRENGTHENING": "Strengthening",
    "ENHANCED_LOW_POWER_SHIELDS": "Enhanced, Low Power",
    "EXPANDED_PROBE_SCANNING_RADIUS": "Expanded Radius",
    "HIGH_CAPACITY_MAGAZINE": "High Capacity", "INCREASED_CARGO_CAPACITY": "Expanded Cargo Rack",
    "INCREASED_FSD_RANGE": "Increased Range",
    "INCREASED_FSD_RANGE_FASTER_FSD_BOOT_SEQUENCE": "Increased Range",
    "LIGHTWEIGHT": "Light Weight", "LIGHT_WEIGHT_SCANNER": "Light Weight",
    "LONG_RANGE_SCANNER": "Long Range", "LONG_RANGE_WEAPON": "Long Range",
    "MERC_EXTENDED_CARGO_RACK": "Extended Cargo Rack",
    "MERC_SCOOP_RATE_ENHANCED_FUEL_SCOOP": "Scoop Rate Enhanced",
    "RAPID_FIRE_MODIFICATION": "Rapid Fire", "EFFICIENT_WEAPON": "Efficient", "REINFORCED_SHIELDS": "Reinforced",
    "SHORT_RANGE_BLASTER": "Short Range", "STURDY_MOUNT": "Sturdy",
    "THERMAL_RESISTANT_HULL_REINFORCEMENT": "Thermal Resistant",
    "THERMAL_RESISTANT_SHIELDS": "Thermal Resistant",
}
_EDOMH_EFFECTS = {"SUPER_CAPACITOR": "Super Capacitors", "HI_CAP": "Hi-Cap",
                  "LO_DRAW": "Lo-Draw", "MULTI_SERVOS": "Multi-Servos",
                  "MULTI_WEAVE": "Multi-Weave"}
_MOUNTS = {"Fixed": "F", "Gimballed": "G", "Turret": "T"}
_EDOMH_ID = re.compile(r"^(?P<base>.+?)_(?P<cls>\d+)_(?P<rating>[A-I])(?P<rest>(?:_[A-Z0-9]+)*)$")
_EDOMH_ARMOUR = re.compile(r"^.+?_ARMOUR_(?:GRADE_(?P<grade>\d+)|(?P<special>REACTIVE|MIRRORED))$")


def _module_index(db) -> dict:
    """Normalized names → [(module id, class, rating, mount)], from EDSY's
    tables and EDLD's own outfitting list."""
    idx = getattr(db, "_edomh_index", None)
    if idx is not None:
        return idx
    idx = {}

    def add(name, fd, cls, rating, mount, rank):
        for key, r in ((_norm(name), rank + 2),
                       (_norm(re.sub(r"\s*\([^)]*\)", "", name)), rank)):
            if key:
                idx.setdefault(key, []).append((r, fd, cls, rating, mount))

    for mod in db.modules.values():
        if mod.name:
            add(mod.name, mod.fdname.lower(), mod.cls, mod.rating, mod.mount, 2)
    try:
        from data.outfitting import OUTFITTING
        for sym, (cls, rating, name, mount) in OUTFITTING.items():
            add(name, sym, cls, rating, _MOUNTS.get(mount, ""), 1)
    except Exception:
        pass
    db._edomh_index = idx
    return idx


def _edomh_module(item_id: str, ship_fd: str, db) -> str:
    upper = item_id.upper()
    arm = _EDOMH_ARMOUR.fullmatch(upper)
    if arm:
        variant = f"Grade{int(arm.group('grade'))}" if arm.group("grade") \
            else arm.group("special").title()
        fd = f"{ship_fd}_armour_{variant}".lower()
        if db.module(fd) is None:
            raise BuildError(f"No {variant} bulkheads for this hull ({item_id}).")
        return fd
    m = _EDOMH_ID.fullmatch(upper)
    base, cls, rating, mount, flags = upper, None, None, None, set()
    if m:
        base, cls, rating = m.group("base"), int(m.group("cls")), m.group("rating")
        toks = [t for t in (m.group("rest") or "").split("_") if t]
        k = 0
        while k < len(toks):
            t = toks[k]
            if t == "MK" and k + 1 < len(toks) and toks[k + 1] == "II":
                flags.add("mkii"); k += 2; continue
            if t in ("F", "G", "T") and mount is None:
                mount = t
            elif t == "FREE":
                flags.add("free")
            k += 1
    key = _norm(base)
    names = (_EDOMH_MKII.get(key, []) if "mkii" in flags else []) + \
        _EDOMH_NAMES.get(key, []) + [base]
    idx = _module_index(db)
    scored = []
    for pos, name in enumerate(names):
        bonus = (len(names) - pos) * 100
        for r, fd, mcls, mrating, mmount in idx.get(_norm(name), []):
            scored.append((r + bonus, fd, mcls, mrating, mmount))
    if not scored:
        raise BuildError(f"No module is named like {item_id}.")
    wants_free = "free" in flags
    ok = [s for s in scored
          if not (mount and s[4] and s[4] != mount) and s[1].endswith("_free") == wants_free]
    ok = ok or scored

    def size_of(fd):
        sm = re.search(r"size(\d+)", fd.replace("_", ""))
        return int(sm.group(1)) if sm else None

    def rank(s):
        r, fd, mcls, mrating, mmount = s
        size_hit = cls is not None and (mcls == cls or size_of(fd) == cls)
        return (int(size_hit), int(rating is not None and (mrating or "").upper() == rating),
                int(mount is not None and mmount == mount), r)

    best = max(ok, key=rank)
    if cls is not None and best[2] != cls and size_of(best[1]) != cls:
        raise BuildError(f"No class {cls} module matches {item_id}.")
    return best[1]


def _edomh_label(raw: str, item: str, db, kind: str) -> Optional[str]:
    key = raw.upper()
    aliases = _EDOMH_BLUEPRINTS if kind == "bp" else _EDOMH_EFFECTS
    label = aliases.get(key)
    if label is None:
        t = key
        while "_" in t and label is None:
            t = t.rsplit("_", 1)[0]
            label = aliases.get(t)
    want = _norm(label or key.replace("_", " "))
    mod = db.module(item)
    mtype = db.mtypes.get(mod.mtype if mod else "", {})
    table = db.blueprints if kind == "bp" else db.effects
    legal = mtype.get("blueprints" if kind == "bp" else "expeffects", [])
    for k in legal:
        e = table.get(k)
        if e and _norm(e.name) == want:
            return e.fdname
    hits = {e.fdname for e in table.values() if _norm(e.name) == want}
    return hits.pop() if len(hits) == 1 else None


def _edomh_slots(ship) -> dict:
    """EDOMH's slot lists → journal slot names: optional slots are internal
    and military merged, largest first, internal before military."""
    opt = []
    for n, size in enumerate(ship.slots.get("internal") or []):
        opt.append((size, 0, _slot_override(ship, "internal", n)
                    or f"Slot{n + 1:02d}_Size{size}"))
    for n, size in enumerate(ship.slots.get("military") or []):
        opt.append((size, 1, _slot_override(ship, "military", n) or f"Military{n + 1:02d}"))
    opt.sort(key=lambda e: (-e[0], e[1]))
    return {"optional": [e[2] for e in opt]}


def _slot_override(ship, group, n) -> str:
    names = ship.slotnames.get(group) or []
    return names[n] if n < len(names) else ""


def from_edomh(obj: dict, db, warnings: list[str], url: str = "") -> dict:
    """A build from EDOMH's ship JSON."""
    db = _need_db(db, "An EDOMH ship")
    cfg = obj.get("shipConfiguration") or {}
    st = str(cfg.get("shipType") or "")
    ship_fd = _EDOMH_SHIPS.get(st.upper())
    ship = db.ship(ship_fd) if ship_fd else None
    if ship is None:
        want = _norm(st)
        ship = next((s for s in db.ships.values()
                     if _norm(s.fdname) == want or _norm(s.name) == want), None)
    if ship is None:
        raise BuildError(f"EDOMH hull {st!r} is not one EDLD knows.")
    fd = ship.fdname.lower()
    opt = _edomh_slots(ship)["optional"]
    mods: list[dict] = []

    def slot_for(group: str, index: int) -> str:
        if group == "core":
            from core.eddb import CORE_SLOTS
            return CORE_SLOTS[index]
        if group == "optional":
            return opt[index]
        return db.slot_name(ship, group, index)

    def add(entry: dict, slot: str) -> None:
        try:
            item = _edomh_module(str(entry["id"]), fd, db)
        except BuildError as exc:
            warnings.append(f"{slot}: {exc}")
            return
        m = {"slot": slot, "item": item, "on": bool(entry.get("powered", True)),
             "priority": max(0, int(entry.get("powerGroup") or 1) - 1)}
        eng: dict = {}
        for mod in (entry.get("modification") or [])[:1]:
            bp = _edomh_label(str(mod.get("type") or ""), item, db, "bp")
            if bp:
                g = re.search(r"(\d+)", str(mod.get("grade") or ""))
                eng.update({"BlueprintName": bp, "Level": int(g.group(1)) if g else 0,
                            "Quality": float(mod.get("percentComplete") or 0)})
            elif mod.get("type"):
                warnings.append(f"{slot}: blueprint {mod.get('type')} not recognized.")
        for ex in (entry.get("experimentalEffect") or [])[:1]:
            fx = _edomh_label(str(ex.get("type") or ""), item, db, "fx")
            if fx:
                eng["ExperimentalEffect"] = fx
            elif ex.get("type"):
                warnings.append(f"{slot}: experimental {ex.get('type')} not recognized.")
        if eng:
            m["engineering"] = eng
        mods.append(m)

    hatch = cfg.get("cargoHatch") or {}
    if hatch.get("id"):
        mods.append({"slot": "CargoHatch", "item": "modularcargobaydoor",
                     "on": bool(hatch.get("powered", True)),
                     "priority": max(0, int(hatch.get("powerGroup") or 1) - 1)})
    for key, group in (("coreSlots", "core"), ("optionalSlots", "optional"),
                       ("hardpointSlots", "hardpoint"), ("utilitySlots", "utility")):
        for entry in cfg.get(key) or []:
            if not entry.get("id"):
                continue
            try:
                slot = slot_for(group, int(entry.get("index") or 0))
            except (IndexError, ValueError):
                warnings.append(f"EDOMH {group} slot {entry.get('index')} is not on this hull.")
                continue
            add(entry, slot)
    return {"ship": fd, "name": str(cfg.get("name") or ""), "ident": "",
            "source": "EDOMH", "url": url, "modules": mods}
