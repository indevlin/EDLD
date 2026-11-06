"""
components/backups.py — automatic journal backups.

The game's journals are the only record of a commander's history, and the
game never backs them up: a reinstall, a cleaned-out Saved Games folder or a
new PC and they are gone. Everything EDLD knows is rebuilt from them.

At startup, on Shutdown, and hourly while running, every journal that is new
or has grown since its last copy is written, compressed, to the backup folder
(``journal-backups`` in EDLD's data folder unless set otherwise). Copies are
never deleted: a journal is a few hundred kilobytes and compresses tenfold.
The game's other files (Cargo.json, NavRoute.json, …) are snapshots rewritten
constantly, so only the journals are kept.
"""
from __future__ import annotations

import gzip
import json
import shutil
import threading
from pathlib import Path

from core.plugin_loader import BasePlugin
from core.settings_spec import Action, Heading, Setting, SettingsSpecMixin

_INTERVAL_S = 3600
_MANIFEST = "manifest.json"


def backup_journals(journal_dir: Path, dest: Path) -> tuple[int, int]:
    """Copy new and grown journals from ``journal_dir`` into ``dest`` as
    ``<name>.gz``. Returns (copied, total journals)."""
    dest.mkdir(parents=True, exist_ok=True)
    man_path = dest / _MANIFEST
    try:
        manifest = json.loads(man_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        manifest = {}
    files = sorted(Path(journal_dir).glob("Journal*.log"))
    copied = 0
    for src in files:
        try:
            size = src.stat().st_size
        except OSError:
            continue
        if manifest.get(src.name) == size and (dest / (src.name + ".gz")).exists():
            continue
        tmp = dest / (src.name + ".gz.part")
        try:
            with src.open("rb") as fin, gzip.open(tmp, "wb", compresslevel=6) as fout:
                shutil.copyfileobj(fin, fout)
            tmp.replace(dest / (src.name + ".gz"))
        except OSError:
            try:
                tmp.unlink()
            except OSError:
                pass
            continue
        manifest[src.name] = size
        copied += 1
    if copied:
        tmp = man_path.with_suffix(".part")
        tmp.write_text(json.dumps(manifest, indent=0, sort_keys=True), encoding="utf-8")
        tmp.replace(man_path)
    return copied, len(files)


class BackupsPlugin(SettingsSpecMixin, BasePlugin):
    PLUGIN_NAME = "backups"
    PLUGIN_DISPLAY = "Journal Backups"
    PLUGIN_VERSION = "1.0.0"
    PLUGIN_DESCRIPTION = "Keeps a compressed copy of every journal the game writes."
    SUBSCRIBED_EVENTS = ["Shutdown"]

    SETTINGS_SECTION = "Backups"
    SETTINGS_TAB = ("pref-tab-backups", "Backups")
    SETTINGS = (
        Heading("Journal backups",
                "A compressed copy of every journal, kept when the game's own are lost."),
        Setting("Enabled", "Back up journals automatically", bool, True),
        Setting("Folder", "Backup folder (empty: EDLD's data folder)", str, ""),
        Action("backup-now", "Back up now"),
    )

    def on_load(self, core) -> None:
        super().on_load(core)
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self.last_result = ""
        threading.Thread(target=self._loop, daemon=True, name="journal-backups").start()

    def on_unload(self) -> None:
        self._stop.set()

    def folder(self) -> Path:
        from core.state import EDLD_DATA_DIR
        raw = str(self.settings().get("Folder") or "").strip()
        return Path(raw).expanduser() if raw else EDLD_DATA_DIR / "journal-backups"

    def run_backup(self) -> str:
        jdir = getattr(self.core, "journal_dir", None)
        if not jdir or not Path(jdir).is_dir():
            return "No journal folder."
        with self._lock:
            try:
                copied, total = backup_journals(Path(jdir), self.folder())
            except OSError as exc:
                self.last_result = f"Backup failed: {exc}"
                from core import debug as _dbg
                _dbg.log(f"  [Backups] {self.last_result}")
                return self.last_result
        self.last_result = (f"{copied} journal{'s' if copied != 1 else ''} copied, "
                            f"{total} kept in {self.folder()}")
        return self.last_result

    def _loop(self) -> None:
        # A short pause first, so a startup's own work is not slowed.
        if self._stop.wait(30):
            return
        while True:
            if self.settings().get("Enabled", True):
                self.run_backup()
            if self._stop.wait(_INTERVAL_S):
                return

    def on_event(self, event: dict, state) -> None:
        if event.get("event") == "Shutdown" and not getattr(state, "in_preload", False):
            if self.settings().get("Enabled", True):
                threading.Thread(target=self.run_backup, daemon=True).start()

    def settings_action(self, action_id: str) -> str:
        if action_id != "backup-now":
            return ""

        def _work():
            text = self.run_backup()
            from core import callout
            callout.say(self.core, "Automation", "💾", f"Journal backup: {text}", sigil="-  BKUP")
        threading.Thread(target=_work, daemon=True, name="journal-backup-now").start()
        return "Backing up — the result is reported when done."
