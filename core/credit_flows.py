"""
core/credit_flows.py — every journal event that moves the commander's credits,
and the credits that arrive with no event at all.

Some income is never written to the journal. Claiming a PowerPlay care package
at a Power contact — 250,000 cr below rank 100, 500,000 cr above, plus credits
for any materials the commander cannot hold — writes nothing to the journal;
the money simply appears in the balance. So does anything else the game pays
without logging it. EDLD reports what it cannot attribute as **Unknown
Credits** rather than guessing which of these it was.

It is found by reconciliation. The balance is known at points the game states
it — ``LoadGame.Credits`` in the journal, ``Balance`` in Status.json while the
game runs — and between two of those points the journal accounts for every
change it logs. Whatever is left over arrived without an event.

Two consumers:

* :func:`credit_delta` gives the signed balance change of one journal event,
  and is what the career ledger uses to reconcile between ``LoadGame`` events.
* :class:`BalanceReconciler` does the same live, against Status.json, for the
  session's Income tab.

Only rises are reported. A fall the journal does not explain is a spend this
table does not know, which is not income; the reconciler simply starts again
from the new balance.
"""

from __future__ import annotations

import threading
from typing import Callable, Optional

#: Below this a residual is rounding, not income. Fuel and repair costs are
#: logged rounded; across a session the remainder is a few credits.
MIN_UNKNOWN_CR = 1000

#: How long the balance and the journal must both be quiet before the
#: reconciler trusts the comparison. Status.json is rewritten the moment the
#: balance changes, and the journal line that explains it can arrive seconds
#: later because the game buffers the journal.
SETTLE_S = 10.0

#: Unknown Credits that a late journal line then explains are taken back if
#: the line is timed within this long of the report.
REVERSAL_WINDOW_S = 120.0


def _i(value) -> int:
    try:
        return int(float(value or 0))
    except (TypeError, ValueError):
        return 0


def credit_delta(event: dict) -> Optional[int]:
    """The signed change one event makes to the commander's credit balance.

    ``None`` for an event that does not move credits. Vouchers count when
    redeemed, not when issued; carrier-bank deposits and withdrawals count,
    because they move money out of and into the commander's own balance.
    """
    ev = event.get("event")
    g = event.get

    # ── money in ──
    if ev == "MarketSell":
        return _i(g("TotalSale"))
    if ev == "RedeemVoucher":
        return _i(g("Amount"))                       # already net of any broker
    if ev == "MissionCompleted":
        donated = g("Donated")
        if donated is None:
            donated = g("Donation")
        return _i(g("Reward")) - _i(donated)
    if ev in ("SellExplorationData", "MultiSellExplorationData"):
        return _i(g("TotalEarnings"))
    if ev == "SellOrganicData":
        return sum(_i(b.get("Value")) + _i(b.get("Bonus"))
                   for b in (g("BioData") or []) if isinstance(b, dict))
    if ev == "CommunityGoalReward":
        return _i(g("Reward"))
    if ev == "SearchAndRescue":
        return _i(g("Reward"))
    if ev == "SellDrones":
        return _i(g("TotalSale"))
    if ev in ("ModuleSell", "ModuleSellRemote"):
        return _i(g("SellPrice"))
    if ev in ("ShipyardSell", "SellShipOnRebuy"):
        return _i(g("ShipPrice"))
    if ev in ("SellSuit", "SellWeapon"):
        return _i(g("Price"))
    if ev == "SellMicroResources":
        return _i(g("Price"))
    if ev == "PowerplaySalary":
        return _i(g("Amount"))
    if ev == "CarrierBankTransfer":
        return _i(g("Withdraw")) - _i(g("Deposit"))

    # ── money out ──
    if ev == "MarketBuy":
        return -_i(g("TotalCost"))
    if ev in ("RefuelAll", "RefuelPartial", "Repair", "RepairAll", "BuyAmmo",
              "RestockVehicle", "Resurrect", "CrewHire", "ModuleStore",
              "ModuleRetrieve", "BuyExplorationData", "BuyTradeData",
              "PowerplayFastTrack", "UpgradeSuit", "UpgradeWeapon"):
        return -_i(g("Cost"))
    if ev == "BuyDrones":
        return -_i(g("TotalCost"))
    if ev == "BuyMicroResources":
        return -_i(g("TotalCost") if g("TotalCost") is not None else g("Price"))
    if ev in ("PayFines", "PayBounties", "PayLegacyFines", "Donate"):
        return -_i(g("Amount"))
    if ev == "NpcCrewPaidWage":
        return -_i(g("Amount"))
    if ev == "ModuleBuy":
        return -_i(g("BuyPrice")) + _i(g("SellPrice"))
    if ev == "ModuleBuyAndStore":
        return -_i(g("BuyPrice"))
    if ev == "FetchRemoteModule":
        return -_i(g("TransferCost"))
    if ev == "ShipyardBuy":
        return -_i(g("ShipPrice")) + _i(g("SellPrice"))
    if ev == "ShipyardTransfer":
        return -_i(g("TransferPrice"))
    if ev in ("BuySuit", "BuyWeapon"):
        return -_i(g("Price"))
    if ev == "CarrierBuy":
        return -_i(g("Price"))
    if ev == "EngineerContribution" and str(g("Type", "")).lower() == "credits":
        return -_i(g("Quantity"))
    return None


#: Every event :func:`credit_delta` knows, for subscribing to them.
CREDIT_EVENTS: tuple[str, ...] = (
    "MarketSell", "RedeemVoucher", "MissionCompleted", "SellExplorationData",
    "MultiSellExplorationData", "SellOrganicData", "CommunityGoalReward",
    "SearchAndRescue", "SellDrones", "ModuleSell", "ModuleSellRemote",
    "ShipyardSell", "SellShipOnRebuy", "SellSuit", "SellWeapon",
    "SellMicroResources", "PowerplaySalary", "CarrierBankTransfer",
    "MarketBuy", "RefuelAll", "RefuelPartial", "Repair", "RepairAll",
    "BuyAmmo", "RestockVehicle", "Resurrect", "CrewHire", "ModuleStore",
    "ModuleRetrieve", "BuyExplorationData", "BuyTradeData",
    "PowerplayFastTrack", "UpgradeSuit", "UpgradeWeapon", "BuyDrones",
    "BuyMicroResources", "PayFines", "PayBounties", "PayLegacyFines", "Donate",
    "NpcCrewPaidWage", "ModuleBuy", "ModuleBuyAndStore", "FetchRemoteModule",
    "ShipyardBuy", "ShipyardTransfer", "BuySuit", "BuyWeapon", "CarrierBuy",
    "EngineerContribution",
)


class BalanceReconciler:
    """Live reconciliation of the Status.json balance against the journal.

    Times are seconds since the epoch, from the game's own timestamps — the
    ``timestamp`` in Status.json and in each journal line — so the two clocks
    being compared are the same clock.

    Status.json shows a balance change the moment it happens; the journal line
    that explains it can arrive seconds later, because the game buffers the
    journal. So nothing is compared until both have been quiet for
    :data:`SETTLE_S`. The balance at that moment is the anchor: it includes
    every event up to then, whether or not its line has been read yet, so
    journal events timed at or before the anchor are never added to it. That
    also keeps the startup replay of old journals out of the sum.

    A line that turns up after a comparison, timed before it, is one the
    comparison was missing. If it is income and that comparison reported
    Unknown Credits, the report is taken back by as much as the line explains.
    """

    def __init__(self, on_unknown: Callable[[int, float], None]):
        self._on_unknown = on_unknown
        self._lock = threading.Lock()
        self._anchor: Optional[int] = None
        self._anchor_ts = 0.0
        self._anchor_event_ts = 0.0
        self._flows = 0
        self._balance: Optional[int] = None
        self._balance_ts = 0.0
        self._last_event_ts = 0.0
        self._recent_unknown = 0
        self._recent_unknown_ts = 0.0

    def observe_balance(self, balance: int, ts: float) -> None:
        with self._lock:
            if balance != self._balance:
                self._balance = int(balance)
                self._balance_ts = ts

    def observe_event(self, event: dict, ts: Optional[float]) -> None:
        delta = credit_delta(event)
        if delta is None or ts is None:
            return
        correction = 0
        with self._lock:
            if self._anchor is not None:
                if ts > self._anchor_ts:
                    self._flows += delta
                elif (ts > self._anchor_event_ts and delta > 0
                        and self._recent_unknown > 0
                        and self._recent_unknown_ts - ts <= REVERSAL_WINDOW_S):
                    correction = -min(delta, self._recent_unknown)
                    self._recent_unknown += correction
            self._last_event_ts = max(self._last_event_ts, ts)
        if correction:
            self._on_unknown(correction, ts)

    def reset(self) -> None:
        """Forget the anchor: a new game session, or another commander."""
        with self._lock:
            self._anchor = None
            self._flows = 0
            self._recent_unknown = 0

    def settle(self, now: float) -> int:
        """Compare, if both sides are quiet. Returns the credits reported."""
        with self._lock:
            if self._balance is None:
                return 0
            if now - max(self._balance_ts, self._last_event_ts) < SETTLE_S:
                return 0
            if self._anchor is None:
                self._reanchor(now)
                return 0
            residual = self._balance - (self._anchor + self._flows)
            self._reanchor(now)
            if residual < MIN_UNKNOWN_CR:
                # Nothing, rounding, or a spend the table does not know —
                # none of which is income.
                return 0
            self._recent_unknown, self._recent_unknown_ts = residual, now
        self._on_unknown(residual, now)
        return residual

    def _reanchor(self, now: float) -> None:
        self._anchor = self._balance
        self._anchor_ts = now
        self._anchor_event_ts = self._last_event_ts
        self._flows = 0
