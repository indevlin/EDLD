"""core/windows — what each dashboard window shows, as data, once.

    ("hdr", title)                       a section heading
    ("kv", label, value, classes[, action])  a row; classes as the blocks use them
                                         ("val", "val dim", "val health-warn"…);
                                         action: a core.panel_actions id pressed
                                         by clicking the row
    ("text", body, classes)              a line of text
    ("rule",)                            a horizontal rule
    ("toggle", text, "system"|"site", key) a heading that collapses its group
    ("table", label, [(heading, width), …])  column headings over the cells
                                         below; label heads the label column
    ("cells", label, [value, …], classes[, action]) a row of a table
"""
from __future__ import annotations

from dataclasses import dataclass, field


# ── Formatters, the blocks' own ──────────────────────────────────────────────
# gui/block_base.py and tui/block_base.py import these: one definition.

def cr(n) -> str:
    """Credits as the windows show them: 1.5K cr, 12.3M cr, 2.50B cr."""
    if not n:
        return "—"
    try:
        v = int(n)
    except (TypeError, ValueError):
        return "—"
    if v >= 1_000_000_000:
        return f"{v / 1_000_000_000:.2f}B cr"
    if v >= 1_000_000:
        return f"{v / 1_000_000:.1f}M cr"
    if v >= 1_000:
        return f"{v / 1_000:.1f}K cr"
    return f"{v} cr"


def num(n) -> str:
    """A count with thousands separators, "—" for none."""
    if not n:
        return "—"
    try:
        return f"{int(n):,}"
    except (TypeError, ValueError):
        return str(n)


def health_cls(pct) -> str:
    if pct is None:
        return ""
    if pct > 75:
        return "health-good"
    if pct >= 25:
        return "health-warn"
    return "health-crit"


class R:
    """Row constructors, named as the blocks' own helpers are."""

    @staticmethod
    def kv(label, value="—", classes: str = "val", action: str | None = None) -> tuple:
        row = ("kv", "" if label is None else str(label),
               "—" if value is None else str(value), classes)
        return row + (action,) if action else row

    @staticmethod
    def hdr(title) -> tuple:
        return ("hdr", str(title))

    @staticmethod
    def text(body, classes: str = "") -> tuple:
        return ("text", "" if body is None else str(body), classes)

    @staticmethod
    def rule() -> tuple:
        return ("rule",)

    @staticmethod
    def table(label, columns) -> tuple:
        return ("table", str(label), [(str(h), int(w)) for h, w in columns])

    @staticmethod
    def cells(label, values, classes: str = "val", action: str | None = None) -> tuple:
        row = ("cells", str(label), [str(v) for v in values], classes)
        return row + (action,) if action else row


@dataclass
class Tab:
    """One tab of a window: an id that stays put, its title, its rows, and
    optionally pages of its own. ``heading`` is a line above the rows that
    the desktop draws as a section header (the Modules count)."""
    id: str
    title: str
    rows: list = field(default_factory=list)
    pages: list = field(default_factory=list)      # [Tab]
    heading: str = ""


# ── Columns, for the interfaces that draw them in text ──────────────────────

def cells_text(widths: list[int], values: list[str]) -> str:
    """A row of cells as one fixed-width string, right-aligned, ' | '
    between them: how the cargo manifest has always been drawn."""
    return " | ".join(f"{v:>{w}}" for v, w in zip(values, widths))


def table_text(columns: list[tuple[str, int]]) -> str:
    """Column headings over ``cells_text``, three spaces apart."""
    return "   ".join(f"{h:>{w}}" for h, w in columns)


def iter_render(rows):
    """Rows with each table's widths carried to its cells: yields
    (kind, row, widths) for an interface to draw."""
    widths: list[int] = []
    for row in rows or []:
        if not row:
            continue
        if row[0] == "table":
            widths = [w for _h, w in row[2]]
        yield row[0], row, widths


# ── For the wire ──────────────────────────────────────────────────────────────

_CLASS_TONES = (("health-crit", "crit"), ("health-warn", "warn"), ("health-good", "good"),
                ("highlight", "accent"), ("dim", "dim"))


def tone_of(classes: str, text: str = "") -> str | None:
    from core.tooltab import plain
    for cls, tone in _CLASS_TONES:
        if cls in (classes or "").split():
            return tone
    return plain(text)[1]


def wire_rows(rows) -> list[dict]:
    """Model rows as protocol rows: label, value, kind (kv | sub | line |
    cells), an optional tone, and for a table its headings and cells."""
    from core.tooltab import plain
    out: list[dict] = []
    for kind, row, _w in iter_render(rows):
        if kind in ("hdr", "toggle"):
            out.append({"label": plain(row[1])[0].strip(), "value": "", "kind": "sub"})
        elif kind == "kv":
            if not str(row[1]).strip() and not str(row[2]).strip():
                continue                    # a spacer between groups
            label, ltone = plain(row[1])
            value, vtone = plain(row[2])
            r = {"label": label, "value": value, "kind": "kv"}
            tone = tone_of(row[3] if len(row) > 3 else "", row[2]) or vtone or ltone
            if tone:
                r["tone"] = tone
            if len(row) > 4 and row[4]:
                r["action"] = row[4]
            out.append(r)
        elif kind == "text":
            body, tone = plain(row[1])
            if not body.strip():
                continue
            r = {"label": "", "value": body, "kind": "line"}
            tone = tone_of(row[2] if len(row) > 2 else "", row[1]) or tone
            if tone:
                r["tone"] = tone
            out.append(r)
        elif kind == "rule":
            out.append({"label": "", "value": "", "kind": "rule"})
        elif kind == "table":
            out.append({"label": plain(row[1])[0], "value": "", "kind": "head",
                        "cells": [plain(h)[0] for h, _w in row[2]]})
        elif kind == "cells":
            label, _ = plain(row[1])
            values = [plain(v)[0] for v in row[2]]
            r = {"label": label, "value": " · ".join(v for v in values if v),
                 "kind": "cells", "cells": values}
            tone = tone_of(row[3] if len(row) > 3 else "", " ".join(row[2]))
            if tone:
                r["tone"] = tone
            if len(row) > 4 and row[4]:
                r["action"] = row[4]
            out.append(r)
    return out
