"""components/income.py — Session income tracking.

Aggregates all realized credit income across activity types into a single
session total with a credits-per-hour rate.

Income sources:
  RedeemVoucher            — bounties, combat bonds, trade vouchers (face value)
  MissionCompleted         — mission reward
  SellExplorationData      — cartography
  MultiSellExplorationData — cartography (batch)
  SellOrganicData          — exobiology
  MarketSell               — commodity sale gross proceeds
  Unknown Credits          — balance rises no journal event explains

CarrierBankTransfer is excluded — moving money between accounts is not income.

Tab title: Income
"""

import threading
import time
from datetime import datetime, timezone

from core.plugin_loader import BasePlugin
from core.activity import ActivityProviderMixin
from core.credit_flows import CREDIT_EVENTS, BalanceReconciler
from core.emit import fmt_credits

#: Label for income the journal does not explain. See core/credit_flows.py.
UNKNOWN_CREDITS = "Unknown Credits"

#: How often the live balance is compared with the journal.
_RECONCILE_EVERY_S = 2.0


def _overlay_credits(value) -> str:
    """Short credit formatting for the overlay."""
    try:
        v = float(value)
    except (TypeError, ValueError):
        return str(value)
    for limit, suffix in ((1e12, "T"), (1e9, "B"), (1e6, "M"), (1e3, "K")):
        if abs(v) >= limit:
            return f"{v / limit:.2f}{suffix} cr"
    return f"{v:.0f} cr"


class ActivityIncomePlugin(BasePlugin, ActivityProviderMixin):
    PLUGIN_NAME         = "income"
    PLUGIN_DISPLAY      = "Income Activity"
    PLUGIN_VERSION      = "1.0.0"
    PLUGIN_DESCRIPTION  = "Tracks total session credit income and credits-per-hour rate."
    ACTIVITY_TAB_TITLE  = "Income"
    #: Career section name, which differs from the tab title here.
    CAREER_SECTION      = "Credits"

    # Every credit-moving event, not only income: the reconciler has to see
    # the spending too, or every purchase would look like money going missing
    # and every sale after it like money appearing.
    SUBSCRIBED_EVENTS = sorted(set(CREDIT_EVENTS) | {
        "RedeemVoucher",
        "MissionCompleted",
        "SellExplorationData",
        "MultiSellExplorationData",
        "SellOrganicData",
        "MarketSell",
        "LoadGame",
        "Commander",
    })

    #: Replaced per instance in on_load; these keep a plugin built without
    #: on_load (as the tests do) working.
    _lock = threading.RLock()
    _reconciler: BalanceReconciler | None = None

    def on_load(self, core) -> None:
        super().on_load(core)
        core.register_session_provider(self)
        self._lock = threading.RLock()
        self._reset_counters()
        self._reconciler = BalanceReconciler(self._on_unknown_credits)
        self._stop = threading.Event()
        threading.Thread(target=self._reconcile_loop, daemon=True,
                         name="edld-income-reconcile").start()

    def on_unload(self) -> None:
        self._stop.set()

    # ── Unknown Credits ───────────────────────────────────────────────────────

    def _reconcile_loop(self) -> None:
        while not self._stop.wait(_RECONCILE_EVERY_S):
            try:
                self.reconcile_now(time.time())
            except Exception as exc:
                try:
                    from core import debug as _debug
                    _debug.info(f"[income] balance reconciliation failed: "
                                f"{type(exc).__name__}: {exc}")
                except Exception:
                    pass

    def reconcile_now(self, now: float) -> int:
        """Feed the live balance in and compare."""
        state = getattr(self.core, "state", None)
        balance = getattr(state, "status_balance", None) if state else None
        if balance is not None:
            self._reconciler.observe_balance(
                balance, float(getattr(state, "status_balance_ts", 0.0) or now))
        return self._reconciler.settle(now)

    def _on_unknown_credits(self, amount: int, ts: float) -> None:
        when = datetime.fromtimestamp(ts, timezone.utc)
        if amount > 0:
            self._add(when, amount, UNKNOWN_CREDITS)
            verb = "found"
        else:
            # A journal line arrived late and explains part of an earlier
            # report; take it back rather than count the money twice.
            with self._lock:
                have = self.by_source.get(UNKNOWN_CREDITS, 0)
                take = min(have, -amount)
                if take:
                    self.by_source[UNKNOWN_CREDITS] = have - take
                    if not self.by_source[UNKNOWN_CREDITS]:
                        del self.by_source[UNKNOWN_CREDITS]
                    self.total_income -= take
            verb = "withdrawn"
        try:
            from core import debug as _debug
            _debug.info(f"[income] {fmt_credits(abs(amount))} of Unknown Credits "
                        f"{verb} — a balance change no journal event explains")
        except Exception:
            pass
        gq = getattr(self.core, "gui_queue", None)
        if gq:
            gq.put(("stats_update", None))

    def _reset_counters(self) -> None:
        self.total_income:    int  = 0
        self.by_source:       dict = {}   # source label → int
        self.session_start_time    = None

    def on_session_reset(self) -> None:
        self._reset_counters()

    def _add(self, logtime, amount: int, label: str) -> None:
        if amount <= 0:
            return
        with self._lock:
            if self.session_start_time is None:
                self.session_start_time = logtime
            self.total_income += amount
            self.by_source[label] = self.by_source.get(label, 0) + amount
        gq = self.core.gui_queue
        if gq:
            gq.put(("stats_update", None))

    def on_event(self, event: dict, state) -> None:
        ev      = event.get("event")
        logtime = event.get("_logtime")

        if ev in ("LoadGame", "Commander"):
            if self._reconciler:
                self._reconciler.reset()
            return
        if self._reconciler:
            self._reconciler.observe_event(
                event, logtime.timestamp() if logtime is not None else None)

        match ev:

            case "RedeemVoucher":
                vtype  = event.get("Type", "")
                amount = int(event.get("Amount", 0))
                pct    = float(event.get("BrokerPercentage", 0.0))
                # Amount is post-broker; recover face value
                face   = round(amount / (1.0 - pct / 100.0)) if pct else amount
                label  = {
                    "bounty":     "Bounties",
                    "CombatBond": "Combat bonds",
                    "trade":      "Trade vouchers",
                }.get(vtype, "Vouchers")
                self._add(logtime, face, label)

            case "MissionCompleted":
                self._add(logtime, int(event.get("Reward", 0)), "Missions")

            case "SellExplorationData" | "MultiSellExplorationData":
                self._add(logtime, int(event.get("TotalEarnings", 0)), "Cartography")

            case "SellOrganicData":
                total = sum(
                    int(item.get("Value", 0))
                    for item in event.get("BioData", [])
                )
                self._add(logtime, total, "Exobiology")

            case "MarketSell":
                # Mined ore was never bought, so it has no average paid price.
                # Selling it is mining revenue, not trade profit, and filing
                # it under Trade made a mining session look like a trade run.
                mined = int(event.get("AvgPricePaid", 0) or 0) == 0
                self._add(logtime, int(event.get("TotalSale", 0)),
                          "Mining" if mined else "Trade")

    # ── ActivityProviderMixin ─────────────────────────────────────────────────

    def has_activity(self) -> bool:
        return self.total_income > 0

    def _cph(self) -> str | None:
        dur = self._duration_seconds()
        if dur < 60 or self.total_income <= 0:
            return None
        cph = self.total_income / (dur / 3600.0)
        return f"{fmt_credits(round(cph))}/hr"

    def get_summary_rows(self) -> list[dict]:
        if not self.total_income:
            return []
        return [{
            "label": "Session income",
            "value": fmt_credits(self.total_income),
            "rate":  self._cph(),
        }]

    # ── overlay ───────────────────────────────────────────────────────────────

    OVERLAY_PANELS = ("income",)

    def overlay_panel(self, panel_id: str, ctx):
        """Credits, and what this session has added to them."""
        if panel_id != "income":
            return None
        from core.overlay_panels import Panel

        state = getattr(self.core, "state", None) if self.core else None
        rows: list[tuple[str, str]] = []

        balance = getattr(state, "assets_balance", None) if state else None
        if balance is not None:
            rows.append(("Credits:", _overlay_credits(balance)))

        if self.total_income:
            rate = self._cph()
            earned = fmt_credits(self.total_income)
            rows.append(("Session:", f"{earned} | {rate}" if rate else earned))

        return Panel(id="income", title="INCOME", rows=rows) if rows else None


    def get_session_rows(self) -> list[dict]:
        """Every earning stream, then the total and the rate.

        Only *redeemed* vouchers count.
        """
        if not self.total_income:
            return []

        rows = [
            {"label": label, "value": fmt_credits(amount), "rate": None}
            for label, amount in sorted(self.by_source.items(),
                                        key=lambda kv: -kv[1])
        ]
        rows.append({"label": "Total earned",
                     "value": fmt_credits(self.total_income), "rate": None})
        rate = self._cph()
        if rate:
            rows.append({"label": "Rate", "value": rate, "rate": None})
        return rows

    def get_tab_rows(self) -> list[dict]:
        rows = self.get_summary_rows()
        if self.by_source:
            rows.append({"label": "─── By source ───", "value": "", "rate": None})
            for label, amount in sorted(
                self.by_source.items(), key=lambda x: -x[1]
            ):
                rows.append({
                    "label": f"  {label}",
                    "value": fmt_credits(amount),
                    "rate":  None,
                })
        return rows
