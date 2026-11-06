"""
tests/test_dossier.py — the commander's dossier.

The fleet data EDLD kept threw away every stored ship's fitting: Frontier's
account data (CAPI) only carries modules for the ship being flown, so
core.fleet.json listed ten of eleven ships with ``loadout: []``. The journals
had all of them. A stored ship cannot be outfitted, so its last Loadout stays
true until it is flown again — these tests hold the dossier to that, and to
where a ship is kept, to what it leaves out by default, and to the two files
it writes.
"""
from __future__ import annotations

import base64
import gzip
import json
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.dossier import names  # noqa: E402
from core.dossier.build import Settings, build, load_state  # noqa: E402
from core.dossier.ledger import (Ledger, hotspot_rates,  # noqa: E402
                                 journal_sort_key)
from core.dossier.model import Model, coriolis_url, edsy_url  # noqa: E402

FID = "F10467336"
CARRIER = 3715178496
STATION = 3230947328


def _ts(minute: int, second: int = 0, day: int = 14, hour: int = 4) -> str:
    return f"2026-10-{day:02d}T{hour:02d}:{minute:02d}:{second:02d}Z"


def _loadout(sid, ship, name, ident, rebuy=1000, ts=_ts(1), eng=False):
    modules = [
        {"Slot": "FrameShiftDrive", "Item": "int_hyperdrive_overcharge_size5_class5",
         "On": True, "Priority": 0, "Health": 1.0},
        {"Slot": "Slot01_Size6", "Item": "int_cargorack_size6_class1",
         "On": True, "Priority": 1, "Health": 1.0},
        {"Slot": "TinyHardpoint1", "Item": "hpt_shieldbooster_size0_class5",
         "On": True, "Priority": 0, "Health": 1.0},
        {"Slot": "PaintJob", "Item": "paintjob_lakonminer_emerald_01",
         "On": True, "Priority": 1, "Health": 1.0},
    ]
    if eng:
        modules[0]["Engineering"] = {
            "Engineer": "Felicity Farseer", "BlueprintName": "FSD_LongRange",
            "Level": 5, "Quality": 1.0, "ExperimentalEffect": "special_fsd_heavy",
            "ExperimentalEffect_Localised": "Mass Manager",
            "Modifiers": [{"Label": "FSDOptimalMass", "Value": 7528.0,
                           "OriginalValue": 4670.0, "LessIsGood": 0}]}
    return {"timestamp": ts, "event": "Loadout", "Ship": ship, "ShipID": sid,
            "ShipName": name, "ShipIdent": ident, "HullHealth": 1.0,
            "UnladenMass": 577.3, "CargoCapacity": 300, "MaxJumpRange": 36.07,
            "FuelCapacity": {"Main": 32.0, "Reserve": 0.6}, "Rebuy": rebuy,
            "Modules": modules}


def _session(minute0: int = 0, fid: str = FID, name: str = "MERRICK CALBRUIN"):
    """A launch, a login in ship 3, docked aboard the carrier."""
    return [
        {"timestamp": _ts(minute0), "event": "Fileheader", "part": 1},
        {"timestamp": _ts(minute0), "event": "Commander", "FID": fid, "Name": name},
        {"timestamp": _ts(minute0), "event": "LoadGame", "FID": fid, "Commander": name,
         "Ship": "lakonminer", "ShipID": 3, "ShipName": "FOSSOR", "ShipIdent": "T11-FO",
         "Credits": 751897248, "GameMode": "Solo"},
        {"timestamp": _ts(minute0, 1), "event": "Docked", "StationName": "N2Z-N8M",
         "StationType": "FleetCarrier", "MarketID": CARRIER, "StarSystem": "HR 5252"},
        {"timestamp": _ts(minute0, 2), "event": "CarrierStats", "CarrierID": CARRIER,
         "Callsign": "N2Z-N8M", "Name": "VECTURA", "DockingAccess": "all",
         "AllowNotorious": True, "FuelLevel": 933, "JumpRangeMax": 500.0,
         "SpaceUsage": {"TotalCapacity": 25000, "FreeSpace": 20309},
         "Finance": {"CarrierBalance": 23535229930, "ReserveBalance": 1062500000,
                     "AvailableBalance": 22002032430, "TaxRate_refuel": 10},
         "Crew": [{"CrewRole": "Refuel", "Activated": True, "Enabled": True,
                   "CrewName": "Kasey Knox"}]},
    ]


def _journal(path: Path, events: list[dict]) -> Path:
    path.write_text("".join(json.dumps(e) + "\n" for e in events), encoding="utf-8")
    return path


def _ledger(tmp_path, events, fid=FID) -> Ledger:
    jdir = tmp_path / "journals"
    jdir.mkdir(exist_ok=True)
    _journal(jdir / "Journal.2026-10-14T040000.01.log", events)
    ledger = Ledger(fid=fid)
    ledger.scan(jdir)
    return ledger


def _fleet(tmp_path):
    """FOSSOR flown and stored aboard the carrier; PICTOR now current."""
    return _session() + [
        _loadout(3, "lakonminer", "FOSSOR", "T11-FO", rebuy=239749, ts=_ts(1, 3), eng=True),
        {"timestamp": _ts(5), "event": "ShipyardSwap", "ShipType": "explorer_nx",
         "ShipID": 12, "StoreOldShip": "LakonMiner", "StoreShipID": 3,
         "MarketID": CARRIER},
        _loadout(12, "explorer_nx", "PICTOR", "CE-PIC", rebuy=107905, ts=_ts(5, 2)),
    ]


# ── fittings are kept ─────────────────────────────────────────────────────────

def test_a_stored_ship_keeps_its_last_fitting(tmp_path):
    s = _ledger(tmp_path, _fleet(tmp_path)).s
    fossor = s["ships"]["3"]
    assert s["current_ship"] == "12"
    assert fossor["loadout"]["Rebuy"] == 239749
    assert len(fossor["loadout"]["Modules"]) == 4
    assert fossor["location"]["kind"] == "station"
    assert fossor["location"]["market_id"] == CARRIER


def test_a_ship_aboard_a_carrier_is_listed_by_the_carrier_never_a_system(tmp_path):
    model = Model(_ledger(tmp_path, _fleet(tmp_path)).s)
    fossor = model.s["ships"]["3"]
    where = model.ship_where(fossor)
    assert where == "Carrier VECTURA (N2Z-N8M)"
    assert "HR 5252" not in where


def test_a_ship_at_a_station_is_listed_by_station_and_system(tmp_path):
    events = _session() + [
        {"timestamp": _ts(2), "event": "Docked", "StationName": "Babylon 4",
         "StationType": "Coriolis", "MarketID": STATION, "StarSystem": "Kitchang Mu"},
        {"timestamp": _ts(3), "event": "ShipyardSwap", "ShipType": "explorer_nx",
         "ShipID": 12, "StoreShipID": 3, "MarketID": STATION},
    ]
    model = Model(_ledger(tmp_path, events).s)
    assert model.ship_where(model.s["ships"]["3"]) == "Babylon 4 · Kitchang Mu"


def test_stored_ships_is_the_whole_roster(tmp_path):
    events = _fleet(tmp_path) + [
        {"timestamp": _ts(9), "event": "StoredShips", "StationName": "N2Z-N8M",
         "MarketID": CARRIER, "StarSystem": "HR 5252",
         "ShipsHere": [{"ShipID": 3, "ShipType": "LakonMiner", "Name": "FOSSOR",
                        "Value": 0, "Hot": False}],
         "ShipsRemote": [{"ShipID": 8, "ShipType": "Type8", "Name": "ALUMINIUM HAULCON",
                          "StarSystem": "Tir", "ShipMarketID": STATION,
                          "TransferPrice": 1000, "TransferTime": 300, "Value": 0,
                          "Hot": False}]},
    ]
    s = _ledger(tmp_path, events).s
    assert s["roster"]["ids"] == ["3", "8", "12"]
    assert s["ships"]["8"]["location"]["system"] == "Tir"


def test_a_sold_ship_leaves_the_fleet(tmp_path):
    events = _fleet(tmp_path) + [
        {"timestamp": _ts(9), "event": "ShipyardSell", "ShipType": "lakonminer",
         "SellShipID": 3, "ShipPrice": 1200000, "MarketID": CARRIER}]
    s = _ledger(tmp_path, events).s
    assert "3" not in s["roster"]["ids"]
    assert [sh["ship_id"] for sh in Model(s).owned_ships()] == [12]
    assert s["ships"]["3"]["record"][-1][2] == "Sold for 1,200,000 cr"


def test_a_transfer_is_in_transit_until_it_arrives(tmp_path):
    events = _fleet(tmp_path) + [
        {"timestamp": _ts(10), "event": "ShipyardTransfer", "ShipType": "Type8",
         "ShipID": 8, "System": "Tir", "ShipMarketID": STATION, "Distance": 12.0,
         "TransferPrice": 1958, "TransferTime": 300, "MarketID": CARRIER}]
    s = _ledger(tmp_path, events).s
    ship = s["ships"]["8"]
    arrives = ship["location"]["arrives"]
    assert Model(s, now=arrives - 60).ship_where(ship).startswith(
        "In transit to Carrier VECTURA")
    assert Model(s, now=arrives + 60).ship_where(ship) == "Carrier VECTURA (N2Z-N8M)"
    assert ship["record"][-1][2] == "Transferred from Tir"


def test_names_are_keyed_on_shipid_not_name(tmp_path):
    """ONERARIUS was ShipID 16, sold, and the name went to ShipID 36."""
    events = _session() + [
        _loadout(16, "panthermkii", "ONERARIUS", "PC-ONE", ts=_ts(1, 5)),
        {"timestamp": _ts(2), "event": "ShipyardBuy", "ShipType": "panthermkii",
         "ShipPrice": 5, "SellOldShip": "panthermkii", "SellShipID": 16,
         "SellPrice": 0, "MarketID": STATION},
        {"timestamp": _ts(2, 1), "event": "ShipyardNew", "ShipType": "panthermkii",
         "NewShipID": 36},
        {"timestamp": _ts(2, 2), "event": "SetUserShipName", "Ship": "panthermkii",
         "ShipID": 36, "UserShipName": "ONERARIUS", "UserShipId": "PC-ONE"},
    ]
    s = _ledger(tmp_path, events).s
    assert s["ships"]["16"]["sold"]
    assert s["ships"]["36"]["acquired"]["how"] == "bought"
    assert s["ships"]["36"]["name"] == "ONERARIUS"


# ── reading the journals ──────────────────────────────────────────────────────

def test_only_new_lines_are_read_and_a_half_written_line_waits(tmp_path):
    jdir = tmp_path / "journals"
    jdir.mkdir()
    path = _journal(jdir / "Journal.2026-10-14T040000.01.log", _fleet(tmp_path))
    ledger = Ledger(fid=FID)
    first = ledger.scan(jdir)
    assert first > 0 and ledger.scan(jdir) == 0
    line = json.dumps({"timestamp": _ts(20), "event": "SetUserShipName",
                       "ShipID": 12, "UserShipName": "PICTOR II", "UserShipId": "CE-PIC"})
    with open(path, "a", encoding="utf-8") as fh:
        fh.write(line[:30])                       # the game is mid-write
    assert ledger.scan(jdir) == 0
    with open(path, "a", encoding="utf-8") as fh:
        fh.write(line[30:] + "\n")
    assert ledger.scan(jdir) == 1
    assert ledger.s["ships"]["12"]["name"] == "PICTOR II"


def test_another_commanders_events_are_left_out(tmp_path):
    other = _session(fid="F99999999", name="SOMEONE ELSE") + [
        _loadout(1, "sidewinder", "NOT MINE", "", ts=_ts(2))]
    s = _ledger(tmp_path, other).s
    assert s["ships"] == {} and s["commander"]["name"] == ""


def test_the_fid_is_never_stored_or_written(tmp_path):
    jdir = tmp_path / "journals"
    jdir.mkdir()
    _journal(jdir / "Journal.2026-10-14T040000.01.log", _fleet(tmp_path))
    cmdr = tmp_path / "cmdr"
    build(jdir, cmdr, FID, settings=Settings(True, True), db_path=tmp_path / "none.db")
    for path in [cmdr / "data" / "dossier.json", *cmdr.joinpath("dossier").rglob("*.*")]:
        assert FID not in path.read_text(encoding="utf-8"), path


def test_fittings_survive_the_journal_being_deleted(tmp_path):
    jdir = tmp_path / "journals"
    jdir.mkdir()
    path = _journal(jdir / "Journal.2026-10-14T040000.01.log", _fleet(tmp_path))
    cmdr = tmp_path / "cmdr"
    build(jdir, cmdr, FID, db_path=tmp_path / "none.db")
    path.unlink()
    result = build(jdir, cmdr, FID, db_path=tmp_path / "none.db")
    assert result.events == 0
    assert load_state(cmdr)["ships"]["3"]["loadout"]["Rebuy"] == 239749
    assert "3 Mining" not in (cmdr / "dossier/md/ships/3-fossor.md").read_text()
    assert "6E Cargo Rack" in (cmdr / "dossier/md/ships/3-fossor.md").read_text()


def test_old_and_new_journal_names_sort_by_date():
    paths = [Path("Journal.2026-10-14T205310.01.log"),
             Path("Journal.211231120000.01.log"),
             Path("Journal.2022-01-02T101010.01.log")]
    assert [p.name for p in sorted(paths, key=journal_sort_key)] == [
        "Journal.211231120000.01.log", "Journal.2022-01-02T101010.01.log",
        "Journal.2026-10-14T205310.01.log"]


def test_time_as_active_ship_ignores_long_gaps(tmp_path):
    events = _session() + [
        {"timestamp": _ts(5), "event": "Music", "MusicTrack": "Exploration"},
        {"timestamp": _ts(10), "event": "Music", "MusicTrack": "Exploration"},
        {"timestamp": _ts(10, hour=6), "event": "Music", "MusicTrack": "Exploration"},
    ]
    seconds = _ledger(tmp_path, events).s["ships"]["3"]["seconds"]
    assert seconds == 10 * 60                     # the two-hour gap is not counted


# ── hotspots ──────────────────────────────────────────────────────────────────

def _visit(start_min, refinements, every_s, commodity="Platinum",
           ring="HR 5252 A 5 A Ring", system="HR 5252"):
    token = "$" + commodity.replace(" ", "") + "_name;"
    events = [
        {"timestamp": _ts(start_min), "event": "SupercruiseDestinationDrop",
         "Type": f"$SAA_RingHotspot:#type={token};", "Type_Localised": f"{commodity} Hotspot"},
        {"timestamp": _ts(start_min, 5), "event": "SupercruiseExit", "StarSystem": system,
         "Body": ring, "BodyType": "PlanetaryRing"},
    ]
    t0 = start_min * 60 + 30
    for i in range(refinements):
        t = t0 + i * every_s
        events.append({"timestamp": _ts(t // 60, t % 60), "event": "MiningRefined",
                       "Type": token.lower(), "Type_Localised": commodity})
    end = t0 + refinements * every_s
    events.append({"timestamp": _ts(end // 60, end % 60), "event": "SupercruiseEntry",
                   "StarSystem": system})
    return events


def test_a_hotspot_rate_is_refinements_per_minute_while_mining(tmp_path):
    s = _ledger(tmp_path, _session() + _visit(1, 11, 30)).s
    (spot,) = s["hotspots"].values()
    overall, best, counted, refined = hotspot_rates(spot)
    assert refined == 11 and counted == 1
    assert overall == pytest.approx(2.0)          # 10 intervals in 5 minutes


def test_a_short_visit_counts_its_refinements_but_not_a_rate(tmp_path):
    s = _ledger(tmp_path, _session() + _visit(1, 3, 20)).s
    overall, best, counted, refined = hotspot_rates(next(iter(s["hotspots"].values())))
    assert (overall, counted, refined) == (None, 0, 3)


def test_hotspots_sort_by_commodity_then_rate_high_to_low(tmp_path):
    events = (_session()
              + _visit(1, 11, 60, ring="A Ring", system="Alpha")      # 1.0/min
              + _visit(20, 11, 20, ring="B Ring", system="Beta")      # 3.0/min
              + _visit(30, 2, 20, ring="C Ring", system="Gamma")      # not rated
              + _visit(40, 11, 30, commodity="Bromellite", ring="D Ring", system="Delta"))
    page = Model(_ledger(tmp_path, events).s).mining_page()
    rows = page["blocks"][0]["rows"]
    assert [(r[0], r[2]) for r in rows] == [
        ("Bromellite", "Delta"), ("Platinum", "Beta"), ("Platinum", "Alpha"),
        ("Platinum", "Gamma")]


# ── what is left out ──────────────────────────────────────────────────────────

def _texts(pages) -> str:
    return json.dumps(pages, default=str)


def test_location_and_balances_are_left_out_by_default(tmp_path):
    s = _ledger(tmp_path, _fleet(tmp_path)).s
    text = _texts(Model(s).pages())
    assert "751,897,248" not in text            # credits
    assert "23,535,229,930" not in text         # carrier bank
    assert "Current system" not in text
    assert "IncludeCurrentLocation" in text     # says why the carrier is quiet


def test_included_when_asked(tmp_path):
    s = _ledger(tmp_path, _fleet(tmp_path)).s
    text = _texts(Model(s, include_location=True, include_balance=True).pages())
    assert "751,897,248 cr" in text and "23,535,229,930 cr" in text
    assert "Current system" in text


# ── outputs ───────────────────────────────────────────────────────────────────

def test_outfitting_links_carry_the_loadout(tmp_path):
    lo = _loadout(3, "lakonminer", "FOSSOR", "T11-FO")
    for url, prefix in ((coriolis_url(lo), "https://coriolis.io/import?data="),
                        (edsy_url(lo), "https://edsy.org/#/I=")):
        assert url.startswith(prefix)
        raw = base64.urlsafe_b64decode(url[len(prefix):].replace("%3D", "="))
        assert json.loads(gzip.decompress(raw)) == lo
    assert coriolis_url(lo) == coriolis_url(lo)  # stable: no gzip timestamp


def _built(tmp_path, theme="elite-orange"):
    jdir = tmp_path / "journals"
    jdir.mkdir(exist_ok=True)
    _journal(jdir / "Journal.2026-10-14T040000.01.log", _fleet(tmp_path))
    cmdr = tmp_path / "cmdr"
    result = build(jdir, cmdr, FID, theme=theme, db_path=tmp_path / "none.db")
    return cmdr / "dossier", result


def test_the_page_is_self_contained_and_themed(tmp_path):
    from core.palette import palette_for
    out, _ = _built(tmp_path)
    page = (out / "html" / "index.html").read_text(encoding="utf-8")
    assert "<script" not in page
    assert not re.search(r'<link|src="https?:', page)
    assert palette_for("elite-orange")["$accent"] in page
    for anchor in ("commander", "fleet", "ship-3", "ship-12", "modules",
                   "engineering", "carrier", "mining", "on-foot"):
        assert f'id="{anchor}"' in page
        assert f'href="#{anchor}"' in page


def test_markdown_links_all_resolve(tmp_path):
    out, _ = _built(tmp_path)
    md = out / "md"
    files = list(md.rglob("*.md"))
    assert {p.relative_to(md).as_posix() for p in files} >= {
        "index.md", "commander.md", "fleet.md", "ships/3-fossor.md",
        "ships/12-pictor.md", "modules.md", "engineering.md", "carrier.md",
        "mining.md", "on-foot.md"}
    for path in files:
        for target in re.findall(r"\]\(([^)]+\.md)\)", path.read_text(encoding="utf-8")):
            assert (path.parent / target).resolve().is_file(), (path, target)


def test_engineering_is_shown_with_its_experimental_and_engineer(tmp_path):
    out, _ = _built(tmp_path)
    text = (out / "md" / "ships" / "3-fossor.md").read_text(encoding="utf-8")
    assert "Increased Range G5 (100%) · Mass Manager · Felicity Farseer" in text
    assert "## Cosmetics" in text


def test_files_for_a_sold_ship_are_removed_but_the_commanders_own_are_not(tmp_path):
    out, _ = _built(tmp_path)
    mine = out / "md" / "my-notes.md"
    mine.write_text("mine")
    jdir = tmp_path / "journals"
    with open(jdir / "Journal.2026-10-14T040000.01.log", "a") as fh:
        fh.write(json.dumps({"timestamp": _ts(30), "event": "ShipyardSell",
                             "SellShipID": 3, "ShipPrice": 1, "MarketID": CARRIER}) + "\n")
    result = build(jdir, tmp_path / "cmdr", FID, db_path=tmp_path / "none.db")
    assert "md/ships/3-fossor.md" in result.removed
    assert mine.read_text() == "mine"


def test_written_files_are_readable_by_others(tmp_path):
    out, _ = _built(tmp_path)
    assert (out / "html" / "index.html").stat().st_mode & 0o044 == 0o044


# ── names ─────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("item,name", [
    ("Hpt_MiningToolV2_Fixed_Large", "3C Mining Volley Repeater (Fixed)"),
    ("hpt_shieldbooster_size0_class5", "0A Shield Booster"),
    ("int_largebuggybay_size4_class3_free", "4F Large Planetary Vehicle Hangar"),
    ("int_mkiilargebuggybay_size4_class3", "4F Mk II Large Planetary Vehicle Hangar"),
    ("int_largecargorack_size8_class1", "8D Mk II Cargo Rack"),
    ("$int_engine_size8_class5_name;", "8A Thrusters"),
])
def test_module_names(item, name):
    assert names.module_name(item) == name


# ── the component ─────────────────────────────────────────────────────────────

def test_every_setting_is_bound_and_is_a_standard_section():
    from components.dossier import CFG_DEFAULTS, DossierPlugin
    from core.config import STANDARD_SECTIONS
    bindings = DossierPlugin.preferences_bindings(DossierPlugin.__new__(DossierPlugin))
    assert {key for _s, key, _t in bindings.values()} == set(CFG_DEFAULTS)
    assert "Dossier" in STANDARD_SECTIONS


def test_the_tui_tab_mounts():
    pytest.importorskip("textual")
    import asyncio
    from textual.app import App
    from textual.containers import VerticalScroll
    from textual.widgets import Select
    from components.dossier import CFG_DEFAULTS, DossierPlugin

    p = DossierPlugin.__new__(DossierPlugin)
    p.cfg = dict(CFG_DEFAULTS)
    p.last_error, p.last_built = "", 0.0
    _id, _label, compose = p.tui_preferences_tab()

    class Host(App):
        def compose(self):
            with VerticalScroll():
                yield from compose()

    async def run():
        async with Host().run_test() as pilot:
            await pilot.pause()
            ids = {s.id for s in pilot.app.query(Select)}
            assert ids == set(p.preferences_bindings())

    asyncio.run(run())
