"""tests/test_overlay_visibility.py — the overlay's visibility tweaks."""
from __future__ import annotations

import itertools
import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core import overlay_panels as op  # noqa: E402
from core.overlay_ink import (CONTRAST_TARGETS, GAME_BACKGROUND,  # noqa: E402
                              apply_contrast_floor, backing_colour, blend,
                              contrast_ratio, ensure_contrast)
from core.palette import (PALETTES, overlay_colours,  # noqa: E402
                          overlay_theme_choices)

TWEAKS = ("Outline", "BackingPanel", "SolidText", "ContrastFloor", "EmphasiseValues")
COMBOS = [dict(zip(TWEAKS, bits))
          for bits in itertools.product((False, True), repeat=len(TWEAKS))]


def _hue(colour: str) -> float:
    import colorsys
    raw = colour.lstrip("#")
    r, g, b = (int(raw[i:i + 2], 16) / 255 for i in (0, 2, 4))
    return colorsys.rgb_to_hls(r, g, b)[0]


# ── the contrast floor ────────────────────────────────────────────────────────

@pytest.mark.parametrize("theme", sorted(PALETTES))
@pytest.mark.parametrize("alpha", (1.0, 0.75))
def test_every_theme_meets_the_floor_over_the_game(theme, alpha):
    colours = apply_contrast_floor(overlay_colours(theme), GAME_BACKGROUND, alpha)
    for key, ratio in CONTRAST_TARGETS.items():
        seen = blend(colours[key], GAME_BACKGROUND, alpha)
        assert contrast_ratio(seen, GAME_BACKGROUND) >= ratio - 0.01, (theme, key)


@pytest.mark.parametrize("theme", sorted(PALETTES))
def test_every_theme_meets_the_floor_over_its_own_backing(theme):
    colours = overlay_colours(theme)
    back = backing_colour(colours)
    floored = apply_contrast_floor(colours, back)
    for key, ratio in CONTRAST_TARGETS.items():
        assert contrast_ratio(floored[key], back) >= ratio - 0.01, (theme, key)


def test_the_floor_keeps_a_theme_looking_like_itself():
    """Lightness moves; hue does not. Elite orange stays orange."""
    out = ensure_contrast("#8a5a22", GAME_BACKGROUND, 5.5, 0.75)
    assert out != "#8a5a22"
    assert abs(_hue(out) - _hue("#8a5a22")) < 0.02


def test_colours_already_readable_are_left_alone():
    assert ensure_contrast("#ffffff", GAME_BACKGROUND, 7.0) == "#ffffff"


def test_custom_colours_go_through_the_floor_too():
    """The explicit Custom colors are the ones nobody has checked."""
    custom = {"TitleColour": "#202020", "LabelColour": "#303030",
              "ValueColour": "#404040"}
    out = apply_contrast_floor(custom, GAME_BACKGROUND)
    for key, ratio in CONTRAST_TARGETS.items():
        assert contrast_ratio(out[key], GAME_BACKGROUND) >= ratio - 0.01


def test_a_bad_colour_is_passed_through_not_raised():
    assert ensure_contrast("not-a-colour", GAME_BACKGROUND, 7.0) == "not-a-colour"


# ── themes: custom dashboard themes and Follow dashboard ──────────────────────

def test_follow_dashboard_and_custom_themes_are_offered(tmp_path, monkeypatch):
    import core.palette as pal
    custom = tmp_path / "themes" / "custom"
    custom.mkdir(parents=True)
    (custom / "mine.css").write_text(
        ":root { --accent: #ff00aa; --dim: #444444; --fg: #eeeeee; }")
    monkeypatch.setattr(pal, "_repo_root", lambda: tmp_path)
    ids = [v for _n, v in overlay_theme_choices()]
    assert ids[:2] == ["custom", "dashboard"]
    assert "custom/mine" in ids
    assert overlay_colours("custom/mine")["TitleColour"] == "#ff00aa"
    assert overlay_colours("dashboard", "custom/mine")["ValueColour"] == "#eeeeee"
    assert overlay_colours("dashboard", "default-green") == overlay_colours("default-green")


# ── the layout ────────────────────────────────────────────────────────────────

def _frame(colours=None, emphasise=False):
    panel = op.Panel(id="income", title="INCOME",
                     rows=[("Credits:", "751.90M cr"), ("", "a note")])
    els, _ = op.layout([op.PanelPlacement("income", "left", "on", 1)],
                       {"income": panel}, 300, colours=colours,
                       emphasise_values=emphasise)
    return {e["id"]: e for e in els}


def test_every_element_knows_its_panel():
    assert {e["group"] for e in _frame().values()} == {"income"}


def test_without_emphasis_a_row_is_one_line_in_the_label_colour():
    """Unchanged unless asked: the overlay looks as it always has."""
    row = _frame()["income.Credits:"]
    assert "runs" not in row
    assert row["colour"] == op.CFG_DEFAULTS["LabelColour"]


def test_emphasis_draws_the_value_in_the_value_colour_and_bold():
    row = _frame(emphasise=True)["income.Credits:"]
    label, value = row["runs"]
    assert label["colour"] == op.CFG_DEFAULTS["LabelColour"]
    assert value == {"text": "751.90M cr", "colour": op.CFG_DEFAULTS["ValueColour"],
                     "weight": "bold"}
    assert row["text"] == "Credits:  751.90M cr"      # the fallback is intact


def test_the_backing_colour_reaches_every_element_when_named():
    els = _frame({"BackingColour": "#0a0b0c"})
    assert {e.get("backing") for e in els.values()} == {"#0a0b0c"}
    assert all("backing" not in e for e in _frame().values())


# ── the component ─────────────────────────────────────────────────────────────

def _component(tweaks: dict, theme: str = "elite-orange"):
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "ov_vis", ROOT / "components" / "overlay.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    p = mod.OverlayPlugin.__new__(mod.OverlayPlugin)

    class Core:
        def load_setting(self, section, defaults, warn=False, include_extra=False):
            return {"Theme": "default-green"} if section == "UI" else dict(defaults)

    p._core = Core()
    p._window_cfg = {**mod.WINDOW_DEFAULTS, "ColourTheme": theme, "Opacity": 0.75,
                     **tweaks}
    p._layout_cfg = dict(mod.LAYOUT_DEFAULTS)
    return mod, p


@pytest.mark.parametrize("tweaks", COMBOS,
                         ids=lambda t: "+".join(k for k, v in t.items() if v) or "none")
def test_every_combination_gives_usable_colours(tweaks):
    _mod, p = _component(tweaks)
    colours = p._frame_colours()
    backed = tweaks["Outline"] or tweaks["BackingPanel"]
    assert ("BackingColour" in colours) == backed
    if tweaks["ContrastFloor"]:
        ground = colours["BackingColour"] if backed else GAME_BACKGROUND
        alpha = 1.0 if tweaks["SolidText"] else 0.75
        for key, ratio in CONTRAST_TARGETS.items():
            seen = blend(colours[key], ground, alpha)
            assert contrast_ratio(seen, ground) >= ratio - 0.01, key
    else:
        assert colours["LabelColour"] == overlay_colours("elite-orange")["LabelColour"]


def test_switches_stored_as_text_still_count():
    _mod, p = _component({"ContrastFloor": "true"})
    assert p._frame_colours()["LabelColour"] != \
        overlay_colours("elite-orange")["LabelColour"]


def test_both_preference_pages_bind_every_tweak():
    mod, p = _component({})
    from core.overlay import CFG_DEFAULTS
    keys = {k for k, _l, _h in mod.VISIBILITY_TWEAKS}
    assert keys == set(TWEAKS)
    assert keys <= set(CFG_DEFAULTS)
    src = (ROOT / "components" / "overlay.py").read_text(encoding="utf-8")
    assert src.count('"VISIBILITY TWEAKS"') == 2          # GUI and TUI
    assert "EXPERIMENTAL" not in src


# ── the renderer, for real ────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def qt():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication
    import core.overlay_proc as proc
    events: list = []
    proc._emit = events.append            # keep the protocol channel quiet
    return (QApplication.instance() or QApplication([])), proc, events


def _render(qt, tweaks: dict):
    """Draw one frame on a transparent canvas; return its alpha channel."""
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QImage
    app, proc, _events = qt
    _mod, p = _component(tweaks)
    els, _ = op.layout([op.PanelPlacement("income", "left", "on", 1)],
                       {"income": op.Panel(id="income", title="INCOME",
                                           rows=[("Credits:", "751.90M cr")])},
                       300, colours=p._frame_colours(),
                       emphasise_values=bool(tweaks.get("EmphasiseValues")))
    w = proc._build(app, {"Width": 300, "Opacity": 0.75, "_compositing": True,
                          **tweaks}, "top")
    w.resize(300, 70)
    w._elements = els
    img = QImage(300, 70, QImage.Format_ARGB32)
    img.fill(Qt.transparent)
    w.render(img)
    alpha = [img.pixelColor(x, y).alpha() for y in range(70) for x in range(300)]
    return alpha


@pytest.mark.parametrize("tweaks", COMBOS,
                         ids=lambda t: "+".join(k for k, v in t.items() if v) or "none")
def test_every_combination_draws_without_error(qt, tweaks):
    _app, _proc, events = qt
    events.clear()
    alpha = _render(qt, tweaks)
    assert any(alpha), "nothing was drawn"
    assert not [e for e in events if e.get("event") == "error"], events


def test_an_outline_adds_ink_round_the_letters(qt):
    plain = sum(1 for a in _render(qt, {}) if a)
    outlined = sum(1 for a in _render(qt, {"Outline": True}) if a)
    assert outlined > plain * 1.3


def test_a_backing_panel_fills_the_space_between_the_letters(qt):
    plain = sum(1 for a in _render(qt, {}) if a)
    panel = sum(1 for a in _render(qt, {"BackingPanel": True}) if a)
    assert panel > plain * 3


def test_solid_text_is_drawn_at_full_strength(qt):
    assert max(_render(qt, {})) < 255                       # Opacity 0.75
    assert max(_render(qt, {"SolidText": True})) == 255
