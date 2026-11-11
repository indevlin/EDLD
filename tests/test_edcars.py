"""
tests/test_edcars.py — the EDCARS style, in core, on the wire and in the
desktop window. The Helm panel it has a section for is
tests/test_helm_panel.py.
"""
from __future__ import annotations

import os
import queue
import re
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core import edcars as H  # noqa: E402
from core.layout_model import BLOCK_DISPLAY  # noqa: E402


# ── The name ──────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("name, home", [("EDCARS", "edcars.py"), ("Helm", "helm.py")])
def test_each_name_is_written_once(name, home):
    """Renaming the style, or the panel, must be a one-line change. No other
    source file may spell the name; they take it from core.edcars or
    core.helm."""
    hits = []
    for path in list(ROOT.glob("core/**/*.py")) + list(ROOT.glob("gui/**/*.py")) \
            + list(ROOT.glob("tui/**/*.py")) + list(ROOT.glob("components/*.py")):
        if path.name == home and path.parent.name == "core":
            continue
        text = path.read_text(encoding="utf-8")
        if re.search(rf'["\']{name}["\']', text):
            hits.append(str(path.relative_to(ROOT)))
    assert not hits, f"{name} is spelled in {hits}; use core/{home}"


def test_the_stored_value_is_not_the_name():
    assert H.EDCARS_ID == "edcars" and H.DASHBOARD_ID == "dashboard"
    assert dict(H.STYLES)[H.EDCARS_ID] == H.EDCARS_NAME == "EDCARS"


def test_style_follows_the_interface_and_alert_mode_falls_back():
    """The desktop window's layout is part of which interface was launched
    (core/modes.py): --edcars, the default, draws EDCARS; --dashg / --gui and
    both terminal interfaces draw the Dashboard."""
    assert H.style_for_mode("edcars") == "edcars"
    assert H.style_for_mode("EDCARS") == "edcars"
    for mode in ("gui", "textual", "terminal", "headless", "", None):
        assert H.style_for_mode(mode) == "dashboard"
    assert H.alert_mode_of({}) == "pulse"
    assert H.alert_mode_of({"EdcarsAlerts": "switch"}) == "switch"
    assert H.alert_mode_of({"EdcarsAlerts": "loud"}) == "pulse"


# ── Sections ──────────────────────────────────────────────────────────────────

def test_every_window_has_a_place():
    placed = {(p.window, p.part) for s in H.SECTIONS for p in s.parts}
    windows = {w for w, _ in placed}
    assert set(BLOCK_DISPLAY) <= windows, set(BLOCK_DISPLAY) - windows
    assert ("helm", "") in placed                       # the Helm panel
    # Split windows are split completely, and nothing is placed twice.
    assert ("commander", "identity") in placed and ("commander", "fleet") in placed
    assert ("status", "crew") in placed and ("alerts", "") in placed
    flat = [(p.window, p.part) for s in H.SECTIONS for p in s.parts]
    assert len(flat) == len(set(flat))


def test_the_agreed_sections_in_order():
    assert [s.id for s in H.SECTIONS] == [
        "alerts", "command", "helm", "objectives", "exploration", "mining", "fleet",
        "engineering", "career"]
    assert H.DEFAULT_SECTION == "command"
    assert H.section("helm").label == "Helm"
    command = H.section("command")
    assert {p.window for p in command.parts} == {"commander", "ship_info", "status"}
    assert {p.window for p in H.section("exploration").parts} == {"exploration", "navigation"}
    assert [p.window for p in H.section("career").parts] == ["career"]


def test_no_section_holds_more_than_three_windows():
    for s in H.SECTIONS:
        assert 1 <= len(s.parts) <= 3, s.id


@pytest.mark.parametrize("pid, group, want", [
    ("commander.info", "commander", "command"),
    ("commander.ships", "commander", "fleet"),
    ("commander.stored-modules", "commander", "fleet"),
    ("commander.carrier", "commander", "fleet"),
    ("commander.squadron-carrier", "commander", "fleet"),
    ("cargo", "vessel", "command"),
    ("status", "status", None),               # the Dashboard style's; EDCARS omits it
    ("missions.missions", "missions", "objectives"),
    ("session.session", "session", "career"),
    ("alerts", "alerts", "alerts"),
    ("navigation.route", "navigation", "exploration"),
    ("something.new", "something", None),
])
def test_wire_panels_find_their_section(pid, group, want):
    assert H.section_for_panel(pid, group) == want


#: Every group EDLD sends that EDCARS draws: core/windows/wire.py's, and the
#: protocol's own. "status" is the Dashboard style's (H.EDCARS_OMITS).
WIRE_GROUPS = {"commander", "ship", "crew", "exploration", "navigation", "missions",
               "colonisation", "vessel", "session", "career", "alerts", "engineering"}


def test_every_group_edld_sends_has_a_section():
    groups = WIRE_GROUPS
    for g in groups:
        assert H.section_for_panel(f"{g}.x", g), g


@pytest.mark.parametrize("pid,group,want", [
    ("commander.info", "commander", "commander.identity"),
    ("commander.wallet", "commander", "commander.identity"),
    ("crew.crew", "crew", "status.crew"),
    ("cargo", "vessel", "ship_info"),
    ("ship", "vessel", "ship_info"),
    ("ship.modules", "ship", "ship_info"),
    ("engineering.fitting", "engineering", "engineering"),
    ("engineering.materials", "engineering", "engineering"),
    ("exploration.system", "exploration", "exploration"),
    ("navigation.route", "navigation", "navigation"),
])
def test_wire_panels_find_their_frame(pid, group, want):
    """EDAM frames the same windows the desktop does: every panel lands in the
    frame showing that window, not in a fallback."""
    sec = H.section(H.section_for_panel(pid, group))
    assert H.part_for_panel(sec, pid, group).id == want


def test_every_group_lands_in_a_frame_that_names_it():
    groups = WIRE_GROUPS
    for g in groups:
        sec = H.section(H.section_for_panel(f"{g}.x", g))
        if len(sec.parts) > 1:
            assert g in H.part_for_panel(sec, f"{g}.x", g).groups, g


def test_the_wire_carries_the_desktop_layout():
    wire = {s["id"]: s for s in H.wire_sections()}
    for sec in H.SECTIONS:
        w = wire[sec.id]
        assert w["columns"] == H.section_columns(sec)
        assert len(w["columns"]) == max(p.column for p in sec.parts) + 1
        assert [(p["id"], p["title"], p["column"], p["weight"]) for p in w["parts"]] == \
            [(p.id, p.title or p.window, p.column, p.weight) for p in sec.parts]
    assert wire["command"]["columns"] == [45, 55]
    # Tabs where the desktop window has them, and nowhere else.
    tabs = {p["id"]: p["tabs"] for s in wire.values() for p in s["parts"]}
    assert not tabs["status.crew"] and not tabs["exploration"] and not tabs["alerts"]
    assert tabs["commander.identity"] and tabs["ship_info"] and tabs["navigation"]
    assert [p["title"] for p in wire["command"]["parts"]] == ["Commander", "Crew / SLF", "Ship"]


# ── Header strip ──────────────────────────────────────────────────────────────

def _state(**kw):
    base = dict(pilot_name="Merrick Calbruin", pilot_squadron_name="Mining and Logistics Ltd",
                pilot_squadron_tag="mall", vessel_mode="ship", ship_name="Fossor",
                ship_ident="T11-FO", pilot_ship="Type-11 Prospector",
                cargo_items={"rhodplumsite": {"count": 66}}, cargo_capacity=1024,
                pilot_system="Col 285 Sector NK-R b20-0",
                pilot_body="Col 285 Sector NK-R b20-0 A 2",
                fuel_current=24.0, fuel_tank_size=32.0, ship_hull=100,
                ship_hull_exact=None, pilot_mode="Solo", assets_balance=1.28e9,
                srv_type="SRV Rhino", srv_cargo_count=5, srv_hull=40)
    base.update(kw)
    return SimpleNamespace(**base)


def _strip(**kw):
    return {f.key: f for f in H.strip(_state(**kw))}


def test_the_strip_in_the_ship():
    s = _strip()
    assert [k for k in s] == ["cmdr", "vessel", "cargo", "location",
                              "fuel", "hull", "mode"]
    assert s["vessel"].value == "Fossor (T11-FO) · Type-11 Prospector"
    assert s["cargo"].value == "66/1,024 t"
    assert s["location"].value == "Col 285 Sector NK-R b20-0 · A 2"
    assert (s["fuel"].value, s["fuel"].tone) == ("75%", "good")
    assert (s["hull"].value, s["hull"].tone) == ("100%", "good")


def test_the_squadron_follows_the_name_in_the_band():
    """It was a fact on the strip, and pushed fuel, hull and mode off the
    end of a tablet's screen."""
    assert H.title_text(_state()) == "CMDR MERRICK CALBRUIN // MINING AND LOGISTICS LTD [MALL]"
    assert H.title_text(_state(pilot_squadron_name="")) == "CMDR MERRICK CALBRUIN"
    assert H.title_text(_state(pilot_squadron_tag="")) == "CMDR MERRICK CALBRUIN // MINING AND LOGISTICS LTD"
    assert H.title_text(_state(pilot_name="")) == "COMMANDER"
    assert H.title_text(None) == "COMMANDER"
    assert "squadron" not in _strip()


def test_the_title_has_shorter_forms_for_a_narrow_band():
    """On a phone or a narrow window the whole title did not fit."""
    assert H.title_forms(_state()) == [
        "CMDR MERRICK CALBRUIN // MINING AND LOGISTICS LTD [MALL]",
        "CMDR MERRICK CALBRUIN [MALL]", "CMDR MERRICK CALBRUIN"]
    assert H.title_forms(_state(pilot_squadron_tag="")) == [
        "CMDR MERRICK CALBRUIN // MINING AND LOGISTICS LTD", "CMDR MERRICK CALBRUIN"]
    assert H.title_forms(_state(pilot_squadron_name="")) == ["CMDR MERRICK CALBRUIN"]
    assert H.title_forms(None) == ["COMMANDER"]


def test_a_narrow_window_shortens_the_title_and_the_long_facts():
    """The strip held the window as wide as all its facts, and the title
    ended in "…" with the squadron's tag lost first."""
    pytest.importorskip("PySide6")
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication([])
    from PySide6.QtWidgets import QWidget, QVBoxLayout
    from gui.edcars import EdcarsHeader, Ink, _qss
    ink = Ink("default")
    host = QWidget()
    host.setStyleSheet(_qss(ink))
    host.setObjectName("edcars")
    lay = QVBoxLayout(host)
    lay.setContentsMargins(0, 0, 0, 0)
    head = EdcarsHeader(ink)
    lay.addWidget(head)
    st = _state(pilot_body="Col 285 Sector NK-R b20-0 A 2 Very Long Settlement Name")
    head.set_strip(H.strip(st))
    head.set_title(H.title_forms(st))
    head.set_clock("08:44")
    wide = head.sizeHint().width()
    host.resize(2400, 100)
    host.show()
    QApplication.processEvents()
    assert head.cmdr.shown_text() == H.title_forms(st)[0]
    # As narrow as a tablet held upright: the window can be, the short facts
    # are whole, and the title has lost the squadron's name but kept its tag.
    assert head.minimumSizeHint().width() < 900 < wide
    host.resize(900, 100)
    QApplication.processEvents()
    for key in ("cargo", "fuel", "hull", "mode"):
        v = head._fields[key][1]
        assert v.width() >= v.sizeHint().width(), key
    shown = head.cmdr.shown_text()
    assert shown in ("CMDR MERRICK CALBRUIN [MALL]", "CMDR MERRICK CALBRUIN") or shown.endswith("…")
    assert shown != H.title_forms(st)[0]
    host.close()


def test_no_credits_on_the_strip():
    assert all("credit" not in f.label.lower() and "cr" not in f.value.split()
               for f in H.strip(_state()))


def test_the_strip_in_an_srv_is_the_srvs():
    s = _strip(vessel_mode="srv")
    assert s["vessel"].value == "SRV Rhino"
    assert s["cargo"].value == "5/72 t"
    assert (s["hull"].value, s["hull"].tone) == ("40%", "warn")
    assert "fuel" not in s, "the ship's tank is not what is running low in an SRV"


def test_on_foot_has_no_cargo_hull_or_fuel():
    s = _strip(vessel_mode="on_foot", suit_name="Maverick")
    assert s["vessel"].value == "Maverick"
    assert not {"cargo", "hull", "fuel"} & set(s)


def test_tones_follow_the_dashboards_thresholds():
    assert _strip(fuel_current=2.0)["fuel"].tone == "crit"
    assert _strip(fuel_current=5.0)["fuel"].tone == "warn"
    assert _strip(ship_hull=20)["hull"].tone == "crit"


def test_an_empty_state_has_an_empty_strip():
    assert H.strip(SimpleNamespace()) == []
    assert H.strip(None) == []


def test_the_clock_is_local_time():
    from datetime import datetime
    assert H.clock_text(datetime(2026, 10, 18, 3, 7)) == "03:07"


# ── Alerts ────────────────────────────────────────────────────────────────────

def _alerts():
    import components.alerts as A
    p = A.AlertsPlugin.__new__(A.AlertsPlugin) if hasattr(A, "AlertsPlugin") else None
    if p is None:
        cls = next(getattr(A, n) for n in dir(A) if n.endswith("Plugin")
                   and isinstance(getattr(A, n), type) and hasattr(getattr(A, n), "_push"))
        p = cls.__new__(cls)
    from collections import deque
    p.alert_queue = deque(maxlen=5)
    p.faults = []
    p.core = SimpleNamespace(state=SimpleNamespace(in_preload=False), gui_queue=None,
                             notify_levels={}, emitter=SimpleNamespace(emit=lambda **k: None))
    return p


def test_which_alerts_are_urgent():
    p = _alerts()
    p._push("⚠️", "Ship hull: 20%")
    p._push("🛡️", "Ship shields back up", urgent=False)
    p.push_external("🛸", "Carrier jump in 14m", sigil="*  CARR")
    p.push_external("🚨", "Under attack", sigil="!! ATCK")
    p.push_fault("⚠", "Component failed")
    urgent = {a["text"]: H.is_urgent(a) for a in p.get_alerts()}
    assert urgent == {"Ship hull: 20%": True, "Ship shields back up": False,
                      "Carrier jump in 14m": False, "Under attack": True,
                      "Component failed": False}


# ── The wire ──────────────────────────────────────────────────────────────────

def _builder(ui_cfg=None, state=None, ui_mode="edcars"):
    from core.server.protocol import SnapshotBuilder
    core = SimpleNamespace(state=state or _state(), cfg=SimpleNamespace(ui_cfg=ui_cfg or {}),
                           _plugins={}, plugin_call=lambda *a, **k: None,
                           ui_mode=ui_mode)
    return SnapshotBuilder(core)


def test_the_header_carries_style_and_edcars():
    b = _builder({"EdcarsAlerts": "switch"})
    h = b.header()
    assert h["style"] == {"id": "edcars", "name": H.EDCARS_NAME}
    e = h["edcars"]
    assert e["name"] == H.EDCARS_NAME
    assert [s["id"] for s in e["sections"]] == [s.id for s in H.SECTIONS]
    assert e["alerts"] == "switch"
    strip = {f["id"]: f for f in e["strip"]}
    assert strip["cargo"]["value"] == "66/1,024 t" and strip["hull"]["tone"] == "good"
    assert e["title"] == "CMDR MERRICK CALBRUIN // MINING AND LOGISTICS LTD [MALL]"
    assert e["titles"] == ["CMDR MERRICK CALBRUIN // MINING AND LOGISTICS LTD [MALL]",
                           "CMDR MERRICK CALBRUIN [MALL]", "CMDR MERRICK CALBRUIN"]
    assert strip["vessel"]["shrinks"] and strip["location"]["shrinks"]
    assert "shrinks" not in strip["fuel"] and "shrinks" not in strip["hull"]
    # The Helm panel's section, framed as the desktop frames it.
    helm = next(s for s in e["sections"] if s["id"] == "helm")
    assert helm["label"] == "Helm" and [p["id"] for p in helm["parts"]] == ["helm"]


def test_edam_is_told_the_dashboard_when_edld_is_not_edcars():
    for mode in ("gui", "textual", "terminal"):
        assert _builder(ui_mode=mode).header()["style"]["id"] == "dashboard"


def test_the_header_location_is_the_body_not_null():
    """It read a field nothing set, so a device was always sent null."""
    assert _builder().header()["location"] == "A 2"
    assert _builder(state=_state(pilot_body=None)).header()["location"] is None


def test_alert_rows_say_which_are_urgent():
    b = _builder()
    p = _alerts()
    p._push("⚠️", "Ship hull: 20%")
    p.push_external("🛸", "Carrier jump", sigil="*  CARR")
    b.core._plugins = {"alerts": p}
    rows = b._alerts_panel()[0]["rows"]
    flags = {r["value"]: r.get("urgent", False) for r in rows}
    assert flags == {"⚠️ Ship hull: 20%": True, "🛸 Carrier jump": False}


# ── The desktop window ────────────────────────────────────────────────────────

class _State:
    in_preload = False

    def __getattr__(self, name):
        if name.startswith("_"):
            raise AttributeError(name)
        return None


class _AlertsStub:
    def __init__(self):
        self.items = []

    def get_alerts(self):
        return list(self.items)

    def clear_alerts(self):
        self.items.clear()

    def opacity_for(self, _a):
        return 1.0


def _window(style="edcars", alerts_mode="pulse", plugins=None):
    pytest.importorskip("PySide6")
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication([])
    stub = _AlertsStub()

    class Cfg:
        config: dict = {}
        ui_cfg = {"EdcarsAlerts": alerts_mode}

        def save(self):
            pass

    class Core:
        ui_mode = "edcars" if style == "edcars" else "gui"
        state = _State()
        cfg = Cfg()
        gui_queue = queue.Queue()
        journal_dir = "/tmp"
        _plugins: dict = {"alerts": stub, **(plugins or {})}
        session_providers: list = []
        app_settings: dict = {}

        def plugin_call(self, name, method, *a, **k):
            p = self._plugins.get(name)
            fn = getattr(p, method, None) if p is not None else None
            return fn(*a, **k) if fn else None

        def register_session_provider(self, provider):
            pass

    from gui.app import EdldWindow
    w = EdldWindow(Core(), "EDLD", "test", "owner", "owner/repo")
    w.resize(1600, 950)
    w.show()
    QApplication.processEvents()
    return w, stub


def test_the_dashboard_is_unchanged_by_default():
    w, _ = _window(style="dashboard")
    assert w._edcars is None


def test_edcars_builds_every_section_and_every_block():
    from gui.app import BLOCK_ID
    w, _ = _window()
    assert w._edcars is not None
    assert set(BLOCK_ID.values()) <= set(w._blocks), set(BLOCK_ID.values()) - set(w._blocks)
    assert list(w._edcars._pages) == [s.id for s in H.SECTIONS]
    for s in H.SECTIONS:
        w._edcars.show_section(s.id)
        assert w._edcars.current_section() == s.id
    w._refresh_all()                          # every block refreshes without raising


def test_the_fleet_tabs_live_in_the_fleet_section():
    from PySide6.QtWidgets import QTabWidget
    w, _ = _window()
    commander = w._blocks["block-commander"]
    assert commander.fleet_tabs is not commander._tabs
    fleet_page = w._edcars.stack.widget(w._edcars._pages["fleet"])
    assert commander.fleet_tabs in fleet_page.findChildren(QTabWidget)
    names = [commander._tabs.tabText(i) for i in range(commander._tabs.count())]
    assert names == ["Info", "Ranks", "Wallet"]


def test_an_urgent_alert_pulses_and_opening_alerts_acknowledges():
    w, stub = _window()
    shell = w._edcars
    stub.items.insert(0, {"emoji": "🛸", "text": "Carrier jump", "mono_time": 1.0,
                          "urgent": False})
    shell.note_alerts()
    assert shell._unacked is None, "status is not an alert"
    stub.items.insert(0, {"emoji": "⚠️", "text": "Ship hull: 20%", "mono_time": 2.0,
                          "urgent": True})
    shell.note_alerts()
    assert shell._unacked and shell._pulse.isActive()
    assert "Ship hull" in shell.header.alert.text()
    assert shell.current_section() == "command", "pulse mode does not switch"
    shell.note_alerts()                         # the same alert again is not new
    shell.show_section("alerts")
    assert shell._unacked is None and not shell._pulse.isActive()
    assert shell.header.alert.text() == ""


def test_switch_mode_opens_the_alerts_section():
    w, stub = _window(alerts_mode="switch")
    stub.items.insert(0, {"emoji": "⚠️", "text": "Fuel critical: 4%", "mono_time": 3.0,
                          "urgent": True})
    w._edcars.note_alerts()
    assert w._edcars.current_section() == "alerts"


def test_clearing_alerts_acknowledges():
    w, stub = _window()
    stub.items.insert(0, {"emoji": "⚠️", "text": "Ship hull: 20%", "mono_time": 2.0,
                          "urgent": True})
    w._edcars.note_alerts()
    w.action_clear_alerts()
    assert w._edcars._unacked is None


def test_section_shortcuts_exist():
    from PySide6.QtGui import QShortcut
    w, _ = _window()
    keys = {s.key().toString() for s in w._edcars.findChildren(QShortcut)}
    assert {f"Ctrl+{i}" for i in range(1, len(H.SECTIONS) + 1)} <= keys


# ── Options ───────────────────────────────────────────────────────────────────

def test_both_options_offer_interface_and_alert_mode():
    """The Style setting became the Interface: both Options offer the same
    choices, from core/modes.py, and changing it restarts nothing."""
    tui = (ROOT / "tui" / "preferences.py").read_text(encoding="utf-8")
    gui = (ROOT / "gui" / "preferences.py").read_text(encoding="utf-8")
    for src in (tui, gui):
        assert "options_choices()" in src and "ALERT_MODES" in src
        assert '"UI":       {"Theme"},' in src
        assert "style_choices" not in src and '"Style"' not in src


def test_the_config_defaults():
    from core.config import CFG_DEFAULTS_UI
    assert "Style" not in CFG_DEFAULTS_UI and "Mode" not in CFG_DEFAULTS_UI
    assert CFG_DEFAULTS_UI["Interface"] == "edcars"
    assert CFG_DEFAULTS_UI["EdcarsAlerts"] == "pulse"
    assert CFG_DEFAULTS_UI["HelmPanel"] is True


# ── EDAM draws what the desktop draws ─────────────────────────────────────────

#: Tabs only the desktop has.
DESKTOP_ONLY = {"Radio"}


class _NavStub:
    def navigation_tool_tabs(self):
        from core import plot_tools
        return plot_tools.tabs()

    def active_route(self):
        return [], ""

    def effective_current_system(self):
        return ""

    def _index_of(self, route, current):
        return -1


def test_every_edcars_tab_reaches_edam():
    """Each tabbed frame of each EDCARS section has, on a device, the same tabs
    in the same order — the panels EDLD sends for that frame, then the
    Navigation forms where the frame carries them — and a window with inner
    tabs (Engineering) sends them as pages. Only the radio is desktop-only."""
    from PySide6.QtWidgets import QTabWidget
    from core import tooltab
    from core.windows import wire
    w, _ = _window(plugins={"navigation": _NavStub()})
    core = w._core
    faults = []
    panels = sorted(wire.panels(core, lambda n, e: faults.append((n, e))),
                    key=lambda p: p["order"])
    assert not faults, faults
    tools = [t.title for t in tooltab.tabs(core)]
    assert tools[:3] == ["FSD", "Neutron", "Carrier"]
    for sec in H.SECTIONS:
        page = w._edcars.stack.widget(w._edcars._pages[sec.id])
        desktop = [[t.tabText(i) for i in range(t.count())]
                   for t in page.findChildren(QTabWidget)]
        desktop = [[x for x in d if x not in DESKTOP_ONLY] for d in desktop]
        device = []
        for part in sec.parts:
            mine = [p for p in panels
                    if p["id"] not in H.EDCARS_OMITS and p["id"] != part.header
                    and H.section_for_panel(p["id"], p["group"]) == sec.id
                    and H.part_for_panel(sec, p["id"], p["group"]) is part]
            if part.tabs:
                device.append([p["title"] for p in mine] + (tools if part.tools else []))
            device += [[pg["title"] for pg in p["pages"]] for p in mine if p.get("pages")]
        assert sorted(desktop) == sorted(device), (sec.id, desktop, device)


def test_edcars_caps_are_bold_without_kerning():
    """Euro Caps kerns L under O by 18 % of the em; drawn thickened for bold,
    the L ran into the O ("LOGISTICS", "EXPLORATION", "LOCATION")."""
    pytest.importorskip("PySide6")
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication([])
    from PySide6.QtGui import QFont
    from gui.edcars import EdcarsHeader, EdcarsRail, Ink, caps_font
    f = caps_font(19)
    assert f.bold() and not f.kerning()
    assert f.letterSpacingType() == QFont.PercentageSpacing and f.letterSpacing() > 100
    head = EdcarsHeader(Ink("default"))
    rail = EdcarsRail(Ink("default"), lambda _sid: None)
    for w in [head.cmdr, head.clock, *rail.pills.values()]:
        assert not w.font().kerning(), w.objectName()
