#!/usr/bin/env python3
"""scripts/export_outfitting.py — every module's in-game name, class and rating.

``hpt_miningtoolv2_fixed_large`` is a 3C Mining Volley Repeater, and nothing in
the id says C; ``int_largebuggybay_size4_class3`` is rated F, not the C its
"class3" suggests.

    python3 scripts/export_outfitting.py            # fetch it, write the table
    python3 scripts/export_outfitting.py FILE.csv   # from a copy on disk

Names are FDevIDs' unless the game's journal names a module more fully.

Run it again when Frontier adds modules.
"""
from __future__ import annotations

import csv
import io
import re
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "outfitting.py"
SOURCE = "https://raw.githubusercontent.com/EDCD/FDevIDs/master/outfitting.csv"

#: Ship modules only: on-foot gear has its own names (core/dossier/names.py).
CATEGORIES = ("standard", "internal", "hardpoint", "utility")

#: The outfitting screen's words for a mount, as EDLD writes them.
MOUNTS = {"Fixed": "Fixed", "Gimballed": "Gimballed", "Turreted": "Turret"}


#: Where the game's own name is fuller than FDevIDs'.
JOURNAL_NAMES = {
    # "POINT DEFENCE TURRET" on the modules screen; FDevIDs: "Point Defence".
    "Point Defence": "Point Defence Turret",
}

#: Spelling FDevIDs is inconsistent about: it hyphenates "Mk II Mining
#: Multi-Limpet Controller" and no other, while the journal hyphenates them all
#: ("Universal Multi-Limpet Controller", "Operations Multi-Limpet Controller").
JOURNAL_SPELLING = (("Multi Limpet", "Multi-Limpet"),)


#: Checked against EDSY's module database (edsy.org, updated 2026-10-20),
#: which covers every module FDevIDs does. Where the two disagree on a rating,
#: EDSY's is the one the game shows; and EDSY has modules FDevIDs lacks.
#: symbol -> (class, rating, name, mount); an entry here replaces FDevIDs'.
EDSY = {
    # Ratings FDevIDs copied from the ordinary missile rack / fixed mount.
    "hpt_atdumbfiremissile_fixed_large":      (3, "C", "AX Missile Rack", "Fixed"),
    "hpt_atdumbfiremissile_fixed_medium":     (2, "E", "AX Missile Rack", "Fixed"),
    "hpt_atdumbfiremissile_turret_large":     (3, "E", "AX Missile Rack", "Turret"),
    "hpt_atdumbfiremissile_turret_medium":    (2, "F", "AX Missile Rack", "Turret"),
    "hpt_guardian_shardcannon_turret_medium": (2, "A", "Guardian Shard Cannon", "Turret"),
    # Not in FDevIDs.
    "int_largecargorack_size6_class1":          (6, "D", "Mk II Cargo Rack", ""),
    "int_corrosionproofcargorack_size2_class1": (2, "E", "Corrosion Resistant Cargo Rack", ""),
    "int_corrosionproofcargorack_size5_class1": (5, "E", "Corrosion Resistant Cargo Rack", ""),
    "int_corrosionproofcargorack_size6_class1": (6, "E", "Corrosion Resistant Cargo Rack", ""),
    "int_shieldgenerator_size1_class4":         (1, "B", "Shield Generator", ""),
    "int_passengercabin_size2_class0":          (2, "E", "Prisoner Cells", ""),
    "int_passengercabin_size3_class0":          (3, "E", "Prisoner Cells", ""),
    "int_passengercabin_size4_class0":          (4, "E", "Prisoner Cells", ""),
    "int_passengercabin_size5_class0":          (5, "E", "Prisoner Cells", ""),
    "int_passengercabin_size6_class0":          (6, "E", "Prisoner Cells", ""),
    "modularcargobaydoor":                      (1, "H", "Cargo Hatch", ""),
    # The Fer-de-Lance's own id for the same hatch; EDSY lists only the first.
    "modularcargobaydoorfdl":                   (1, "H", "Cargo Hatch", ""),
}


def game_name(name: str) -> str:
    name = JOURNAL_NAMES.get(name, name)
    for old, new in JOURNAL_SPELLING:
        name = name.replace(old, new)
    return name


def read(source: str) -> list[dict]:
    if source.startswith("http"):
        with urllib.request.urlopen(source, timeout=30) as resp:
            text = resp.read().decode("utf-8")
    else:
        text = Path(source).read_text(encoding="utf-8")
    return list(csv.DictReader(io.StringIO(text)))


def render(rows: list[dict]) -> str:
    table: dict[str, tuple] = {}
    for r in rows:
        if r.get("category") not in CATEGORIES:
            continue
        sym = (r.get("symbol") or "").strip().lower()
        if not sym or "_armour_" in sym:
            continue        # bulkheads: data/modules.py names them by grade
        try:
            size = int(r.get("class") or 0)
        except ValueError:
            continue
        # An id that carries its size is right about it: across every module
        # in the list the class matches the id's _sizeN, except the two
        # size 6 Mk II passenger cabins, listed as class 5 — a slip in the
        # list, not a size 6 cabin that fits a size 5 slot.
        m = re.search(r"_size(\d+)_", sym)
        if m and int(m.group(1)) > 0:
            size = int(m.group(1))
        rating = (r.get("rating") or "").strip().upper()[:1]
        name = game_name((r.get("name") or "").strip())
        if not name or not rating:
            continue
        table[sym] = (size, rating, name, MOUNTS.get((r.get("mount") or "").strip(), ""))
    lines = [
        '"""',
        "data/outfitting.py — ship modules' in-game names, classes and ratings.",
        "",
        "Generated by scripts/export_outfitting.py from EDCD's FDevIDs",
        "outfitting.csv:",
        f"{SOURCE}",
        "Do not edit; run the script again.",
        "",
        "symbol (lower case) -> (class, rating, name, mount)",
        '"""',
        "",
        "OUTFITTING: dict[str, tuple[int, str, str, str]] = {",
    ]
    table.update(EDSY)
    for sym in sorted(table):
        size, rating, name, mount = table[sym]
        lines.append(f"    {sym!r}: ({size}, {rating!r}, {name!r}, {mount!r}),")
    lines.append("}")
    return "\n".join(lines) + "\n"


def main(argv: list[str]) -> int:
    source = argv[1] if len(argv) > 1 else SOURCE
    text = render(read(source))
    OUT.write_text(text, encoding="utf-8")
    print(f"wrote {OUT.relative_to(ROOT)} ({text.count(chr(10) + '    ' + chr(39))} modules)")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
