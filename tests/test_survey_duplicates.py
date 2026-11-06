"""One rig site, one deposit — however the commodity was spelled, wherever
the SRV was standing when it refined.

Reproduces Kitchang Mu 3 d on 2026-10-11: a Low Temp. Diamonds site recorded
from the deposit form, then refined from two spots 180 m apart, became three
deposits on the shared sheet.
"""
import pytest

import core.surface_survey as survey
from core.mining_db import MiningDB
from core.surface_survey import canonical_commodity, learn_commodity_name

SA, BID, R = 18264214218209, 24, 2687705.5
FORM = (-11.387536, 19.314709)        # recorded from the deposit form
BATCH_1 = (-11.387727, 19.312658)     # first refine batch, 94.7 m away
BATCH_2 = (-11.386536, 19.316385)     # second, 90.2 m from the form, 180 m from batch 1


@pytest.fixture
def db(tmp_path):
    d = MiningDB(tmp_path / "mining.db")
    d.upsert_body(SA, BID, radius_m=R, body_name="Kitchang Mu 3 d")
    return d


def _ltd(db):
    return [r for r in db.deposits_on(SA, BID)
            if r["commodity"] == "lowtemperaturediamond"]


def test_the_name_the_game_shows_is_the_commodity_it_refines():
    assert canonical_commodity("Low Temp. Diamonds") == "lowtemperaturediamond"
    assert canonical_commodity("$lowtemperaturediamond_name;") == "lowtemperaturediamond"
    assert canonical_commodity("Void Opals") == "opal"
    assert canonical_commodity("Helium-3") == "helium3"


def test_a_name_seen_on_a_refine_is_learned():
    assert canonical_commodity("Shiny New Rock") == "shinynewrock"
    assert learn_commodity_name("$sparklite_name;", "Shiny New Rock")
    try:
        assert canonical_commodity("Shiny New Rock") == "sparklite"
    finally:
        survey._COMMODITY_ALIASES.pop("shinynewrock", None)


def test_refines_find_the_deposit_recorded_from_the_form(db):
    dep, created = db.record_deposit(SA, BID, "lowtempdiamonds", *FORM,
                                     commodity_display="Low Temp. Diamonds", rigs=5)
    assert created
    for pos, n in ((BATCH_1, 91), (BATCH_2, 61)):
        got, created = db.record_deposit(SA, BID, "lowtemperaturediamond", *pos,
                                         commodity_display="Low Temp. Diamonds",
                                         refined=n)
        assert (got, created) == (dep, False)
    (row,) = _ltd(db)
    assert row["refine_count"] == 152 and row["rigs"] == 5


def test_refines_across_one_rig_site_are_one_deposit(db):
    a, _ = db.record_deposit(SA, BID, "lowtemperaturediamond", *BATCH_1, refined=91)
    b, created = db.record_deposit(SA, BID, "lowtemperaturediamond", *BATCH_2, refined=61)
    assert (b, created) == (a, False)


def test_a_neighbouring_site_stays_separate(db):
    db.record_deposit(SA, BID, "lowtemperaturediamond", *FORM, refined=1)
    # 450 m due north: the closest real neighbours are 400-500 m apart.
    north = (FORM[0] + 450 / (R * 3.141592653589793 / 180), FORM[1])
    _, created = db.record_deposit(SA, BID, "lowtemperaturediamond", *north, refined=1)
    assert created


def _insert_raw(db, dep_id, commodity, pos, *, first, refines=0, rigs=None,
                notes="", published=True):
    conn = db._connect()
    conn.execute(
        "INSERT INTO deposits(deposit_id, system_address, body_id, commodity,"
        " commodity_display, latitude, longitude, rigs, refine_count, first_seen,"
        " last_confirmed, published_at, notes)"
        " VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (dep_id, SA, BID, commodity, "Low Temp. Diamonds", pos[0], pos[1], rigs,
         refines, first, first, "2026-10-11T09:10:00Z" if published else "", notes))
    conn.commit()


def test_repair_folds_the_three_rows_into_the_one_recorded_first(db):
    # The store as it was: one row under the typed name, two under the symbol.
    _insert_raw(db, "62cb28f82f30", "lowtempdiamonds", FORM,
                first="2026-10-11T08:44:50Z", rigs=5, notes="5 Rigs easy, maybe 6")
    _insert_raw(db, "96bcb13bc7e8", "lowtemperaturediamond", BATCH_1,
                first="2026-10-11T08:48:29Z", refines=91)
    _insert_raw(db, "1452a7cc00a0", "lowtemperaturediamond", BATCH_2,
                first="2026-10-11T08:49:36Z", refines=61)

    assert db.repair() == {"rekeyed": 1, "merged": 2}
    (row,) = _ltd(db)
    assert row["deposit_id"] == "62cb28f82f30"
    assert (row["refine_count"], row["rigs"]) == (152, 5)
    assert row["notes"] == "5 Rigs easy, maybe 6"
    assert row["published_at"] == ""                 # re-sent with the totals
    assert sorted(db.pending_sheet_removals()) == ["1452a7cc00a0", "96bcb13bc7e8"]
    assert db.repair() == {"rekeyed": 0, "merged": 0}


def test_the_sheet_cannot_bring_a_merged_duplicate_back(db):
    _insert_raw(db, "62cb28f82f30", "lowtemperaturediamond", FORM,
                first="2026-10-11T08:44:50Z", rigs=5)
    _insert_raw(db, "96bcb13bc7e8", "lowtemperaturediamond", BATCH_1,
                first="2026-10-11T08:48:29Z", refines=91)
    db.repair()
    sheet_row = {"deposit_id": "96bcb13bc7e8", "system_address": SA, "body_id": BID,
                 "commodity": "Low Temp. Diamonds",
                 "latitude": BATCH_1[0], "longitude": BATCH_1[1]}
    assert db.import_deposits([sheet_row]) == (0, 0)
    assert len(_ltd(db)) == 1


def test_another_commanders_id_for_the_same_site_merges_on_import(db):
    db.record_deposit(SA, BID, "lowtemperaturediamond", *FORM, refined=3)
    theirs = {"deposit_id": "0123456789ab", "system_address": SA, "body_id": BID,
              "commodity": "Low Temp. Diamonds", "amount": "High",
              "latitude": BATCH_2[0], "longitude": BATCH_2[1]}
    added, updated = db.import_deposits([theirs])
    assert (added, updated) == (0, 1)
    (row,) = _ltd(db)
    assert row["amount"] == "High"


def test_an_imported_row_is_keyed_on_the_symbol(db):
    row = {"deposit_id": "abcdefabcdef", "system_address": SA, "body_id": BID,
           "commodity": "Low Temp. Diamonds", "latitude": 10.0, "longitude": 10.0}
    assert db.import_deposits([row]) == (1, 0)
    (got,) = _ltd(db)
    assert got["commodity_display"] == "Low Temp. Diamonds"
