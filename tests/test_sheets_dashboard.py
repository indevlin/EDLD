"""tests/test_sheets_dashboard.py — The sheet template agrees with what it reads.

Only the last two need openpyxl, and they skip without it.
"""
from __future__ import annotations

import ast
import re
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SHEETS = ROOT / "sheets"
BUILD = SHEETS / "build_dashboard.py"
TEMPLATE = SHEETS / "Mining_Dashboard.xlsx"

#: What the dashboard table shows, in column order.
DASHBOARD_FIELDS = ("system", "body", "gravity", "signal_no", "commodity",
                    "amount", "density_observed", "rigs", "depleted_on", "notes")

#: Every Ring Hotspots field the ring table reads, in the order its columns
#: name them: System, Body, Ring, Type, Commodity (with count), Reserve,
#: Overlap (with note).
RING_FIELDS = ("system", "body", "ring", "ring_type", "commodity", "count",
               "count", "reserve_level", "overlap", "note", "note", "overlap")


# ── helpers ───────────────────────────────────────────────────────────────────

def _code_gs_columns() -> tuple[str, ...]:
    gs = (SHEETS / "Code.gs").read_text(encoding="utf-8")
    block = re.search(r"var COLUMNS = \[(.*?)\];", gs, re.S)
    assert block, "COLUMNS not found in Code.gs"
    return tuple(re.findall(r"'([a-z_]+)'", block.group(1)))


def _literal(path: Path, name: str):
    """A module-level constant, read without importing the module."""
    for node in ast.parse(path.read_text(encoding="utf-8")).body:
        if isinstance(node, ast.Assign) and any(
                isinstance(t, ast.Name) and t.id == name for t in node.targets):
            return ast.literal_eval(node.value)
    raise AssertionError(f"{name} not found in {path.relative_to(ROOT)}")


def _formulas() -> dict[str, str]:
    text = (SHEETS / "Dashboard.gs").read_text(encoding="utf-8")
    block = re.search(r"const FORMULAS = \{(.*?)\n\};", text, re.S)
    assert block, "FORMULAS not found in Dashboard.gs"
    return dict(re.findall(r"'([A-Za-z]+![A-Z]+\d+)':\s*`([^`]*)`", block.group(1)))


def _hotspot_columns() -> tuple[str, ...]:
    gs = (SHEETS / "Code.gs").read_text(encoding="utf-8")
    block = re.search(r"var HOTSPOT_COLUMNS = \[(.*?)\];", gs, re.S)
    assert block, "HOTSPOT_COLUMNS not found in Code.gs"
    return tuple(re.findall(r"'([a-z_]+)'", block.group(1)))


def _field(letter: str, columns=None) -> str:
    n = 0
    for ch in letter:
        n = n * 26 + ord(ch) - 64
    return (columns or _code_gs_columns())[n - 1]


def _ring(letter: str) -> str:
    return _field(letter, _hotspot_columns())


def _ring_branch() -> str:
    """Dashboard!A7 from the ring table's header on: the second of its two tables."""
    f = _formulas()["Dashboard!A7"]
    return f[f.index("Queries!$D$2:", f.index("Queries!$D$2:") + 1):]


#: The surface sites and ring hotspots tabs as the formulas reference them.
SITES = r"'Surface Sites'!"
RINGS = r"'Ring Hotspots'!"


def _condition_field(formula: str, pattern: str) -> str:
    m = re.search(pattern, formula)
    assert m, f"no condition matching {pattern!r}"
    return _field(m.group(1))


# ── the column contract ───────────────────────────────────────────────────────

def test_template_deposits_header_is_code_gs_columns():
    assert tuple(_literal(BUILD, "DEPOSIT_COLUMNS")) == _code_gs_columns(), (
        "the template's Surface Sites header must be COLUMNS from Code.gs, in order")


def test_template_hotspot_header_is_code_gs_hotspot_columns():
    from core.sheets_publish import HOTSPOT_COLUMNS
    code = (SHEETS / "Code.gs").read_text(encoding="utf-8")
    m = re.search(r"var HOTSPOT_COLUMNS = \[(.*?)\]", code, re.S)
    assert tuple(re.findall(r"'(\w+)'", m.group(1))) == HOTSPOT_COLUMNS
    assert tuple(_literal(BUILD, "HOTSPOT_COLUMNS")) == HOTSPOT_COLUMNS


def test_dashboard_filter_shows_the_intended_fields():
    formula = _formulas()["Dashboard!A7"]
    shown = re.search(r"FILTER\(\s*\{(.*?)\}", formula, re.S)
    assert shown, "FILTER column list not found"
    letters = re.findall(SITES + r"([A-Z]+)2:\1\b", shown.group(1))
    assert tuple(_field(x) for x in letters) == DASHBOARD_FIELDS


def test_dashboard_filter_conditions_test_the_intended_fields():
    formula = _formulas()["Dashboard!A7"]
    assert _condition_field(formula, r"\(" + SITES + r"([A-Z]+)2:\1=Dashboard!\$A\$5\)") == "system"
    assert _condition_field(formula, r"\(" + SITES + r"([A-Z]+)2:\1=Dashboard!\$B\$5\)") == "commodity"
    assert _condition_field(formula, SITES + r"([A-Z]+)2:\1 <> 1") == "is_test"


def test_dropdown_lists_read_both_tabs_without_test_rows():
    f = _formulas()
    for key, field in (("Queries!A1", "system"), ("Queries!B1", "commodity")):
        stacks = re.findall(r"\{" + SITES + r"([A-Z]+)2:\1; " + RINGS + r"([A-Z]+)2:\2\}",
                            f[key])
        assert len(stacks) == 3, key
        (vals, nonblank, test) = stacks
        assert vals == nonblank, key
        assert (_field(vals[0]), _ring(vals[1])) == (field, field), key
        assert (_field(test[0]), _ring(test[1])) == ("is_test", "is_test"), key
        assert re.search(r"\}<>\"\",", f[key]) and re.search(r"\}<>1\)", f[key]), key


# ── ring hotspots ─────────────────────────────────────────────────────────────

def test_ring_table_shows_the_intended_fields():
    shown = re.search(r"FILTER\(\s*\{(.*?)\},\s*\(", _ring_branch(), re.S)
    assert shown, "ring FILTER column list not found"
    letters = re.findall(RINGS + r"([A-Z]+)2:\1\b", shown.group(1))
    assert tuple(_ring(x) for x in letters) == RING_FIELDS


def test_ring_table_conditions_test_the_intended_fields():
    f = _ring_branch()
    assert _ring(re.search(r"\(" + RINGS + r"([A-Z]+)2:\1=Dashboard!\$A\$5\)", f).group(1)) == "system"
    assert _ring(re.search(r"\(" + RINGS + r"([A-Z]+)2:\1=Dashboard!\$B\$5\)", f).group(1)) == "commodity"
    assert _ring(re.search(RINGS + r"([A-Z]+)2:\1 <> 1", f).group(1)) == "is_test"


def test_overlap_with_a_hotspot_names_it_from_the_choice_edld_offers():
    from core.ring_hotspots import OVERLAPS
    m = re.search(r'IF\(' + RINGS + r'[A-Z]+2:[A-Z]+ = "([^"]+)"', _ring_branch())
    assert m and m.group(1) in OVERLAPS and m.group(1).startswith("Hotspot")


def test_ring_sort_rank_is_the_reserve_levels_edld_records():
    from core.ring_hotspots import RESERVE_LEVELS
    rank = re.search(r"MATCH\(sortkey, \{([^}]*)\}", _ring_branch())
    assert rank, "rank list not found in the ring SORT"
    assert tuple(re.findall(r'"([^"]+)"', rank.group(1))) == tuple(reversed(RESERVE_LEVELS))


def test_ring_rows_are_as_wide_as_the_ring_header():
    rings = _literal(BUILD, "RING_HEADERS")
    f = _ring_branch()
    heads = re.findall(r"Queries!\$D\$2:\$([A-Z])\$2;", _formulas()["Dashboard!A7"])
    assert heads[1] == chr(ord("D") + len(rings) - 1), "ring header range"
    empty = re.search(r'\{"No hotspots match this filter"((?:,"")*)\}', f)
    assert empty and empty.group(1).count(",") + 1 == len(rings)
    shown = re.search(r"FILTER\(\s*\{(.*?)\},\s*\(", f, re.S).group(1)
    depth, cols = 0, 1
    for ch in shown:
        depth += ch == "("
        depth -= ch == ")"
        cols += ch == "," and depth == 0
    assert cols == len(rings)


def test_both_files_list_the_same_ring_columns():
    gs = (SHEETS / "Dashboard.gs").read_text(encoding="utf-8")
    block = re.search(r"RING_HEADERS: \[(.*?)\]", gs, re.S)
    assert block, "ED.RING_HEADERS not found in Dashboard.gs"
    rings = _literal(BUILD, "RING_HEADERS")
    assert re.findall(r"'([^']+)'", block.group(1)) == rings
    widths = re.search(r"RING_WIDTHS: \[(.*?)\]", gs).group(1).split(",")
    assert len(widths) == len(rings)
    assert len(rings) <= len(_literal(BUILD, "HEADERS"))


def test_site_type_picks_the_table_and_surface_is_the_default():
    f = _formulas()["Dashboard!A7"]
    assert re.search(r'IF\(\s*Dashboard!\$D\$5<>"Ring",', f)
    assert f.index(SITES.replace("\\", "")) < f.index("'Ring Hotspots'!")
    assert _literal(BUILD, "SITE_TYPES") == ["Surface", "Ring"]
    assert _literal(BUILD, "DASH_LABELS")["D4"] == "Site Type"


def test_both_files_list_the_same_table_columns():
    """Repair lays an older sheet out from ED.HEADERS; the build from HEADERS."""
    gs = (SHEETS / "Dashboard.gs").read_text(encoding="utf-8")
    block = re.search(r"HEADERS: \[(.*?)\]", gs, re.S)
    assert block, "ED.HEADERS not found in Dashboard.gs"
    assert re.findall(r"'([^']+)'", block.group(1)) == _literal(BUILD, "HEADERS")


def test_every_table_row_is_as_wide_as_the_header():
    """An array literal with a short row is an error in Sheets, not a blank."""
    headers = _literal(BUILD, "HEADERS")
    assert len(headers) == len(DASHBOARD_FIELDS)
    empty = re.search(r'\{"No deposits match this filter"((?:,"")*)\}',
                      _formulas()["Dashboard!A7"])
    assert empty and empty.group(1).count(",") + 1 == len(headers)


# ── sorting ───────────────────────────────────────────────────────────────────

def test_sort_rank_is_the_levels_edld_records():
    rank = re.search(r"MATCH\(sortkey, \{([^}]*)\}", _formulas()["Dashboard!A7"])
    assert rank, "rank list not found in the SORT"
    ranked = tuple(re.findall(r'"([^"]+)"', rank.group(1)))
    mining_db = ROOT / "core" / "mining_db.py"
    assert ranked == tuple(_literal(mining_db, "AMOUNT_LEVELS")), (
        "Amount sorts by this list; it must be AMOUNT_LEVELS, lowest first")
    density = tuple(_literal(mining_db, "DENSITY_LEVELS"))
    assert tuple(x for x in ranked if x in density) == density, (
        "Density sorts by the same list, so its levels must appear in it in order")


def test_a_single_matching_deposit_is_not_handed_to_sort():
    """One matching row made the sort key a single value, which SORT reads as a
    column number. A system name is not one, the IFERROR caught the failure,
    and the dashboard said "No deposits match this filter" over a row that
    matched (a lone Rhodplumsite site, 20261018)."""
    f = _formulas()["Dashboard!A7"]
    guard = re.search(r"IF\(\s*ROWS\(dep\)\s*=\s*1,\s*dep,\s*SORT\(", f)
    assert guard, "the SORT must be skipped when FILTER returns one row"
    assert f.index("ROWS(dep)") < f.index("SORT("), "the guard must wrap the SORT"


def test_the_site_type_reaches_existing_sheets():
    up = (SHEETS / "Upgrade.gs").read_text(encoding="utf-8")
    steps = re.findall(r"to:\s*(\d+),\s*name:\s*'([^']*)'", up)
    assert any("Site Type" in name for _n, name in steps)


def test_the_one_row_fix_reaches_existing_sheets():
    """A formula change only reaches a live sheet when an upgrade step rebuilds
    the dashboard, so it needs a layout step of its own."""
    up = (SHEETS / "Upgrade.gs").read_text(encoding="utf-8")
    steps = re.findall(r"to:\s*(\d+),\s*name:\s*'([^']*)'", up)
    assert steps and int(steps[-1][0]) >= 3
    assert any("single deposit" in name for _n, name in steps)


# ── theme ─────────────────────────────────────────────────────────────────────

def test_classic_hud_matches_the_script_fallback():
    roles = [r for r, _ in _literal(BUILD, "ROLES")]
    classic = _literal(BUILD, "THEMES")["Classic HUD"]
    gs = (SHEETS / "Dashboard.gs").read_text(encoding="utf-8")
    block = re.search(r"FALLBACK: \{(.*?)\}", gs, re.S)
    assert block, "ED.FALLBACK not found in Dashboard.gs"
    fallback = dict(re.findall(r"'([A-Za-z ]+)':\s*'(#[0-9A-Fa-f]{6})'", block.group(1)))
    assert fallback == dict(zip(roles, classic))


# ── the committed template ────────────────────────────────────────────────────

def _load(path: Path):
    openpyxl = pytest.importorskip("openpyxl")
    return openpyxl.load_workbook(path)


def _snapshot(wb) -> dict:
    out = {}
    for ws in wb.worksheets:
        out[ws.title] = {
            "state": ws.sheet_state,
            "cells": {c.coordinate: c.value for row in ws.iter_rows()
                      for c in row if c.value is not None},
            "merged": sorted(str(r) for r in ws.merged_cells.ranges),
            "validation": sorted((str(dv.sqref), dv.type, dv.formula1)
                                 for dv in ws.data_validations.dataValidation),
            "conditional": sorted((str(cf.sqref), tuple(r.formula))
                                  for cf in ws.conditional_formatting for r in cf.rules),
        }
    return out


def test_committed_template_is_a_fresh_build(tmp_path):
    committed = _load(TEMPLATE)
    version = re.search(r"v(\S+) powered", committed["Settings"]["D1"].value).group(1)
    fresh_path = tmp_path / "fresh.xlsx"
    subprocess.run([sys.executable, str(BUILD), "--out", str(fresh_path),
                    "--version", version, "--bundle-dir", str(tmp_path)],
                   check=True, capture_output=True)
    assert _snapshot(_load(fresh_path)) == _snapshot(committed), (
        "sheets/Mining_Dashboard.xlsx is stale; run python3 sheets/build_dashboard.py")
    # The loader's bundle and manifest come from the same run, from the same
    # sources; a stale one is code a sheet would install that is not the code
    # in this commit.
    for name in ("edld_sheet.js", "release.json"):
        assert (tmp_path / name).read_bytes() == (SHEETS / name).read_bytes(), (
            f"sheets/{name} is stale; run python3 sheets/build_dashboard.py")


def test_wrapped_formulas_unwrap_to_dashboard_gs_and_fit_xlsx_strings():
    """xlsx caps a string literal at 255 characters; Sheets unwraps on import."""
    wb = _load(TEMPLATE)
    for key, source in _formulas().items():
        sheet, a1 = key.split("!")
        cell = wb[sheet][a1].value
        m = re.fullmatch(r'=IFERROR\(__xludf\.DUMMYFUNCTION\((.*)\),.*\)', cell, re.S)
        assert m, f"{key} is not in the Sheets export wrapper"
        parts = [p.replace('""', '"')
                 for p in re.findall(r'"((?:[^"]|"")*)"(?:&|$)', m.group(1))]
        assert all(len(p) <= 255 for p in parts), key
        assert "=" + "".join(parts) == source, key
