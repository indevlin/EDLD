"""tests/test_custom_theme_dirs.py — custom themes are found in the data directory.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import core.palette as pal  # noqa: E402
import core.state as state  # noqa: E402


def _theme(d: Path, stem: str, accent: str) -> None:
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{stem}.css").write_text(f":root {{ --accent: {accent}; }}\n", encoding="utf-8")


def _dirs(monkeypatch, tmp_path):
    data, repo = tmp_path / "data", tmp_path / "repo"
    monkeypatch.setattr(state, "EDLD_DATA_DIR", data)
    monkeypatch.setattr(pal, "_repo_root", lambda: repo)
    return data / "themes" / "custom", repo / "themes" / "custom"


def test_a_theme_in_the_data_directory_is_listed_and_used(monkeypatch, tmp_path):
    data, _repo = _dirs(monkeypatch, tmp_path)
    _theme(data, "night", "#123456")
    assert pal.list_custom_themes() == [("custom/night", "night")]
    assert pal.palette_for("custom/night")["$accent"] == "#123456"


def test_a_theme_beside_the_code_still_works(monkeypatch, tmp_path):
    _data, repo = _dirs(monkeypatch, tmp_path)
    _theme(repo, "old", "#654321")
    assert pal.list_custom_themes() == [("custom/old", "old")]
    assert pal.palette_for("custom/old")["$accent"] == "#654321"


def test_the_data_directory_wins_and_a_stem_is_listed_once(monkeypatch, tmp_path):
    data, repo = _dirs(monkeypatch, tmp_path)
    _theme(repo, "same", "#000001")
    _theme(data, "same", "#000002")
    _theme(repo, "other", "#000003")
    assert pal.list_custom_themes() == [("custom/other", "other"), ("custom/same", "same")]
    assert pal.palette_for("custom/same")["$accent"] == "#000002"


def test_a_missing_or_escaping_name_falls_back_to_default(monkeypatch, tmp_path):
    data, _repo = _dirs(monkeypatch, tmp_path)
    _theme(data.parent, "outside", "#ff00ff")
    for name in ("custom/nope", "custom/../outside", "custom/", "custom/.hidden"):
        assert pal.custom_theme_path(name) is None
        assert pal.palette_for(name) == pal.PALETTES["default"]


def test_the_terminal_dashboard_resolves_through_the_same_place(monkeypatch, tmp_path):
    data, _repo = _dirs(monkeypatch, tmp_path)
    _theme(data, "night", "#abcdef")
    from tui.theme import build_css
    assert "#abcdef" in build_css("custom/night")


def test_the_template_holds_exactly_what_is_read():
    """The template once listed a dozen variables from the retired GTK4
    interface that nothing read. Every variable in it must be one
    load_custom_palette() reads, and every one it reads must be there."""
    import inspect
    import re
    tpl = (ROOT / "themes" / "custom-template.css").read_text(encoding="utf-8")
    declared = set(re.findall(r"^\s*--([a-z-]+)\s*:", tpl, re.M))
    read = set(re.findall(r'_v\("([a-z-]+)"', inspect.getsource(pal.load_custom_palette)))
    assert declared == read
    loaded = pal.load_custom_palette(ROOT / "themes" / "custom-template.css")
    assert loaded["$accent"] == "#e07b20" and loaded["$bg"] == "#0d0f12"
