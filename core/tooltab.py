"""
core/tooltab.py — a Navigation tab described once, drawn everywhere.

Every tab of the Navigation window but Route is described here: its fields,
the button, what to fill in from the game, and what to run — the FSD, Neutron
and Carrier plot forms (core/plot_tools.py), survey routes, nearby systems,
the nearest service, discoveries. gui/blocks and tui/blocks draw any ToolTab
the same way and run it off the UI thread, and a paired EDAM device is sent
the same description (``describe``), draws it, and has EDLD run it (``cmd
tool`` in core/server/service.py) — so all three show the same form and the
same answer.

A run returns a ToolResult: a status line, rows in the markup both front ends
draw — ("hdr", title) / ("kv", key, value) / ("text", body) — and optionally
a route to store and follow, as (Spansh-shaped result, kind).
"""
from __future__ import annotations

import re as _re
from dataclasses import dataclass, field
from typing import Any, Callable


@dataclass(frozen=True)
class Field:
    key: str
    label: str
    kind: str = "text"                 # "text" | "choice" | "check"
    choices: tuple = ()                # (value, label) pairs for "choice"
    default: Any = ""

    def __post_init__(self):
        # A check's default given where its choices go — Field(k, l, "check",
        # True) — was taken as the choices and the default lost.
        if not isinstance(self.choices, (tuple, list)):
            raise TypeError(f"Field {self.key!r}: choices must be (value, label) pairs; "
                            f"pass a default as default=")
    #: Shown only when the "kind" field (if the tab has one) has one of these
    #: values; empty means always shown.
    only_for: tuple = ()
    #: Show a paste button beside it (the desktop window): a system name.
    system: bool = False


@dataclass
class ToolResult:
    status: str
    rows: list = field(default_factory=list)
    route: tuple | None = None          # (result, kind) to store and follow


@dataclass(frozen=True)
class ToolTab:
    id: str                             # widget id prefix, e.g. "survey"
    title: str                          # tab label
    fields: tuple
    button: str
    #: run(core, values) -> ToolResult. Called on a worker thread.
    run: Callable[[Any, dict], ToolResult]
    #: autofill(core) -> {key: value}: values that follow the game until the
    #: commander types in the field.
    autofill: Callable[[Any], dict] | None = None
    #: intro(core) -> str: a dim line above the form, refreshed with the game.
    intro: Callable[[Any], str] | None = None
    #: Place among the tabs, lowest first: the plot forms, then the finders.
    order: int = 100


def visible(tab: ToolTab, f: Field, values: dict) -> bool:
    if not f.only_for:
        return True
    return str(values.get("kind", "")) in f.only_for


def parse_values(tab: ToolTab, raw: dict) -> dict:
    """The widgets' text as the run expects it: checks as bools, empty
    choices as their default."""
    out = {}
    for f in tab.fields:
        v = raw.get(f.key, f.default)
        if f.kind == "check":
            out[f.key] = v if isinstance(v, bool) else str(v).lower() in ("1", "true", "on", "yes")
        elif f.kind == "choice":
            vals = [str(c[0]) for c in f.choices]
            out[f.key] = str(v) if str(v) in vals else str(f.default or (vals[0] if vals else ""))
        else:
            out[f.key] = str(v or "").strip()
    return out


def number(values: dict, key: str, lo: float, hi: float, default: float | None = None,
           integer: bool = False, name: str | None = None):
    """A field's number within [lo, hi], raising ValueError with a message the
    form can show. ``name`` is what the message calls it."""
    what = name or key.replace("_", " ").capitalize()
    raw = str(values.get(key, "") or "").strip()
    if not raw:
        if default is None:
            raise ValueError(f"{what} is required.")
        return default
    try:
        v = float(raw)
    except ValueError:
        raise ValueError(f"{what} must be a number.")
    if not lo <= v <= hi:
        raise ValueError(f"{what} must be {lo:g}–{hi:g}.")
    return int(v) if integer else v


def tabs(core) -> list[ToolTab]:
    """The tool tabs the loaded components offer, in order."""
    out: list[ToolTab] = []
    for plugin in list(getattr(core, "_plugins", {}).values()):
        fn = getattr(plugin, "navigation_tool_tabs", None)
        if callable(fn):
            try:
                out += list(fn() or [])
            except Exception as exc:
                try:
                    from core import debug as _dbg
                    _dbg.info(f"  [Tools] {type(plugin).__name__}: {type(exc).__name__}: {exc}")
                except Exception:
                    pass
    out.sort(key=lambda t: t.order)
    return out


# ── For EDAM ──────────────────────────────────────────────────────────────────
#
# A device draws a tab from its description and sends the values back; EDLD
# runs it and sends the result. Text goes plain, with the colour it was
# marked up in as a tone: good, warn, crit, accent or dim.

# One Rich style word, and a tag of one or more of them: "[green]", and also
# "[bold cyan]" and its "[/bold cyan]", which the one-word pattern this used
# to be left in the text — EDAM showed "[bold cyan]HIP 73225[/bold cyan]" as
# the heading of a colonisation site. "[/]" closes whatever is open.
_STYLE = (r"(?:b|i|u|s|dim|bold|italic|underline|reverse|strike|green|yellow|red|cyan|"
          r"magenta|blue|white|black|orange|bright_[a-z]+)")
_TAG = _re.compile(rf"\[/?{_STYLE}(?: +{_STYLE})*\]|\[/\]")
_OPEN = _re.compile(rf"\[({_STYLE}(?: +{_STYLE})*)\]")
_TONES = (("red", "crit"), ("yellow", "warn"), ("orange", "warn"), ("green", "good"),
          ("cyan", "accent"), ("magenta", "accent"), ("blue", "accent"), ("dim", "dim"))


def plain(text) -> tuple[str, str | None]:
    """(text without markup, the tone of its most urgent colour, or None):
    a row marked partly red reads as critical, whatever else is coloured."""
    raw = "" if text is None else str(text)
    words = {w for m in _OPEN.finditer(raw) for w in m.group(1).split()}
    tone = next((t for tag, t in _TONES if tag in words), None)
    return _TAG.sub("", raw), tone


def wire_rows(rows) -> list[dict]:
    """ToolResult rows as wire rows: ("hdr", t) a sub-heading, ("kv", l, v)
    a row, anything else a line."""
    out = []
    for r in rows or []:
        if not r:
            continue
        if r[0] == "hdr":
            text, tone = plain(r[1])
            out.append({"label": text, "value": "", "kind": "sub"})
        elif r[0] == "kv":
            label, _ = plain(r[1])
            value, tone = plain(r[2] if len(r) > 2 else "")
            row = {"label": label, "value": value, "kind": "kv"}
            if tone:
                row["tone"] = tone
            out.append(row)
        else:
            text, tone = plain(r[1] if len(r) > 1 else "")
            row = {"label": "", "value": text, "kind": "line"}
            if tone:
                row["tone"] = tone
            out.append(row)
    return out


def describe(tab: ToolTab, core) -> dict:
    """What a device needs to draw a tab: its fields, their choices, which
    route kinds each applies to, the values that follow the game, and the
    line above the form."""
    try:
        fills = (tab.autofill(core) or {}) if tab.autofill else {}
    except Exception:
        fills = {}
    try:
        intro = plain(tab.intro(core) or "")[0] if tab.intro else ""
    except Exception:
        intro = ""
    return {
        "id": tab.id, "title": tab.title, "button": tab.button,
        "fields": [{"key": f.key, "label": f.label, "kind": f.kind,
                    "choices": [[str(v), str(l)] for v, l in f.choices],
                    "default": f.default if isinstance(f.default, bool) else str(f.default or ""),
                    "onlyFor": list(f.only_for), "system": bool(f.system)}
                   for f in tab.fields],
        "values": {k: str(v) for k, v in fills.items() if v not in (None, "")},
        "intro": intro,
    }


def result_message(tab: ToolTab, cid, result: ToolResult) -> dict:
    status, tone = plain(result.status)
    return {"t": "toolResult", "id": cid, "tool": tab.id, "status": status,
            "tone": tone, "rows": wire_rows(result.rows), "route": bool(result.route)}


def store_route(core, result: ToolResult) -> bool:
    """Make a tab's plotted route the followed route, wherever it was run."""
    if not result.route:
        return False
    nav = (getattr(core, "_plugins", None) or {}).get("navigation")
    if nav is None:
        return False
    try:
        nav.store_route(*result.route)
        return True
    except Exception as exc:
        try:
            from core import debug as _dbg
            _dbg.info(f"  [Nav] could not store plotted route: {exc}")
        except Exception:
            pass
        return False


def run(tab: ToolTab, core, values: dict) -> ToolResult:
    """Run a tab from any interface or a device: the answer, with any route
    it plotted already stored as the followed route."""
    result = run_safely(tab, core, values)
    store_route(core, result)
    return result


def run_safely(tab: ToolTab, core, values: dict) -> ToolResult:
    try:
        return tab.run(core, parse_values(tab, values))
    except ValueError as exc:
        return ToolResult(f"[red]{exc}[/red]")
    except Exception as exc:
        try:
            from core import debug as _dbg
            _dbg.exception(f"{tab.title} failed", exc)
        except Exception:
            pass
        return ToolResult(f"[red]{tab.title} failed: {type(exc).__name__}: {exc}[/red]")
