"""tests/test_helm_panel.py — the Helm panel: the game's controls and EDLD's
automation as buttons, in EDCARS, along the foot of both Dashboards, and on
EDAM.
"""
from __future__ import annotations

import asyncio
import os
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core import helm as H  # noqa: E402
from core.state import MonitorState  # noqa: E402


# ── The model ─────────────────────────────────────────────────────────────────

SHIP_GROUPS = ["ship", "throttle", "targeting", "orders", "panels", "combat", "power"]


def test_every_control_is_in_a_known_group_once():
    groups = [g for g, _ in H.GROUPS]
    ids = [c.id for c in H.CONTROLS]
    assert len(ids) == len(set(ids))
    assert all(c.group in groups for c in H.CONTROLS)
    contexts = {c for c, _ in H.CONTEXTS}
    assert all(c.contexts and set(c.contexts) <= contexts for c in H.CONTROLS)
    # Each context's groups, in drawing order.
    def groups_of(ctx):
        return [g for g in groups if any(c.group == g and ctx in c.contexts
                                         for c in H.CONTROLS)]
    assert set(groups_of(H.SHIP)) == set(SHIP_GROUPS)
    assert set(groups_of(H.SRV)) == {"vehicle", "targeting", "combat", "power", "panels"}
    assert set(groups_of(H.FOOT)) == {"suit", "tools", "weapons", "grenades", "panels"}
    # Every context's groups are in its lines, and the lines name no other.
    for ctx, _l in H.CONTEXTS:
        lined = [g for row in H.ROWS[ctx] for g in row]
        assert sorted(lined) == sorted(groups_of(ctx))
        assert H.group_order(ctx)[:len(lined)] == lined
    # The automata are sequences; everything else is one binding.
    assert [c.id for c in H.CONTROLS if c.sequence] == [H.HONK, H.NEXT_STOP]


def test_what_a_device_could_press_before_it_still_can():
    """The old control rail's ids are kept, so a device's buttons mean what
    they did."""
    from core.automation import CONTROLS
    for cid in ("gear", "scoop", "lights", "nightvision", "hardpoints", "silent",
                "heatsink", "chaff", "shieldcell", "fa", "boost", "supercruise",
                "jump", "nextroute", "pips-reset", "pips-sys", "pips-eng",
                "pips-wep", "galmap", "sysmap", "fss", "hudmode"):
        assert cid in CONTROLS, cid
    assert H.HONK not in CONTROLS and H.NEXT_STOP not in CONTROLS


def test_the_view_keeps_the_order_and_says_why():
    v = H.build_view(True, lambda c: c.id != "nightvision",
                     lambda c: "Night Vision is not bound", status="Pressed Jump.")
    assert [g.id for g in v.groups] == SHIP_GROUPS
    assert v.where == "Ship" and H.status_line(v) == "Ship · Pressed Jump."
    ship = next(g for g in v.groups if g.id == "ship")
    nv = next(b for b in ship.buttons if b.id == "nightvision")
    assert not nv.ready and nv.tip == "Night Vision is not bound"
    assert all(b.ready for g in v.groups for b in g.buttons if b.id != "nightvision")
    off = H.build_view(False, lambda c: True, lambda c: "", "Automation is off.")
    assert not any(b.ready for g in off.groups for b in g.buttons)


def test_the_ship_and_its_throttle_share_a_line_then_targeting_and_the_orders():
    groups = [("ship", 7), ("throttle", 5), ("targeting", 9), ("orders", 7), ("panels", 8)]
    wide = H.plan(groups, H.SHIP, 1200, 104, 4, 16)
    assert [[g for g, _c in line] for line in wide] == [
        ["ship", "throttle"], ["targeting", "orders"], ["panels"]]
    # The orders read in pairs, whatever the width.
    assert all(c == 2 for line in wide for g, c in line if g == "orders")
    # A phone, upright: still two to a line, the columns shared.
    narrow = H.plan(groups, H.SHIP, 360, 84, 4, 10)
    assert [[g for g, _c in line] for line in narrow][:2] == [
        ["ship", "throttle"], ["targeting", "orders"]]


def test_a_line_too_narrow_for_two_groups_stacks_them():
    lines = H.plan([("ship", 16), ("throttle", 6)], H.SHIP, 200, 90, 4, 10)
    assert lines == [[("ship", 2)], [("throttle", 2)]]


def test_columns_go_where_they_save_rows_and_no_row_is_left_with_one():
    lines = H.plan([("ship", 7), ("throttle", 6)], H.SHIP, 600, 84, 4, 10)
    (ship, s_cols), (thr, t_cols) = lines[0]
    assert -(-7 // s_cols) <= 2 and -(-6 // t_cols) <= 3
    assert H.plan([("panels", 8)], H.SHIP, 2000, 84, 4, 10) == [[("panels", 8)]]
    # Seven buttons over six columns would leave one alone: four and three.
    assert H.plan([("panels", 7)], H.SHIP, 540, 84, 4, 10) == [[("panels", 4)]]


def test_the_panel_setting():
    assert H.panel_wanted({}) is True
    assert H.panel_wanted({"HelmPanel": False}) is False
    assert H.panel_wanted({"HelmPanel": "false"}) is False


# ── The automation component ──────────────────────────────────────────────────

def _auto(cfg, bound=("LandingGearToggle", "PrimaryFire", "Supercruise"), pad_all=False):
    """``pad_all``: every other Helm binding given a controller button, so
    the whole panel is drawn, those grayed."""
    from components.automation import AutomationPlugin
    from core.binds import Binding, Bindings, Slot
    state = MonitorState()
    state.in_preload = False
    queued = []
    core = SimpleNamespace(state=state, journal_dir=Path("/nonexistent"), _plugins={},
                           load_setting=lambda s, d, warn=False: dict(cfg),
                           plugin_call=lambda *a, **k: None,
                           gui_queue=SimpleNamespace(put=queued.append),
                           notify_levels={}, emitter=SimpleNamespace(emit=lambda **k: None))
    p = AutomationPlugin.__new__(AutomationPlugin)
    p.core = core
    p.bindings = Bindings()
    p.bindings._map = {b: Binding("Key_L") for b in bound}
    p.bindings._map["ToggleCargoScoop"] = None
    p.bindings._slots = {"ToggleCargoScoop": (Slot("28DE11FF", "GamePad_DPadUp"),)}
    if pad_all:
        for c in H.CONTROLS:
            if c.binding and c.binding not in bound:
                p.bindings._map.setdefault(c.binding, None)
                p.bindings._slots.setdefault(c.binding, (Slot("28DE11FF", "GamePad_FaceUp"),))
    p.bindings._path = Path("/x")
    p._auto, p._honked_here, p._arrival_seq = None, False, 0
    p._binds_loaded_at = time.monotonic() + 1e9
    p.last_result, p._pressing = "", False
    return p, queued


def test_the_view_while_automation_is_off():
    p, _ = _auto({})
    v = p.helm_view()
    assert not v.enabled and "Options → Automation" in v.note
    assert not any(b.ready for g in v.groups for b in g.buttons)


def test_the_view_greys_what_cannot_be_pressed():
    p, _ = _auto({"Enabled": True, "AutoHonk": True})
    v = p.helm_view()
    ready = {b.id: b for g in v.groups for b in g.buttons}
    assert ready["gear"].ready and ready["supercruise"].ready and ready["honk"].ready
    assert not ready["scoop"].ready and "controller" in ready["scoop"].tip
    assert not ready["nextstop"].ready           # the galaxy-map script's keys
    # Bound to nothing in the game: not used, so not drawn.
    assert "lights" not in ready and "chaff" not in ready
    assert v.status == "On its own: auto honk."


def test_a_device_is_sent_only_what_it_may_press():
    p, _ = _auto({"Enabled": True})
    assert p.controls() == []
    assert "Allow paired devices" in p.controls_note()
    p, _ = _auto({"Enabled": True, "AllowControl": True})
    assert [c["id"] for c in p.controls()] == ["honk", "supercruise", "gear"]
    assert p.controls_note() == ""
    assert _auto({})[0].controls_note().startswith("Automation is off")


def test_a_press_from_edlds_window_brings_the_game_forward_first(monkeypatch):
    p, _ = _auto({"Enabled": True})
    order = []
    monkeypatch.setattr("core.keys.focus_game", lambda: (order.append("focus"), (True, ""))[1])
    eng = SimpleNamespace(press=lambda cid: (order.append(cid), (True, ""))[1])
    p._engine = lambda: eng
    assert p.press_control("gear", here=True) == (True, "")
    assert order == ["focus", "gear"]
    # A device's press does not: the game is meant to be in front already,
    # and it is not EDLD's place to take the focus from whatever is.
    order.clear()
    assert p.press_control("gear") == (False, "not available")      # not allowed
    p, _ = _auto({"Enabled": True, "AllowControl": True})
    p._engine = lambda: eng
    assert p.press_control("gear") == (True, "") and order == ["gear"]


def test_nothing_is_pressed_when_the_game_cannot_be_brought_forward(monkeypatch):
    p, _ = _auto({"Enabled": True})
    pressed = []
    monkeypatch.setattr("core.keys.focus_game", lambda: (False, "the game's window was not found"))
    p._engine = lambda: SimpleNamespace(press=lambda cid: pressed.append(cid))
    assert p.press_control("gear", here=True) == (False, "the game's window was not found")
    assert pressed == []


def test_next_stop_needs_a_route_edld_plotted(monkeypatch):
    p, _ = _auto({"Enabled": True}, bound=("GalaxyMapOpen", "UI_Up", "UI_Select", "UI_Right"))
    monkeypatch.setattr("core.keys.focus_game", lambda: (True, ""))
    p.core._plugins["navigation"] = SimpleNamespace(active_route=lambda: ([], ""))
    ok, why = p.press_control("nextstop", here=True)
    assert not ok and "no route" in why
    plotted = []
    p.core._plugins["navigation"] = SimpleNamespace(
        active_route=lambda: ([{"StarSystem": "Sol"}], "edld"),
        next_system=lambda: ("Jackson's Lighthouse", ""))
    p._plot_to = lambda system: (plotted.append(system), (True, f"plotted to {system}"))[1]
    assert p.press_control("nextstop", here=True) == (True, "plotted to Jackson's Lighthouse")


def test_press_here_reports_on_the_status_line(monkeypatch):
    p, queued = _auto({"Enabled": True})
    import components.automation as AM
    monkeypatch.setattr(AM.threading, "Thread",
                        lambda target, **k: SimpleNamespace(start=target))
    p.press_control = lambda cid, here=False: (True, "")
    p.press_here("gear")
    assert p.last_result == "Pressed Landing gear." and not p._pressing
    p.press_control = lambda cid, here=False: (True, "honked")
    p.press_here("honk")
    assert p.last_result == "Honked."
    p.press_control = lambda cid, here=False: (False, "the ship is in danger")
    p.press_here("jump")
    assert p.last_result == "Jump not pressed: the ship is in danger"
    assert queued.count(("helm_update", None)) == 6        # pressing, then done


def test_focus_game_never_guesses(monkeypatch):
    import core.keys as K
    monkeypatch.setattr(K, "_active_title", lambda: None)
    ok, why = K.focus_game()
    assert not ok and "EDAM can" in why
    monkeypatch.setattr(K, "_active_title", lambda: "Elite - Dangerous (CLIENT)")
    assert K.focus_game() == (True, "")


def test_the_server_says_why_a_device_has_nothing():
    from core.server.protocol import SnapshotBuilder
    p, _ = _auto({"Enabled": True})
    core = SimpleNamespace(state=MonitorState(), cfg=SimpleNamespace(ui_cfg={}),
                           _plugins={"automation": p}, plugin_call=lambda *a, **k: None,
                           ui_mode="edcars")
    h = SnapshotBuilder(core).header()
    assert h["controls"] == [] and "Allow paired devices" in h["helm"]["note"]
    sec = next(s for s in h["edcars"]["sections"] if s["id"] == h["helm"]["section"])
    assert sec["label"] == "Helm"


# ── The desktop window ────────────────────────────────────────────────────────

def _qt():
    pytest.importorskip("PySide6")
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def _host(p, ui=None):
    return SimpleNamespace(state=MonitorState(), _plugins={"automation": p},
                           cfg=SimpleNamespace(ui_cfg=ui or {}))


def test_the_dashboard_strip_shows_only_while_automation_is_on():
    app = _qt()
    from PySide6.QtWidgets import QVBoxLayout, QWidget
    from gui.blocks.helm import HelmBlock
    p, _ = _auto({}, pad_all=True)
    win = QWidget()
    lay = QVBoxLayout(win)
    block = HelmBlock(_host(p), compact=True)
    lay.addWidget(block)
    win.resize(1600, 200)
    win.show()
    block.refresh_data()
    app.processEvents()
    assert not block.isVisible()
    p.settings = lambda: {"Enabled": True}
    block.refresh_data()
    app.processEvents()
    ship = [c for c in H.CONTROLS if H.SHIP in c.contexts]
    assert block.isVisible() and len(block._buttons) == len(ship)
    assert block._buttons["gear"].isEnabled() and not block._buttons["scoop"].isEnabled()
    assert block._status.text().startswith("Ship")
    block.core.cfg.ui_cfg["HelmPanel"] = False
    block.refresh_data()
    assert not block.isVisible()
    win.close()


def test_a_narrow_strip_stacks_and_edcars_packs_at_the_top():
    app = _qt()
    from gui.blocks.helm import HelmBlock
    p, _ = _auto({"Enabled": True}, pad_all=True)
    strip = HelmBlock(_host(p), compact=True)
    strip.resize(380, 300)
    strip.show()
    strip.refresh_data()
    app.processEvents()
    assert any(len(line) == 1 and line[0][0] == "targeting" for line in strip._layout)
    big = HelmBlock(_host(p), compact=False)
    big.resize(1400, 800)
    big.show()
    big.refresh_data()
    app.processEvents()
    assert [[g for g, _c in line] for line in big._layout][:2] == [
        ["ship", "throttle"], ["targeting", "orders"]]
    # Buttons keep their height, whatever room the section has.
    assert big._buttons["gear"].height() == HelmBlock.LARGE[1]
    strip.close()
    big.close()


def test_a_click_presses_from_edlds_window():
    app = _qt()
    from gui.blocks.helm import HelmBlock
    p, _ = _auto({"Enabled": True})
    clicked = []
    p.press_here = clicked.append
    block = HelmBlock(_host(p), compact=False)
    block.refresh_data()
    block._buttons["gear"].click()
    app.processEvents()
    assert clicked == ["gear"]


# ── The terminal ──────────────────────────────────────────────────────────────

def test_the_terminal_shares_a_line_out_in_whole_cells():
    from tui.blocks.helm import GROUP_GAP, spans
    line = [("ship", 6), ("throttle", 2)]
    cells = spans(196, line, 16)
    assert sum(cells) == 196 and cells[0] > cells[1]
    assert cells[0] >= 6 * 16 + 5 + GROUP_GAP and cells[1] >= 2 * 16 + 1


def test_the_terminal_strip_draws_and_presses():
    pytest.importorskip("textual")
    from textual.app import App
    from tui.blocks.helm import HelmBlock
    from tui.theme import build_css
    p, _ = _auto({"Enabled": True}, pad_all=True)
    pressed = []
    p.press_here = pressed.append
    host = _host(p)
    host.gui_queue = None

    class One(App):
        CSS = build_css("default")

        def compose(self):
            yield HelmBlock(host, id="block-helm")

    async def run():
        app = One()
        async with app.run_test(size=(200, 40)) as pilot:
            block = app.query_one(HelmBlock)
            block.refresh_data()
            await pilot.pause(0.2)
            lines = ["".join(seg.text for seg in s)
                     for s in app.screen._compositor.render_strips()]
            text = "\n".join(lines)
            for label in ("Honk", "Next stop", "Next system", "Landing gear",
                          "Silent running", "Reset pips", "HUD mode"):
                assert label in text, label
            await pilot.click("#helm-gear")
            await pilot.pause()
            assert block.display
        return pressed

    assert asyncio.run(run()) == ["gear"]


def test_both_dashboards_place_it_and_refresh_it():
    tui = (ROOT / "tui" / "app.py").read_text(encoding="utf-8")
    gui = (ROOT / "gui" / "app.py").read_text(encoding="utf-8")
    for src in (tui, gui):
        assert '"helm_update":        ["block-helm"]' in src
        assert '"automation":    "block-helm"' in src
    assert 'HelmBlock(self._core, id=BLOCK_DOM_ID["helm"])' in tui
    assert "HelmBlock(self._core, theme=self._theme, compact=True)" in gui
