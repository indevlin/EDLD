"""
components/edastro.py — EDAstro journal uploader for EDLD.

Uploads journal events to EDAstro (https://edastro.com).

Subscription model — "send everything EDAstro accepts":
  The plugin subscribes with the wildcard "*" and receives every journal
  event the dispatcher sees.  Runtime filtering uses EDAstro's published
  interest list from /api/journal/interested — only events on that list
  are forwarded.  The hardcoded _FALLBACK_INTEREST set kicks in during
  startup and as a safety net if the interest fetch fails.  New events
  EDAstro decides to accept in the future flow through automatically
  without code changes here.

Config [EDAstro]:
    Enabled             = false   # opt-in
    UploadCarrierEvents = false   # CarrierStatus / CarrierJumpRequest are opt-in
                                  # (may expose carrier location to third parties)

EDAstro notes:
  - Anonymous — no API key required.
  - Rate limit: 100 requests per 15 minutes (per EDAstro API headers).
  - Live galaxy only; beta data is suppressed.
"""

import gzip
import json
import queue
import threading
import time
import urllib.error
import urllib.request

from core.plugin_loader import BasePlugin
from core import debug as _dbg
from core import push_triggers as _push
from core import integration_log as _ilog
from core.state import VERSION

# ── Constants ─────────────────────────────────────────────────────────────────

PLUGIN_VERSION        = "1.0.0"
EDASTRO_UPLOAD_URL    = "https://edastro.com/api/journal"
EDASTRO_INTEREST_URL  = "https://edastro.com/api/journal/interested"
SOFTWARE_NAME         = "EDLD"
SOFTWARE_VERSION      = VERSION
HTTP_TIMEOUT_S        = 30
SEND_INTERVAL_S       = 10      # ~6/min, leaves comfortable headroom under 100/15 min
BATCH_MAX             = 30
STARTUP_DELAY_S       = 12      # stagger slightly behind EDSM startup

# Carrier events that require explicit opt-in
_CARRIER_EVENTS = frozenset({
    "CarrierStatus",
    "CarrierJumpRequest",
})

# Fallback interest set — used until /api/journal/interested completes,
# and as a safety net if that fetch fails entirely.  Once the runtime
# interest list arrives it supersedes this.  Subscription itself is
# wildcard ("*") so every journal event reaches on_event and is gated
# only by the interest set — future EDAstro additions then flow without
# code changes here.
_FALLBACK_INTEREST = frozenset({
    "Scan", "SAAScanComplete", "SAASignalsFound", "FSSBodySignals",
    "FSSDiscoveryScan", "FSSSignalDiscovered", "NavBeaconScan",
    "CodexEntry",
    "ScanOrganic", "SellOrganicData",
    "FSDJump", "CarrierJump", "Location",
    "Docked", "Undocked",
    "MarketBuy", "MarketSell",
    "MissionAccepted", "MissionCompleted", "MissionFailed", "MissionAbandoned",
    "Bounty", "RedeemVoucher",
    "Rank", "Progress", "Promotion",
    "Powerplay", "PowerplaySalary", "PowerplayCollect",
    "EngineerProgress",
    "MaterialCollected", "MaterialTrade",
    "MiningRefined", "ProspectedAsteroid",
    "ShipyardBuy", "ShipyardSell", "ModuleBuy", "ModuleSell",
    "Loadout",
    "CommunityGoal", "CommunityGoalJoin", "CommunityGoalReward",
    "CarrierStats", "CarrierJumpCancelled",
    "CarrierStatus",        # opt-in
    "CarrierJumpRequest",   # opt-in
})

# Wildcard subscription — see _FALLBACK_INTEREST above for rationale.
SUBSCRIBED_EVENTS = ["*"]

CFG_DEFAULTS = {
    "Enabled":             False,
    "UploadCarrierEvents": False,
}

# Beta / legacy detection helper (mirrors EDDN plugin approach)
_BETA_TAGS = ("beta", "alpha", "test", "legacy")


def _is_beta(gameversion: str) -> bool:
    return any(t in gameversion.lower() for t in _BETA_TAGS)


# ── Sender thread ─────────────────────────────────────────────────────────────

class _Sender(threading.Thread):

    def __init__(self, queue_file) -> None:
        super().__init__(daemon=True, name="edastro-sender")
        self._queue_file = queue_file
        self._q         = queue.Queue()
        self._stop_evt  = threading.Event()
        self._last_send = 0.0

    def push(self, event: dict) -> None:
        self._q.put(event)

    def flush(self) -> None:
        self._q.put(_FLUSH_SENTINEL)

    def stop(self) -> None:
        self._stop_evt.set()
        self._q.put(None)

    def run(self) -> None:
        _ilog.sender_started("EDAstro", self._queue_file)
        time.sleep(STARTUP_DELAY_S)
        self._last_drain = time.monotonic()
        self._drain_disk()

        batch: list[dict] = []
        pushed = 0
        self._counts = [0, 0]                 # sent, failed (by _send_batch)
        last_heartbeat = time.monotonic()

        while not self._stop_evt.is_set():
            try:
                item = self._q.get(timeout=1.0)
            except queue.Empty:
                if batch and (time.monotonic() - self._last_send >= SEND_INTERVAL_S):
                    self._send_batch(batch)
                    batch = []
                # Events kept on disk after a failed send are tried again in
                # this session, not only at the next start.
                if (time.monotonic() - getattr(self, "_last_drain", 0.0) >= 300
                        and self._queue_file.exists()):
                    self._last_drain = time.monotonic()
                    self._drain_disk()
                if time.monotonic() - last_heartbeat >= 60:
                    sent, failed = self._counts
                    _ilog.heartbeat("EDAstro", pushed=pushed, batch=len(batch),
                                    sent=sent, failures=failed)
                    last_heartbeat = time.monotonic()
                continue

            if item is None:
                if batch:
                    self._send_batch(batch)
                return

            if item is _FLUSH_SENTINEL:
                if batch:
                    self._send_batch(batch)
                    batch = []
                continue

            pushed += 1
            batch.append(item)
            if len(batch) >= BATCH_MAX:
                self._send_batch(batch)
                batch = []

        if batch:
            self._send_batch(batch)

    # ── HTTP ──────────────────────────────────────────────────────────────────

    def _send_batch(self, events: list[dict]) -> None:
        gap = SEND_INTERVAL_S - (time.monotonic() - self._last_send)
        if gap > 0:
            time.sleep(gap)

        try:
            raw     = json.dumps(events, separators=(",", ":")).encode("utf-8")
            encoded = gzip.compress(raw)
            req = urllib.request.Request(
                EDASTRO_UPLOAD_URL,
                data=encoded,
                headers={
                    "Content-Type":     "application/json",
                    "Content-Encoding": "gzip",
                    "User-Agent":       f"{SOFTWARE_NAME}/{SOFTWARE_VERSION}",
                },
                method="POST",
            )
            _ilog.request_posted("EDAstro", len(events))
            with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT_S) as resp:
                self._last_send = time.monotonic()
                if resp.status != 200:
                    _ilog.response_failed("EDAstro", resp.status, "queued to disk")
                    self._bump(1)
                    self._persist(events)
                else:
                    _ilog.response_ok("EDAstro", resp.status, len(events))
                    self._bump(0)

        except urllib.error.HTTPError as e:
            if 400 <= e.code < 500 and e.code not in (408, 429):
                # Refused as sent: sending it again would be refused again,
                # every time the queue is tried.
                _dbg.info(f"  [EDAstro] HTTP {e.code} — {len(events)} event(s) "
                          f"refused, not retried")
                return
            _dbg.info(f"  [EDAstro] HTTP {e.code} — queuing {len(events)} event(s) to disk")
            self._persist(events)
        except TimeoutError:
            _ilog.transient("EDAstro", f"timeout — {len(events)} event(s) queued to disk")
            self._bump(1)
            self._persist(events)
        except Exception as exc:
            _dbg.info(f"  [EDAstro] Send error ({type(exc).__name__}: {exc}) — queuing to disk")
            self._persist(events)

    def _bump(self, i: int) -> None:
        counts = getattr(self, "_counts", None)
        if counts is not None:
            counts[i] += 1

    # ── Disk persistence ──────────────────────────────────────────────────────

    def _persist(self, events: list[dict]) -> None:
        try:
            self._queue_file.parent.mkdir(parents=True, exist_ok=True)
            import builtins as _bi
            with _bi.open(self._queue_file, "a", encoding="utf-8") as f:
                for ev in events:
                    f.write(json.dumps({"queued_at": time.time(), "msg": ev}) + "\n")
        except Exception as e:
            _dbg.info(f"  [EDAstro] Failed to persist events to disk queue: {e}")

    def _drain_disk(self) -> None:
        from core.disk_queue import drain
        drain(self._queue_file, BATCH_MAX, self._send_batch, "EDAstro",
              pause_s=SEND_INTERVAL_S)


_FLUSH_SENTINEL = object()


# ── Plugin ────────────────────────────────────────────────────────────────────

class EDAstroPlugin(BasePlugin):

    PLUGIN_NAME        = "edastro"
    PLUGIN_DISPLAY     = "EDAstro Uploader"
    PLUGIN_DESCRIPTION = "Contributes exploration and carrier data to ED Astronomer (EDAstro)."
    PLUGIN_VERSION     = PLUGIN_VERSION
    SUBSCRIBED_EVENTS  = SUBSCRIBED_EVENTS

    def on_load(self, core) -> None:
        self.core                  = core
        self._enabled              = False
        self._carrier_opt_in       = False
        self._interest_set:        frozenset[str] = _FALLBACK_INTEREST
        self._sender: _Sender | None = None
        self._gameversion          = ""

        cfg = core.load_setting("EDAstro", CFG_DEFAULTS, warn=False)

        if not bool(core.cfg.app_settings.get("PrimaryInstance", True)):
            _dbg.info("  [EDAstro] Uploads suppressed (PrimaryInstance = false)")
            return
        if not cfg["Enabled"]:
            return

        self._enabled        = True
        self._carrier_opt_in = bool(cfg["UploadCarrierEvents"])

        threading.Thread(
            target=self._fetch_interest_list,
            daemon=True,
            name="edastro-interest",
        ).start()

        self._sender = _Sender(self.storage.file_path("queue.jsonl"))
        self._sender.start()

        carrier_note = " (carrier events: on)" if self._carrier_opt_in else ""
        self._load_note = f"enabled{carrier_note}"

    def on_unload(self) -> None:
        if self.__dict__.get("_mark") is not None:
            self._mark.save()
        if self._sender:
            self._sender.stop()
            self._sender.join(timeout=5)

    def on_event(self, event: dict, state) -> None:
        # An event an earlier run of EDLD already uploaded — replayed from the
        # current journal at startup — is handled for tracking but not sent
        # again (core/upload_mark.py).
        mark = self._upload_mark()
        self._replaying = mark.replayed(event, state)
        replayed = self._replaying
        try:
            self._on_event(event, state)
        finally:
            self._replaying = False
            if getattr(self, "_enabled", False):
                mark.advance(event, state)
                # core/push_triggers: send the batch now.
                if (not replayed and getattr(self, "_sender", None) is not None
                        and _push.is_push(event)):
                    self._sender.flush()

    def _upload_mark(self):
        mark = self.__dict__.get("_mark")
        if mark is None:
            from core.upload_mark import UploadMark
            mark = self._mark = UploadMark(self.storage)
        return mark

    def _on_event(self, event: dict, state) -> None:
        if not self._enabled or self._sender is None:
            return

        event_name = event.get("event", "")

        # Beta / legacy suppression
        gv = event.get("gameversion", self._gameversion)
        if gv:
            self._gameversion = gv
        if self._gameversion and _is_beta(self._gameversion):
            return

        # Carrier events require opt-in
        if event_name in _CARRIER_EVENTS and not self._carrier_opt_in:
            return

        # Only send events EDAstro is interested in
        if event_name not in self._interest_set:
            return

        if self._replaying:
            return
        ev_clean = {k: v for k, v in event.items() if k != "_logtime"}
        self._sender.push(ev_clean)


    # ── Interest list ──────────────────────────────────────────────────────────

    def _fetch_interest_list(self) -> None:
        try:
            req = urllib.request.Request(
                EDASTRO_INTEREST_URL,
                headers={"User-Agent": f"{SOFTWARE_NAME}/{SOFTWARE_VERSION}"},
            )
            with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT_S) as resp:
                if resp.status == 200:
                    data = json.loads(resp.read().decode("utf-8"))
                    if isinstance(data, list) and data:
                        new_set = frozenset(data)
                        new_events  = sorted(new_set - _FALLBACK_INTEREST)
                        lost_events = sorted(_FALLBACK_INTEREST - new_set)
                        self._interest_set = new_set
                        _dbg.info(
                            f"  [EDAstro] Interest list loaded: "
                            f"{len(new_set)} event types accepted "
                            f"(+{len(new_events)} vs fallback, "
                            f"-{len(lost_events)} no longer wanted)"
                        )
                        if new_events:
                            _dbg.info(f"  [EDAstro]   newly capturable: "
                                      f"{', '.join(new_events[:8])}"
                                      f"{' …' if len(new_events) > 8 else ''}")
                        return
                    _dbg.info(f"  [EDAstro] Interest list not a non-empty list — "
                              f"using {len(_FALLBACK_INTEREST)}-event fallback")
                    return
                _dbg.info(f"  [EDAstro] Interest list HTTP {resp.status} — "
                          f"using {len(_FALLBACK_INTEREST)}-event fallback")
        except Exception as exc:
            _dbg.info(
                f"  [EDAstro] Could not fetch interest list "
                f"({type(exc).__name__}: {exc}) — using {len(_FALLBACK_INTEREST)}-event fallback"
            )
