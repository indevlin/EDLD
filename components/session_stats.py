"""
components/session_stats.py — Session timing and summary aggregator.

Owns the session clock and on_new_session boundary logic.
Collects summary rows from registered ActivityProviderMixin plugins.
No longer owns kill/merit/credit counters — those live in activity plugins.

Dashboard block: session stats.

Session reset behaviour
-----------------------
Manual reset (gap=0, triggered by dashboard reset):
  - _session_start_time is set to the current event time immediately, so
    session_duration_seconds() starts counting from zero straight away.
  - A _reset_after sentinel (ISO timestamp string) is persisted to data.json.
  - On the next EDLD launch, any LoadGame event replayed from the journal
    whose timestamp is <= _reset_after is ignored when arming the clock.
    If no post-reset LoadGame is found during preload, _reset_after itself
    is used as the start time so the clock keeps counting since the reset.
  - Once a LoadGame event fires with timestamp > _reset_after the sentinel
    is cleared; the session henceforth tracks from that LoadGame normally.

Automatic session boundary (gap>0, triggered by commander plugin on LoadGame):
  - _session_start_time is set to None so the next LoadGame re-arms it.
  - Any persisted _reset_after sentinel is cleared because a real game
    boundary supersedes a manual reset.
"""

from core.plugin_loader import BasePlugin
from core.emit import fmt_duration


def _log_info(message: str) -> None:
    try:
        from core import debug as _debug
        _debug.info(message)
    except Exception:
        pass


class SessionStatsPlugin(BasePlugin):
    PLUGIN_NAME    = "session_stats"
    PLUGIN_DISPLAY = "Session Stats"
    PLUGIN_DESCRIPTION = "Session summary and per-activity statistics. Aggregates data from activity plugins."
    PLUGIN_VERSION = "2.1.0"

    SUBSCRIBED_EVENTS = [
        "LoadGame",
        "Shutdown",
    ]

    # Block geometry — kept for backward-compat with stored layouts that
    # reference "session_stats", but the component no longer registers a
    # block of its own.  The Career block absorbed the visible Summary
    # tab (with reset button) and the activity-provider rendering; this
    # plugin retains only the session-timing and on_new_session reset API.
    DEFAULT_COL    = 8
    DEFAULT_ROW    = 0
    DEFAULT_WIDTH  = 8
    DEFAULT_HEIGHT = 10

    def on_load(self, core) -> None:
        super().on_load(core)
        # Note: no register_block call — the Career block consumes our
        # session_duration_seconds() + the registered ActivityProviderMixin
        # plugins to render the session-scoped Summary tab.  Reset is also
        # initiated from the Career block (and from the TUI Ctrl+R binding)
        # via plugin_call('session_stats', 'on_new_session', 0).
        self._session_start_time = None
        self._reset_after        = None   # datetime | None
        # Whether the activity counters have been reset to _reset_after in
        # this run.  A reset made live is applied at once; one restored from
        # data.json is applied when the replay reaches it.
        self._reset_applied      = True

        # Restore persisted reset sentinel so the preload gate works on restart.
        self._restore()

    # ── Persistence ───────────────────────────────────────────────────────────

    def _restore(self) -> None:
        """Load any persisted reset sentinel from plugin storage."""
        try:
            data = self.storage.read_json() or {}
            ra   = data.get("reset_after")
            if ra:
                from datetime import datetime, timezone
                self._reset_after = datetime.fromisoformat(ra)
                # Pre-arm with the reset time so duration counts from the
                # reset even if no post-reset LoadGame replays during preload.
                self._session_start_time = self._reset_after
                self._reset_applied = False
        except Exception:
            pass

    def _persist_reset(self) -> None:
        """Persist the current reset sentinel to data.json."""
        try:
            ra_str = self._reset_after.isoformat() if self._reset_after else None
            self.storage.write_json({"reset_after": ra_str})
        except Exception:
            pass

    def _clear_reset(self) -> None:
        """Clear the reset sentinel and remove it from storage."""
        self._reset_after = None
        try:
            self.storage.write_json({"reset_after": None})
        except Exception:
            pass

    # ── Public API called by commander plugin and dashboard reset ─────────────

    def on_new_session(self, gap_minutes: float = 0) -> None:
        """Called when a session boundary is detected.

        gap_minutes == 0  →  manual dashboard reset: restart clock from right now.
        gap_minutes >  0  →  automatic boundary: clear clock so next LoadGame
                             re-arms it (normal session boundary behaviour).
        """
        state = self.core.state

        if gap_minutes == 0:
            # Manual reset: arm the clock immediately at the current event
            # timestamp so duration shows 0:00 and starts accumulating at once.
            now = getattr(state, "event_time", None)
            self._session_start_time = now
            self._reset_after        = now
            self._reset_applied      = True
            self._persist_reset()
            # Logged, because it discards the session's figures and nothing
            # else records that it happened.  A reset nobody remembered making
            # once cost five hours of a session with no trace of why.
            _log_info(f"[session] session counters reset; the session now "
                      f"counts from {now.isoformat() if now else 'now'}")
        else:
            event_time = getattr(state, "event_time", None)
            if (self._reset_after is not None and event_time is not None
                    and event_time <= self._reset_after):
                # A game-session boundary from before the manual reset, met
                # again while the journal is replayed at startup.  The reset
                # came later and supersedes it; clearing it here is how a
                # restart used to throw the reset away.  The counters the
                # caller has just cleared are cleared again, and properly,
                # when the replay reaches the reset.
                return
            # Automatic session boundary: let next LoadGame re-arm.
            self._session_start_time = None
            self._clear_reset()

        # Notify registered activity providers to reset their counters.
        for provider in getattr(self.core, "session_providers", []):
            try:
                provider.on_session_reset()
            except Exception:
                pass

        gq = self.core.gui_queue
        if gq:
            gq.put(("stats_update", None))

    # ── Replaying a reset ─────────────────────────────────────────────────────

    def before_event(self, logtime) -> None:
        """Called for every journal event before any component sees it.

        While a reset restored from data.json has not been applied, the first
        event later than it clears every activity's counters — so a restart
        counts exactly what the running dashboard counted: nothing before the
        reset, everything after it, including that event.
        """
        if self._reset_applied or self._reset_after is None or logtime is None:
            return
        if logtime > self._reset_after:
            self._apply_restored_reset()

    def after_preload(self) -> None:
        """A reset later than every replayed event is applied when replay ends."""
        if not self._reset_applied and self._reset_after is not None:
            self._apply_restored_reset()

    def _apply_restored_reset(self) -> None:
        self._reset_applied = True
        self._session_start_time = self._reset_after
        for provider in getattr(self.core, "session_providers", []):
            try:
                provider.on_session_reset()
            except Exception:
                pass

    # ── Event handler ─────────────────────────────────────────────────────────

    def on_event(self, event: dict, state) -> None:
        ev      = event.get("event")
        logtime = event.get("_logtime")

        if ev == "LoadGame" and logtime:
            if self._reset_after is not None:
                if logtime <= self._reset_after:
                    # This LoadGame predates the manual reset — ignore it.
                    return
                else:
                    # First LoadGame after the reset: arm from here and
                    # clear the sentinel so future restarts behave normally.
                    self._session_start_time = logtime
                    self._clear_reset()
            else:
                # Normal path: arm on first LoadGame of the session.
                if self._session_start_time is None:
                    self._session_start_time = logtime

    # ── Duration query ────────────────────────────────────────────────────────

    def session_duration_seconds(self) -> float:
        """Wall-clock duration of the current session in seconds."""
        if not self._session_start_time:
            return 0.0
        state = self.core.state
        if state.event_time:
            return (state.event_time - self._session_start_time).total_seconds()
        return 0.0

