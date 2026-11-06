"""
core/dossier/render_html.py — the dossier as one self-contained web page.

One file, ``html/index.html``, with every page in it as a section and the
navigation done in CSS (``:target``): no script, no network, nothing beside
it. It opens from disk in any current browser and reads the same anywhere it
is copied to. A ship has its own address, ``index.html#ship-36``.

The colours are the EDLD theme in use when it was written, custom themes
included, so it is regenerated when the theme changes. The frame — a rail
down the left joined to a bar across the top by a curved elbow — is an
original layout in that spirit, drawn entirely from the theme's colours.

Headings are set in Euro Caps, the face EDLD's overlay uses, embedded in the
page from EDLD's own ``fonts/`` so the file stays self-contained.
"""

from __future__ import annotations

import base64
import html
from functools import lru_cache
from pathlib import Path

from core.dossier.model import when

_ROOT = Path(__file__).resolve().parents[2]


def _e(text) -> str:
    return html.escape("" if text is None else str(text), quote=True)


def _fonts_dir() -> Path:
    """Where EDLD's own fonts are, frozen or not — as core/overlay_proc.py."""
    import sys
    base = getattr(sys, "_MEIPASS", None)
    return Path(base) / "fonts" if base else _ROOT / "fonts"


@lru_cache(maxsize=1)
def _font_face() -> str:
    """The heading face, embedded. Nothing when it is not shipped — the
    EDLD-server build has no fonts — and the headings fall back to a system
    face."""
    path = _fonts_dir() / "EUROCAPS.TTF"
    try:
        data = base64.b64encode(path.read_bytes()).decode("ascii")
    except OSError:
        return ""
    return ("@font-face{font-family:'Dossier Caps';"
            f"src:url(data:font/ttf;base64,{data}) format('truetype');"
            "font-display:swap}")


def _palette_css(palette: dict) -> str:
    keys = ("bg", "block-bg", "title-bg", "fg", "dim", "accent", "border",
            "green", "amber", "red", "row-alt")
    lines = [f"--{k}:{palette.get('$' + k, '')};" for k in keys if palette.get("$" + k)]
    return ":root{" + "".join(lines) + "}"


_CSS = r"""
*{box-sizing:border-box}
html{background:var(--bg);color:var(--fg)}
body{margin:0;background:var(--bg);color:var(--fg);
  font:15px/1.5 system-ui,-apple-system,"Segoe UI",Roboto,"Noto Sans",sans-serif;
  font-variant-numeric:tabular-nums}
a{color:var(--accent)}
.caps{font-family:'Dossier Caps',"Arial Narrow",system-ui,sans-serif;
  letter-spacing:.06em;text-transform:uppercase}

/* the frame: one continuous L — a band across the top and a rail down the
   left, joined by an elbow with a curved inner corner */
.frame{display:grid;grid-template-columns:190px 1fr;grid-template-rows:64px 1fr;
  min-height:100vh}
.elbow{grid-column:1;grid-row:1;background:var(--accent);
  border-top-left-radius:46px;position:relative}
.elbow::after{content:"";position:absolute;right:-28px;bottom:-28px;width:28px;
  height:28px;pointer-events:none;
  background:radial-gradient(circle at 100% 100%,transparent 27.5px,var(--accent) 28px)}
.bar{grid-column:2;grid-row:1;display:flex;align-items:stretch;gap:6px;background:var(--bg)}
.bar-main{flex:1;background:var(--accent);color:var(--bg);display:flex;
  align-items:flex-end;justify-content:space-between;gap:16px;padding:0 18px 9px 22px}
.bar-main .cmdr{font-size:25px;line-height:1}
.bar-main .stamp{font-size:13px;opacity:.85;white-space:nowrap;line-height:1}
.bar-cap{width:46px;background:color-mix(in srgb,var(--accent) 60%,var(--bg));
  border-radius:0 32px 32px 0}
.rail{grid-column:1;grid-row:2;display:flex;flex-direction:column;gap:5px;
  padding:5px 0 0;background:var(--bg)}
.rail a{display:flex;align-items:flex-end;justify-content:flex-end;min-height:38px;
  text-decoration:none;color:var(--bg);padding:0 14px 6px;font-size:15px;line-height:1.1;
  text-align:right;background:color-mix(in srgb,var(--accent) 58%,var(--bg))}
.rail a:hover{background:color-mix(in srgb,var(--accent) 82%,var(--bg))}
.rail .ships{display:flex;flex-direction:column;gap:3px;margin:0 0 0 30px}
.rail .ships a{min-height:24px;padding:0 12px 4px;font-size:12px;color:var(--fg);
  background:color-mix(in srgb,var(--dim) 42%,var(--bg))}
.rail .fill{flex:1;min-height:60px;border-bottom-left-radius:46px;
  background:color-mix(in srgb,var(--accent) 35%,var(--bg))}
main{grid-column:2;grid-row:2;padding:30px 30px 60px 40px;min-width:0}
.view{scroll-margin-top:200px}

/* one page at a time */
.view{display:none}
.view:target{display:block}
main:not(:has(.view:target)) #commander{display:block}

h1{font-size:34px;margin:4px 0 0;line-height:1.1;color:var(--fg)}
.subtitle{margin:2px 0 22px;color:var(--dim);font-size:14px}
.crumbs{font-size:13px;margin:0 0 6px;color:var(--dim)}
.crumbs a{color:var(--dim)}
h2{display:flex;align-items:center;gap:12px;margin:26px 0 10px;font-size:17px;
  color:var(--accent)}
h2::after{content:"";flex:1;height:6px;border-radius:3px;
  background:color-mix(in srgb,var(--accent) 35%,var(--bg))}
h3{font-size:14px;margin:18px 0 8px;color:var(--fg)}

.facts{display:grid;grid-template-columns:minmax(150px,max-content) 1fr;gap:4px 22px;
  margin:0 0 6px;padding:12px 16px;background:var(--block-bg);border:1px solid var(--border);
  border-left:6px solid var(--accent);border-radius:0 10px 10px 0;max-width:820px}
.facts dt{color:var(--dim)}
.facts dd{margin:0}
.table-wrap{overflow-x:auto;border:1px solid var(--border);border-radius:8px;
  background:var(--block-bg)}
table{border-collapse:collapse;width:100%;font-size:14px}
th{text-align:left;font-weight:600;color:var(--dim);background:var(--title-bg);
  padding:7px 10px;border-bottom:1px solid var(--border);white-space:nowrap}
td{padding:6px 10px;border-bottom:1px solid var(--border);vertical-align:top}
tr:last-child td{border-bottom:0}
tbody tr:nth-child(even) td{background:color-mix(in srgb,var(--row-alt) 45%,var(--block-bg))}
th.num,td.num{text-align:right;white-space:nowrap}
td.nw{white-space:nowrap}
td a{color:var(--accent);font-weight:600;text-decoration:none}
td a:hover{text-decoration:underline}
.note{color:var(--dim);font-size:13px;max-width:820px;margin:10px 0}
.empty{color:var(--dim);font-style:italic}
.links{display:flex;flex-wrap:wrap;gap:8px;margin:4px 0}
.links a{display:inline-block;text-decoration:none;color:var(--bg);background:var(--accent);
  padding:7px 16px 6px;border-radius:18px;font-size:13px}
.links a:hover{filter:brightness(1.1)}
details{margin:14px 0;border:1px solid var(--border);border-radius:8px;
  background:var(--block-bg);padding:0 14px}
details>summary{cursor:pointer;padding:10px 0;color:var(--accent);font-weight:600}
details[open]{padding-bottom:12px}
details .table-wrap{background:var(--bg)}
footer{grid-column:2;padding:0 28px 24px;color:var(--dim);font-size:12px}

@media (max-width:760px){
  .frame{grid-template-columns:1fr;grid-template-rows:auto auto 1fr}
  .elbow,.bar-cap,.rail .fill{display:none}
  .bar{grid-column:1;padding:0}
  .bar-main{border-radius:0 0 18px 18px;padding:14px 16px 10px;flex-wrap:wrap}
  .rail{grid-column:1;grid-row:2;flex-direction:row;overflow-x:auto;padding:8px 10px;gap:6px}
  .rail a{border-radius:16px;white-space:nowrap;min-height:0;padding:7px 14px 6px}
  .rail .ships{flex-direction:row;margin:0}
  main{grid-column:1;grid-row:3;padding:16px}
  footer{grid-column:1;padding:0 16px 20px}
  .facts{grid-template-columns:1fr}
  .facts dd{margin-bottom:6px}
}
@media print{
  .rail,.elbow,.bar-cap{display:none}
  .frame{display:block}
  .view{display:block!important;page-break-after:always}
  details{display:block}
}
"""


def render(model: dict, palette: dict, theme_name: str = "") -> str:
    pages = model["pages"]
    ids = [p["id"] for p in pages]

    def href(page_id: str) -> str:
        return f"#{page_id}" if page_id in ids else "#"

    # Highlight the rail button of the page on screen — the Fleet button too
    # while one of its ships is.
    active = []
    for p in pages:
        sel = f'body:has(#{p["id"]}:target) .rail a[href="#{p["id"]}"]'
        active.append(sel)
        if p.get("parent"):
            active.append(f'body:has(#{p["id"]}:target) .rail a[href="#{p["parent"]}"]')
    active.append('body:not(:has(.view:target)) .rail a[href="#commander"]')
    active_css = (",".join(active) +
                  "{background:var(--accent)!important;color:var(--bg)!important}")

    rail = []
    for p in pages:
        if p.get("parent"):
            continue
        rail.append(f'<a class="caps" href="#{_e(p["id"])}">{_e(p["nav"])}</a>')
        if p["id"] == "fleet":
            ships = [q for q in pages if q.get("parent") == "fleet"]
            if ships:
                rail.append('<div class="ships">' + "".join(
                    f'<a class="caps" href="#{_e(q["id"])}">{_e(q["nav"])}</a>'
                    for q in ships) + "</div>")
    rail.append('<div class="fill"></div>')

    sections = []
    for p in pages:
        crumbs = ""
        if p.get("parent"):
            parent = next((q for q in pages if q["id"] == p["parent"]), None)
            if parent:
                crumbs = (f'<p class="crumbs caps"><a href="#{_e(parent["id"])}">'
                          f'{_e(parent["nav"])}</a> ›</p>')
        body = "".join(_block(b, href) for b in p["blocks"])
        sections.append(
            f'<section class="view" id="{_e(p["id"])}">{crumbs}'
            f'<h1 class="caps">{_e(p["title"])}</h1>'
            f'<p class="subtitle">{_e(p.get("subtitle", ""))}</p>{body}</section>')

    stamp = f"Updated {when(model.get('generated'))}"
    title = f"CMDR {model.get('commander', '')} — Dossier"
    footer = (f"Generated by EDLD {_e(model.get('version', ''))}"
              + (f" · theme {_e(theme_name)}" if theme_name else "")
              + f" · journals read to {_e(when(model.get('as_of')))}")
    return (
        "<!doctype html>\n<html lang=\"en\"><head><meta charset=\"utf-8\">"
        "<meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">"
        "<meta name=\"generator\" content=\"EDLD\">"
        f"<title>{_e(title)}</title><style>{_font_face()}{_palette_css(palette)}"
        f"{_CSS}{active_css}</style></head><body>"
        '<div class="frame">'
        '<div class="elbow"></div>'
        '<header class="bar"><div class="bar-main">'
        f'<span class="cmdr caps">CMDR {_e(model.get("commander", ""))}</span>'
        f'<span class="stamp caps">Dossier · {_e(stamp)}</span></div>'
        '<div class="bar-cap"></div></header>'
        f'<nav class="rail" aria-label="Dossier">{"".join(rail)}</nav>'
        f'<main>{"".join(sections)}</main>'
        f'<footer>{footer}</footer>'
        "</div></body></html>\n")


# ── blocks ────────────────────────────────────────────────────────────────────

def _cell(value, href) -> str:
    if isinstance(value, dict):
        text = _e(value.get("text", ""))
        if value.get("page"):
            return f'<a href="{_e(href(value["page"]))}">{text}</a>'
        if value.get("url"):
            return (f'<a href="{_e(value["url"])}" rel="noopener noreferrer" '
                    f'target="_blank">{text}</a>')
        return text
    return _e(value)


def _block(block: dict, href, level: int = 2) -> str:
    kind = block["type"]
    title = block.get("title") or ""
    head = f'<h{level} class="caps">{_e(title)}</h{level}>' if title else ""
    if kind == "facts":
        if not block["rows"]:
            return ""
        rows = "".join(f"<dt>{_e(k)}</dt><dd>{_cell(v, href)}</dd>"
                       for k, v in block["rows"])
        return f'{head}<dl class="facts">{rows}</dl>'
    if kind == "table":
        if not block["rows"]:
            return (f'{head}<p class="empty">{_e(block.get("empty") or "Nothing recorded.")}</p>'
                    if block.get("empty") else "")
        numeric = block.get("numeric") or set()
        nowrap = block.get("nowrap") or set()

        def cls(i):
            names = (["num"] if i in numeric else []) + (["nw"] if i in nowrap else [])
            return f' class="{" ".join(names)}"' if names else ""
        cols = "".join(f"<th{cls(i)}>{_e(c)}</th>"
                       for i, c in enumerate(block["columns"]))
        body = "".join(
            "<tr>" + "".join(f"<td{cls(i)}>{_cell(v, href)}</td>"
                             for i, v in enumerate(row)) + "</tr>"
            for row in block["rows"])
        return (f'{head}<div class="table-wrap"><table><thead><tr>{cols}</tr></thead>'
                f"<tbody>{body}</tbody></table></div>")
    if kind == "note":
        return f'<p class="note">{_e(block["text"])}</p>'
    if kind == "links":
        items = "".join(
            f'<a class="caps" href="{_e(i["url"])}" rel="noopener noreferrer" '
            f'target="_blank">{_e(i["text"])}</a>' for i in block["items"])
        return f'{head}<div class="links">{items}</div>'
    if kind == "details":
        inner = "".join(_block(b, href, level=3) for b in block["blocks"])
        return f"<details><summary>{_e(title)}</summary>{inner}</details>"
    return ""
