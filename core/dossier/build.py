"""
core/dossier/build.py — reading, keeping, and writing the dossier.

    <commander>/data/dossier.json      what the ledger knows, and how far into
                                       each journal it has read
    <commander>/dossier/html/index.html
    <commander>/dossier/md/*.md

``build()`` reads whatever the journals gained since last time, saves the
ledger, and rewrites both outputs. Files are replaced atomically, so a page
open in a browser never sees half a file, and Markdown files for ships no
longer owned are removed.
"""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from core.dossier import render_html, render_md, sources
from core.dossier.ledger import Ledger
from core.dossier.model import Model

STATE_FILE = "dossier.json"


@dataclass
class Settings:
    include_location: bool = False
    include_balance: bool = False


@dataclass
class Result:
    events: int = 0
    pages: int = 0
    written: list = field(default_factory=list)
    removed: list = field(default_factory=list)
    out_dir: Optional[Path] = None


def state_path(cmdr_dir: Path) -> Path:
    return Path(cmdr_dir) / "data" / STATE_FILE


def load_state(cmdr_dir: Path) -> Optional[dict]:
    try:
        return json.loads(state_path(cmdr_dir).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _write(path: Path, text: str) -> bool:
    """Write atomically; skip when the content is already there."""
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        if path.read_text(encoding="utf-8") == text:
            return False
    except OSError:
        pass
    fd, tmp = tempfile.mkstemp(prefix=".tmp-", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(text)
        # mkstemp creates the file readable by its owner only; these are
        # documents, meant to be opened and copied like any other.
        os.chmod(tmp, 0o644)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
    return True


def scan(journal_dir, cmdr_dir: Path, fid: Optional[str]) -> tuple[Ledger, int]:
    """Bring the saved ledger up to date with the journals, and save it."""
    ledger = Ledger(fid=fid, state=load_state(cmdr_dir))
    events = ledger.scan(journal_dir)
    if events or not state_path(cmdr_dir).exists():
        _write(state_path(cmdr_dir), json.dumps(ledger.s, separators=(",", ":")))
    return ledger, events


def build(journal_dir, cmdr_dir: Path, fid: Optional[str], *,
          settings: Settings = Settings(), theme: str = "default",
          core=None, live_balance: Optional[int] = None,
          db_path: Optional[Path] = None, version: str = "",
          now: Optional[float] = None) -> Result:
    from core.palette import palette_for, theme_name

    cmdr_dir = Path(cmdr_dir)
    ledger, events = scan(journal_dir, cmdr_dir, fid)
    if db_path is None:
        try:
            from core.state import shared_data_dir
            db_path = shared_data_dir() / "mining.db"
        except Exception:
            db_path = None
    model = Model(
        ledger.s,
        include_location=settings.include_location,
        include_balance=settings.include_balance,
        deposits=sources.deposits(db_path) if db_path else [],
        carrier_capi=sources.capi_carrier(cmdr_dir),
        career=sources.career(core),
        live_balance=live_balance,
        now=now, version=version,
    ).build()

    out = cmdr_dir / "dossier"
    result = Result(events=events, pages=len(model["pages"]), out_dir=out)
    html_text = render_html.render(model, palette_for(theme), theme_name(theme))
    if _write(out / "html" / "index.html", html_text):
        result.written.append("html/index.html")

    md_dir = out / "md"
    files = render_md.render(model)
    for rel, text in files.items():
        if _write(md_dir / rel, text):
            result.written.append(f"md/{rel}")
    # Pages that no longer exist: a ship sold, a carrier decommissioned. Only
    # files the dossier writes are ever removed; anything else in md/ is the
    # commander's and is left alone.
    ours = set(render_md._FILES.values()) | {"index.md"}
    for path in list(md_dir.rglob("*.md")):
        rel = path.relative_to(md_dir).as_posix()
        if rel not in files and (rel in ours or rel.startswith("ships/")):
            try:
                path.unlink()
                result.removed.append(f"md/{rel}")
            except OSError:
                pass
    return result
