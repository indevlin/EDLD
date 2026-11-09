"""core/upload_mark.py — how far through the journal an uploader has sent."""
from __future__ import annotations

import time
from typing import Any

#: How often the mark is written during the startup replay.
SAVE_EVERY_S = 5.0


class UploadMark:
    """The sent-through mark for one uploader, kept in its PluginStorage.
    """

    PURPOSE = "sent"

    def __init__(self, storage: Any) -> None:
        self._storage = storage
        self._path = None
        self._through = ""
        self._dirty = False
        self._saved_at = 0.0

    # ── reading ───────────────────────────────────────────────────────────────

    def _current(self) -> str:
        try:
            path = self._storage.path
        except Exception:
            return self._through
        if path != self._path:
            if self._dirty:
                self.save()
            self._path = path
            try:
                data = self._storage.read_json(self.PURPOSE) or {}
            except Exception:
                data = {}
            self._through = str(data.get("through", "") or "")
            self._dirty = False
        return self._through

    @property
    def through(self) -> str:
        return self._current()

    def replayed(self, event: dict, state: Any) -> bool:
        """True for an event an earlier run already handled: one replayed at
        startup whose timestamp is not after the mark."""
        if not getattr(state, "in_preload", False):
            return False
        ts = str((event or {}).get("timestamp", "") or "")
        mark = self._current()
        return bool(ts) and bool(mark) and ts <= mark

    # ── writing ───────────────────────────────────────────────────────────────

    def advance(self, event: dict, state: Any = None) -> None:
        """Note that this event has been handled."""
        ts = str((event or {}).get("timestamp", "") or "")
        if not ts or ts <= self._current():
            return
        self._through = ts
        self._dirty = True
        live = not getattr(state, "in_preload", False)
        if live or time.monotonic() - self._saved_at >= SAVE_EVERY_S:
            self.save()

    def save(self) -> None:
        if not self._dirty:
            return
        try:
            self._storage.write_json({"through": self._through}, self.PURPOSE)
            self._dirty = False
            self._saved_at = time.monotonic()
        except Exception:
            pass   # best effort: the worst case is a resend, as before
