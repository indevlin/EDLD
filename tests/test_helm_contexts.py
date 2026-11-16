"""tests/test_helm_contexts.py — the Helm panel follows the commander: the
ship, a ship-launched fighter, an SRV, on foot."""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core import helm as H  # noqa: E402
from core.binds import ACTION_NAMES, parse_slots  # noqa: E402
from core.state import MonitorState  # noqa: E402
from tests.test_helm_panel import _auto, _host  # noqa: E402


def _state(mode="ship", slf=False, srv=""):
    s = MonitorState()
    s.vessel_mode, s.cmdr_in_slf, s.srv_type = mode, slf, srv
    return s


def test_where_the_commander_is():
    assert H.context_of(_state()) == H.SHIP
    assert H.context_of(_state(slf=True)) == H.FIGHTER
    assert H.context_of(_state("srv")) == H.SRV
    assert H.context_of(_state("on_foot")) == H.FOOT
    assert H.context_of(None) == H.SHIP


def test_every_helm_binding_has_the_controls_page_name():
    missing = [c.binding for c in H.CONTROLS if c.binding and c.binding not in ACTION_NAMES]
    assert missing == []


def test_the_bindings_named_are_the_games(tmp_path):
    """Each binding is one a real .binds file carries."""
    names = sorted({c.binding for c in H.CONTROLS if c.binding})
    xml = "".join(f'<{n}><Primary Device="Keyboard" Key="Key_A" />'
                  f'<Secondary Device="{{NoDevice}}" Key="" /></{n}>' for n in names)
    f = tmp_path / "Custom.4.2.binds"
    f.write_text(f'<?xml version="1.0"?><Root>{xml}</Root>', encoding="utf-8")
    assert set(parse_slots(f)) == set(names)
    for n in ("HumanoidToggleFlashlightButton", "HeadlightsBuggyButton", "OrderFollow",
              "HumanoidSwitchToCompAnalyser", "NightVisionToggle", "RecallDismissShip"):
        assert n in names


def _all_bound(cfg=None):
    every = tuple(c.binding for c in H.CONTROLS if c.binding)
    return _auto(cfg or {"Enabled": True, "AllowControl": True}, bound=every)[0]


def _ids(view):
    return {b.id for g in view.groups for b in g.buttons}


def test_on_foot_the_panel_is_the_suit_its_tools_and_weapons():
    p = _all_bound()
    p.core.state = _state("on_foot")
    v = p.helm_view()
    assert v.where == "On foot" and v.context == H.FOOT
    assert [g.id for g in v.groups] == ["suit", "tools", "weapons", "grenades", "views"]
    ids = _ids(v)
    assert {"foot-light", "foot-nightvision", "foot-energylink", "foot-analyser",
            "foot-toolmode", "foot-recall"} <= ids
    assert not ids & {"gear", "honk", "lights", "pips-sys"}


def test_in_an_srv_it_names_the_vehicle_and_gives_its_own_bindings():
    p = _all_bound()
    p.core.state = _state("srv", srv="SRV Nomad")
    v = p.helm_view()
    assert v.where == "SRV Nomad" and H.status_line(v) == ""
    ids = _ids(v)
    assert {"srv-lights", "srv-nightvision", "srv-assist", "srv-turret", "srv-recall",
            "srv-pips-sys", "srv-galmap"} <= ids
    assert not ids & {"lights", "pips-sys", "galmap", "honk"}
    p.core.state = _state("srv", srv="Scarab")
    assert p.helm_view().where == "SRV Scarab"


def test_in_a_fighter_its_orders_go_to_the_ship_and_the_ship_controls_are_gone():
    p = _all_bound()
    p.core.state = _state(slf=True)
    v = p.helm_view()
    labels = {g.id: g.label for g in v.groups}
    assert labels["orders"] == "Orders" and labels["ship"] == "Fighter"
    ids = _ids(v)
    assert {"ord-dock", "ord-follow", "boost", "lights", "pips-wep", "tgt-threat"} <= ids
    assert not ids & {"gear", "scoop", "supercruise", "jump", "honk", "heatsink"}


def test_in_the_ship_the_fighter_orders_and_targeting_are_there():
    v = _all_bound().helm_view()
    labels = {g.id: g.label for g in v.groups}
    assert labels["orders"] == "Fighter orders"
    assert {"ord-holdfire", "tgt-sub", "thr-75", "pnl-role", "fg-next"} <= _ids(v)


def test_a_device_is_sent_only_the_current_contexts_controls():
    p = _all_bound()
    ship = {c["id"] for c in p.controls()}
    p.core.state = _state("on_foot")
    foot = {c["id"] for c in p.controls()}
    assert "gear" in ship and "gear" not in foot and "foot-light" in foot
    assert all(H.in_context(H.BY_ID[c], H.FOOT) for c in foot)


def test_a_press_for_somewhere_else_is_refused(monkeypatch):
    p = _all_bound()
    p.core.state = _state("on_foot")
    pressed = []
    p._engine = lambda: type("E", (), {"press": lambda _s, cid: (pressed.append(cid), (True, ""))[1]})()
    ok, why = p.press_control("gear")
    assert not ok and why == "Landing gear is not available on foot" and pressed == []
    p.core.state = _state("srv", srv="SRV Nomad")
    ok, why = p.press_control("foot-light")
    assert not ok and why == "Flashlight is not available in the SRV Nomad"
    ok, _ = p.press_control("srv-lights")
    assert ok and pressed == ["srv-lights"]


def test_a_binding_left_empty_in_the_game_is_left_off():
    from core.binds import Slot
    p, _ = _auto({"Enabled": True}, bound=("LandingGearToggle",))
    p.bindings._slots["ShipSpotLightToggle"] = (Slot("28DE11FF", "GamePad_DPadRight",
                                                     (("28DE11FF", "GamePad_FaceRight"),)),)
    p.bindings._map["ShipSpotLightToggle"] = None
    v = p.helm_view()
    btn = {b.id: b for g in v.groups for b in g.buttons}
    assert btn["gear"].ready
    assert not btn["lights"].ready and "controller" in btn["lights"].tip
    assert "chaff" not in btn and "nightvision" not in btn
    # Bindings not found: everything shown, to say why.
    p.bindings._path = None
    assert "chaff" in _ids(p.helm_view())


def test_the_device_is_told_where_the_panel_is_for():
    from core.server.protocol import SnapshotBuilder as Builder
    p = _all_bound()
    p.core.state = _state("on_foot")
    core = _host(p)
    core.state = p.core.state
    b = Builder.__new__(Builder)
    b.core = core
    b._fault = lambda *a: None
    helm = b.helm()
    assert helm["context"] == H.FOOT and helm["where"] == "On foot"
    assert helm["rows"] == [["suit", "tools"], ["weapons", "grenades"], ["views"]]
    assert helm["columns"] == {"orders": 2} and helm["steps"] == {"orders": 2}
    assert helm["bars"] == ["power", "systems", "throttle"] and helm["pairs"] == []
    p.core.state = _state()
    core.state = p.core.state
    assert {"prev": "tgt-prev", "next": "tgt-next", "label": "Target"} in b.helm()["pairs"]
    assert all(x["prev"] != "srv-fg-prev" for x in b.helm()["pairs"])
    p.core.state = _state(slf=True)
    core.state = p.core.state
    labels = {g["id"]: g["label"] for g in b.helm()["groups"]}
    assert labels["orders"] == "Orders"


def test_the_binding_report_goes_context_by_context():
    p = _all_bound()
    p.bindings.load = lambda *a, **k: True
    report = p.binding_report()
    for where in ("Helm panel, ship:", "Helm panel, fighter:", "Helm panel, srv:",
                  "Helm panel, on foot:"):
        assert where in report


def test_the_terminal_panel_changes_with_the_context():
    pytest.importorskip("textual")
    from textual.app import App
    from tui.blocks.helm import HelmBlock
    from tui.theme import build_css
    p = _all_bound({"Enabled": True})
    host = _host(p)
    host.gui_queue = None

    class One(App):
        CSS = build_css("default")

        def compose(self):
            yield HelmBlock(host, id="block-helm")

    async def run():
        app = One()
        async with app.run_test(size=(200, 60)) as pilot:
            block = app.query_one(HelmBlock)
            block.refresh_data()
            await pilot.pause(0.2)
            assert app.query("#helm-gear")
            p.core.state = _state("on_foot")
            block.refresh_data()
            await pilot.pause(0.3)
            assert not app.query("#helm-gear") and app.query("#helm-foot-light")
            p.core.state = _state()
            block.refresh_data()
            await pilot.pause(0.3)
            assert app.query("#helm-gear") and not app.query("#helm-foot-light")
    asyncio.run(run())


def test_a_controllers_face_buttons_and_triggers_are_named_as_on_the_pad():
    from core.binds import Slot, key_text
    assert [key_text("28DE11FF", k) for k in ("GamePad_FaceUp", "GamePad_FaceRight",
                                              "Pos_GamePad_RTrigger", "Neg_GamePad_LTrigger")] \
        == ["Y", "B", "RT", "LT"]
    s = Slot("28DE11FF", "GamePad_DPadLeft", (("28DE11FF", "GamePad_FaceRight"),))
    assert s.text() == "controller B+D-pad left"


def test_fighter_orders_on_the_number_pad_are_pressable_from_the_ship(tmp_path):
    from core.binds import Bindings
    from core.keys import KEYS
    orders = {"OrderRequestDock": "Numpad_0", "OrderDefensiveBehaviour": "Numpad_1",
              "OrderAggressiveBehaviour": "Numpad_2", "OrderFocusTarget": "Numpad_3",
              "OrderHoldFire": "Numpad_4", "OrderHoldPosition": "Numpad_5",
              "OrderFollow": "Numpad_6"}
    xml = "".join(f'<{a}><Primary Device="Keyboard" Key="Key_{k}" />'
                  f'<Secondary Device="{{NoDevice}}" Key="" /></{a}>' for a, k in orders.items())
    (tmp_path / "Custom.4.2.binds").write_text(f'<?xml version="1.0"?><Root>{xml}</Root>',
                                              encoding="utf-8")
    (tmp_path / "StartPreset.4.start").write_text("Custom\nCustom\nCustom\nCustom\n",
                                                 encoding="utf-8")
    p, _ = _auto({"Enabled": True})
    p.bindings = Bindings()
    assert p.bindings.load(None, str(tmp_path))
    p._binds_loaded_at = 1e18
    p._engine = lambda: None
    for ctx_state in (_state(), _state(slf=True)):
        p.core.state = ctx_state
        btn = {b.id: b for g in p.helm_view().groups for b in g.buttons}
        for cid in ("ord-dock", "ord-defend", "ord-engage", "ord-attack", "ord-holdfire",
                    "ord-hold", "ord-follow"):
            assert btn[cid].ready, (cid, btn[cid].tip)
    for a, k in orders.items():
        assert p.bindings.get(a).key == f"Key_{k}" and f"Key_{k}" in KEYS


def test_one_press_needs_the_game_in_front_not_status_json(tmp_path):
    from core.automation import Automation
    from core.binds import Binding, Bindings
    pressed = []

    class KB:
        def available(self):
            return True, ""

        def press(self, key, modifiers=(), hold=0.06):
            pressed.append(key)
            return True

    b = Bindings()
    b._map = {"OpenCodexGoToDiscovery": Binding("Key_Slash")}
    eng = Automation(tmp_path, KB(), b, assume_focus=True)      # no Status.json at all
    ok, why = eng.press("codex")
    assert ok, why
    assert pressed == ["Key_Slash"]


def test_status_json_caught_mid_write_is_read_again(tmp_path, monkeypatch):
    from core import automation as A
    reads = iter(["", "{\"Flags\":", "{\"Flags\": 16}"])
    real = A.Path.read_text
    monkeypatch.setattr(A.Path, "read_text",
                        lambda self, *a, **k: next(reads) if self.name == "Status.json"
                        else real(self, *a, **k))
    assert A.read_status(tmp_path, gap=0) == {"Flags": 16}
