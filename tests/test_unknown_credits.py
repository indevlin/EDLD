"""Unknown Credits: income the journal never mentions.

Claiming a PowerPlay care package writes nothing to the journal; the credits
just appear in the balance. These tests pin down how EDLD notices that, live
from Status.json and across a career from LoadGame, and how it avoids
counting money the journal does explain.
"""
import json
from types import SimpleNamespace

from core.credit_flows import (BalanceReconciler, SETTLE_S, credit_delta,
                               MIN_UNKNOWN_CR)

T0 = 1_760_000_000.0


def test_credit_delta_signs():
    assert credit_delta({"event": "MarketSell", "TotalSale": 95_371_264}) == 95_371_264
    assert credit_delta({"event": "MarketBuy", "TotalCost": 1_000}) == -1_000
    assert credit_delta({"event": "NpcCrewPaidWage", "Amount": 9_537_127}) == -9_537_127
    assert credit_delta({"event": "MissionCompleted", "Reward": 0,
                         "Donation": "1000000", "Donated": 1_000_000}) == -1_000_000
    assert credit_delta({"event": "CarrierBankTransfer", "Deposit": 5, "Withdraw": 0}) == -5
    assert credit_delta({"event": "PowerplayMerits", "MeritsGained": 56}) is None
    assert credit_delta({"event": "Bounty", "TotalReward": 9}) is None   # a voucher, not cash


class _Rec:
    def __init__(self):
        self.reports = []
        self.r = BalanceReconciler(lambda amount, ts: self.reports.append(amount))

    def balance(self, b, t):
        self.r.observe_balance(b, t)

    def event(self, ev, t):
        self.r.observe_event(ev, t)

    def settle(self, t):
        return self.r.settle(t)


def _anchored(balance=751_897_248):
    rec = _Rec()
    rec.balance(balance, T0)
    rec.settle(T0 + SETTLE_S + 1)          # first quiet moment anchors
    return rec


def test_a_care_package_is_reported():
    rec = _anchored()
    rec.balance(751_897_248 + 500_000, T0 + 100)
    assert rec.settle(T0 + 100 + SETTLE_S + 1) == 500_000
    assert rec.reports == [500_000]


def test_logged_income_is_not_reported():
    rec = _anchored()
    rec.balance(751_897_248 + 95_371_264 - 9_537_127, T0 + 100)
    rec.event({"event": "MarketSell", "TotalSale": 95_371_264}, T0 + 100)
    rec.event({"event": "NpcCrewPaidWage", "Amount": 9_537_127}, T0 + 100)
    assert rec.settle(T0 + 100 + SETTLE_S + 1) == 0
    assert rec.reports == []


def test_nothing_is_compared_until_both_sides_are_quiet():
    rec = _anchored()
    rec.balance(751_897_248 + 500_000, T0 + 100)
    assert rec.settle(T0 + 100 + SETTLE_S - 1) == 0
    rec.event({"event": "RedeemVoucher", "Type": "trade", "Amount": 500_000}, T0 + 100)
    assert rec.settle(T0 + 100 + SETTLE_S + 1) == 0
    assert rec.reports == []


def test_a_journal_line_that_arrives_late_takes_its_share_back():
    rec = _anchored()
    rec.balance(751_897_248 + 47_685_632, T0 + 100)
    assert rec.settle(T0 + 100 + SETTLE_S + 1) == 47_685_632
    # The buffered journal finally delivers the voucher, timed before the
    # comparison: the "unknown" credits were not unknown after all.
    rec.event({"event": "RedeemVoucher", "Type": "trade", "Amount": 47_685_632}, T0 + 100)
    assert rec.reports == [47_685_632, -47_685_632]


def test_replayed_old_journal_lines_are_ignored():
    rec = _anchored()
    rec.event({"event": "MarketSell", "TotalSale": 10_000_000}, T0 - 86_400)
    assert rec.settle(T0 + 2 * SETTLE_S) == 0
    assert rec.reports == []


def test_spending_the_table_does_not_know_is_not_income():
    rec = _anchored()
    rec.balance(751_897_248 - 2_000_000, T0 + 100)
    assert rec.settle(T0 + 100 + SETTLE_S + 1) == 0


def test_rounding_is_not_income():
    rec = _anchored()
    rec.balance(751_897_248 + MIN_UNKNOWN_CR - 1, T0 + 100)
    assert rec.settle(T0 + 100 + SETTLE_S + 1) == 0


# ── the Income tab ────────────────────────────────────────────────────────────

def _income():
    import importlib.util
    from pathlib import Path
    spec = importlib.util.spec_from_file_location(
        "income_under_test", Path(__file__).resolve().parents[1] / "components" / "income.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    plugin = mod.ActivityIncomePlugin.__new__(mod.ActivityIncomePlugin)
    state = SimpleNamespace(status_balance=None, status_balance_ts=0.0)
    core = SimpleNamespace(state=state, gui_queue=None, _plugins={},
                           register_session_provider=lambda p: None)
    import threading
    plugin.core = core
    plugin._lock = threading.RLock()
    plugin._reset_counters()
    plugin._reconciler = mod.BalanceReconciler(plugin._on_unknown_credits)
    return mod, plugin, state


def test_unknown_credits_show_in_the_session_breakdown():
    mod, plugin, state = _income()
    state.status_balance, state.status_balance_ts = 1_000_000, T0
    plugin.reconcile_now(T0 + SETTLE_S + 1)
    state.status_balance, state.status_balance_ts = 1_500_000, T0 + 100
    plugin.reconcile_now(T0 + 100 + SETTLE_S + 1)
    rows = {r["label"]: r["value"] for r in plugin.get_session_rows()}
    assert mod.UNKNOWN_CREDITS == "Unknown Credits"
    assert "Unknown Credits" in rows and plugin.total_income == 500_000


# ── the career ledger ─────────────────────────────────────────────────────────

def test_career_ledger_reconciles_between_game_loads(tmp_path):
    lines = [
        {"timestamp": "2026-10-12T05:48:04Z", "event": "LoadGame", "FID": "F1", "Credits": 1_000_000},
        {"timestamp": "2026-10-12T06:00:00Z", "event": "MarketSell", "TotalSale": 2_000_000, "Count": 1, "AvgPricePaid": 0},
        {"timestamp": "2026-10-12T06:10:00Z", "event": "PowerplayRank", "Power": "X", "Rank": 124},
        {"timestamp": "2026-10-13T02:19:55Z", "event": "LoadGame", "FID": "F1", "Credits": 3_500_000},
    ]
    (tmp_path / "Journal.2026-10-12T054800.01.log").write_text(
        "\n".join(json.dumps(x) for x in lines) + "\n")

    import importlib.util
    from pathlib import Path
    spec = importlib.util.spec_from_file_location(
        "jh_under_test", Path(__file__).resolve().parents[1] / "components" / "journal_history.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    import threading
    plugin = mod.JournalHistoryPlugin.__new__(mod.JournalHistoryPlugin)
    plugin.core = SimpleNamespace(journal_dir=str(tmp_path), _plugins={}, gui_queue=None)
    plugin.scan_done = threading.Event()
    plugin.results = {}
    plugin._scan()
    assert plugin.results["finance"]["in"]["Unknown Credits"] == 500_000
