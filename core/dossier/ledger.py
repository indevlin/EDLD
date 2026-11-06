"""
core/dossier/ledger.py — what the dossier knows, kept from the journals.

The ledger reads every journal once and keeps what it learned. Each journal's
read position is stored with the state, so a later run reads only what has
been written since: the current journal's new lines, and any new files. That
also means what the ledger knows outlives the journals. A ship's fitting is
kept from the last time it was flown, and survives the journal that recorded
it being deleted.

A stored ship cannot be outfitted or engineered, so its last ``Loadout`` stays
true until it is flown again. Only these change a stored ship: a new
``Loadout`` for its ShipID, a transfer, a sale, a rename. Everything is keyed
on ShipID, never on name — names are reused (ONERARIUS was ShipID 16, sold,
and is now ShipID 36).

One journal folder can hold more than one commander. Only events between a
``Commander``/``LoadGame`` for this commander's FID and the next game launch
are applied. The FID is used for that and nothing else; it is never stored in
the state or written to a document.

The state is a plain JSON-able dict, so it can be persisted as it is. Ship and
market ids are strings in it for that reason.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Optional

#: Bumped when the state's shape or meaning changes. A state of another
#: version is discarded and the journals are read again from the start.
STATE_VERSION = 1

#: A visit to a ring hotspot ends if no refinement or other event has been
#: seen for this long — the commander left without a journal line saying so.
#: Gaps between consecutive events longer than this are not counted as time
#: flown, either: the game was idle or not running.
IDLE_GAP_S = 600

#: A visit's refinement rate counts only when it is long enough to mean
#: something: a few refinements over a couple of minutes is a sample, not a
#: rate.
MIN_VISIT_REFINED = 5
MIN_VISIT_SPAN_S = 120

#: The only events parsed in full. Everything else is read just far enough to
#: find its timestamp, for the time-flown clock.
RELEVANT = frozenset({
    "Fileheader", "Commander", "LoadGame", "Shutdown", "Music",
    "Rank", "Progress", "Reputation", "Statistics",
    "Powerplay", "PowerplayJoin", "PowerplayLeave", "PowerplayDefect",
    "PowerplayRank",
    "SquadronStartup", "JoinedSquadron", "LeftSquadron", "KickedFromSquadron",
    "DisbandedSquadron", "SquadronPromotion", "SquadronDemotion",
    "EngineerProgress",
    "Loadout", "StoredShips", "ShipyardSwap", "ShipyardBuy", "ShipyardNew",
    "ShipyardSell", "SellShipOnRebuy", "ShipyardTransfer", "SetUserShipName",
    "ShipRedeemed", "Died", "Resurrect",
    "FSDJump", "Location", "Docked", "Undocked", "CarrierJump",
    "CarrierStats", "CarrierLocation", "CarrierJumpRequest",
    "CarrierJumpCancelled", "CarrierNameChange", "CarrierDecommission",
    "CarrierCancelDecommission",
    "StoredModules",
    "BuySuit", "SellSuit", "UpgradeSuit", "BuyWeapon", "SellWeapon",
    "UpgradeWeapon", "SuitLoadout", "SwitchSuitLoadout", "CreateSuitLoadout",
    "DeleteSuitLoadout", "RenameSuitLoadout", "LoadoutEquipModule",
    "LoadoutRemoveModule",
    "SupercruiseDestinationDrop", "SupercruiseExit", "SupercruiseEntry",
    "MiningRefined", "SAASignalsFound",
})

#: The head of every journal line: timestamp, then event name.
_HEAD = re.compile(rb'"timestamp"\s*:\s*"([^"]+)"\s*,\s*"event"\s*:\s*"([A-Za-z0-9_]+)"')


def _epoch(stamp: str) -> float:
    try:
        return datetime.fromisoformat(stamp.replace("Z", "+00:00")).timestamp()
    except (ValueError, AttributeError):
        return 0.0


def commodity_key(token: str) -> str:
    """``$LowTemperatureDiamond_name;`` and ``$lowtemperaturediamond_name;``
    — the hotspot and the refinement spell it differently — as one key."""
    key = (token or "").strip().lower().lstrip("$").rstrip(";")
    if key.endswith("_name"):
        key = key[:-5]
    return key


def journal_sort_key(path: Path) -> str:
    """Chronological order for journal file names, old style and new.

    New: ``Journal.2026-10-14T205310.01.log``. Old (before 2022):
    ``Journal.221231235959.01.log``, which sorts after every new name as a
    plain string. Rewritten to the new form so the two interleave by date.
    """
    name = path.name
    m = re.match(r"Journal\.(\d{2})(\d{2})(\d{2})(\d{6})\.(\d+)\.log$", name)
    if m:
        yy, mm, dd, hms, part = m.groups()
        return f"Journal.20{yy}-{mm}-{dd}T{hms}.{part}.log"
    return name


def fresh_state() -> dict:
    return {
        "version": STATE_VERSION,
        "offsets": {},                 # journal file name → bytes applied
        "resume": {},                  # file being written → was it this commander
        "as_of": 0.0,                  # timestamp of the last event applied
        "clock": {"last_ts": 0.0, "in_game": False, "ours": False},
        "commander": {
            "name": "", "ranks": {}, "progress": {}, "reputation": {},
            "powerplay": {}, "squadron": {}, "statistics": {},
            "engineers": {}, "credits": None, "credits_ts": 0.0,
        },
        "where": {"system": "", "station": "", "market_id": None,
                  "docked": False, "ts": 0.0},
        "current_ship": None,
        "ships": {},
        "roster": {"ids": [], "ts": 0.0},
        "markets": {},
        "carrier": {"id": None, "callsign": "", "name": "", "stats": {},
                    "stats_ts": 0.0, "positions": [], "requests": []},
        "stored_modules": {"ts": 0.0, "market_id": None, "items": []},
        "suits": {}, "weapons": {}, "loadouts": {},
        "rings": {},
        "hotspots": {},
        "visit": None,
        "pending_hotspot": None,
        "pending_buy_price": None,
    }


class Ledger:
    """Applies journal events to a state dict. See the module docstring."""

    def __init__(self, fid: Optional[str] = None, state: Optional[dict] = None):
        self.fid = fid or None
        if not isinstance(state, dict) or state.get("version") != STATE_VERSION:
            state = fresh_state()
        self.s = state
        self._active_fid: Optional[str] = None

    # ── reading journals ─────────────────────────────────────────────────────

    def scan(self, journal_dir) -> int:
        """Apply whatever has been written since the last scan.

        Returns the number of events applied. Only whole lines are read; a
        line still being written is picked up next time.
        """
        try:
            files = sorted(Path(journal_dir).glob("Journal*.log"),
                           key=journal_sort_key)
        except OSError:
            return 0
        offsets = self.s["offsets"]
        applied = 0
        for path in files:
            try:
                size = path.stat().st_size
            except OSError:
                continue
            done = int(offsets.get(path.name, 0))
            if size == done:
                continue
            if size < done:
                # Rewritten or truncated in place — not something the game
                # does. Reading it again would count everything twice.
                offsets[path.name] = size
                continue
            try:
                with open(path, "rb") as fh:
                    fh.seek(done)
                    data = fh.read()
            except OSError:
                continue
            end = data.rfind(b"\n")
            if end < 0:
                continue
            # A file is a new game launch: whoever was playing is unknown
            # until its Commander line. The position within a file being
            # resumed is restored from the state.
            #
            # What is kept is only whether the commander playing was this
            # one — never an FID.
            if done == 0:
                self._active_fid = None
            else:
                playing = self.s.get("resume", {}).get(path.name)
                self._active_fid = (None if playing is None
                                    else (self.fid or "?") if playing else "another")
            for raw in data[:end + 1].splitlines():
                applied += self.apply_line(raw)
            offsets[path.name] = done + end + 1
            # Only the file still being written needs it.
            self.s["resume"] = {path.name: (None if self._active_fid is None
                                            else self._ours())}
        return applied

    def apply_line(self, raw: bytes) -> int:
        m = _HEAD.search(raw[:160])
        if not m:
            return 0
        ts = _epoch(m.group(1).decode("ascii", "replace"))
        event = m.group(2).decode("ascii")
        if event == "Fileheader":
            # A game launch. Whatever this commander was doing has stopped,
            # and who plays next is unknown until a Commander line.
            self._stop_playing()
            self._active_fid = None
            return 1
        if event in ("Commander", "LoadGame"):
            # Who is playing is decided before anything else is counted.
            try:
                ev = json.loads(raw)
            except ValueError:
                return 0
            self._identify(event, ev)
            if not self._ours():
                self._stop_playing()
                return 0
            self._tick(ts)
            self._dispatch(event, ev, ts)
            return 1
        if not self._ours():
            return 0
        self._tick(ts)
        if event not in RELEVANT:
            return 0
        if event == "Music" and b"MainMenu" not in raw:
            return 0
        try:
            ev = json.loads(raw)
        except ValueError:
            return 0
        self._dispatch(event, ev, ts)
        return 1

    def apply_events(self, events: Iterable[dict]) -> None:
        """Apply already-parsed events, in order. For tests and tools."""
        for ev in events:
            self.apply_line(json.dumps(ev).encode())

    # ── who is playing ────────────────────────────────────────────────────────

    def _identify(self, event: str, ev: dict) -> None:
        self._active_fid = ev.get("FID") or self._active_fid or "?"

    def _stop_playing(self) -> None:
        self._end_visit()
        self.s["clock"]["in_game"] = False

    def _ours(self) -> bool:
        if self.fid is None:
            return self._active_fid is not None
        return self._active_fid == self.fid

    # ── the clock: time flown, and hotspot visits left without a word ─────────

    def _tick(self, ts: float) -> None:
        clock = self.s["clock"]
        last = clock["last_ts"]
        gap = ts - last if last else 0.0
        if 0 < gap <= IDLE_GAP_S and clock["in_game"]:
            ship = self._ship(self.s["current_ship"])
            if ship is not None:
                ship["seconds"] = ship.get("seconds", 0.0) + gap
        if gap > IDLE_GAP_S:
            self._end_visit()
        clock["last_ts"] = max(last, ts)
        self.s["as_of"] = max(self.s["as_of"], ts)

    # ── dispatch ──────────────────────────────────────────────────────────────

    def _dispatch(self, event: str, ev: dict, ts: float) -> None:
        handler = getattr(self, "_on_" + event, None)
        if handler is not None:
            handler(ev, ts)

    # ── ships: helpers ────────────────────────────────────────────────────────

    def _ship(self, sid, create: bool = False) -> Optional[dict]:
        if sid is None:
            return None
        key = str(sid)
        ship = self.s["ships"].get(key)
        if ship is None and create:
            ship = {"ship_id": int(sid) if str(sid).isdigit() else sid,
                    "type": "", "name": "", "ident": "",
                    "loadout": None, "loadout_ts": 0.0,
                    "location": {"kind": "unknown"},
                    "acquired": None, "record": [],
                    "seconds": 0.0, "jumps": 0, "ly": 0.0,
                    "first_flown": 0.0, "last_flown": 0.0,
                    "destroyed": 0, "rebuys": 0, "rebuy_spent": 0,
                    "sold": None}
            self.s["ships"][key] = ship
        return ship

    def _owned(self, sid, ts: float) -> None:
        ids = self.s["roster"]["ids"]
        key = str(sid)
        if key not in ids:
            ids.append(key)
        ship = self._ship(sid, create=True)
        ship["sold"] = None

    def _note(self, ship: dict, ts: float, kind: str, text: str) -> None:
        entry = [ts, kind, text]
        if entry not in ship["record"]:
            ship["record"].append(entry)

    def _make_current(self, sid, ts: float) -> None:
        if sid is None:
            return
        self._owned(sid, ts)
        self.s["current_ship"] = str(sid)
        ship = self._ship(sid)
        ship["location"] = {"kind": "current"}
        if not ship["first_flown"]:
            ship["first_flown"] = ts
        ship["last_flown"] = max(ship["last_flown"], ts)

    def _store_here(self, sid, market_id, ts: float) -> None:
        ship = self._ship(sid, create=True)
        where = self.s["where"]
        market = self.s["markets"].get(str(market_id), {})
        ship["location"] = {
            "kind": "station", "market_id": market_id,
            "station": market.get("name") or where.get("station", ""),
            "system": market.get("system") or where.get("system", ""),
            "ts": ts,
        }
        self._owned(sid, ts)

    def _gone(self, sid, ts: float, text: str) -> None:
        if sid is None:
            return
        ship = self._ship(sid, create=True)
        ship["sold"] = ts
        self._note(ship, ts, "sold", text)
        ids = self.s["roster"]["ids"]
        if str(sid) in ids:
            ids.remove(str(sid))
        if self.s["current_ship"] == str(sid):
            self.s["current_ship"] = None

    def _set_names(self, ship: dict, ev: dict, *, type_key="Ship",
                   name_key="ShipName", ident_key="ShipIdent") -> None:
        if ev.get(type_key):
            ship["type"] = str(ev[type_key]).lower()
            if ev.get(type_key + "_Localised"):
                ship["type_display"] = ev[type_key + "_Localised"]
        if name_key in ev and ev.get(name_key) is not None:
            ship["name"] = ev.get(name_key) or ship.get("name", "")
        if ident_key in ev and ev.get(ident_key) is not None:
            ship["ident"] = ev.get(ident_key) or ship.get("ident", "")

    # ── commander ─────────────────────────────────────────────────────────────

    def _on_Commander(self, ev, ts):
        if ev.get("Name"):
            self.s["commander"]["name"] = ev["Name"]

    def _on_LoadGame(self, ev, ts):
        cmdr = self.s["commander"]
        if ev.get("Commander"):
            cmdr["name"] = ev["Commander"]
        if ev.get("Credits") is not None:
            cmdr["credits"] = int(ev["Credits"])
            cmdr["credits_ts"] = ts
        self._end_visit()
        self.s["clock"]["in_game"] = True
        sid = ev.get("ShipID")
        try:
            from data.ships import SRV_TYPE_NAMES
        except Exception:
            SRV_TYPE_NAMES = ()
        # Resuming in a surface vehicle names the vehicle as the ship.
        if sid is not None and str(ev.get("Ship", "")).lower() not in SRV_TYPE_NAMES:
            ship = self._ship(sid, create=True)
            self._set_names(ship, ev)
            self._make_current(sid, ts)

    def _on_Shutdown(self, ev, ts):
        self._end_visit()
        self.s["clock"]["in_game"] = False

    def _on_Music(self, ev, ts):
        if ev.get("MusicTrack") == "MainMenu":
            self._end_visit()
            self.s["clock"]["in_game"] = False

    def _on_Rank(self, ev, ts):
        self.s["commander"]["ranks"] = _strip(ev)

    def _on_Progress(self, ev, ts):
        self.s["commander"]["progress"] = _strip(ev)

    def _on_Reputation(self, ev, ts):
        self.s["commander"]["reputation"] = _strip(ev)

    def _on_Statistics(self, ev, ts):
        self.s["commander"]["statistics"] = _strip(ev)

    def _on_Powerplay(self, ev, ts):
        self.s["commander"]["powerplay"] = _strip(ev)

    def _on_PowerplayJoin(self, ev, ts):
        self.s["commander"]["powerplay"] = {"Power": ev.get("Power", "")}

    def _on_PowerplayLeave(self, ev, ts):
        self.s["commander"]["powerplay"] = {}

    def _on_PowerplayDefect(self, ev, ts):
        self.s["commander"]["powerplay"] = {"Power": ev.get("ToPower", "")}

    def _on_PowerplayRank(self, ev, ts):
        pp = self.s["commander"]["powerplay"]
        if ev.get("Power"):
            pp["Power"] = ev["Power"]
        if ev.get("Rank") is not None:
            pp["Rank"] = ev["Rank"]

    def _on_SquadronStartup(self, ev, ts):
        self.s["commander"]["squadron"] = {
            "name": ev.get("SquadronName", ""),
            "rank": ev.get("CurrentRankName") or "",
        }

    def _on_JoinedSquadron(self, ev, ts):
        self.s["commander"]["squadron"] = {"name": ev.get("SquadronName", ""),
                                           "rank": ""}

    def _left_squadron(self, ev, ts):
        self.s["commander"]["squadron"] = {}

    _on_LeftSquadron = _left_squadron
    _on_KickedFromSquadron = _left_squadron
    _on_DisbandedSquadron = _left_squadron

    def _squadron_rank(self, ev, ts):
        sq = self.s["commander"]["squadron"]
        if sq and ev.get("NewRankName"):
            sq["rank"] = ev["NewRankName"]

    _on_SquadronPromotion = _squadron_rank
    _on_SquadronDemotion = _squadron_rank

    def _on_EngineerProgress(self, ev, ts):
        engineers = self.s["commander"]["engineers"]
        rows = ev.get("Engineers")
        if rows is None and ev.get("Engineer"):
            rows = [ev]
        for row in rows or []:
            name = row.get("Engineer")
            if not name:
                continue
            entry = engineers.setdefault(name, {})
            for key in ("Progress", "Rank", "RankProgress"):
                if key in row:
                    entry[key] = row[key]

    # ── where the commander is ────────────────────────────────────────────────

    def _learn_market(self, ev, *, name_key="StationName", system_key="StarSystem",
                      type_key="StationType", id_key="MarketID") -> None:
        mid = ev.get(id_key)
        if mid is None:
            return
        entry = self.s["markets"].setdefault(str(mid), {})
        if ev.get(name_key):
            entry["name"] = ev[name_key]
        if ev.get(system_key):
            entry["system"] = ev[system_key]
        if ev.get(type_key):
            entry["type"] = ev[type_key]

    def _on_Docked(self, ev, ts):
        self._learn_market(ev)
        self.s["where"] = {"system": ev.get("StarSystem", ""),
                           "station": ev.get("StationName", ""),
                           "market_id": ev.get("MarketID"),
                           "docked": True, "ts": ts}
        self._carrier_seen_at(ev, ts)

    def _on_Undocked(self, ev, ts):
        self.s["where"]["docked"] = False
        self.s["where"]["station"] = ""
        self.s["where"]["ts"] = ts

    def _on_Location(self, ev, ts):
        if ev.get("Docked"):
            self._on_Docked(ev, ts)
        else:
            self.s["where"] = {"system": ev.get("StarSystem", ""), "station": "",
                               "market_id": None, "docked": False, "ts": ts}

    def _on_CarrierJump(self, ev, ts):
        # Written only when the commander is aboard a carrier that jumps.
        self._on_Location(ev, ts)

    def _on_FSDJump(self, ev, ts):
        self._end_visit()
        self.s["where"] = {"system": ev.get("StarSystem", ""), "station": "",
                           "market_id": None, "docked": False, "ts": ts}
        ship = self._ship(self.s["current_ship"])
        if ship is not None:
            ship["jumps"] = ship.get("jumps", 0) + 1
            ship["ly"] = ship.get("ly", 0.0) + float(ev.get("JumpDist") or 0.0)

    # ── ships ─────────────────────────────────────────────────────────────────

    def _on_Loadout(self, ev, ts):
        sid = ev.get("ShipID")
        if sid is None:
            return
        ship = self._ship(sid, create=True)
        self._set_names(ship, ev)
        ship["loadout"] = _strip(ev, keep_event=True)
        ship["loadout_ts"] = ts
        self._make_current(sid, ts)

    def _on_ShipyardSwap(self, ev, ts):
        if ev.get("StoreShipID") is not None:
            self._store_here(ev["StoreShipID"], ev.get("MarketID"), ts)
        if ev.get("SellShipID") is not None:
            self._gone(ev["SellShipID"], ts, "Sold")
        sid = ev.get("ShipID")
        if sid is not None:
            ship = self._ship(sid, create=True)
            self._set_names(ship, ev, type_key="ShipType", name_key="_",
                            ident_key="_")
            self._make_current(sid, ts)

    def _on_ShipyardBuy(self, ev, ts):
        if ev.get("StoreShipID") is not None:
            self._store_here(ev["StoreShipID"], ev.get("MarketID"), ts)
        if ev.get("SellShipID") is not None:
            self._gone(ev["SellShipID"], ts,
                       f"Sold for {int(ev.get('SellPrice') or 0):,} cr")
        self.s["pending_buy_price"] = ev.get("ShipPrice")

    def _on_ShipyardNew(self, ev, ts):
        sid = ev.get("NewShipID")
        if sid is None:
            return
        ship = self._ship(sid, create=True)
        self._set_names(ship, ev, type_key="ShipType", name_key="_", ident_key="_")
        price = self.s.get("pending_buy_price")
        ship["acquired"] = {"ts": ts, "how": "bought", "price": price}
        self._note(ship, ts, "acquired",
                   f"Bought for {int(price):,} cr" if price else "Bought")
        self.s["pending_buy_price"] = None
        self._make_current(sid, ts)

    def _on_ShipRedeemed(self, ev, ts):
        sid = ev.get("NewShipID")
        if sid is None:
            return
        ship = self._ship(sid, create=True)
        self._set_names(ship, ev, type_key="ShipType", name_key="_", ident_key="_")
        ship["acquired"] = {"ts": ts, "how": "redeemed", "price": None}
        self._note(ship, ts, "acquired", "Redeemed")
        self._owned(sid, ts)

    def _on_ShipyardSell(self, ev, ts):
        price = int(ev.get("ShipPrice") or 0)
        self._gone(ev.get("SellShipID"), ts,
                   f"Sold for {price:,} cr" if price else "Sold")

    def _on_SellShipOnRebuy(self, ev, ts):
        self._gone(ev.get("SellShipId", ev.get("SellShipID")), ts, "Sold on rebuy")

    def _on_ShipyardTransfer(self, ev, ts):
        sid = ev.get("ShipID")
        if sid is None:
            return
        ship = self._ship(sid, create=True)
        self._set_names(ship, ev, type_key="ShipType", name_key="_", ident_key="_")
        dest = ev.get("MarketID")
        market = self.s["markets"].get(str(dest), {})
        where = self.s["where"]
        ship["location"] = {
            "kind": "transit", "market_id": dest,
            "station": market.get("name") or where.get("station", ""),
            "system": market.get("system") or where.get("system", ""),
            "from_system": ev.get("System", ""),
            "arrives": ts + float(ev.get("TransferTime") or 0),
            "ts": ts,
        }
        self._owned(sid, ts)
        src = ev.get("System") or "elsewhere"
        self._note(ship, ts, "transfer", f"Transferred from {src}")

    def _on_SetUserShipName(self, ev, ts):
        sid = ev.get("ShipID")
        if sid is None:
            return
        ship = self._ship(sid, create=True)
        name, ident = ev.get("UserShipName", ""), ev.get("UserShipId", "")
        if (name, ident) != (ship.get("name", ""), ship.get("ident", "")):
            label = f"{name} ({ident})" if ident else name
            self._note(ship, ts, "named", f"Named {label}" if label else "Name cleared")
        ship["name"], ship["ident"] = name, ident

    def _on_StoredShips(self, ev, ts):
        here_market = ev.get("MarketID")
        self._learn_market(ev)
        roster = set()
        for row in ev.get("ShipsHere") or []:
            sid = row.get("ShipID")
            if sid is None:
                continue
            ship = self._ship(sid, create=True)
            self._set_names(ship, row, type_key="ShipType", name_key="Name",
                            ident_key="Ident")
            ship["location"] = {"kind": "station", "market_id": here_market,
                                "station": ev.get("StationName", ""),
                                "system": ev.get("StarSystem", ""), "ts": ts}
            roster.add(str(sid))
        for row in ev.get("ShipsRemote") or []:
            sid = row.get("ShipID")
            if sid is None:
                continue
            ship = self._ship(sid, create=True)
            self._set_names(ship, row, type_key="ShipType", name_key="Name",
                            ident_key="Ident")
            if row.get("InTransit"):
                if ship["location"].get("kind") != "transit":
                    ship["location"] = {"kind": "transit", "market_id": None,
                                        "station": "", "system": "",
                                        "arrives": None, "ts": ts}
            else:
                mid = row.get("ShipMarketID")
                market = self.s["markets"].get(str(mid), {})
                ship["location"] = {"kind": "station", "market_id": mid,
                                    "station": market.get("name", ""),
                                    "system": row.get("StarSystem", "")
                                              or market.get("system", ""),
                                    "ts": ts}
            roster.add(str(sid))
        if self.s["current_ship"]:
            roster.add(self.s["current_ship"])
        # The list is complete: a ship not in it is no longer owned, however
        # it went. A sale already noted keeps its own record.
        for key in list(self.s["roster"]["ids"]):
            if key not in roster:
                ship = self._ship(key)
                if ship is not None and not ship.get("sold"):
                    ship["sold"] = ts
        for key in roster:
            ship = self._ship(key, create=True)
            ship["sold"] = None
        self.s["roster"] = {"ids": sorted(roster, key=_int_key), "ts": ts}

    def _on_Died(self, ev, ts):
        self._end_visit()
        ship = self._ship(self.s["current_ship"])
        if ship is not None:
            ship["destroyed"] = ship.get("destroyed", 0) + 1
            self._note(ship, ts, "destroyed", "Destroyed")

    def _on_Resurrect(self, ev, ts):
        ship = self._ship(self.s["current_ship"])
        if ship is None:
            return
        cost = int(ev.get("Cost") or 0)
        if str(ev.get("Option", "")).lower() == "rebuy":
            ship["rebuys"] = ship.get("rebuys", 0) + 1
            ship["rebuy_spent"] = ship.get("rebuy_spent", 0) + cost
            self._note(ship, ts, "rebuy", f"Rebought for {cost:,} cr")

    # ── stored modules ────────────────────────────────────────────────────────

    def _on_StoredModules(self, ev, ts):
        self._learn_market(ev)
        self.s["stored_modules"] = {"ts": ts, "market_id": ev.get("MarketID"),
                                    "items": list(ev.get("Items") or [])}

    # ── fleet carrier ─────────────────────────────────────────────────────────

    def _carrier_seen_at(self, ev, ts):
        carrier = self.s["carrier"]
        if (carrier["id"] is not None and ev.get("MarketID") == carrier["id"]
                and ev.get("StarSystem")):
            self._carrier_position(ts, ev["StarSystem"], ev.get("Body", ""))

    def _carrier_position(self, ts, system, body=""):
        positions = self.s["carrier"]["positions"]
        positions.append({"ts": ts, "system": system, "body": body or ""})
        del positions[:-200]

    def _on_CarrierStats(self, ev, ts):
        carrier = self.s["carrier"]
        carrier["id"] = ev.get("CarrierID", carrier["id"])
        carrier["callsign"] = ev.get("Callsign", carrier["callsign"])
        carrier["name"] = ev.get("Name", carrier["name"])
        carrier["stats"] = _strip(ev)
        carrier["stats_ts"] = ts
        self.s["markets"].setdefault(str(carrier["id"]), {})["type"] = "FleetCarrier"

    def _on_CarrierLocation(self, ev, ts):
        carrier = self.s["carrier"]
        if ev.get("CarrierType", "FleetCarrier") != "FleetCarrier":
            return
        if carrier["id"] is None or ev.get("CarrierID") == carrier["id"]:
            if carrier["id"] is None:
                carrier["id"] = ev.get("CarrierID")
            self._carrier_position(ts, ev.get("StarSystem", ""), "")

    def _on_CarrierJumpRequest(self, ev, ts):
        carrier = self.s["carrier"]
        if carrier["id"] is not None and ev.get("CarrierID") not in (None, carrier["id"]):
            return
        departs = _epoch(ev.get("DepartureTime", "")) or ts
        carrier["requests"].append({"ts": ts, "departs": departs,
                                    "system": ev.get("SystemName", ""),
                                    "body": ev.get("Body", ""),
                                    "cancelled": False})
        del carrier["requests"][:-200]

    def _on_CarrierJumpCancelled(self, ev, ts):
        for req in reversed(self.s["carrier"]["requests"]):
            if not req["cancelled"] and req["departs"] >= ts:
                req["cancelled"] = True
                break

    def _on_CarrierNameChange(self, ev, ts):
        carrier = self.s["carrier"]
        if ev.get("Name"):
            carrier["name"] = ev["Name"]
        if ev.get("Callsign"):
            carrier["callsign"] = ev["Callsign"]

    def _on_CarrierDecommission(self, ev, ts):
        self.s["carrier"]["decommission"] = ev.get("ScrapTime")

    def _on_CarrierCancelDecommission(self, ev, ts):
        self.s["carrier"].pop("decommission", None)

    # ── on foot ───────────────────────────────────────────────────────────────

    def _suit(self, ev, ts, *, id_key="SuitID", name_key="SuitName"):
        sid = ev.get(id_key)
        if sid is None:
            return None
        suit = self.s["suits"].setdefault(str(sid), {"id": sid})
        if ev.get(name_key):
            suit["name"] = str(ev[name_key]).lower()
        if "SuitMods" in ev:
            suit["mods"] = list(ev.get("SuitMods") or [])
        suit["gone"] = None
        return suit

    def _weapon(self, row, ts):
        wid = row.get("SuitModuleID")
        if wid is None:
            return None
        weapon = self.s["weapons"].setdefault(str(wid), {"id": wid})
        name = row.get("ModuleName") or row.get("Name")
        if name:
            weapon["name"] = str(name).lower()
        local = row.get("ModuleName_Localised") or row.get("Name_Localised")
        if local and not str(local).startswith("$"):
            weapon["display"] = local
        if row.get("Class") is not None:
            weapon["class"] = int(row["Class"])
        if "WeaponMods" in row:
            weapon["mods"] = list(row.get("WeaponMods") or [])
        weapon["gone"] = None
        return weapon

    def _loadout_from(self, ev, ts):
        lid = ev.get("LoadoutID")
        if lid is None:
            return
        self._suit(ev, ts)
        slots = {}
        for row in ev.get("Modules") or []:
            self._weapon(row, ts)
            if row.get("SlotName"):
                slots[row["SlotName"]] = str(row.get("SuitModuleID"))
        self.s["loadouts"][str(lid)] = {"id": lid, "name": ev.get("LoadoutName", ""),
                                        "suit": str(ev.get("SuitID")),
                                        "slots": slots}

    _on_SuitLoadout = _loadout_from
    _on_SwitchSuitLoadout = _loadout_from
    _on_CreateSuitLoadout = _loadout_from

    def _on_DeleteSuitLoadout(self, ev, ts):
        self.s["loadouts"].pop(str(ev.get("LoadoutID")), None)

    def _on_RenameSuitLoadout(self, ev, ts):
        lo = self.s["loadouts"].get(str(ev.get("LoadoutID")))
        if lo is not None:
            lo["name"] = ev.get("LoadoutName", lo["name"])

    def _on_LoadoutEquipModule(self, ev, ts):
        self._weapon(ev, ts)
        lo = self.s["loadouts"].get(str(ev.get("LoadoutID")))
        if lo is not None and ev.get("SlotName"):
            lo["slots"][ev["SlotName"]] = str(ev.get("SuitModuleID"))

    def _on_LoadoutRemoveModule(self, ev, ts):
        lo = self.s["loadouts"].get(str(ev.get("LoadoutID")))
        if lo is not None:
            lo["slots"].pop(ev.get("SlotName", ""), None)

    def _on_BuySuit(self, ev, ts):
        suit = self._suit(ev, ts, name_key="Name")
        if suit is not None:
            suit["bought"] = ts

    def _on_SellSuit(self, ev, ts):
        suit = self.s["suits"].get(str(ev.get("SuitID")))
        if suit is not None:
            suit["gone"] = ts
        for key in [k for k, lo in self.s["loadouts"].items()
                    if lo.get("suit") == str(ev.get("SuitID"))]:
            del self.s["loadouts"][key]

    def _on_UpgradeSuit(self, ev, ts):
        suit = self._suit(ev, ts, name_key="Name")
        if suit is not None and ev.get("Class") is not None:
            suit["class"] = int(ev["Class"])

    def _on_BuyWeapon(self, ev, ts):
        weapon = self._weapon(ev, ts)
        if weapon is not None:
            weapon["bought"] = ts

    def _on_SellWeapon(self, ev, ts):
        weapon = self.s["weapons"].get(str(ev.get("SuitModuleID")))
        if weapon is not None:
            weapon["gone"] = ts

    def _on_UpgradeWeapon(self, ev, ts):
        self._weapon(ev, ts)

    # ── ring hotspots ─────────────────────────────────────────────────────────

    def _on_SAASignalsFound(self, ev, ts):
        body = ev.get("BodyName", "")
        if not body.endswith("Ring"):
            return
        system = self.s["where"].get("system", "")
        signals = {}
        for sig in ev.get("Signals") or []:
            token = str(sig.get("Type", ""))
            if token.lower().startswith("$saa_signaltype"):
                continue
            key = commodity_key(token)
            if key:
                signals[key] = {"name": sig.get("Type_Localised") or key.title(),
                                "count": int(sig.get("Count") or 0)}
        if signals:
            self.s["rings"][f"{system}|{body}"] = {"system": system, "ring": body,
                                                   "signals": signals}

    def _on_SupercruiseDestinationDrop(self, ev, ts):
        token = str(ev.get("Type", ""))
        m = re.search(r"RingHotspot:#type=([^;]+;)", token)
        if not m:
            self.s["pending_hotspot"] = None
            return
        name = re.sub(r"\s*Hotspot$", "", ev.get("Type_Localised") or "").strip()
        key = commodity_key(m.group(1))
        self.s["pending_hotspot"] = {"key": key, "name": name or key.title()}

    def _on_SupercruiseExit(self, ev, ts):
        self._end_visit()
        pending, self.s["pending_hotspot"] = self.s["pending_hotspot"], None
        if pending and ev.get("BodyType") == "PlanetaryRing":
            self.s["visit"] = {"system": ev.get("StarSystem", ""),
                               "ring": ev.get("Body", ""),
                               "key": pending["key"], "name": pending["name"],
                               "start": ts, "refined": 0,
                               "first": None, "last": None}

    def _on_SupercruiseEntry(self, ev, ts):
        self._end_visit()

    def _on_MiningRefined(self, ev, ts):
        visit = self.s["visit"]
        if not visit or commodity_key(ev.get("Type", "")) != visit["key"]:
            return
        visit["refined"] += 1
        visit["first"] = visit["first"] or ts
        visit["last"] = ts
        local = ev.get("Type_Localised")
        if local:
            visit["name"] = local

    def _end_visit(self) -> None:
        visit, self.s["visit"] = self.s.get("visit"), None
        if not visit or not visit.get("refined"):
            return
        key = f"{visit['system']}|{visit['ring']}|{visit['key']}"
        spot = self.s["hotspots"].setdefault(key, {
            "system": visit["system"], "ring": visit["ring"],
            "key": visit["key"], "name": visit["name"], "visits": []})
        spot["name"] = visit["name"] or spot["name"]
        record = {"start": visit["start"], "refined": visit["refined"],
                  "span": (visit["last"] or 0) - (visit["first"] or 0)}
        if record not in spot["visits"]:
            spot["visits"].append(record)


# ── helpers ───────────────────────────────────────────────────────────────────

def _strip(ev: dict, keep_event: bool = False) -> dict:
    """An event without the bookkeeping fields EDLD adds."""
    out = {k: v for k, v in ev.items() if not k.startswith("_")}
    if not keep_event:
        out.pop("event", None)
    return out


def _int_key(value: str):
    return (0, int(value)) if str(value).isdigit() else (1, str(value))


def hotspot_rates(spot: dict) -> tuple[Optional[float], Optional[float], int, int]:
    """(overall RPM, best visit RPM, visits counted, refinements) for a hotspot.

    A visit's rate is its refinements over the time from the first to the
    last of them — the intervals, so ``refined - 1`` of them — which is the
    rate while actually mining rather than diluted by the flight in and out.
    Short visits are left out of the rate; their refinements still count.
    """
    total_refined = sum(v.get("refined", 0) for v in spot.get("visits", []))
    intervals = 0
    seconds = 0.0
    best = None
    counted = 0
    for v in spot.get("visits", []):
        n, span = int(v.get("refined", 0)), float(v.get("span", 0.0))
        if n < MIN_VISIT_REFINED or span < MIN_VISIT_SPAN_S:
            continue
        counted += 1
        intervals += n - 1
        seconds += span
        rate = (n - 1) / (span / 60.0)
        best = rate if best is None else max(best, rate)
    overall = (intervals / (seconds / 60.0)) if seconds > 0 else None
    return overall, best, counted, total_refined


def now_utc() -> float:
    return datetime.now(timezone.utc).timestamp()
