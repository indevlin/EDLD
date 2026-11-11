"""components/engineering.py — Combined engineering materials inventory.

Tracks all seven engineering material categories across both the Horizons and Odyssey systems:

  Horizons (ship-based engineering)
    Raw          — geological elements (Carbon, Vanadium, Polonium …)
    Manufactured — salvaged tech components (Heat Conductors, Polymer Capacitors …)
    Encoded      — scanned data (Modified Consumer Firmware …)

  Odyssey (on-foot engineering)
    Components   — physical parts found at settlements and on bodies
    Items        — crafted or looted objects
    Consumables  — single-use items (medkits, energy cells …)
    Data         — mission and intel data packages

Horizons materials are sourced entirely from journal events.

The plugin also keeps the Engineering window's builds: a target build for any
owned ship, and planned builds for hulls not yet bought (core/eng_plan.py says
what each still needs). They are stored as engineering.builds.json:

    {"targets":  {"<ShipID>": build},
     "planned":  {"<plan id>": {"ship": journal ship id, "build": build | null}},
     "selected": "ship:<ShipID>" | "plan:<plan id>"}

A build is core/builds.py's.

State stored on MonitorState (all added via hasattr guard in on_load):
    materials_raw          dict  — {name_lower: {"count": int, "name_local": str}}
    materials_manufactured dict
    materials_encoded      dict
    engineering_locker     dict  — {
                                     "components":  {name_lower: {"count": int, "name_local": str}},
                                     "items":       { … },
                                     "consumables": { … },
                                     "data":        { … },
                                   }

Dashboard block: engineering (replaces the former 'materials' block)
"""

import json
from pathlib import Path

from core.plugin_loader import BasePlugin


class EngineeringPlugin(BasePlugin):
    PLUGIN_NAME        = "engineering"
    PLUGIN_DISPLAY     = "Engineering"
    PLUGIN_VERSION     = "1.0.0"
    PLUGIN_DESCRIPTION = "Engineering materials — Horizons Raw/Manufactured/Encoded and Odyssey ShipLocker inventory."

    SUBSCRIBED_EVENTS = [
        # Horizons materials
        "Materials",            # Full snapshot — always authoritative
        "MaterialCollected",    # Picked up one item
        "MaterialDiscarded",    # Discarded one or more
        "MaterialTrade",        # Traded at a material trader
        "EngineerCraft",        # Consumed materials for a blueprint
        "TechnologyBroker",     # Consumed materials for a tech unlock
        "Synthesis",            # Consumed materials for synthesis
        "EngineerContribution", # Materials given to unlock an engineer
        "MissionCompleted",     # Materials given as a reward
        "ScientificResearch",   # Materials given to research
        # Odyssey ShipLocker
        "ShipLocker",
        "BackpackChange", "BuyMicroResources", "SellMicroResources",           # Full snapshot of on-foot inventory
    ]

    def on_load(self, core) -> None:
        super().on_load(core)
        core.register_block(self, priority=50)

        s = core.state
        if not hasattr(s, "materials_raw"):          s.materials_raw          = {}
        if not hasattr(s, "materials_manufactured"): s.materials_manufactured = {}
        if not hasattr(s, "materials_encoded"):      s.materials_encoded      = {}
        if not hasattr(s, "engineering_locker"):
            s.engineering_locker = {
                "components":  {},
                "items":       {},
                "consumables": {},
                "data":        {},
            }

        # Ship materials as the journals before this one left them.
        self._bootstrap_materials()
        # Recipes every craft in the journals shows.
        self._learn_recipes()
        # Bootstrap Backpack.json for immediate Odyssey backpack display
        _bootstrap_backpack(s, core.journal_dir)
        # Read ShipLocker.json for immediate locker display on startup
        self._read_shiplocker_json(core)

        # Deferred startup refresh — fires after the app event loop is running
        import threading
        threading.Timer(3.0, self._startup_refresh).start()

    #: The events that change ship materials, the snapshot first.
    _MATERIAL_EVENTS = ("Materials", "MaterialCollected", "MaterialDiscarded",
                        "MaterialTrade", "EngineerCraft", "TechnologyBroker", "Synthesis",
                        "EngineerContribution", "MissionCompleted", "ScientificResearch")

    def _bootstrap_materials(self) -> None:
        """Replay the newest Materials snapshot in the journals before the
        current one, and every material event after it there. The current
        journal is replayed by the preload, so is left to it."""
        try:
            from core.journal import find_latest_journal
            from core.journal_index import index_for
            jdir = Path(self.core.journal_dir)
            latest = find_latest_journal(jdir)
            idx = index_for(jdir)
            older = [f for f in idx.files() if latest is None or f != latest.name]
            if not older:
                return
            hit = idx.last(("Materials",), files=older)
            if hit is None:
                return
            start = older.index(hit[0])
            seen = False
            for _f, ev in idx.events(self._MATERIAL_EVENTS, files=older[start:]):
                if ev.get("event") == "Materials":
                    seen = ev.get("timestamp") == hit[1].get("timestamp") or seen
                if seen:
                    self.on_event(ev, self.core.state)
        except Exception as exc:
            from core import debug as _dbg
            _dbg.log(f"  [engineering] materials not read from the journals: "
                     f"{type(exc).__name__}: {exc}")

    def _learn_recipes(self) -> None:
        try:
            from core import eddb
            from core.journal_index import index_for
            db = eddb.load()
            for _f, ev in index_for(Path(self.core.journal_dir)).events(("EngineerCraft",)):
                eddb.observe_craft(ev, db)
        except Exception as exc:
            from core import debug as _dbg
            _dbg.log(f"  [engineering] recipes not read from the journals: "
                     f"{type(exc).__name__}: {exc}")

    def _startup_refresh(self) -> None:
        gq = self.core.gui_queue if self.core else None
        if gq:
            gq.put(("plugin_refresh", "engineering"))

    def _read_shiplocker_json(self, core) -> None:
        """Read ShipLocker.json on startup for an immediate locker snapshot."""
        try:
            path = Path(core.journal_dir) / "ShipLocker.json"
            if path.exists():
                data = json.loads(path.read_text(encoding="utf-8"))
                core.state.engineering_locker = _parse_shiplocker(data)
        except Exception:
            pass

    def on_event(self, event: dict, state) -> None:
        core = self.core
        gq   = core.gui_queue
        ev   = event.get("event")

        match ev:

            case "Materials":
                state.materials_raw          = _parse_horizons_list(event.get("Raw", []))
                state.materials_manufactured = _parse_horizons_list(event.get("Manufactured", []))
                state.materials_encoded      = _parse_horizons_list(event.get("Encoded", []))
                if gq: gq.put(("plugin_refresh", "engineering"))

            case "MaterialCollected":
                cat    = event.get("Category", "").lower()
                key    = event.get("Name", "").lower()
                count  = int(event.get("Count", 1))
                bucket = _horizons_bucket(state, cat)
                if bucket is not None and key:
                    entry = bucket.setdefault(key, {
                        "count":      0,
                        "name_local": event.get("Name_Localised") or _fmt_name(key),
                    })
                    entry["count"] += count
                if gq: gq.put(("plugin_refresh", "engineering"))

            case "MaterialDiscarded":
                cat    = event.get("Category", "").lower()
                key    = event.get("Name", "").lower()
                count  = int(event.get("Count", 1))
                bucket = _horizons_bucket(state, cat)
                if bucket is not None and key and key in bucket:
                    bucket[key]["count"] -= count
                    if bucket[key]["count"] <= 0:
                        del bucket[key]
                if gq: gq.put(("plugin_refresh", "engineering"))

            case "MaterialTrade":
                # Each side is Material/Quantity, not Name/Count.
                for side, sign in ((event.get("Paid") or {}, -1),
                                   (event.get("Received") or {}, 1)):
                    key = str(side.get("Material") or side.get("Name") or "").lower()
                    count = int(side.get("Quantity", side.get("Count", 0)) or 0)
                    local = side.get("Material_Localised") or side.get("Name_Localised")
                    _adjust(state, side.get("Category", ""), key, sign * count, local)
                if gq: gq.put(("plugin_refresh", "engineering"))

            case "EngineerContribution":
                if str(event.get("Type") or "") == "Materials":
                    _adjust(state, "", str(event.get("Material") or "").lower(),
                            -int(event.get("Quantity") or 0))
                    if gq: gq.put(("plugin_refresh", "engineering"))

            case "MissionCompleted":
                rewards = event.get("MaterialsReward") or []
                for item in rewards:
                    _adjust(state, item.get("Category", ""),
                            str(item.get("Name") or "").lower(),
                            int(item.get("Count") or 0), item.get("Name_Localised"))
                if rewards and gq:
                    gq.put(("plugin_refresh", "engineering"))

            case "ScientificResearch":
                _adjust(state, event.get("Category", ""),
                        str(event.get("Name") or "").lower(),
                        -int(event.get("Count") or 0))
                if gq: gq.put(("plugin_refresh", "engineering"))

            case "EngineerCraft" | "TechnologyBroker" | "Synthesis":
                if ev == "EngineerCraft":
                    from core import eddb
                    eddb.observe_craft(event)
                key_ingr = "Ingredients" if ev != "Synthesis" else "Materials"
                for item in event.get(key_ingr, []):
                    cat    = item.get("Category", "").lower()
                    key    = item.get("Name", "").lower()
                    count  = int(item.get("Count", 1))
                    bucket = _horizons_bucket(state, cat)
                    if bucket is None:
                        for b in (state.materials_raw,
                                  state.materials_manufactured,
                                  state.materials_encoded):
                            if key in b:
                                bucket = b
                                break
                    if bucket is not None and key and key in bucket:
                        bucket[key]["count"] -= count
                        if bucket[key]["count"] <= 0:
                            del bucket[key]
                if gq: gq.put(("plugin_refresh", "engineering"))

            case "ShipLocker":
                state.engineering_locker = _parse_shiplocker(event)
                if gq: gq.put(("plugin_refresh", "engineering"))

    # ── Builds ────────────────────────────────────────────────────────────────

    def _builds(self) -> dict:
        data = getattr(self, "_builds_cache", None)
        if data is None:
            try:
                data = self.storage.read_json("builds") or {}
            except Exception:
                data = {}
            data.setdefault("targets", {})
            data.setdefault("planned", {})
            data.setdefault("selected", "")
            self._builds_cache = data
        return data

    def _save_builds(self) -> None:
        try:
            self.storage.write_json(self._builds(), "builds")
        except Exception as exc:
            from core import debug as _dbg
            _dbg.log(f"  [engineering] builds not saved: {type(exc).__name__}: {exc}",
                     level="WARN", echo=True)
        gq = self.core.gui_queue if self.core else None
        if gq:
            gq.put(("plugin_refresh", "engineering"))

    def selected(self) -> str:
        return str(self._builds().get("selected") or "")

    def select(self, key: str) -> None:
        if key != self.selected():
            self._builds()["selected"] = key
            self._save_builds()

    def target(self, key: str) -> dict | None:
        """The build planned for ``ship:<id>`` or ``plan:<id>``."""
        kind, _, ident = (key or "").partition(":")
        b = self._builds()
        if kind == "ship":
            return b["targets"].get(ident)
        if kind == "plan":
            return (b["planned"].get(ident) or {}).get("build")
        return None

    def set_target(self, key: str, build: dict | None) -> None:
        kind, _, ident = (key or "").partition(":")
        b = self._builds()
        if kind == "ship":
            if build:
                b["targets"][ident] = build
            else:
                b["targets"].pop(ident, None)
        elif kind == "plan" and ident in b["planned"]:
            b["planned"][ident]["build"] = build or None
        else:
            return
        self._save_builds()

    def planned(self) -> dict:
        return dict(self._builds()["planned"])

    def add_plan(self, ship_type: str) -> str:
        """A new planned build for a hull; its key."""
        b = self._builds()
        n = 1 + max([int(k) for k in b["planned"] if str(k).isdigit()] or [0])
        b["planned"][str(n)] = {"ship": str(ship_type).lower(), "build": None}
        b["selected"] = f"plan:{n}"
        self._save_builds()
        return f"plan:{n}"

    def delete_plan(self, key: str) -> None:
        kind, _, ident = (key or "").partition(":")
        b = self._builds()
        if kind == "plan" and b["planned"].pop(ident, None) is not None:
            if b.get("selected") == key:
                b["selected"] = ""
            self._save_builds()

    def apply_plan(self, plan_key: str, ship_key: str) -> bool:
        """Move a planned build onto an owned hull of its type, as that
        ship's target, and show the ship."""
        kind, _, pid = (plan_key or "").partition(":")
        skind, _, sid = (ship_key or "").partition(":")
        b = self._builds()
        plan = b["planned"].get(pid) if kind == "plan" else None
        if plan is None or skind != "ship" or not plan.get("build"):
            return False
        b["targets"][sid] = plan["build"]
        del b["planned"][pid]
        b["selected"] = ship_key
        self._save_builds()
        return True

    def import_build(self, text: str, ship_type: str = "") -> tuple[dict, list[str]]:
        """Read a build (core/builds.py), following short links over the
        network; raises BuildError. ``ship_type`` refuses another hull."""
        from core import builds, eddb
        db = eddb.load()
        build, warnings = builds.parse(text, fetch=builds.redirect_target, db=db)
        want = (ship_type or "").lower()
        if want and build.get("ship") and build["ship"] != want:
            from core.windows.engineering import hull_name
            raise builds.BuildError(f"That build is for the {hull_name(build['ship'])}, "
                                    f"not the {hull_name(want)}.")
        return build, warnings

    def nearest_traders(self, kinds, per_kind: int = 3) -> dict:
        """{kind: [station record]} for the nearest material traders of each
        kind ("raw", "mfc", "enc"), from Spansh; {} when that cannot be asked."""
        from core.eng_trade import nearest_traders
        return nearest_traders(self.core, kinds, per_kind)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _adjust(state, category: str, key: str, delta: int, local: str | None = None) -> None:
    """Add (or take) ``delta`` of a Horizons material. Without a category
    the bucket already holding it is used, then the one EDSY's tables name."""
    if not key or not delta:
        return
    cat = str(category or "").lower()
    if cat.startswith("$microresource_category_"):
        cat = cat[len("$microresource_category_"):]
    bucket = _horizons_bucket(state, cat) if cat else None
    if bucket is None:
        for b in (state.materials_raw, state.materials_manufactured, state.materials_encoded):
            if key in b:
                bucket = b
                break
    if bucket is None:
        bucket = _bucket_from_tables(state, key)
    if bucket is None:
        return
    if delta < 0:
        if key in bucket:
            bucket[key]["count"] += delta
            if bucket[key]["count"] <= 0:
                del bucket[key]
        return
    entry = bucket.setdefault(key, {"count": 0, "name_local": local or _fmt_name(key)})
    entry["count"] += delta


def _bucket_from_tables(state, key: str):
    try:
        from core import eddb
        db = eddb.load()
        mat = db.material(key) if db is not None else None
    except Exception:
        mat = None
    kind = getattr(mat, "kind", "")
    return {"raw": state.materials_raw, "mfc": state.materials_manufactured,
            "enc": state.materials_encoded}.get(kind)


def _parse_horizons_list(items: list) -> dict:
    """Parse a Horizons material list from a journal event into a name→data dict."""
    result = {}
    for item in items:
        key = item.get("Name", "").lower()
        if not key:
            continue
        result[key] = {
            "count":      int(item.get("Count", 0)),
            "name_local": item.get("Name_Localised") or _fmt_name(key),
        }
    return result


def _parse_shiplocker(data: dict) -> dict:
    """Parse a ShipLocker event or ShipLocker.json into the engineering_locker
    structure: dict of group name → {name_lower: {"count": int, "name_local": str}}.
    """
    result: dict[str, dict] = {}
    for group in ("Components", "Items", "Consumables", "Data"):
        bucket: dict = {}
        for item in data.get(group, []):
            count = int(item.get("Count", 0))
            if count <= 0:
                continue
            key  = item.get("Name", "").lower()
            disp = item.get("Name_Localised") or _fmt_name(key)
            bucket[key] = {"count": count, "name_local": disp}
        result[group.lower()] = bucket
    return result


def _horizons_bucket(state, category: str):
    """Return the correct Horizons materials dict for a category string."""
    if "raw" in category:          return state.materials_raw
    if "manufactured" in category: return state.materials_manufactured
    if "encoded" in category:      return state.materials_encoded
    return None


def _fmt_name(key: str) -> str:
    return key.replace("_", " ").title()


# ── Backpack JSON helpers ─────────────────────────────────────────────────────

def _bootstrap_backpack(state, journal_dir) -> None:
    """Bootstrap Odyssey backpack micro-resources from Backpack.json on startup."""
    if not hasattr(state, "engineering_backpack"):
        state.engineering_backpack = {}
    data = _read_backpack_json(journal_dir)
    if data:
        state.engineering_backpack = data


def _read_backpack_json(journal_dir) -> dict | None:
    """Read Backpack.json and return {category: [{name, name_local, count}]} or None."""
    if journal_dir is None:
        return None
    import json as _json
    from pathlib import Path as _Path
    import builtins as _bi
    path = _Path(journal_dir) / "Backpack.json"
    try:
        data = _json.load(_bi.open(path, encoding="utf-8"))
    except Exception:
        return None
    result = {}
    for cat in ("Items", "Components", "Consumables", "Data"):
        items = data.get(cat, [])
        if items:
            result[cat.lower()] = [
                {
                    "name":       i.get("Name", ""),
                    "name_local": i.get("Name_Localised") or i.get("Name", ""),
                    "count":      int(i.get("Count", 0)),
                }
                for i in items
            ]
    return result or None


