"""tests/test_overlay_hud.py — the overlay's two kinds of panel, and the HUD
panels: the massacre stack, the mining missions' ore, and the current
system's exploration and biology.
"""
from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
for p in (ROOT, ROOT / "tests"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from core import overlay_panels as op  # noqa: E402
from core.state import MonitorState  # noqa: E402
from tests.test_missions_board import TGT, _component, _stack_state  # noqa: E402


# ── Categories ────────────────────────────────────────────────────────────────

def test_a_panel_is_reporting_unless_its_component_says_hud():
    comp = SimpleNamespace(OVERLAY_CATEGORY={"a": "hud", "b": "nonsense"})
    assert op.category_of(comp, "a") == "hud"
    assert op.category_of(comp, "b") == "reporting"
    assert op.category_of(SimpleNamespace(), "c") == "reporting"
    assert [c for c, _l in op.CATEGORIES] == ["reporting", "hud"]


def test_options_lists_reporting_then_hud():
    from components.overlay import OverlayPlugin
    rep = SimpleNamespace(OVERLAY_PANELS=("income", "cargo"))
    hud = SimpleNamespace(OVERLAY_PANELS=("massacre",), OVERLAY_CATEGORY={"massacre": "hud"})
    p = OverlayPlugin.__new__(OverlayPlugin)
    p._core = SimpleNamespace()
    p._placements = []
    p._layout_cfg = {}
    p._components = lambda: [hud, rep]
    rows = p._panel_rows()
    assert [(r[0], r[6]) for r in rows] == [
        ("cargo", "reporting"), ("income", "reporting"), ("massacre", "hud")]


# ── Missions ──────────────────────────────────────────────────────────────────

def test_the_massacre_hud_is_each_target_factions_kills():
    p, _state, _said = _component()
    p.core.state = _stack_state(done={3}, credited={1: 7})
    panel = p.overlay_panel("massacre", op.PanelContext())
    assert panel.title == "MASSACRE" and panel.rows == [(TGT, "07 / 45")]
    p.core.state = _stack_state(done={1, 2, 3})
    assert p.overlay_panel("massacre", op.PanelContext()).rows == [(TGT, "done")]
    p.core.state = MonitorState()
    assert p.overlay_panel("massacre", op.PanelContext()) is None


def test_the_mining_hud_is_the_ore_still_wanted_and_what_the_ship_holds():
    p, _state, _said = _component()
    s = MonitorState()
    s.all_missions = {
        1: {"category": "Mining", "commodity": "Bromellite", "commodity_key": "bromellite",
            "count": 80, "reward": 1, "status": "Active", "dest_system": "Far away"},
        2: {"category": "Mining", "commodity": "Bromellite", "commodity_key": "bromellite",
            "count": 118, "reward": 1, "status": "Active"},
        3: {"category": "Mining", "commodity": "Samarium", "commodity_key": "samarium",
            "count": 36, "reward": 1, "status": "Active"},
        4: {"category": "Courier", "reward": 1},
    }
    s.cargo_items = {"bromellite": {"count": 64}, "samarium": {"count": 40}}
    p.core.state = s
    panel = p.overlay_panel("mining_missions", op.PanelContext())
    assert panel.title == "MINING"
    assert panel.rows == [("Bromellite", "64 / 198 t"), ("Samarium", "✓")]
    s.all_missions = {4: {"category": "Courier", "reward": 1}}
    assert p.overlay_panel("mining_missions", op.PanelContext()) is None


# ── The current system ────────────────────────────────────────────────────────

def _explo(view, bio):
    from components.explo_sync import ExploSyncPlugin
    p = ExploSyncPlugin.__new__(ExploSyncPlugin)
    p.core = SimpleNamespace(state=MonitorState())
    p._hud_views = lambda: (view, bio)
    return p


def _body(short, typ, **kw):
    return {"short": short, "name": f"Sys {short}", "type": typ, "is_star": False,
            "high_value": False, "mapped": False, "terraformable": False, **kw}


def test_the_exploration_hud_is_the_bodies_left_to_map():
    view = {"system": {"name": "Col 285 Sector AB-C", "body_count": 9},
            "totals": {"scanned": 6, "bodies": 6, "value_now": 1_200_000,
                       "value_max": 4_800_000},
            "bodies": [_body("A", "K", is_star=True),
                       _body("1", "Earthlike body", high_value=True),
                       _body("2", "Water world", high_value=True, mapped=True),
                       _body("3", "Icy body")]}
    panel = _explo(view, None).overlay_panel("system_exploration", op.PanelContext())
    assert panel.title == "COL 285 SECTOR AB-C"
    assert panel.rows == [("Bodies", "6 / 9"), ("Map", "1 ELW"), ("Value", "1.2M / 4.8M")]
    assert _explo(None, None).overlay_panel("system_exploration", op.PanelContext()) is None


def test_the_exobio_hud_is_the_bodies_left_to_sample_and_the_species_in_hand():
    bio = {"bodies": [
        {"short": "1 a", "bio_signals": 3, "analysed": 1, "complete": False, "current": True,
         "flora": [{"name": "Bacterium Aurasus", "stage": 2, "logged": False, "clonal": 500},
                   {"name": "Stratum Tectonicas", "stage": 3, "logged": True, "clonal": 500}]},
        {"short": "2", "bio_signals": 2, "analysed": 0, "complete": False, "flora": []},
        {"short": "3", "bio_signals": 1, "analysed": 1, "complete": True, "flora": []},
    ]}
    panel = _explo(None, bio).overlay_panel("system_exobio", op.PanelContext())
    assert panel.title == "EXOBIOLOGY"
    assert panel.rows == [("▸ 1 a", "1 / 3 sampled"),
                          ("  Bacterium Aurasus", "2/3 · ≥500 m"),
                          ("2", "0 / 2 sampled")]
    done = {"bodies": [bio["bodies"][2]]}
    assert _explo(None, done).overlay_panel("system_exobio", op.PanelContext()) is None
