"""
core/dossier/render_md.py — the dossier as Markdown files.

The same pages as the HTML, one file each, in GitHub-flavoured Markdown:

    md/index.md            what is here, with links
    md/commander.md
    md/fleet.md
    md/ships/<id>-<name>.md   one per ship
    md/modules.md, engineering.md, carrier.md, mining.md, on-foot.md

Links between them are relative, so the folder can be moved, committed or
dropped into a wiki as it is.
"""

from __future__ import annotations

import re

from core.dossier.model import when

_FILES = {
    "commander": "commander.md", "fleet": "fleet.md", "modules": "modules.md",
    "engineering": "engineering.md", "carrier": "carrier.md",
    "mining": "mining.md", "on-foot": "on-foot.md",
}


def _slug(text: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", (text or "").lower()).strip("-")
    return slug or "ship"


def file_for(page: dict) -> str:
    """The path of a page's file, relative to md/."""
    if page["id"].startswith("ship-"):
        return f"ships/{page['id'][5:]}-{_slug(page.get('title', ''))}.md"
    return _FILES.get(page["id"], f"{page['id']}.md")


def _esc(text) -> str:
    text = "" if text is None else str(text)
    return text.replace("\\", "\\\\").replace("|", "\\|").replace("\n", " ")


def render(model: dict) -> dict[str, str]:
    """``{relative path: content}`` for every file, index.md included."""
    pages = model["pages"]
    paths = {p["id"]: file_for(p) for p in pages}
    out: dict[str, str] = {}

    for p in pages:
        here = paths[p["id"]]
        depth = here.count("/")
        up = "../" * depth

        def href(page_id: str, _up=up) -> str:
            return _up + paths.get(page_id, "index.md")

        lines = [f"[Dossier]({up}index.md)"
                 + (f" › [{_esc(_nav(pages, p['parent']))}]({href(p['parent'])})"
                    if p.get("parent") else ""),
                 "", f"# {p['title']}", ""]
        if p.get("subtitle"):
            lines += [f"*{p['subtitle']}*", ""]
        for block in p["blocks"]:
            lines += _block(block, href, 2)
        lines += ["---", "", f"*Updated {when(model.get('generated'))} by EDLD "
                  f"{model.get('version', '')}.*", ""]
        out[here] = "\n".join(lines)

    index = [f"# CMDR {model.get('commander', '')} — Dossier", "",
             f"*Updated {when(model.get('generated'))}; journals read to "
             f"{when(model.get('as_of'))}.*", ""]
    for p in pages:
        if p.get("parent"):
            continue
        index.append(f"- [{p['nav']}]({paths[p['id']]}) — {p.get('subtitle', '')}")
        if p["id"] == "fleet":
            for q in pages:
                if q.get("parent") == "fleet":
                    index.append(f"  - [{q['nav']}]({paths[q['id']]}) — {q.get('subtitle', '')}")
    index.append("")
    out["index.md"] = "\n".join(index)
    return out


def _nav(pages, page_id) -> str:
    return next((p["nav"] for p in pages if p["id"] == page_id), page_id)


def _cell(value, href) -> str:
    if isinstance(value, dict):
        text = _esc(value.get("text", ""))
        if value.get("page"):
            return f"[{text}]({href(value['page'])})"
        if value.get("url"):
            return f"[{text}]({value['url']})"
        return text
    return _esc(value)


def _block(block: dict, href, level: int) -> list[str]:
    kind = block["type"]
    title = block.get("title") or ""
    head = [f"{'#' * level} {title}", ""] if title else []
    if kind == "facts":
        if not block["rows"]:
            return []
        return head + [f"- **{_esc(k)}:** {_cell(v, href)}" for k, v in block["rows"]] + [""]
    if kind == "table":
        if not block["rows"]:
            return head + [f"*{block['empty']}*", ""] if block.get("empty") else []
        numeric = block.get("numeric") or set()
        cols = block["columns"]
        lines = ["| " + " | ".join(_esc(c) for c in cols) + " |",
                 "|" + "|".join("---:" if i in numeric else "---"
                                for i in range(len(cols))) + "|"]
        for row in block["rows"]:
            lines.append("| " + " | ".join(_cell(v, href) for v in row) + " |")
        return head + lines + [""]
    if kind == "note":
        return [f"> {block['text']}", ""]
    if kind == "links":
        return head + [f"- [{_esc(i['text'])}]({i['url']})" for i in block["items"]] + [""]
    if kind == "details":
        lines = [f"{'#' * level} {title}", ""]
        for inner in block["blocks"]:
            lines += _block(inner, href, level + 1)
        return lines
    return []
