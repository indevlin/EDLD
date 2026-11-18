#!/usr/bin/env python3
"""Post a release's changelog section to a Discord webhook.

The webhook comes from DISCORD_WEBHOOK_URL; with none set, nothing is posted
and the exit status is 0. Any rejection by Discord exits 1 with its reply.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.error
import urllib.request

#: Discord's limit for an embed description is 4096; this leaves room for the
#: closing line.
DESCRIPTION_LIMIT = 3900

#: Discord blurple, as an integer colour.
EMBED_COLOR = 0x5865F2


def section(changelog: str, version: str) -> str:
    """The text under ``## Released in <version>``, up to the next release."""
    lines = changelog.splitlines()
    out: list[str] = []
    inside = False
    head = re.compile(rf"^## Released in {re.escape(version)}\s*$")
    for line in lines:
        if inside and line.startswith("## Released in "):
            break
        if inside:
            out.append(line)
        elif head.match(line):
            inside = True
    text = "\n".join(out).strip()
    return re.sub(r"\n-{3,}\s*$", "", text).strip()


def headings(text: str) -> list[str]:
    """Each ``###`` heading in ``text``, without its hashes."""
    return [l[4:].strip() for l in text.splitlines() if l.startswith("### ")]


def to_discord(text: str) -> str:
    """Markdown from the changelog, unwrapped and with headings in bold."""
    out: list[str] = []
    para: list[str] = []
    fenced = False

    def flush() -> None:
        if para:
            out.append(" ".join(s.strip() for s in para))
            para.clear()

    for line in text.splitlines():
        if line.startswith("```"):
            flush()
            fenced = not fenced
            out.append(line)
        elif fenced:
            out.append(line)
        elif not line.strip():
            flush()
            out.append("")
        elif line.startswith("#"):
            flush()
            out.append(f"**{line.lstrip('#').strip()}**")
        elif re.match(r"^\s*([-*|]|\d+\.)\s", line):
            flush()
            out.append(line)
        else:
            para.append(line)
    flush()
    return re.sub(r"\n{3,}", "\n\n", "\n".join(out)).strip()


def description(text: str, limit: int = DESCRIPTION_LIMIT) -> str:
    """The whole section when it fits, else its headings, as many as fit."""
    full = to_discord(text)
    if len(full) <= limit:
        return full
    items = [f"• {h}" for h in headings(text)]
    dropped = 0
    while items:
        tail = f"\n…and {dropped} more" if dropped else ""
        body = "\n".join(items) + tail
        if len(body) <= limit:
            return body
        items.pop()
        dropped += 1
    return full[:limit - 1].rstrip() + "…"


def payload(product: str, version: str, text: str, link: str, label: str) -> dict:
    footer = f"\n\n[{label}]({link})"
    body = description(text, DESCRIPTION_LIMIT - len(footer)) or "See the release for details."
    return {
        "embeds": [{
            "title": f"{product} {version}",
            "url": link,
            "description": body + footer,
            "color": EMBED_COLOR,
        }],
        "allowed_mentions": {"parse": []},
    }


def post(url: str, data: dict) -> None:
    req = urllib.request.Request(
        url, data=json.dumps(data).encode("utf-8"), method="POST",
        headers={"Content-Type": "application/json",
                 "User-Agent": "release-announce (urllib)"})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            if resp.status not in (200, 204):
                raise RuntimeError(f"HTTP {resp.status}: {resp.read()[:500]!r}")
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"HTTP {e.code}: {e.read()[:500].decode('utf-8', 'replace')}")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--product", required=True)
    ap.add_argument("--version", required=True)
    ap.add_argument("--changelog", required=True)
    ap.add_argument("--link", required=True)
    ap.add_argument("--link-label", default="Release notes")
    ap.add_argument("--dry-run", action="store_true", help="print the payload, post nothing")
    args = ap.parse_args(argv)

    with open(args.changelog, encoding="utf-8") as fh:
        text = section(fh.read(), args.version)
    if not text:
        print(f"::error::No '## Released in {args.version}' section in {args.changelog}")
        return 1
    data = payload(args.product, args.version, text, args.link, args.link_label)

    if args.dry_run:
        print(json.dumps(data, indent=2, ensure_ascii=False))
        return 0
    url = os.environ.get("DISCORD_WEBHOOK_URL", "").strip()
    if not url:
        print("DISCORD_WEBHOOK_URL is not set; nothing posted.")
        return 0
    try:
        post(url, data)
    except (RuntimeError, OSError) as e:
        print(f"::error::Discord rejected the announcement: {e}")
        return 1
    print(f"Announced {args.product} {args.version} on Discord.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
