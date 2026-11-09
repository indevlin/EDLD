"""core/dossier/model.py — the dossier's pages, before they are HTML or Markdown.

Privacy
-------
* ``IncludeCurrentLocation`` — where the commander and the current ship are
  now, where the fleet carrier is, and its jump history. Stored ships are
  always listed where they are kept: that is the point of the fleet list, and
  a ship aboard a carrier is listed by the carrier, never by a system.
* ``IncludeBalance`` — the credit balance, total wealth, and the carrier's
  bank and how long it would cover upkeep.

The FID, and any token or key, are never in the model at all.
"""

from __future__ import annotations

import base64
import gzip
import json
import re
from datetime import datetime, timezone
from typing import Optional

from core.dossier import names
from core.dossier.ledger import hotspot_rates, now_utc

#: Page ids, in navigation order. Ship pages are ``ship-<ShipID>`` and sit
#: under Fleet.
PAGE_ORDER = ("commander", "fleet", "modules", "engineering", "carrier",
              "mining", "on-foot")


# ── formatting ────────────────────────────────────────────────────────────────

def cr(value) -> str:
    try:
        return f"{int(value):,} cr"
    except (TypeError, ValueError):
        return "—"


def num(value, digits: int = 0, unit: str = "") -> str:
    try:
        text = f"{float(value):,.{digits}f}"
    except (TypeError, ValueError):
        return "—"
    return f"{text} {unit}".strip()


def date(ts) -> str:
    if not ts:
        return "—"
    try:
        return datetime.fromtimestamp(float(ts), timezone.utc).strftime("%Y-%m-%d")
    except (TypeError, ValueError, OSError):
        return "—"


def when(ts) -> str:
    if not ts:
        return "—"
    try:
        return datetime.fromtimestamp(float(ts), timezone.utc).strftime(
            "%Y-%m-%d %H:%M UTC")
    except (TypeError, ValueError, OSError):
        return "—"


def duration(seconds) -> str:
    try:
        total = int(float(seconds))
    except (TypeError, ValueError):
        return "—"
    if total <= 0:
        return "—"
    days, rem = divmod(total, 86400)
    hours, rem = divmod(rem, 3600)
    minutes = rem // 60
    if days:
        return f"{days} d {hours} h"
    if hours:
        return f"{hours} h {minutes} m"
    return f"{minutes} m"


def pct(value, digits: int = 0) -> str:
    try:
        return f"{float(value):.{digits}f}%"
    except (TypeError, ValueError):
        return "—"


def iso_epoch(text) -> float:
    try:
        return datetime.fromisoformat(str(text).replace("Z", "+00:00")
                                      .replace(" ", "T")).replace(
            tzinfo=timezone.utc).timestamp()
    except (TypeError, ValueError):
        return 0.0


# ── outside tools ─────────────────────────────────────────────────────────────

def _encoded_loadout(loadout: dict) -> str:
    """A journal Loadout as Coriolis and EDSY take it in an import link.
    """
    body = {k: v for k, v in loadout.items() if not k.startswith("_")}
    data = json.dumps(body, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":")).encode("utf-8")
    packed = gzip.compress(data, mtime=0)
    return base64.urlsafe_b64encode(packed).decode().replace("=", "%3D")


def coriolis_url(loadout: dict) -> str:
    return "https://coriolis.io/import?data=" + _encoded_loadout(loadout)


def edsy_url(loadout: dict) -> str:
    return "https://edsy.org/#/I=" + _encoded_loadout(loadout)


# ── blocks ────────────────────────────────────────────────────────────────────

def facts(rows, title: str = "") -> dict:
    return {"type": "facts", "title": title,
            "rows": [(k, v) for k, v in rows if v not in (None, "", "—")]}


def table(columns, rows, title: str = "", numeric=(), empty: str = "",
          nowrap=()) -> dict:
    """``numeric`` columns are right-aligned; ``nowrap`` ones never break —
    a date or a carrier callsign split across two lines reads as two
    values."""
    return {"type": "table", "title": title, "columns": list(columns),
            "rows": rows, "numeric": set(numeric), "nowrap": set(nowrap),
            "empty": empty}


def note(text: str) -> dict:
    return {"type": "note", "text": text}


def links(items, title: str = "") -> dict:
    return {"type": "links", "title": title, "items": items}


def details(title: str, blocks: list) -> dict:
    return {"type": "details", "title": title, "blocks": blocks}


# ── the model ─────────────────────────────────────────────────────────────────

class Model:
    """Builds every page from the ledger's state and the other sources."""

    def __init__(self, state: dict, *, include_location: bool = False,
                 include_balance: bool = False, deposits=None,
                 carrier_capi: Optional[dict] = None,
                 career: Optional[dict] = None,
                 live_balance: Optional[int] = None,
                 now: Optional[float] = None, version: str = ""):
        self.s = state
        self.loc = bool(include_location)
        self.bal = bool(include_balance)
        self.deposits = deposits or []
        self.capi = carrier_capi or {}
        self.career = career
        self.live_balance = live_balance
        self.now = now if now is not None else now_utc()
        self.version = version

    # ── shared lookups ────────────────────────────────────────────────────────

    def owned_ships(self) -> list[dict]:
        ships = self.s.get("ships", {})
        current = self.s.get("current_ship")
        out = [ships[k] for k in self.s.get("roster", {}).get("ids", [])
               if k in ships and not ships[k].get("sold")]
        out.sort(key=lambda sh: (str(sh["ship_id"]) != str(current),
                                 (sh.get("name") or "").lower() or "~",
                                 self.ship_type(sh)))
        return out

    def ship_type(self, ship: dict) -> str:
        return names.ship_type(ship.get("type", ""), ship.get("type_display", ""))

    def ship_title(self, ship: dict) -> str:
        return ship.get("name") or self.ship_type(ship)

    def own_carrier_id(self):
        return self.s.get("carrier", {}).get("id")

    def is_carrier(self, market_id) -> bool:
        if market_id is None:
            return False
        if market_id == self.own_carrier_id():
            return True
        market = self.s.get("markets", {}).get(str(market_id), {})
        return market.get("type") == "FleetCarrier"

    def carrier_label(self, market_id) -> str:
        carrier = self.s.get("carrier", {})
        if market_id == carrier.get("id") and carrier.get("callsign"):
            name = carrier.get("name") or ""
            return (f"Carrier {name} ({carrier['callsign']})" if name
                    else f"Carrier {carrier['callsign']}")
        market = self.s.get("markets", {}).get(str(market_id), {})
        return f"Carrier {market.get('name') or market_id}"

    def place(self, market_id, station: str, system: str) -> str:
        """A storage place. A carrier is named, never placed — it moves."""
        if self.is_carrier(market_id):
            return self.carrier_label(market_id)
        market = self.s.get("markets", {}).get(str(market_id), {}) if market_id else {}
        station = station or market.get("name", "")
        system = system or market.get("system", "")
        if station and system:
            return f"{station} · {system}"
        return station or system or "Unknown"

    def where_now(self) -> str:
        where = self.s.get("where", {})
        system = where.get("system", "")
        mid = where.get("market_id")
        if where.get("docked") and mid is not None:
            if self.is_carrier(mid):
                label = self.carrier_label(mid)
                return f"{label} · {system}" if system else label
            return self.place(mid, where.get("station", ""), system)
        return system or "Unknown"

    def ship_where(self, ship: dict) -> str:
        loc = ship.get("location") or {}
        kind = loc.get("kind")
        if str(ship["ship_id"]) == str(self.s.get("current_ship")) or kind == "current":
            return ("Current ship · " + self.where_now()) if self.loc else "Current ship"
        if kind == "transit":
            dest = self.place(loc.get("market_id"), loc.get("station", ""),
                              loc.get("system", ""))
            arrives = loc.get("arrives")
            if arrives and arrives <= self.now:
                return dest
            eta = f", arrives {when(arrives)}" if arrives else ""
            return f"In transit to {dest}{eta}"
        if kind == "station":
            return self.place(loc.get("market_id"), loc.get("station", ""),
                              loc.get("system", ""))
        return "Unknown"

    # ── pages ─────────────────────────────────────────────────────────────────

    def pages(self) -> list[dict]:
        pages = [self.commander_page(), self.fleet_page()]
        pages += [self.ship_page(sh) for sh in self.owned_ships()]
        pages += [self.modules_page(), self.engineering_page()]
        carrier = self.carrier_page()
        if carrier is not None:
            pages.append(carrier)
        pages += [self.mining_page(), self.on_foot_page()]
        return pages

    def build(self) -> dict:
        cmdr = self.s.get("commander", {})
        return {
            "commander": cmdr.get("name") or "Commander",
            "generated": self.now,
            "as_of": self.s.get("as_of", 0),
            "version": self.version,
            "pages": self.pages(),
            "ships": [{"id": f"ship-{sh['ship_id']}", "title": self.ship_title(sh)}
                      for sh in self.owned_ships()],
        }

    # Commander ────────────────────────────────────────────────────────────────

    _STATS = (
        ("Exploration", "Time_Played", "Time played", "duration"),
        ("Exploration", "Systems_Visited", "Systems visited", "int"),
        ("Exploration", "Total_Hyperspace_Jumps", "Hyperspace jumps", "int"),
        ("Exploration", "Total_Hyperspace_Distance", "Hyperspace distance", "ly"),
        ("Exploration", "Greatest_Distance_From_Start", "Furthest from start", "ly"),
        ("Exploration", "Exploration_Profits", "Exploration profits", "cr"),
        ("Exploration", "First_Footfalls", "First footfalls", "int"),
        ("Exploration", "Planet_Footfalls", "Planet footfalls", "int"),
        ("Exploration", "Settlements_Visited", "Settlements visited", "int"),
        ("Exobiology", "Organic_Data_Profits", "Exobiology profits", "cr"),
        ("Exobiology", "Organic_Species_Encountered", "Species encountered", "int"),
        ("Exobiology", "First_Logged", "Species first logged", "int"),
        ("Trading", "Market_Profits", "Trade profits", "cr"),
        ("Trading", "Markets_Traded_With", "Markets traded with", "int"),
        ("Mining", "Mining_Profits", "Mining profits", "cr"),
        ("Mining", "Quantity_Mined", "Quantity mined", "t"),
        ("Combat", "Bounties_Claimed", "Bounties claimed", "int"),
        ("Combat", "Bounty_Hunting_Profit", "Bounty hunting profits", "cr"),
        ("Combat", "Combat_Bonds", "Combat bonds", "int"),
        ("Combat", "Combat_Bond_Profits", "Combat bond profits", "cr"),
        ("Passengers", "Passengers_Missions_Delivered", "Passengers delivered", "int"),
        ("Search_And_Rescue", "SearchRescue_Count", "Search and rescue", "int"),
        ("Crafting", "Count_Of_Used_Engineers", "Engineers used", "int"),
        ("Crafting", "Recipes_Generated", "Blueprints applied", "int"),
        ("Bank_Account", "Owned_Ship_Count", "Ships owned", "int"),
        ("Bank_Account", "Spent_On_Ships", "Spent on ships", "cr"),
        ("Bank_Account", "Spent_On_Outfitting", "Spent on outfitting", "cr"),
    )

    def _stat(self, section, key, kind):
        value = (self.s.get("commander", {}).get("statistics", {})
                 .get(section, {}) or {}).get(key)
        if value is None:
            return None
        if kind == "duration":
            return duration(value)
        if kind == "cr":
            return cr(value)
        if kind == "ly":
            return num(value, 0, "ly")
        if kind == "t":
            return num(value, 0, "t")
        return num(value)

    def commander_page(self) -> dict:
        cmdr = self.s.get("commander", {})
        sq = cmdr.get("squadron") or {}
        pp = cmdr.get("powerplay") or {}
        rows = [("Commander", cmdr.get("name") or "—")]
        if sq.get("name"):
            rows.append(("Squadron", sq["name"] + (f" · {sq['rank']}" if sq.get("rank") else "")))
        if pp.get("Power"):
            line = pp["Power"]
            if pp.get("Rank") is not None:
                line += f" · rank {pp['Rank']}"
            rows.append(("Powerplay", line))
            if pp.get("Merits") is not None:
                rows.append(("Powerplay merits", num(pp["Merits"])))
            if pp.get("TimePledged"):
                rows.append(("Pledged for", duration(pp["TimePledged"])))
        owned = self.owned_ships()
        rows.append(("Ships", str(len(owned))))
        engineers = cmdr.get("engineers") or {}
        unlocked = sum(1 for e in engineers.values() if e.get("Progress") == "Unlocked")
        if engineers:
            rows.append(("Engineers unlocked", str(unlocked)))
        if self.bal:
            balance = self.live_balance if self.live_balance is not None else cmdr.get("credits")
            rows.append(("Credits", cr(balance)))
            wealth = self._stat("Bank_Account", "Current_Wealth", "cr")
            if wealth:
                rows.append(("Total wealth", wealth))
        if self.loc:
            rows.append(("Location", self.where_now()))
        blocks = [facts(rows)]

        ranks = cmdr.get("ranks") or {}
        progress = cmdr.get("progress") or {}
        if ranks:
            blocks.append(table(
                ["Rank", "Grade", "Progress"],
                [[label, names.rank_name(table_, ranks.get(key)),
                  pct(progress.get(key)) if key in progress else "—"]
                 for key, label, table_ in names.RANKS if key in ranks],
                title="Ranks", numeric=(2,)))
        rep = cmdr.get("reputation") or {}
        if rep:
            blocks.append(table(
                ["Superpower", "Reputation"],
                [[k, pct(v)] for k, v in sorted(rep.items())],
                title="Reputation", numeric=(1,)))
        stats = [(label, self._stat(sec, key, kind))
                 for sec, key, label, kind in self._STATS]
        if any(v for _l, v in stats):
            blocks.append(facts(stats, title="Career statistics"))
        if self.career and self.career.get("in"):
            blocks.append(self._ledger_table(self.career["in"], "Income by source"))
        if self.career and self.career.get("out"):
            blocks.append(self._ledger_table(self.career["out"], "Spending by category"))
        return {"id": "commander", "nav": "Commander",
                "title": f"CMDR {cmdr.get('name') or ''}".strip(),
                "subtitle": "Commander record", "blocks": blocks}

    def _ledger_table(self, amounts: dict, title: str) -> dict:
        total = sum(int(v or 0) for v in amounts.values()) or 1
        rows = [[k, cr(v), pct(100.0 * int(v or 0) / total, 1)]
                for k, v in sorted(amounts.items(), key=lambda kv: -int(kv[1] or 0))
                if int(v or 0)]
        rows.append(["Total", cr(sum(int(v or 0) for v in amounts.values())), ""])
        return table(["Source" if "Income" in title else "Category", "Credits", "Share"],
                     rows, title=title, numeric=(1, 2))

    # Fleet ────────────────────────────────────────────────────────────────────

    def fleet_page(self) -> dict:
        rows = []
        rebuy_total = 0
        for sh in self.owned_ships():
            lo = sh.get("loadout") or {}
            rebuy_total += int(lo.get("Rebuy") or 0)
            title = self.ship_title(sh)
            if sh.get("ident"):
                title += f" ({sh['ident']})"
            rows.append([
                {"text": title, "page": f"ship-{sh['ship_id']}"},
                self.ship_type(sh),
                self.ship_where(sh),
                num(lo.get("MaxJumpRange"), 2, "ly") if lo else "—",
                num(lo.get("CargoCapacity"), 0, "t") if lo else "—",
                cr(lo.get("Rebuy")) if lo else "—",
                duration(sh.get("seconds")),
                date(sh.get("last_flown")),
            ])
        blocks = [
            table(["Ship", "Type", "Where", "Jump range", "Cargo", "Rebuy",
                   "Time as active ship", "Last flown"], rows,
                  numeric=(3, 4, 5, 6), nowrap=(2, 7), empty="No ships recorded yet."),
            facts([("Ships", str(len(rows))), ("Rebuy, whole fleet", cr(rebuy_total))]),
            note("Fittings are each ship's last recorded Loadout: a stored ship "
                 "cannot be outfitted, so it stays true until the ship is flown "
                 "again. Ships kept aboard a fleet carrier are listed by the "
                 "carrier, which moves, rather than by a system."),
        ]
        return {"id": "fleet", "nav": "Fleet", "title": "Fleet",
                "subtitle": f"{len(rows)} ships", "blocks": blocks}

    # Ship ─────────────────────────────────────────────────────────────────────

    def ship_page(self, sh: dict) -> dict:
        lo = sh.get("loadout") or {}
        rows = [("Type", self.ship_type(sh)), ("Ident", sh.get("ident") or ""),
                ("Where", self.ship_where(sh))]
        blocks = []
        if lo:
            fuel = lo.get("FuelCapacity") or {}
            fuel_text = (num(fuel.get("Main"), 0, "t") +
                         (f" + {num(fuel.get('Reserve'), 2, 't')} reserve"
                          if fuel.get("Reserve") else "")) if isinstance(fuel, dict) \
                else num(fuel, 0, "t")
            rows += [
                ("Max jump range", num(lo.get("MaxJumpRange"), 2, "ly")),
                ("Cargo capacity", num(lo.get("CargoCapacity"), 0, "t")),
                ("Unladen mass", num(lo.get("UnladenMass"), 1, "t")),
                ("Fuel", fuel_text),
                ("Rebuy", cr(lo.get("Rebuy"))),
                ("Hull value", cr(lo["HullValue"]) if lo.get("HullValue") else ""),
                ("Modules value", cr(lo["ModulesValue"]) if lo.get("ModulesValue") else ""),
                ("Hull health", pct(100 * float(lo.get("HullHealth", 1.0)))),
                ("Fitting as of", when(sh.get("loadout_ts"))),
            ]
            blocks.append(facts(rows))
            blocks.append(links([
                {"text": "Open in Coriolis", "url": coriolis_url(lo)},
                {"text": "Open in EDSY", "url": edsy_url(lo)},
            ], title="Outfitting tools"))
            blocks += self._fitting(lo)
        else:
            blocks.append(facts(rows))
            blocks.append(note("No fitting recorded yet. It is recorded the next "
                               "time this ship is flown."))
        blocks += self._service_record(sh)
        title = self.ship_title(sh)
        sub = self.ship_type(sh) + (f" · {sh['ident']}" if sh.get("ident") else "")
        return {"id": f"ship-{sh['ship_id']}", "nav": title, "parent": "fleet",
                "title": title, "subtitle": sub, "blocks": blocks}

    @staticmethod
    def _engineering_text(eng: dict) -> str:
        if not eng or not eng.get("BlueprintName"):
            return ""
        parts = [f"{names.engineering_name(eng['BlueprintName'])} "
                 f"G{eng.get('Level', '?')}"]
        if eng.get("Quality") is not None:
            parts[0] += f" ({pct(100 * float(eng['Quality']))})"
        effect = eng.get("ExperimentalEffect_Localised") or (
            names.engineering_name(eng["ExperimentalEffect"])
            if eng.get("ExperimentalEffect") else "")
        if effect:
            parts.append(effect)
        if eng.get("Engineer"):
            parts.append(eng["Engineer"])
        return " · ".join(parts)

    def _fitting(self, lo: dict) -> list[dict]:
        groups: dict[str, list] = {key: [] for key, _t in names.GROUPS}
        modifiers = []
        for mod in lo.get("Modules") or []:
            slot, item = mod.get("Slot", ""), mod.get("Item", "")
            if not slot or not item or slot.lower() in names.HIDDEN_SLOTS:
                continue
            group = names.slot_group(slot, item)
            if group == "cosmetic":
                groups[group].append((names.slot_sort_key(slot), [
                    names.slot_label(slot), names.module_name(item)]))
                continue
            eng = mod.get("Engineering") or {}
            groups[group].append((names.slot_sort_key(slot), [
                names.slot_label(slot),
                names.module_name(item),
                self._engineering_text(eng),
                str(int(mod.get("Priority", 0)) + 1),
                "On" if mod.get("On", True) else "Off",
            ]))
            if eng.get("Modifiers"):
                modifiers.append(table(
                    ["Modifier", "Value", "Original", "Change"],
                    [[_modifier_label(m.get("Label", "")),
                      _modifier_value(m.get("Value")),
                      _modifier_value(m.get("OriginalValue")),
                      _modifier_change(m)]
                     for m in eng["Modifiers"] if "Value" in m],
                    title=f"{names.slot_label(slot)}: {names.module_name(item)}",
                    numeric=(1, 2, 3)))
        blocks = []
        for key, heading in names.GROUPS:
            rows = [r for _k, r in sorted(groups[key], key=lambda x: x[0])]
            if not rows:
                continue
            if key == "cosmetic":
                blocks.append(details(heading, [table(["Slot", "Item"], rows)]))
            else:
                blocks.append(table(["Slot", "Module", "Engineering", "Priority", "Power"],
                                    rows, title=heading, numeric=(3,)))
        if modifiers:
            blocks.append(details("Engineering modifiers", modifiers))
        return blocks

    def _service_record(self, sh: dict) -> list[dict]:
        acq = sh.get("acquired") or {}
        how = ""
        if acq:
            how = {"bought": "Bought", "redeemed": "Redeemed"}.get(acq.get("how"), "")
            if acq.get("price"):
                how += f" for {cr(acq['price'])}"
            how += f", {date(acq.get('ts'))}"
        rows = [
            ("Acquired", how),
            ("Time as active ship", duration(sh.get("seconds"))),
            ("Hyperspace jumps", num(sh.get("jumps")) if sh.get("jumps") else ""),
            ("Distance jumped", num(sh.get("ly"), 0, "ly") if sh.get("ly") else ""),
            ("First flown", date(sh.get("first_flown"))),
            ("Last flown", date(sh.get("last_flown"))),
            ("Destroyed", str(sh["destroyed"]) if sh.get("destroyed") else ""),
            ("Rebuys", f"{sh['rebuys']} · {cr(sh.get('rebuy_spent'))}"
             if sh.get("rebuys") else ""),
        ]
        events = sorted(sh.get("record") or [], key=lambda e: e[0], reverse=True)
        blocks = [facts(rows, title="Service record")]
        if events:
            blocks.append(table(["Date", "Event"], [[date(ts), text] for ts, _k, text in events],
                                title="History", nowrap=(0,)))
        return blocks

    # Stored modules ───────────────────────────────────────────────────────────

    def modules_page(self) -> dict:
        sm = self.s.get("stored_modules") or {}
        rows = []
        for item in sm.get("items") or []:
            eng = ""
            if item.get("EngineerModifications"):
                eng = (f"{names.engineering_name(item['EngineerModifications'])} "
                       f"G{item.get('Level', '?')}")
                if item.get("Quality") is not None:
                    eng += f" ({pct(100 * float(item['Quality']))})"
            if item.get("InTransit"):
                where = "In transit"
            else:
                where = self.place(item.get("MarketID"), "", item.get("StarSystem", ""))
            rows.append([names.module_name(item.get("Name", "")), eng, where,
                         cr(item.get("BuyPrice")) if item.get("BuyPrice") else "—",
                         "Yes" if item.get("Hot") else ""])
        rows.sort(key=lambda r: (r[2], r[0]))
        blocks = [table(["Module", "Engineering", "Where", "Bought for", "Hot"], rows,
                        numeric=(3,), nowrap=(2,), empty="No stored modules recorded.")]
        if sm.get("ts"):
            blocks.append(note(f"As of {when(sm['ts'])}, the last time outfitting "
                               f"was opened."))
        return {"id": "modules", "nav": "Stored modules", "title": "Stored modules",
                "subtitle": f"{len(rows)} modules", "blocks": blocks}

    # Engineering ──────────────────────────────────────────────────────────────

    def engineering_page(self) -> dict:
        engineers = self.s.get("commander", {}).get("engineers") or {}
        order = {"Unlocked": 0, "Invited": 1, "Acquainted": 2, "Known": 3, "Barred": 4}
        eng_rows = [[name, e.get("Progress", ""),
                     f"G{e['Rank']}" if e.get("Rank") is not None else "—",
                     pct(e["RankProgress"]) if e.get("RankProgress") and e.get("Rank", 5) < 5 else ""]
                    for name, e in sorted(engineers.items(),
                                          key=lambda kv: (order.get(kv[1].get("Progress"), 9), kv[0]))]
        fleet_rows = []
        grades = {}
        for sh in self.owned_ships():
            for mod in (sh.get("loadout") or {}).get("Modules") or []:
                eng = mod.get("Engineering") or {}
                if not eng.get("BlueprintName"):
                    continue
                level = eng.get("Level")
                grades[level] = grades.get(level, 0) + 1
                effect = eng.get("ExperimentalEffect_Localised") or (
                    names.engineering_name(eng["ExperimentalEffect"])
                    if eng.get("ExperimentalEffect") else "")
                fleet_rows.append([
                    {"text": self.ship_title(sh), "page": f"ship-{sh['ship_id']}"},
                    names.module_name(mod.get("Item", "")),
                    names.engineering_name(eng["BlueprintName"]),
                    f"G{level}", pct(100 * float(eng.get("Quality") or 0)),
                    effect, eng.get("Engineer", ""),
                ])
        summary = [("Engineers unlocked",
                    str(sum(1 for e in engineers.values() if e.get("Progress") == "Unlocked"))),
                   ("Engineered modules in the fleet", str(len(fleet_rows)))]
        summary += [(f"Grade {g} modules", str(n)) for g, n in sorted(
            grades.items(), key=lambda kv: -(kv[0] or 0))]
        blocks = [facts(summary),
                  table(["Engineer", "Status", "Grade", "To next grade"], eng_rows,
                        title="Engineers", empty="No engineer progress recorded."),
                  table(["Ship", "Module", "Blueprint", "Grade", "Quality",
                         "Experimental", "Engineer"], fleet_rows,
                        title="Blueprints across the fleet", numeric=(4,),
                        empty="No engineered modules in the fleet.")]
        return {"id": "engineering", "nav": "Engineering", "title": "Engineering",
                "subtitle": "Engineers and blueprints", "blocks": blocks}

    # Carrier ──────────────────────────────────────────────────────────────────

    def carrier_page(self) -> Optional[dict]:
        carrier = self.s.get("carrier") or {}
        stats = carrier.get("stats") or {}
        if not carrier.get("callsign") and not self.capi:
            return None
        capi_fin = (self.capi.get("finance") or {}) if self.capi else {}
        space = stats.get("SpaceUsage") or {}
        rows = [
            ("Name", carrier.get("name", "")),
            ("Callsign", carrier.get("callsign", "")),
            ("Docking access", str(stats.get("DockingAccess", "")).title()),
            ("Notorious commanders", "Allowed" if stats.get("AllowNotorious") else
             ("Refused" if "AllowNotorious" in stats else "")),
            ("Tritium", num(stats.get("FuelLevel"), 0, "t") if "FuelLevel" in stats else ""),
            ("Jump range", num(stats.get("JumpRangeMax"), 0, "ly") if stats.get("JumpRangeMax") else ""),
            ("Capacity", f"{num(space.get('TotalCapacity') - space.get('FreeSpace', 0), 0, 't')} used of "
                         f"{num(space.get('TotalCapacity'), 0, 't')}" if space.get("TotalCapacity") else ""),
            ("Weekly upkeep", cr(capi_fin.get("maintenance")) if capi_fin.get("maintenance") else ""),
            ("Decommission pending", "Yes" if carrier.get("decommission") else ""),
            ("As of", when(carrier.get("stats_ts"))),
        ]
        blocks = [facts(rows)]
        fin = stats.get("Finance") or {}
        if self.bal and (fin or capi_fin):
            balance = fin.get("CarrierBalance", capi_fin.get("bankBalance"))
            upkeep = capi_fin.get("maintenance")
            runway = ""
            if balance and upkeep:
                runway = f"{int(balance) // int(upkeep):,} weeks"
            blocks.append(facts([
                ("Balance", cr(balance)),
                ("Reserved", cr(fin.get("ReserveBalance", capi_fin.get("bankReservedBalance")))),
                ("Available", cr(fin.get("AvailableBalance")) if fin.get("AvailableBalance") is not None else ""),
                ("Covers upkeep for", runway),
            ], title="Finances"))
        taxes = [(k.replace("TaxRate_", "").title() + " tax", pct(v))
                 for k, v in fin.items() if k.startswith("TaxRate_")]
        if taxes:
            blocks.append(facts(taxes, title="Tariffs"))
        crew = stats.get("Crew") or []
        if crew:
            blocks.append(table(["Service", "Status", "Crew"], [
                [_split_words(c.get("CrewRole", "")),
                 ("Active" if c.get("Enabled") else "Suspended") if c.get("Activated")
                 else "Not installed",
                 c.get("CrewName", "")]
                for c in sorted(crew, key=lambda c: (not c.get("Activated"), c.get("CrewRole", "")))],
                title="Services"))
        fc = (self.s.get("commander", {}).get("statistics", {}) or {}).get("FLEETCARRIER") or {}
        if fc:
            blocks.append(facts([
                ("Jumps", num(fc.get("FLEETCARRIER_TOTAL_JUMPS"))),
                ("Distance traveled", num(fc.get("FLEETCARRIER_DISTANCE_TRAVELLED"), 0, "ly")
                 if fc.get("FLEETCARRIER_DISTANCE_TRAVELLED") else ""),
                ("Market exports", num(fc.get("FLEETCARRIER_EXPORT_TOTAL"), 0, "t")),
                ("Market imports", num(fc.get("FLEETCARRIER_IMPORT_TOTAL"), 0, "t")),
                ("Trade profit", cr(fc.get("FLEETCARRIER_TRADEPROFIT_TOTAL"))),
                ("Refuel profit", cr(fc.get("FLEETCARRIER_REFUEL_PROFIT"))),
            ], title="Lifetime"))
        if self.loc:
            blocks += self._carrier_whereabouts(carrier)
        else:
            blocks.append(note("Where the carrier is, and where it has been, are left "
                               "out. Set IncludeCurrentLocation under [Dossier] to "
                               "include them."))
        title = carrier.get("name") or carrier.get("callsign") or "Fleet carrier"
        return {"id": "carrier", "nav": "Carrier", "title": title,
                "subtitle": f"Fleet carrier {carrier.get('callsign', '')}".strip(),
                "blocks": blocks}

    def _carrier_whereabouts(self, carrier: dict) -> list[dict]:
        positions = [(p["ts"], p["system"]) for p in carrier.get("positions") or []
                     if p.get("system")]
        positions += [(r["departs"], r["system"]) for r in carrier.get("requests") or []
                      if not r.get("cancelled") and r.get("departs", 0) <= self.now]
        current = self.capi.get("currentStarSystem") if self.capi else ""
        if positions:
            ts, system = max(positions)
            if not current:
                current = system
        blocks = [facts([("Current system", current or "Unknown")])]
        itinerary = ((self.capi.get("itinerary") or {}).get("completed") or []) if self.capi else []
        if itinerary:
            rows = [[when(iso_epoch(j.get("arrivalTime"))), j.get("starsystem", ""),
                     duration(j.get("visitDurationSeconds"))]
                    for j in reversed(itinerary)]
            blocks.append(table(["Arrived", "System", "Stayed"], rows,
                                title="Jump history", numeric=(2,)))
        else:
            rows = [[when(r["departs"]), r["system"], r.get("body", "")]
                    for r in reversed(carrier.get("requests") or [])
                    if not r.get("cancelled")]
            if rows:
                blocks.append(table(["Departed", "System", "Body"], rows,
                                    title="Jumps scheduled"))
        return blocks

    # Survey & mining ──────────────────────────────────────────────────────────

    def mining_page(self) -> dict:
        spots = []
        mined = set()
        for spot in (self.s.get("hotspots") or {}).values():
            overall, best, counted, refined = hotspot_rates(spot)
            mined.add((spot["system"], spot["ring"], spot["key"]))
            spots.append((spot.get("name") or spot["key"].title(), overall, [
                spot.get("name") or spot["key"].title(),
                spot["ring"], spot["system"],
                num(overall, 1) if overall is not None else "—",
                num(best, 1) if best is not None else "—",
                f"{counted} of {len(spot.get('visits') or [])}",
                num(refined),
            ]))
        spots.sort(key=lambda r: (r[0].lower(), r[1] is None, -(r[1] or 0)))
        known = []
        for ring in (self.s.get("rings") or {}).values():
            for key, sig in (ring.get("signals") or {}).items():
                if (ring["system"], ring["ring"], key) in mined:
                    continue
                known.append([sig.get("name") or key.title(), ring["ring"],
                              ring["system"], str(sig.get("count", ""))])
        known.sort(key=lambda r: (r[0].lower(), r[2], r[1]))
        dep_rows = []
        for d in self.deposits:
            status = ""
            if d.get("depleted_at") and (not d.get("last_confirmed")
                                         or d["depleted_at"] >= d["last_confirmed"]):
                status = f"Depleted {str(d['depleted_at'])[:10]}"
            dep_rows.append([
                d.get("commodity_display") or str(d.get("commodity", "")).title(),
                d.get("body_name") or "", d.get("system_name") or "",
                f"{float(d.get('latitude') or 0):.4f}, {float(d.get('longitude') or 0):.4f}",
                d.get("amount") or "", d.get("density_observed") or d.get("density_claimed") or "",
                str(d["rigs"]) if d.get("rigs") else "",
                num(d.get("refine_count")) if d.get("refine_count") else "",
                str(d.get("last_confirmed") or "")[:10], status,
            ])
        dep_rows.sort(key=lambda r: (r[0].lower(), r[2], r[1]))
        blocks = [
            table(["Commodity", "Ring", "System", "Refined/min", "Best visit",
                   "Visits rated", "Refined"], [r for _n, _o, r in spots],
                  title="Hotspots mined", numeric=(3, 4, 6),
                  empty="No ring hotspot visits recorded."),
            note("Refined/min is the hotspot commodity refined per minute while "
                 "mining — from the first refinement of a visit to the last — over "
                 "every visit long enough to rate (at least 5 refinements over "
                 "2 minutes). A visit is counted when the hotspot was the "
                 "supercruise destination."),
            table(["Commodity", "Body", "System", "Position", "Amount", "Density",
                   "Rigs", "Refines", "Last confirmed", "Status"], dep_rows,
                  title="Surface deposits", numeric=(6, 7), nowrap=(3, 8, 9),
                  empty="No surface deposits recorded."),
        ]
        if known:
            blocks.append(details(f"Hotspots found, not yet mined ({len(known)})", [
                table(["Commodity", "Ring", "System", "Hotspots"], known, numeric=(3,))]))
        return {"id": "mining", "nav": "Survey & mining", "title": "Survey & mining",
                "subtitle": "Ring hotspots and surface deposits", "blocks": blocks}

    # On foot ──────────────────────────────────────────────────────────────────

    def on_foot_page(self) -> dict:
        suits = {k: v for k, v in (self.s.get("suits") or {}).items() if not v.get("gone")}
        weapons = {k: v for k, v in (self.s.get("weapons") or {}).items() if not v.get("gone")}
        suit_rows = []
        for suit in suits.values():
            name, cls = names.suit_name(suit.get("name", ""))
            suit_rows.append([name, str(suit.get("class") or cls or ""),
                              ", ".join(names.suit_mod(m) for m in suit.get("mods") or [])])
        suit_rows.sort()
        weapon_rows = sorted([
            names.weapon_name(w.get("name", ""), w.get("display", "")),
            str(w.get("class") or ""),
            ", ".join(names.weapon_mod(m) for m in w.get("mods") or [])]
            for w in weapons.values())
        lo_rows = []
        for lo in (self.s.get("loadouts") or {}).values():
            suit = (self.s.get("suits") or {}).get(lo.get("suit"), {})
            sname, scls = names.suit_name(suit.get("name", ""))
            cls = suit.get("class") or scls
            slots = lo.get("slots") or {}

            def weapon(slot):
                w = (self.s.get("weapons") or {}).get(slots.get(slot, ""), {})
                return names.weapon_name(w.get("name", ""), w.get("display", "")) if w else ""
            lo_rows.append([lo.get("name", ""), sname + (f" (class {cls})" if cls else ""),
                            weapon("PrimaryWeapon1"), weapon("PrimaryWeapon2"),
                            weapon("SecondaryWeapon")])
        lo_rows.sort(key=lambda r: r[0].lower())
        blocks = [
            table(["Loadout", "Suit", "Primary 1", "Primary 2", "Secondary"], lo_rows,
                  title="Loadouts", empty="No suit loadouts recorded."),
            table(["Suit", "Class", "Modifications"], suit_rows, title="Suits",
                  numeric=(1,), empty="No suits recorded."),
            table(["Weapon", "Class", "Modifications"], weapon_rows, title="Weapons",
                  numeric=(1,), empty="No weapons recorded."),
            note("Suits and weapons bought before the earliest journal EDLD has read "
                 "appear once they are used in a loadout."),
        ]
        return {"id": "on-foot", "nav": "On foot", "title": "On foot",
                "subtitle": "Suits, weapons and loadouts", "blocks": blocks}


# ── modifiers ─────────────────────────────────────────────────────────────────

_MODIFIER_LABELS = {
    "FSDOptimalMass": "Optimal mass", "MaxFuelPerJump": "Max fuel per jump",
    "PowerDraw": "Power draw", "Mass": "Mass", "Integrity": "Integrity",
    "ShieldGenStrength": "Shield strength", "EngineOptimalMass": "Optimal mass",
    "EngineOptPerformance": "Optimal multiplier", "DamagePerSecond": "DPS",
    "Damage": "Damage", "RateOfFire": "Rate of fire", "Range": "Range",
    "PowerCapacity": "Power capacity", "WeaponsCapacity": "Weapons capacity",
    "WeaponsRecharge": "Weapons recharge", "EnginesCapacity": "Engines capacity",
    "EnginesRecharge": "Engines recharge", "SystemsCapacity": "Systems capacity",
    "SystemsRecharge": "Systems recharge", "CargoCapacity": "Capacity",
    "DefenceModifierHealthMultiplier": "Hull boost",
    "DefenceModifierShieldMultiplier": "Shield boost",
    "ScannerRange": "Scanner range", "SensorTargetScanAngle": "Scan angle",
    "MaxRange": "Max range", "BootTime": "Boot time", "HeatEfficiency": "Heat efficiency",
}


def _split_words(text: str) -> str:
    out = re.sub(r"(?<=[a-z])(?=[A-Z])", " ", text or "")
    return out[:1].upper() + out[1:].lower()


def _modifier_label(label: str) -> str:
    return _MODIFIER_LABELS.get(label, _split_words(label))


def _modifier_value(value) -> str:
    try:
        v = float(value)
    except (TypeError, ValueError):
        return "—"
    if abs(v) >= 100:
        return f"{v:,.0f}"
    if abs(v) >= 10:
        return f"{v:,.1f}"
    return f"{v:,.3f}".rstrip("0").rstrip(".")


def _modifier_change(m: dict) -> str:
    try:
        value, original = float(m.get("Value")), float(m.get("OriginalValue"))
    except (TypeError, ValueError):
        return ""
    if not original:
        return ""
    change = 100.0 * (value - original) / abs(original)
    better = (change < 0) if m.get("LessIsGood") else (change > 0)
    sign = "+" if change > 0 else ""
    return f"{sign}{change:.1f}%" + (" ▲" if better else " ▼") if change else "0%"
