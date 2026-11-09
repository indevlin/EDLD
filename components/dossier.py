"""components/dossier.py — keeps the commander's dossier up to date.

When it is written
------------------
* Once at startup, in the background, after the journal-history scan (which
  supplies career income) has finished.
* A short while after any event that changes a page — a new fitting, a ship
  stored or transferred, a carrier update — so a burst of events is one
  rewrite, not dozens.
* When the dashboard theme or a ``[Dossier]`` setting changes.
* On request, from the button in Options.
"""

from __future__ import annotations

import threading
import time
from pathlib import Path

from core.plugin_loader import BasePlugin

CFG_DEFAULTS = {
    "Enabled": True,
    # Where the commander, the current ship and the fleet carrier are now,
    # and the carrier's jump history. Stored ships are always listed where
    # they are kept.
    "IncludeCurrentLocation": False,
    # Credit balance, total wealth, and the carrier's bank.
    "IncludeBalance": False,
}

#: Seconds to wait after a relevant event before rewriting, so a burst of
#: them — docking, a shipyard visit, an outfitting session — is one rewrite.
REBUILD_DELAY_S = 15.0

#: How often the worker looks for a theme or settings change.
_POLL_S = 10.0
#: Seconds after start before the first rewrite.
_FIRST_BUILD_S = 20.0

#: Events that change something a page shows.
TRIGGERS = (
    "LoadGame", "Loadout", "StoredShips", "ShipyardSwap", "ShipyardNew",
    "ShipyardSell", "SellShipOnRebuy", "ShipyardTransfer", "SetUserShipName",
    "ShipRedeemed", "StoredModules", "EngineerProgress", "Rank", "Progress",
    "Reputation", "Powerplay", "PowerplayRank", "SquadronStartup",
    "CarrierStats", "CarrierJumpRequest", "CarrierJumpCancelled",
    "CarrierLocation", "CarrierNameChange", "SuitLoadout", "CreateSuitLoadout",
    "DeleteSuitLoadout", "RenameSuitLoadout", "LoadoutEquipModule",
    "LoadoutRemoveModule", "BuySuit", "SellSuit", "UpgradeSuit", "BuyWeapon",
    "SellWeapon", "UpgradeWeapon", "SupercruiseEntry", "FSDJump", "Docked",
    "Died", "Resurrect", "Shutdown",
)


def _on(value) -> bool:
    if isinstance(value, str):
        return value.strip().lower() in ("1", "true", "yes", "on")
    return bool(value)


class DossierPlugin(BasePlugin):
    PLUGIN_NAME = "dossier"
    PLUGIN_DISPLAY = "Dossier"
    PLUGIN_DESCRIPTION = ("Writes the commander's dossier — fleet with fittings, "
                          "engineering, carrier, mining and more — as a web page "
                          "and Markdown files.")
    PLUGIN_VERSION = "1.0.0"

    SUBSCRIBED_EVENTS = list(TRIGGERS)

    def on_load(self, core) -> None:
        super().on_load(core)
        self._lock = threading.Lock()
        self._wake = threading.Event()
        self._stop = threading.Event()
        self._due = 0.0                  # monotonic time a rewrite is due; 0 = none
        self._inputs = None              # theme and settings at the last rewrite
        self._cfg_mtime = None
        self.cfg = core.load_setting("Dossier", CFG_DEFAULTS, warn=False)
        self.last_built = 0.0
        self.last_error = ""
        self.last_result = None
        self._thread = threading.Thread(target=self._run, daemon=True,
                                        name="dossier")
        self._thread.start()

    def on_unload(self) -> None:
        self._stop.set()
        self._wake.set()

    # ── triggers ──────────────────────────────────────────────────────────────

    def on_event(self, event: dict, state) -> None:
        if getattr(state, "in_preload", False):
            return
        self.schedule(REBUILD_DELAY_S)

    def schedule(self, delay: float = 0.0) -> None:
        due = time.monotonic() + max(0.0, delay)
        with self._lock:
            # A rewrite already due sooner stays due sooner.
            if not self._due or due < self._due or delay == 0.0:
                self._due = due
        self._wake.set()

    # ── the worker ────────────────────────────────────────────────────────────

    def _run(self) -> None:
        # The first rewrite waits until start-up is over: it reads every
        # window's data, which the journals are still filling in, and nothing
        # needs the files in the first seconds of a run.
        self.schedule(_FIRST_BUILD_S)
        self._inputs = self._current_inputs()
        while not self._stop.is_set():
            with self._lock:
                due = self._due
            timeout = _POLL_S if not due else max(
                0.0, min(_POLL_S, due - time.monotonic()))
            self._wake.wait(timeout=timeout)
            self._wake.clear()
            if self._stop.is_set():
                break
            self._reload_if_changed()
            with self._lock:
                fire = bool(self._due) and time.monotonic() >= self._due
                if fire:
                    self._due = 0.0
            if fire or self._current_inputs() != self._inputs:
                self.build_now()

    def _reload_if_changed(self) -> None:
        """Pick up Apply & Save, as the overlay does: by config.toml's mtime."""
        try:
            path = self.core.cfg.config_path
            mtime = Path(path).stat().st_mtime
        except Exception:
            return
        if self._cfg_mtime is None:
            self._cfg_mtime = mtime
            return
        if mtime <= self._cfg_mtime:
            return
        self._cfg_mtime = mtime
        try:
            self.core.cfg.refresh(terminal_print=False)
        except Exception:
            pass
        self.cfg = self.core.load_setting("Dossier", CFG_DEFAULTS, warn=False)

    def _theme(self) -> str:
        try:
            return str(self.core.load_setting("UI", {"Theme": "default"},
                                              warn=False).get("Theme") or "default")
        except Exception:
            return "default"

    def _current_inputs(self) -> tuple:
        return (self._theme(), _on(self.cfg.get("Enabled", True)),
                _on(self.cfg.get("IncludeCurrentLocation")),
                _on(self.cfg.get("IncludeBalance")))

    def _fid(self):
        state = getattr(self.core, "state", None)
        fid = getattr(state, "pilot_fid", None)
        if not fid:
            try:
                import core.state as st
                fid = st._active_fid
            except Exception:
                fid = None
        return fid or None

    def build_now(self):
        """Rewrite the dossier now, on the calling thread. Returns the result."""
        inputs = self._current_inputs()
        theme, enabled, loc, bal = inputs
        self._inputs = inputs
        if not enabled:
            return None
        fid = self._fid()
        if not fid:
            # Nothing is written until EDLD knows whose dossier it is — EDLD
            # started before the game, say. Try again shortly.
            with self._lock:
                if not self._due:
                    self._due = time.monotonic() + _POLL_S
            return None
        try:
            from core.dossier.build import Settings, build
            from core.state import VERSION, cmdr_data_dir
            state = getattr(self.core, "state", None)
            live = getattr(state, "status_balance", None) if state else None
            result = build(self.core.journal_dir, cmdr_data_dir(), fid,
                           settings=Settings(include_location=loc,
                                             include_balance=bal),
                           theme=theme, core=self.core, live_balance=live,
                           version=VERSION)
            self.last_result = result
            self.last_built = time.time()
            self.last_error = ""
            if result.written or result.removed:
                self._log(f"[dossier] {len(result.written)} file(s) written, "
                          f"{len(result.removed)} removed, {result.events} new "
                          f"journal event(s), in {result.out_dir}")
            return result
        except Exception as exc:
            self.last_error = f"{type(exc).__name__}: {exc}"
            self._log(f"[dossier] could not be written: {self.last_error}")
            return None

    def _log(self, message: str) -> None:
        try:
            from core import debug as _debug
            _debug.info(message)
        except Exception:
            pass

    # ── preferences ───────────────────────────────────────────────────────────

    _TOGGLES = (
        ("Enabled", "Write the dossier", "dos-enabled"),
        ("IncludeCurrentLocation", "Include current location", "dos-location"),
        ("IncludeBalance", "Include balances", "dos-balance"),
    )

    def preferences_bindings(self) -> dict:
        return {wid: ("Dossier", key, bool) for key, _label, wid in self._TOGGLES}

    def _status(self) -> str:
        # Worked out, not cmdr_data_dir(): that creates the directory, and
        # opening Options before the commander is known would leave an empty
        # commanders/unknown behind.
        try:
            from core.state import EDLD_DATA_DIR
            where = str(EDLD_DATA_DIR / "commanders" / (self._fid() or "<FID>") / "dossier")
        except Exception:
            where = "<commander>/dossier"
        if self.last_error:
            return f"{where} — last attempt failed: {self.last_error}"
        if self.last_built:
            stamp = time.strftime("%Y-%m-%d %H:%M", time.localtime(self.last_built))
            return f"{where} — written {stamp}"
        return f"{where} — not written yet"

    _NOTE = ("A web page (html/index.html) and Markdown files (md/) about this "
             "commander, rewritten as things change. Stored ships are always "
             "listed where they are kept; the current location, the carrier's "
             "whereabouts, and balances are left out unless included here. "
             "See docs/DOSSIER.md.")

    def preferences_action(self, action_id: str, values: dict | None = None):
        if action_id != "btn-dossier-build":
            return None
        self.schedule(0.0)
        return "Rewriting — this takes a second or two."

    def tui_preferences_tab(self):
        def _compose():
            from textual.containers import Horizontal
            from textual.widgets import Button, Label, Select

            bools = [("Off", "false"), ("On", "true")]
            yield Label("DOSSIER", classes="pref-section")
            yield Label(self._NOTE, classes="pref-note")
            with Horizontal(classes="pref-row"):
                yield Label("Written to", classes="key")
                yield Label(self._status(), classes="pref-note")
            for key, label, wid in self._TOGGLES:
                with Horizontal(classes="pref-row"):
                    yield Label(label, classes="key")
                    yield Select(bools, id=wid, classes="pref-bool-sel",
                                 allow_blank=False,
                                 value="true" if _on(self.cfg.get(key, CFG_DEFAULTS[key]))
                                 else "false")
            with Horizontal(classes="pref-row"):
                yield Button("Rewrite now", id="btn-dossier-build")
                yield Label("", id="btn-dossier-build-result", classes="pref-note")

        return ("pref-tab-dossier", "Dossier", _compose)

    def gui_preferences_tab(self):
        def _build(dlg):
            from PySide6.QtWidgets import (QFormLayout, QLabel, QPushButton,
                                           QVBoxLayout, QWidget)
            page = QWidget()
            lay = QVBoxLayout(page)
            lay.setContentsMargins(10, 10, 10, 10)
            title = QLabel("DOSSIER")
            title.setProperty("role", "section")
            lay.addWidget(title)
            note = QLabel(self._NOTE)
            note.setWordWrap(True)
            note.setProperty("role", "dim")
            lay.addWidget(note)
            form = QFormLayout()
            lay.addLayout(form)
            status = QLabel(self._status())
            status.setWordWrap(True)
            form.addRow("Written to", status)
            for key, label, _wid in self._TOGGLES:
                form.addRow(label, dlg._bool_combo(
                    _on(self.cfg.get(key, CFG_DEFAULTS[key])), "Dossier", key))
            button = QPushButton("Rewrite now")
            result = QLabel("")
            result.setProperty("role", "dim")
            button.clicked.connect(
                lambda: result.setText(self.preferences_action("btn-dossier-build") or ""))
            form.addRow(button, result)
            lay.addStretch(1)
            return page

        return ("pref-tab-dossier", "Dossier", _build)
