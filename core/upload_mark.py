"""
core/upload_mark.py — how far through the journal an uploader has sent.

At startup EDLD replays the current journal from its first line, so that the
dashboard knows everything that has happened this game session. The uploaders
— EDDN, EDSM, Inara, EDAstro — see that replay like any other event. Before
this mark existed they uploaded it all again on every start: a restart of EDLD
mid-session (and Options restarts it for some settings) sent every jump, dock,
scan and docking request of the session a second time, and a third, and so on.

Each uploader now records the timestamp of the last journal event it handled,
in ``<plugin>.sent.json`` beside its other files. During the replay an event at
or before that time is one an earlier run already handled, and is not sent
again. Everything else is unchanged: the uploader still sees the event and
keeps its own tracking (current system, station, game version) up to date —
only the upload is skipped. Live events are never skipped.

The first run on a journal has no mark for it, so EDLD started after the game
still sends what happened before it started, as it always has.
"""
from __future__ import annotations

import time
from typing import Any

#: How often the mark is written during the startup replay.
SAVE_EVERY_S = 5.0


class UploadMark:
    """The sent-through mark for one uploader, kept in its PluginStorage.

    The storage follows the active commander, so the mark is per commander;
    it is re-read whenever the commander's data directory changes.
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
        """Note that this event has been handled.

        A live event is written at once — they come a few at a time. The
        startup replay can be thousands of events in a second or two, so it
        is written at most every SAVE_EVERY_S, and in full by the first live
        event after it or when EDLD stops.
        """
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
