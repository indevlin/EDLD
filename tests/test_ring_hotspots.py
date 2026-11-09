"""tests/test_ring_hotspots.py — Ring hotspots: capture from Scan and
SAASignalsFound, the form, the sheet merge, publishing and the Mining tables."""
from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core import ring_hotspots as RH  # noqa: E402
from core.sheets_publish import HOTSPOT_COLUMNS, SheetsPublisher  # noqa: E402
from components.ring_hotspots import RingHotspotsPlugin  # noqa: E402

SYS, ADDR = "Borann", 1458309141194


def _scan(**kw):
    ev = {"event": "Scan", "StarSystem": SYS, "SystemAddress": ADDR, "BodyName": "Borann A 2",
          "BodyID": 4, "ReserveLevel": "PristineResources",
          "Rings": [{"Name": "Borann A 2 A Ring", "RingClass": "eRingClass_Icy"},
                    {"Name": "Borann A 2 B Ring", "RingClass": "eRingClass_Metalic"}]}
    ev.update(kw)
    return ev


def _signals(ring="A", sigs=None):
    return {"event": "SAASignalsFound", "SystemAddress": ADDR, "BodyID": 5,
            "BodyName": f"Borann A 2 {ring} Ring",
            "Signals": sigs or [{"Type": "LowTemperatureDiamond",
                                 "Type_Localised": "Low Temperature Diamonds", "Count": 3},
                                {"Type": "Tritium", "Type_Localised": "Tritium", "Count": 1}]}


@pytest.fixture
def plugin(tmp_path, monkeypatch):
    db = RH.HotspotDB(tmp_path / "ring_hotspots.db")
    monkeypatch.setattr(RH, "get_db", lambda: db)
    core = SimpleNamespace(gui_queue=None, journal_dir=None, _plugins={},
                           load_setting=lambda *a, **k: {})
    p = RingHotspotsPlugin.__new__(RingHotspotsPlugin)
    p._core, p._db = core, db
    p._system_name, p._system_address = SYS, ADDR
    p._publisher, p._reporter = None, "CMDR T"
    p._include_test = p._mark_as_test = p._fetch_enabled = False
    p._fetched, p.status = set(), "off"
    core._plugins["ring_hotspots"] = p
    state = SimpleNamespace(in_preload=False)
    p.on_event_ = lambda ev: p.on_event(ev, state)
    return p


# ── vocabulary ────────────────────────────────────────────────────────────────

def test_names_and_classes():
    assert RH.split_ring("Col 285 Sector KZ-C c14-15 3 A Ring") == ("Col 285 Sector KZ-C c14-15 3", "A")
    assert RH.split_ring("Borann A 2") == ("", "")
    assert RH.ring_type("eRingClass_MetalRich") == "Metal Rich"
    assert RH.ring_type("eRingClass_Metalic") == "Metallic"
    assert RH.reserve_level("MajorResources") == "Major"
    assert RH.commodity_display("LowTemperatureDiamond") == "Low Temperature Diamonds"
    assert RH.commodity_display("Opal") == "Void Opals"
    assert RH.hotspot_id(SYS, "Borann A 2", "a", "Low Temperature Diamonds") == \
        RH.hotspot_id("borann", "BORANN A 2", "A", "lowtemperaturediamond")


# ── capture ───────────────────────────────────────────────────────────────────

def test_scan_then_signals_gives_typed_hotspots(plugin):
    plugin.on_event_(_scan())
    plugin.on_event_(_signals())
    rows = plugin.records()
    assert [(r["ring"], r["commodity_display"], r["ring_type"], r["reserve_level"], r["count"])
            for r in rows] == [("A", "Low Temperature Diamonds", "Icy", "Pristine", 3),
                               ("A", "Tritium", "Icy", "Pristine", 1)]
    assert all(r["system_address"] == ADDR and r["reported_by"] == "CMDR T" for r in rows)


def test_signals_before_the_scan_are_filled_by_it(plugin):
    plugin.on_event_(_signals("B", [{"Type": "Platinum", "Count": 1}]))
    assert plugin.records()[0]["ring_type"] == ""
    plugin.on_event_(_scan())
    h = plugin.records()[0]
    assert (h["ring_type"], h["reserve_level"]) == ("Metallic", "Pristine")


def test_repeat_signals_do_not_duplicate_and_surface_tokens_are_skipped(plugin):
    plugin.on_event_(_signals())
    plugin.on_event_(_signals())
    plugin.on_event_({"event": "SAASignalsFound", "BodyName": "Borann A 2",
                      "Signals": [{"Type": "$SAA_SignalType_Geological;", "Count": 2}]})
    assert len(plugin.records()) == 2


def test_backfill_reads_journal_history(plugin, tmp_path, monkeypatch):
    events = [{"event": "FSDJump", "StarSystem": SYS, "SystemAddress": ADDR},
              _scan(), _signals()]
    import core.journal_index as JI
    monkeypatch.setattr(JI, "index_for", lambda d: SimpleNamespace(
        events=lambda names: ((None, e) for e in events if e["event"] in names)))
    plugin._core.journal_dir = tmp_path
    plugin._system_name = ""
    plugin._backfill()
    assert {r["commodity_display"] for r in plugin.records()} == {
        "Low Temperature Diamonds", "Tritium"}


# ── form ──────────────────────────────────────────────────────────────────────

def test_clean_requires_identity_for_a_new_hotspot_and_checks_choices():
    c = RH.clean({"system_name": "", "ring": "AB", "reserve_level": "Huge"}, new=True)
    assert set(c.errors) == {"system_name", "body_name", "ring", "commodity", "reserve_level"}
    c = RH.clean({"overlap": "resource [haz]", "note": ""})
    assert c.values == {"overlap": "Resource [HAZ]", "note": ""} and not c.errors
    c = RH.clean({"overlap": "Resource [LOW]", "note": "Platinum"})
    assert "note" in c.errors


def test_edit_overlap_and_note(plugin):
    plugin.on_event_(_scan())
    plugin.on_event_(_signals())
    hid = plugin.records()[0]["hotspot_id"]
    plugin._db.mark_published([hid])
    assert plugin.submit_form_for(hid, {"note": "tritium"}).startswith("updated")
    h = plugin._db.hotspot(hid)
    assert (h["overlap"], h["note"]) == ("Hotspot [NOTE]", "Tritium")
    assert h["overlap_updated"] and h["published_at"] == ""
    assert plugin.save_cell(hid, "overlap", "Resource [HIGH]").startswith("updated")
    h = plugin._db.hotspot(hid)
    assert (h["overlap"], h["note"]) == ("Resource [HIGH]", "")
    assert plugin.submit_form_for(hid, {"commodity": "Gold", "ring": "B"}) == "nothing to change"
    assert plugin.submit_form_for("nope", {"overlap": ""}) == "hotspot nope is not in the store"


def test_add_by_hand(plugin):
    out = plugin.submit_form_for(None, {"system_name": "Hip 1", "body_name": "Hip 1 3", "ring": "a",
                                        "commodity": "painite", "ring_type": "Metallic",
                                        "overlap": "Resource [HAZ]"})
    assert out.startswith("recorded")
    h = plugin.records()[0]
    assert (h["ring"], h["commodity_display"], h["ring_type"], h["overlap"]) == \
        ("A", "Painite", "Metallic", "Resource [HAZ]")
    assert plugin.submit_form_for(None, {"system_name": "Hip 1"}).startswith("Body is required")


def test_form_for_new_defaults_to_the_current_system(plugin):
    form, heading = plugin.form_for(None)
    assert form["system_name"] == SYS and heading == "New ring hotspot"


# ── sheet ─────────────────────────────────────────────────────────────────────

def test_import_merges_without_republishing(plugin):
    plugin.on_event_(_signals("A", [{"Type": "Platinum", "Count": 1}]))
    mine = plugin.records()[0]
    sheet = [
        {"hotspot_id": mine["hotspot_id"], "system": SYS, "body": "Borann A 2", "ring": "A",
         "commodity": "Platinum", "ring_type": "Icy", "overlap": "Resource [HAZ]",
         "overlap_updated": "2099-01-01T00:00:00Z"},
        {"hotspot_id": "remote000001", "system": SYS, "body": "Borann A 3", "ring": "B",
         "commodity": "Painite", "reserve_level": "Major"},
        {"hotspot_id": "remote000002", "system": SYS, "body": "Borann A 3", "ring": "B",
         "commodity": "Gold", "is_test": 1},
    ]
    assert plugin._db.import_rows(sheet) == (1, 1)
    h = plugin._db.hotspot(mine["hotspot_id"])
    assert (h["ring_type"], h["overlap"]) == ("Icy", "Resource [HAZ]")
    assert [r["hotspot_id"] for r in plugin._db.unpublished()] == [mine["hotspot_id"]]
    assert plugin._db.hotspot("remote000001")["remote"] == 1


def _publisher(reply):
    sent = []

    def opener(url, data, timeout):
        sent.append(json.loads(data))
        return json.dumps(reply(sent[-1]))
    return SheetsPublisher("https://script.google.com/macros/s/X/exec", "t", opener=opener), sent


def test_publish_marks_rows_only_when_the_sheet_takes_hotspots(plugin):
    plugin.on_event_(_signals())
    pub, sent = _publisher(lambda b: {"ok": True, "added": 0, "updated": 0, "unchanged": 0})
    plugin._publisher = pub
    assert "Upgrade" in plugin.publish_now()                 # pre-v4 receiver
    assert len(plugin._db.unpublished()) == 2
    pub, sent = _publisher(lambda b: {"ok": True, "kind": "hotspots",
                                      "added": len(b["hotspots"]), "updated": 0, "unchanged": 0})
    plugin._publisher = pub
    assert plugin.publish_now().startswith("published 2 new")
    assert plugin._db.unpublished() == []
    assert list(sent[0]["hotspots"][0]) == list(HOTSPOT_COLUMNS)


def test_fetch_imports_once_per_system(plugin):
    calls = []
    pub, _ = _publisher(lambda b: calls.append(b) or {
        "ok": True, "kind": "hotspots", "hotspots": [
            {"hotspot_id": "remote000001", "system": SYS, "body": "Borann A 3", "ring": "B",
             "commodity": "Painite"}]})
    plugin._publisher, plugin._fetch_enabled = pub, True
    plugin.fetch_system(SYS, ADDR)
    plugin.fetch_system(SYS, ADDR)
    assert len(calls) == 1 and calls[0]["fetch_hotspots"] == {"system_address": ADDR, "system": SYS}
    assert plugin.records()[0]["commodity_display"] == "Painite"


# ── Mining window ─────────────────────────────────────────────────────────────

def test_mining_tables(plugin):
    from core.windows import mining as W
    from core.windows.wire import panels
    plugin.on_event_(_scan())
    plugin.on_event_(_signals())
    rows = W.hotspots(plugin._core).rows
    assert rows[0][0] == "table" and [h for h, _w in rows[0][2]][-1] == ""
    cells = [r for r in rows if r[0] == "cells"]
    assert all(r[2][-1] == W.EDIT and r[4].startswith("edit:") for r in cells)
    assert [r[2][3] for r in W.hotspots(plugin._core, "tritium").rows if r[0] == "cells"] == ["Tritium"]
    assert W.hotspots(plugin._core, "osmium").rows == [("text", "No hotspots match", "dim")]
    wire = {p["id"]: p for p in panels(plugin._core)}
    assert [wire[i]["title"] for i in ("mining.hotspots", "mining.sites")] == \
        ["Ring Hotspots", "Surface Sites"]
    assert wire["mining.hotspots"]["order"] < wire["mining.sites"]["order"]
    assert all(W.EDIT not in r.get("cells", []) for r in wire["mining.hotspots"]["rows"])


def test_gui_table_and_dialog(plugin):
    import os
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    from gui.hotspot_dialog import HotspotDialog
    from gui.hotspots_table import COLUMNS, HotspotsTable
    plugin.on_event_(_scan())
    plugin.on_event_(_signals())
    t = HotspotsTable(plugin._core)
    t.refresh()
    assert t.table.rowCount() == 2 and len(t.edit_buttons) == 2
    assert t.add_btn is not None and t.add_btn.text() == "Add hotspot…"
    hid = plugin.records()[0]["hotspot_id"]
    row = t.row_of(hid)
    overlap = next(i for i, c in enumerate(COLUMNS) if c[2] == "overlap")
    assert t.save_cell(row, overlap, "Resource [LOW]")
    assert plugin._db.hotspot(hid)["overlap"] == "Resource [LOW]"
    d = HotspotDialog(plugin, None, hid=hid)
    assert not d._widgets["commodity"].isEnabled() and d._widgets["overlap"].isEnabled()
    d._widgets["overlap"].setCurrentIndex(d._widgets["overlap"].findData("Hotspot [NOTE]"))
    d._widgets["note"].setCurrentIndex(d._widgets["note"].findData("Tritium"))
    d._save()
    assert d.result() == d.DialogCode.Accepted
    assert plugin._db.hotspot(hid)["note"] == "Tritium"
    app.processEvents()


def test_tui_mining_block_tabs_filter_and_edit(plugin):
    import asyncio
    pytest.importorskip("textual")
    from textual.app import App
    from textual.widgets import Input, TabbedContent
    from tui.blocks.mining import MiningBlock
    from tui.hotspot_screen import HotspotScreen
    plugin.on_event_(_scan())
    plugin.on_event_(_signals())
    core = plugin._core
    core.state = SimpleNamespace()
    seen = {}

    class _A(App):
        def compose(self):
            yield MiningBlock(core, id="b")

    async def run():
        app = _A()
        async with app.run_test(size=(120, 30)) as pilot:
            b = app.query_one("#b")
            await pilot.pause()
            assert app.query_one("#mining-tabs", TabbedContent).active == "mining-tab-hotspots"
            b.refresh_data()
            seen["rows"] = len([r for r in b._shown["hotspots"] if r[0] == "cells"])
            app.query_one("#hotspots-filter", Input).value = "tritium"
            await pilot.pause()
            seen["filtered"] = len([r for r in b._shown["hotspots"] if r[0] == "cells"])
            b.row_action("edit:" + plugin.records()[0]["hotspot_id"])
            await pilot.pause()
            seen["screen"] = isinstance(app.screen, HotspotScreen)
            app.screen.dismiss()
            await pilot.pause()
            await pilot.click("#hotspot-add-btn")
            await pilot.pause()
            seen["add"] = app.screen._hid is None

    asyncio.run(run())
    assert seen == {"rows": 2, "filtered": 1, "screen": True, "add": True}
