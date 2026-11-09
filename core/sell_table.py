"""core/sell_table.py — "what is worth selling here", as one table.

One model, three surfaces.  ``sell_table()`` builds the table from state, and
``render_markdown()`` / ``render_html()`` turn it into the files written
beside the catalog.  The TUI and GUI popups render the same dict, so the
files and the popups cannot disagree about what a commodity is worth.

  * a Spansh target market, when one is set and loaded;
  * otherwise the station underfoot, from Market.json;
  * otherwise the galactic average, from the catalog.

NPC prices only
---------------
A commodity with no galactic average is not one NPCs trade.  Stations list
such commodities anyway and quote a sell price for them, but no NPC will pay
it — the price is whatever players set on carriers.  Those rows are dropped,
so the table only ever offers prices that can actually be collected.  Which
commodities those are is read from the catalog, not from the market in
hand, so the judgment improves as more markets are seen.

Carriers
--------
Fleet and squadron carriers are excluded at every point.  Their markets are
player-run, mobile, and change without notice, so a carrier is never treated
as the focused station — the table falls through to whatever was quoting
before it, exactly as if the commander had not docked at all.  The test is a
substring rather than a fixed list of station types, because Frontier's
``FleetCarrier`` and Spansh's ``Drake-Class Carrier`` are two spellings of the
same thing and a squadron carrier will be a third.
"""

from __future__ import annotations

import html as _html

from core.ui_helpers import cargo_price_context
from data.mining import is_mineable

#: What the table calls itself when it is quoting nothing in particular.
GALACTIC_LABEL = "Galactic Average"


def is_carrier(station_type: str) -> bool:
    """True for any flavor of carrier, however the source spells it."""
    return "carrier" in (station_type or "").lower()


# ── Model ─────────────────────────────────────────────────────────────────────

def sell_table(state, ledger_rows: dict | None = None) -> dict:
    """Resolve the sell table for the current moment.

    Returns ``{"mode", "source_label", "rows"}`` where each row is
    ``{"name", "price"}`` and rows are ordered by price, highest first.
    """
    ctx = cargo_price_context(state)
    mode = ctx["mode"]
    label = ctx["source_label"]
    comms: dict = {}

    if mode == "target":
        target = getattr(state, "cargo_target_market", {}) or {}
        if is_carrier(target.get("station_type", "")):
            mode = "galactic"
        else:
            comms = ctx["tgt_comms"]
    elif mode == "station":
        # cargo_market_info is already carrier-free — the Market.json reader
        # declines to record one — so an empty market here means either a
        # carrier underfoot or nowhere docked.  Either way there is no focused
        # station and the galactic average is the honest answer.
        comms = ctx["gal_comms"]
        if not comms:
            mode = "galactic"

    if mode == "galactic":
        label = GALACTIC_LABEL
        rows = _rows_from_ledger(ledger_rows or {})
    else:
        rows = _rows_from_market(comms, _non_npc_names(ledger_rows or {}))

    rows.sort(key=lambda r: (-r["price"], r["name"].lower()))
    return {"mode": mode, "source_label": label, "rows": rows}


def _squash(name: str) -> str:
    """Reduce a display name to something two sources can agree on."""
    return "".join(ch for ch in str(name or "").lower() if ch.isalnum())


def _non_npc_names(ledger_rows: dict) -> set[str]:
    """Squashed names of commodities no NPC market has ever priced."""
    return {
        _squash(row.get("name_localised") or key)
        for key, row in (ledger_rows or {}).items()
        if _int(row.get("mean_price", 0)) <= 0
    }


def _rows_from_market(comms: dict, non_npc: set[str] | None = None) -> list[dict]:
    """Rows from a station's own market — what it will pay, per ton."""
    non_npc = non_npc or set()
    rows = []
    for key, c in (comms or {}).items():
        price = _int(c.get("sell_price", 0))
        if price <= 0:
            continue
        name = c.get("name_local") or _pretty(key)
        if _squash(name) in non_npc or _squash(key) in non_npc:
            continue
        rows.append({
            "name":     name,
            "price":    price,
            "mineable": is_mineable(name, c.get("category", ""))
                        or is_mineable(key, c.get("category_local", "")),
        })
    return rows


def _rows_from_ledger(ledger_rows: dict) -> list[dict]:
    """Rows from the commodity catalog — the galactic average."""
    rows = []
    for key, r in (ledger_rows or {}).items():
        price = _int(r.get("mean_price", 0))
        if price <= 0:
            continue
        name = r.get("name_localised") or _pretty(key)
        rows.append({
            "name":     name,
            "price":    price,
            "mineable": is_mineable(name, r.get("category", ""))
                        or is_mineable(key),
        })
    return rows


def _int(value, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _pretty(key: str) -> str:
    return str(key).replace("_", " ").title()


def _credits(n: int) -> str:
    return f"{int(n):,} cr"


# ── Renderers ─────────────────────────────────────────────────────────────────

def render_markdown(table: dict) -> str:
    """The table as GitHub-flavoured Markdown."""
    label = table.get("source_label") or GALACTIC_LABEL
    lines = [f"# {label}", "", "| Commodity | Sell |", "| --- | ---: |"]
    for row in table.get("rows", []):
        # Escape the cell separator; nothing else in a commodity name can
        # break a Markdown table.
        name = str(row["name"]).replace("|", "\\|")
        lines.append(f"| {name} | {_credits(row['price'])} |")
    if not table.get("rows"):
        lines.append("| _no prices available_ | |")
    lines.append("")
    return "\n".join(lines)


#: Self-contained so the file opens correctly from anywhere — no stylesheet to
#: ship alongside it, and no assumption about the reader's browser theme.
_HTML_CSS = """\
:root { color-scheme: light dark; }
body { font: 15px/1.5 system-ui, -apple-system, Segoe UI, Roboto, sans-serif;
       margin: 2rem auto; max-width: 42rem; padding: 0 1rem; }
h1 { font-size: 1.25rem; font-weight: 600; margin: 0 0 1rem; }
table { border-collapse: collapse; width: 100%; }
th, td { padding: .35rem .6rem; border-bottom: 1px solid rgba(128,128,128,.3); }
th { text-align: left; font-weight: 600; }
th.num, td.num { text-align: right; font-variant-numeric: tabular-nums; }
tbody tr:hover { background: rgba(128,128,128,.12); }
"""


def render_html(table: dict) -> str:
    """The table as a standalone HTML document."""
    label = table.get("source_label") or GALACTIC_LABEL
    esc = _html.escape
    parts = [
        "<!doctype html>",
        '<html lang="en"><head><meta charset="utf-8">',
        '<meta name="viewport" content="width=device-width,initial-scale=1">',
        f"<title>EDLD — {esc(label)}</title>",
        f"<style>{_HTML_CSS}</style></head><body>",
        f"<h1>{esc(label)}</h1>",
        '<table><thead><tr><th>Commodity</th><th class="num">Sell</th></tr>'
        "</thead><tbody>",
    ]
    for row in table.get("rows", []):
        parts.append(
            f'<tr><td>{esc(str(row["name"]))}</td>'
            f'<td class="num">{esc(_credits(row["price"]))}</td></tr>'
        )
    if not table.get("rows"):
        parts.append('<tr><td colspan="2">No prices available.</td></tr>')
    parts.append("</tbody></table></body></html>")
    return "\n".join(parts) + "\n"


def mineable_rows(table: dict) -> list[dict]:
    """Just the rows a mining laser can produce, in the same order."""
    return [r for r in table.get("rows", []) if r.get("mineable")]


def render_columns(table: dict, mineable_only: bool = False) -> list[tuple[str, str]]:
    """The table as (name, price) string pairs, for the TUI and GUI popups.
    """
    rows = mineable_rows(table) if mineable_only else table.get("rows", [])
    return [(str(r["name"]), _credits(r["price"])) for r in rows]
