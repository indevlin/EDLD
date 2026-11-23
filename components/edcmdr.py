"""
components/edcmdr.py — publishes to ED Commanders (edcmdr.com), as the EDCMDR client does.

Runs the EDCMDR client's engine, vendored in vendor/edcmdr-client (refreshed by
scripts/sync_edcmdr.py), on its own thread over EDLD's journal folder. The
engine reads the journals itself, keeps one state per commander, and pushes
only the sections switched on in its settings, each on its delay; verification
and portraits work as in the client.

Keys and settings are the EDCMDR client's own files (its config directory), so
EDLD and the client publish as the same installation and can take turns. Only
one publishes at a time: the other stands by until it stops.

Release builds sign pushes with EDLD's own EDCMDR build key, written into the
vendored package by the release workflow. Source runs read $EDCMDR_BUILD_KEY or
~/.config/edcmdr/build.key; without one, ED Commanders refuses the pushes.

Config [EDCMDR]:
    Enabled = false   # opt-in
"""

import sys
from pathlib import Path

from core.plugin_loader import BasePlugin
from core import debug as _dbg
from core.state import VERSION

PLUGIN_VERSION = "1.0.0"
CFG_DEFAULTS = {"Enabled": False}


def _engine_classes():
    """Import the vendored client with EDLD's name and version on its pushes."""
    root = Path(__file__).resolve().parent.parent / "vendor" / "edcmdr-client"
    if root.is_dir() and str(root) not in sys.path:
        sys.path.insert(0, str(root))
    import edcmdr
    edcmdr.NAME, edcmdr.VERSION = "EDLD", VERSION
    from edcmdr.config import Settings
    from edcmdr.uplink import Engine
    return Settings, Engine


class EDCMDRPlugin(BasePlugin):
    PLUGIN_NAME = "edcmdr"
    PLUGIN_DISPLAY = "ED Commanders"
    PLUGIN_VERSION = PLUGIN_VERSION
    PLUGIN_DESCRIPTION = "Publishes the sections you choose to edcmdr.com"
    SUBSCRIBED_EVENTS: list[str] = []

    def on_load(self, core) -> None:
        super().on_load(core)
        self.engine = None
        self.window = None
        self.reason = "off in Options → Services"
        cfg = core.load_setting("EDCMDR", CFG_DEFAULTS, warn=False)
        if not bool(core.cfg.app_settings.get("PrimaryInstance", True)):
            self.reason = "not the primary instance"
            return
        if not cfg["Enabled"]:
            return
        try:
            Settings, Engine = _engine_classes()
        except Exception as e:
            self.reason = f"unavailable: {e}"
            _dbg.info(f"  [EDCMDR] {self.reason}")
            return
        settings = Settings()
        jd = str(Path(core.journal_dir))
        if jd not in settings.data["journal_dirs"]:
            settings.set_journal_dirs(settings.data["journal_dirs"] + [jd])
        self.engine = Engine(settings)
        self.engine.start()
        _dbg.info(f"  [EDCMDR] publishing to {self.engine.client.base}")

    def on_unload(self) -> None:
        if self.engine is not None:
            self.engine.shutdown()

    def get_summary_line(self) -> str | None:
        if self.engine is None:
            return None
        return f"ED Commanders: {self.engine.status}"

    def status(self) -> str:
        return self.engine.status if self.engine is not None else f"ED Commanders is {self.reason}."

    def open_settings(self, parent=None) -> bool:
        """The EDCMDR client's settings window, hosted by EDLD. False when not publishing."""
        if self.engine is None:
            return False
        from edcmdr.ui.settings import SettingsWindow
        if self.window is None:
            self.window = SettingsWindow(self.engine, host="EDLD")
        self.window.show()
        self.window.raise_()
        self.window.activateWindow()
        return True
