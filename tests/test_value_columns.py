"""tests/test_value_columns.py — figures in a window's rows line up in
columns, in the desktop window and the terminal dashboard alike."""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.windows import R, align_values  # noqa: E402

_MARKUP = re.compile(r"\[/?[a-z#][^\]]*\]")


def _shown(rows):
    return {r[1]: _MARKUP.sub("", r[2]) for r in rows if r[0] == "kv"}


SESSION = [R.hdr("Session"), R.kv("Duration", "5:22:46"),
           R.kv("Jumps", "6  313 ly"), R.kv("Bodies scanned", "1  30.4k"),
           R.kv("Kills", "15  6.3 /hr"), R.kv("Bounties", "4,512,000 cr"),
           R.kv("Share", "[b]1,234 cr[/b]  12.5%")]


def test_every_figure_row_is_one_width():
    got = _shown(align_values(SESSION))
    assert len({len(v) for v in got.values()}) == 1, got


def test_numbers_end_together_and_units_start_together():
    got = _shown(align_values(SESSION))
    # The counts' last digits, in the first column.
    ends = {k: got[k].index(n) + len(n) for k, n in
            (("Duration", "5:22:46"), ("Jumps", "6"), ("Bodies scanned", "1"),
             ("Kills", "15"), ("Bounties", "4,512,000"), ("Share", "1,234"))}
    assert len(set(ends.values())) == 1, ends
    # The rates' last digits, in the second.
    rates = {k: got[k].rindex(n) + len(n) for k, n in
             (("Jumps", "313"), ("Kills", "6.3"), ("Share", "12.5%"))}
    assert len(set(rates.values())) == 1, rates
    assert got["Jumps"].index("ly") == got["Kills"].index("/hr")


def test_text_and_tables_are_left_alone():
    rows = [R.kv("Location", "Jameson Memorial  (Shinrarta Dezhra)"),
            R.kv("Kills", "15"), R.kv("Bounties", "4,512,000 cr"),
            R.table("Commodity", (("Tons", 5),)), R.kv("", "12 t"),
            R.hdr("After"), R.kv("Mode", "Solo")]
    got = align_values(rows)
    assert got[0] == rows[0] and got[4] == rows[4] and got[6] == rows[6]
    assert got[1][2].rstrip().endswith("15") and len(got[1][2]) == len(got[2][2])


def test_a_lone_figure_is_not_padded():
    rows = [R.kv("Kills", "15"), R.kv("Mode", "Solo")]
    assert align_values(rows) == rows


def test_each_heading_starts_its_own_columns():
    """A lone figure among text keeps its own place; the figures under the
    next heading are padded among themselves."""
    rows = [R.hdr("Info"), R.kv("Mode", "Solo"), R.kv("Hull", "100%"),
            R.hdr("Session"), R.kv("Duration", "5:22:46"), R.kv("Bounties", "4,512,000 cr")]
    got = align_values(rows)
    assert got[2] == rows[2]
    assert len(got[4][2]) == len(got[5][2]) and got[4][2] != rows[4][2]


def test_carrier_route_waypoints_line_up():
    from core.ui_helpers import carrier_route_rows
    rows = carrier_route_rows({"jumps": [
        {"name": "Sol"},
        {"name": "Alpha", "distance": 500, "fuel_used": 12, "fuel_in_tank": 988,
         "has_icy_ring": True},
        {"name": "Beta", "distance": 499.5, "fuel_used": 112, "fuel_in_tank": 876,
         "must_restock": True, "restock_amount": 300, "tritium_in_market": 40}]})
    values = [v for _l, v in rows]
    assert len({v.index("]") for v in values}) == 1
    assert values[1].index("ly") == values[2].index("ly")
    assert rows[0][0] == "0. Sol"


def test_qt_keeps_a_trailing_pad():
    from gui.markup import to_html
    assert to_html("12 ", {}).endswith("&nbsp;")
