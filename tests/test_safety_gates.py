import fcntl
import inspect
import os
from pathlib import Path
import subprocess
import sys
import time
import sqlite3
from decimal import Decimal
from types import SimpleNamespace

import pytest
import requests
from ladder_dragon.supervision import runtime as ai_supervisor
from ladder_dragon.execution.worker.buy_service import (
    place_buys as place_buys_service,
)
from ladder_dragon.execution.worker.holdings_service import (
    place_sells_from_holdings as place_holdings_service,
)
from tests.support.module_loaders import load_worker


def place_buys(worker, *args, **kwargs):
    """Exercise the package BUY service with explicit test adapters."""
    return place_buys_service(*args, runtime=vars(worker), **kwargs)


def place_holdings(worker, *args, **kwargs):
    """Exercise the package holdings service with explicit test adapters."""
    return place_holdings_service(*args, runtime=vars(worker), **kwargs)


@pytest.mark.parametrize(
    ("desired", "operator_limit", "expected"),
    [
        (3, 1, 1),
        (2, 4, 2),
        (0, 0, 1),
    ],
)
def test_adaptive_target_buys_cannot_exceed_operator_limit(
    desired,
    operator_limit,
    expected,
):
    assert ai_supervisor.limit_target_buys(desired, operator_limit) == expected


def test_strategy_apply_requires_explicit_approval_and_statistical_gate(
    monkeypatch,
):
    class Store:
        def resolved_samples(self, symbol, *, kind):
            assert symbol == "SOLUSDT"
            assert kind == "CONTROL_EXPECTANCY"
            return ["historical-only"]

    monkeypatch.setattr(ai_supervisor, "_PREDICTION_SHADOW", Store())
    monkeypatch.setattr(
        ai_supervisor,
        "walk_forward_prediction_report",
        lambda samples: {
            "gate": {
                "approved": True,
                "mode": "APPLY",
                "reasons": [],
            }
        },
    )
    ai_supervisor._STRATEGY_CONTROL_GATE_CACHE.clear()
    monkeypatch.setenv("BOT_EXPECTANCY_APPROVED", "NO")
    allowed, _ = ai_supervisor._strategy_control_apply_allowed(
        "SOLUSDT", "expectancy"
    )
    assert allowed is False

    monkeypatch.setenv("BOT_EXPECTANCY_APPROVED", "YES")
    allowed, evidence = ai_supervisor._strategy_control_apply_allowed(
        "SOLUSDT", "expectancy"
    )
    assert allowed is True
    assert evidence["approved"] is True
    ai_supervisor._STRATEGY_CONTROL_GATE_CACHE.clear()


def test_strategy_apply_blocks_when_evidence_is_unavailable(monkeypatch):
    monkeypatch.setattr(ai_supervisor, "_PREDICTION_SHADOW", None)
    monkeypatch.setenv("BOT_MAKER_POLICY_APPROVED", "YES")
    ai_supervisor._STRATEGY_CONTROL_GATE_CACHE.clear()

    allowed, evidence = ai_supervisor._strategy_control_apply_allowed(
        "SOLUSDT", "maker"
    )

    assert allowed is False
    assert evidence["approved"] is False
    ai_supervisor._STRATEGY_CONTROL_GATE_CACHE.clear()


def test_managed_inventory_cap_never_falls_back_to_portfolio(monkeypatch):
    monkeypatch.delenv(
        "RISK_MANAGED_INVENTORY_HARD_CAP_SOLUSDT", raising=False
    )
    monkeypatch.delenv(
        "RISK_MANAGED_INVENTORY_HARD_CAP_USDT", raising=False
    )
    monkeypatch.setenv("RISK_PORTFOLIO_CAP_USDT", "3000")

    with pytest.raises(ValueError, match="explicitly configured"):
        ai_supervisor._managed_inventory_hard_cap("SOLUSDT")

    monkeypatch.setenv("RISK_MANAGED_INVENTORY_HARD_CAP_SOLUSDT", "30")
    assert ai_supervisor._managed_inventory_hard_cap(
        "SOLUSDT"
    ) == Decimal("30")


def test_expectancy_shadow_never_exports_execution_edge(monkeypatch):
    schedule = ai_supervisor.CommissionSchedule(
        maker_buy=Decimal("0.00075"),
        maker_sell=Decimal("0.00075"),
        taker_buy=Decimal("0.001"),
        taker_sell=Decimal("0.001"),
        discount_observed=True,
    )

    shadow = ai_supervisor._strategy_child_env(
        commission_schedule=schedule,
        required_edge=Decimal("0.0096"),
        expectancy_mode="SHADOW",
        maker_mode="SHADOW",
    )
    apply = ai_supervisor._strategy_child_env(
        commission_schedule=schedule,
        required_edge=Decimal("0.0096"),
        expectancy_mode="APPLY",
        maker_mode="SHADOW",
    )

    assert shadow["BOT_BUY_FEE_PCT"] == "0.00075"
    assert shadow["BOT_SELL_FEE_PCT"] == "0.00075"
    assert "BOT_REQUIRED_EDGE_PCT" not in shadow
    assert apply["BOT_REQUIRED_EDGE_PCT"] == "0.0096"
    monkeypatch.setenv("BOT_REQUIRED_EDGE_PCT", "0.777-stale")
    assert "BOT_REQUIRED_EDGE_PCT" not in (
        ai_supervisor._child_process_env(shadow)
    )
    assert ai_supervisor._child_process_env(apply)[
        "BOT_REQUIRED_EDGE_PCT"
    ] == "0.0096"


def test_cap_scaling_reports_enabled_controls_without_cap():
    assert ai_supervisor._cap_scaling_inactive_reason(
        Decimal("0"),
        inventory_mode="APPLY",
        regime_mode="SHADOW",
    ) == (
        "BOT_CAP_PER_ORDER is not positive;"
        " inactive_controls=inventory,regime"
    )
    assert ai_supervisor._cap_scaling_inactive_reason(
        Decimal("10"),
        inventory_mode="APPLY",
        regime_mode="APPLY",
    ) is None
    assert ai_supervisor._cap_scaling_inactive_reason(
        Decimal("0"),
        inventory_mode="OFF",
        regime_mode="OFF",
    ) is None


def _entry_settings(mode: str):
    return ai_supervisor._directional_entry_settings(
        base_gap="0.004",
        atr_pct="0.001",
        base_min_profit="0.002",
        auto_adapt=True,
        gap_atr_coefficient="0.6",
        profit_atr_coefficient="0.6",
        gap_floor="0.0025",
        gap_ceiling="0.02",
        mode=mode,
        up_gap_multiplier="0.80",
        down_gap_multiplier="1.50",
        take_profit_pct="0.006",
        up_tp_multiplier="1.00",
        down_tp_multiplier="1.00",
        tp_floor="0.003",
        tp_ceiling="0.009",
    )


def test_directional_entry_follows_rising_market_without_crossing_it():
    up_gap, up_min_profit, up_tp = _entry_settings("UP")
    flat_gap, _, _ = _entry_settings("FLAT")
    down_gap, _, _ = _entry_settings("DOWN")
    market = Decimal("75.11")
    buy = ai_supervisor._adaptive_best_buy_price(market, up_gap)

    assert up_gap < flat_gap < down_gap
    assert Decimal("0") < buy < market
    assert buy > market * Decimal("0.995")
    assert (market - buy) / market == up_gap
    assert up_tp >= up_min_profit


def test_directional_entry_fails_closed_when_profit_floor_exceeds_tp_cap():
    with pytest.raises(ValueError, match="minimum profitable TP"):
        ai_supervisor._directional_entry_settings(
            base_gap="0.004",
            atr_pct="0.02",
            base_min_profit="0.002",
            auto_adapt=True,
            gap_atr_coefficient="0.6",
            profit_atr_coefficient="0.6",
            gap_floor="0.0025",
            gap_ceiling="0.02",
            mode="UP",
            up_gap_multiplier="0.80",
            down_gap_multiplier="1.50",
            take_profit_pct="0.006",
            up_tp_multiplier="1.00",
            down_tp_multiplier="1.00",
            tp_floor="0.003",
            tp_ceiling="0.009",
        )


@pytest.mark.parametrize(
    ("market", "gap"),
    [("0", "0.004"), ("75", "0"), ("75", "1"), ("75", "-0.1")],
)
def test_adaptive_best_buy_rejects_unsafe_inputs(market, gap):
    with pytest.raises(ValueError, match="adaptive BUY"):
        ai_supervisor._adaptive_best_buy_price(market, gap)


def test_runtime_recovery_reason_redacts_signed_url_material():
    reason = ai_supervisor._runtime_recovery_reason(
        RuntimeError(
            "failed https://api.binance.com/api/v3/order?"
            "symbol=SOLUSDT&signature=private-signature"
        )
    )

    assert "private-signature" not in reason
    assert "<redacted>" in reason


def test_worker_average_entry_uses_verified_local_lots_without_trade_history(
    monkeypatch,
):
    from ladder_dragon.execution.inventory_lots import CostBasisCoverage

    worker = load_worker()
    worker._AVG_CACHE.clear()
    worker.STATS_CON = object()
    monkeypatch.setattr(worker, "_stats_init_if_needed", lambda: None)
    monkeypatch.setattr(worker, "get_symbol_assets", lambda symbol: ("SOL", "USDT"))
    monkeypatch.setattr(
        worker,
        "get_balances",
        lambda: {"SOL": {"free": "1.25", "locked": "0"}},
    )
    monkeypatch.setattr(worker, "pull_filters", lambda symbol: {"stepSize": "0.001"})
    monkeypatch.setattr(
        worker,
        "cost_basis_coverage",
        lambda *args, **kwargs: CostBasisCoverage(
            symbol="SOLUSDT",
            account_qty=Decimal("1.25"),
            covered_qty=Decimal("1.25"),
            average_price=Decimal("77.125"),
            uncovered_qty=Decimal("0"),
            tolerance_qty=Decimal("0.0025"),
            covered=True,
            reason="covered",
        ),
    )
    monkeypatch.setattr(
        worker,
        "_signed_request",
        lambda *args, **kwargs: pytest.fail("exchange trade history requested"),
    )

    assert worker.avg_entry("SOLUSDT") == Decimal("77.125")


def test_worker_average_entry_fails_closed_for_unverified_legacy_lots(
    monkeypatch,
):
    from ladder_dragon.execution.inventory_lots import CostBasisCoverage

    worker = load_worker()
    worker._AVG_CACHE.clear()
    worker.STATS_CON = object()
    monkeypatch.setattr(worker, "_stats_init_if_needed", lambda: None)
    monkeypatch.setattr(worker, "get_symbol_assets", lambda symbol: ("SOL", "USDT"))
    monkeypatch.setattr(
        worker,
        "get_balances",
        lambda: {"SOL": {"free": "3.75", "locked": "0"}},
    )
    monkeypatch.setattr(worker, "pull_filters", lambda symbol: {"stepSize": "0.001"})
    monkeypatch.setattr(
        worker,
        "cost_basis_coverage",
        lambda *args, **kwargs: CostBasisCoverage(
            symbol="SOLUSDT",
            account_qty=Decimal("3.75"),
            covered_qty=Decimal("0"),
            average_price=None,
            uncovered_qty=Decimal("3.75"),
            tolerance_qty=Decimal("0.0075"),
            covered=False,
            reason="unverified legacy inventory",
        ),
    )
    monkeypatch.setattr(
        worker,
        "_signed_request",
        lambda *args, **kwargs: pytest.fail("exchange trade history requested"),
    )

    assert worker.avg_entry("SOLUSDT") is None


def test_supervisor_singleton_flock_rejects_second_process(tmp_path):
    path = tmp_path / "ai_supervisor.lock"
    competing = path.open("w+")
    fcntl.flock(competing.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    ai_supervisor._SINGLETON_LOCK_HANDLE = None
    try:
        with pytest.raises(BlockingIOError):
            ai_supervisor._acquire_singleton_lock(str(path))
    finally:
        fcntl.flock(competing.fileno(), fcntl.LOCK_UN)
        competing.close()
        ai_supervisor._release_singleton_lock()


def test_supervisor_exports_sanitized_order_journal_runtime_snapshot(
    tmp_path, monkeypatch
):
    from ladder_dragon.execution.order_recovery import OrderJournal

    journal = OrderJournal(tmp_path / "order_intents.sqlite3", venue="mainnet")
    journal.prepare(
        client_order_id="LDBLAD-runtime-private",
        symbol="SOLUSDT",
        side="BUY",
        purpose="ladder",
        order_type="LIMIT",
        quantity="0.127",
        price="75.57",
    )
    monkeypatch.setenv("BOT_ORDER_JOURNAL", str(journal.path))

    snapshot = ai_supervisor._runtime_order_journal_snapshot()

    assert snapshot["available"] is True
    assert snapshot["pending"] == 1
    assert "LDBLAD-runtime-private" not in str(snapshot)


def test_supervisor_singleton_flock_is_held_for_process_lifetime(tmp_path):
    path = tmp_path / "ai_supervisor.lock"
    ai_supervisor._SINGLETON_LOCK_HANDLE = None
    try:
        ai_supervisor._acquire_singleton_lock(str(path))
        assert path.read_text() == str(os.getpid())
        with path.open("r+") as competing:
            with pytest.raises(BlockingIOError):
                fcntl.flock(competing.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    finally:
        ai_supervisor._release_singleton_lock()


def test_auto_cap_uses_decimal_and_zeroes_stale_cap(monkeypatch):
    args = SimpleNamespace(
        auto_cap=True,
        alloc_pct="0.50",
        cap_floor_usdt="5",
        cap_ceil_usdt="10",
        target_buy_per_symbol=1,
    )
    monkeypatch.setenv("RISK_RESERVE_USDT", "300")
    monkeypatch.setattr(ai_supervisor, "get_balances", lambda: {"USDT": "331.09148973"})
    messages = []
    monkeypatch.setattr(ai_supervisor, "log", messages.append)

    cap = ai_supervisor.auto_cap_if_needed(args, n_syms=1)

    assert cap == Decimal("10")
    assert os.environ["BOT_CAP_PER_ORDER"] == "10.00"
    assert messages == [
        "[BAL] USDT total_free≈331.09 reserve≈300.00 "
        "spendable_after_reserve≈31.09",
        "[AUTO-CAP] spendable_after_reserve≈31.09 "
        "→ BOT_CAP_PER_ORDER≈10.00 (n_syms=1)",
    ]

    monkeypatch.setattr(
        ai_supervisor,
        "get_balances",
        lambda: (_ for _ in ()).throw(RuntimeError("balance unavailable")),
    )
    assert ai_supervisor.auto_cap_if_needed(args, n_syms=1) == Decimal("0")
    assert os.environ["BOT_CAP_PER_ORDER"] == "0"


def test_auto_cap_threshold_log_identifies_post_reserve_balance(monkeypatch):
    args = SimpleNamespace(
        auto_cap=True,
        alloc_pct="0.50",
        cap_floor_usdt="5",
        cap_ceil_usdt="10",
        target_buy_per_symbol=1,
    )
    monkeypatch.setenv("RISK_RESERVE_USDT", "300")
    monkeypatch.setattr(ai_supervisor, "get_balances", lambda: {"USDT": "305"})
    messages = []
    monkeypatch.setattr(ai_supervisor, "log", messages.append)

    assert ai_supervisor.auto_cap_if_needed(args, n_syms=1) == Decimal("0")
    assert messages == [
        "[AUTO-CAP] spendable_after_reserve≈5.00 < threshold; "
        "failed closed with BOT_CAP_PER_ORDER=0"
    ]


def test_panic_failure_blocks_buy_and_repeated_failure_halts(monkeypatch):
    worker = load_worker()
    worker.LIVE_MODE = True
    worker._SAFETY_CONTROL_FAILURES.clear()
    halts = []
    monkeypatch.setenv("BOT_SAFETY_FAILURE_HALT_THRESHOLD", "2")
    monkeypatch.setattr(
        worker,
        "_trip_execution_halt",
        lambda reason, **metadata: halts.append((reason, metadata)),
    )
    monkeypatch.setattr(worker, "log", lambda message: None)

    def unavailable():
        raise RuntimeError("indicator failure")

    assert worker._panic_state_fail_closed(
        "panic-state", "SOLUSDT", unavailable
    ) == (True, "panic-state-unavailable")
    assert halts == []
    assert worker._panic_state_fail_closed(
        "panic-state", "SOLUSDT", unavailable
    ) == (True, "panic-state-unavailable")
    assert halts[0][1]["control"] == "panic-state"


def test_panic_debounce_state_survives_executor_restart(tmp_path, monkeypatch):
    monkeypatch.setenv("BOT_RUN_DIR", str(tmp_path))
    first = load_worker()
    first._panic.clear()
    first._panic_loaded.clear()

    assert first.update_panic_state(
        "SOLUSDT",
        now_px=90.0,
        ema20=100.0,
        atr=1.0,
        prev_close=100.0,
        avg_entry_px=None,
        debounce_checks=2,
    ) is False

    state_file = tmp_path / "panic_state_SOLUSDT.json"
    assert state_file.exists()
    assert state_file.stat().st_mode & 0o777 == 0o600

    restarted = load_worker()
    restarted._panic.clear()
    restarted._panic_loaded.clear()
    assert restarted.update_panic_state(
        "SOLUSDT",
        now_px=90.0,
        ema20=100.0,
        atr=1.0,
        prev_close=100.0,
        avg_entry_px=None,
        debounce_checks=2,
    ) is True


def test_live_raw_panic_signal_blocks_buy_before_debounce():
    worker = load_worker()

    assert worker._panic_buy_block_reason(
        None,
        live_mode=True,
        raw_signal=True,
        debounced_active=False,
        skip_while_panic=False,
    ) == "panic-raw-signal"
    assert worker._panic_buy_block_reason(
        None,
        live_mode=False,
        raw_signal=True,
        debounced_active=False,
        skip_while_panic=False,
    ) is None


def test_live_panic_recovery_restarts_only_after_confirmed_empty_transition():
    worker = load_worker()

    assert worker._panic_recovery_restart_required(
        live_mode=True,
        was_active=True,
        is_active=False,
        tracked_buy_order_ids=[],
    ) is True
    assert worker._panic_recovery_restart_required(
        live_mode=True,
        was_active=True,
        is_active=True,
        tracked_buy_order_ids=[],
    ) is False
    assert worker._panic_recovery_restart_required(
        live_mode=True,
        was_active=False,
        is_active=False,
        tracked_buy_order_ids=[],
    ) is False
    assert worker._panic_recovery_restart_required(
        live_mode=True,
        was_active=True,
        is_active=False,
        tracked_buy_order_ids=[12345],
    ) is False
    assert worker._panic_recovery_restart_required(
        live_mode=False,
        was_active=True,
        is_active=False,
        tracked_buy_order_ids=[],
    ) is False


def test_panic_recovery_restart_uses_no_market_future_or_secret_input():
    worker = load_worker()
    parameters = set(
        inspect.signature(worker._panic_recovery_restart_required).parameters
    )

    assert parameters == {
        "live_mode",
        "was_active",
        "is_active",
        "tracked_buy_order_ids",
    }


def test_corrupt_panic_state_fails_closed(tmp_path, monkeypatch):
    worker = load_worker()
    worker.LIVE_MODE = True
    worker._panic.clear()
    worker._panic_loaded.clear()
    monkeypatch.setenv("BOT_RUN_DIR", str(tmp_path))
    (tmp_path / "panic_state_SOLUSDT.json").write_text("not-json")
    monkeypatch.setattr(worker, "log", lambda message: None)

    active, reason = worker._panic_state_fail_closed(
        "panic-state",
        "SOLUSDT",
        lambda: worker.update_panic_state(
            "SOLUSDT",
            now_px=100.0,
            ema20=100.0,
            atr=1.0,
            prev_close=100.0,
            avg_entry_px=None,
        ),
    )

    assert active is True
    assert reason == "panic-state-unavailable"


def test_gap_watchdog_failure_blocks_buy_and_escalates(monkeypatch):
    worker = load_worker()
    worker.LIVE_MODE = True
    worker._SAFETY_CONTROL_FAILURES.clear()
    halts = []
    monkeypatch.setenv("BOT_SAFETY_FAILURE_HALT_THRESHOLD", "2")
    monkeypatch.setattr(worker, "log", lambda message: None)
    monkeypatch.setattr(
        worker,
        "_trip_execution_halt",
        lambda reason, **metadata: halts.append((reason, metadata)),
    )
    monkeypatch.setattr(
        worker,
        "emergency_gap_flatten",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            RuntimeError("gap state unavailable")
        ),
    )

    kwargs = {
        "dependencies": worker._protection_dependencies(),
        "gap_tolerance_pct": 0.001,
    }
    assert worker._gap_watchdog_fail_closed(
        "SOLUSDT", 75.0, **kwargs
    ) == "gap-watchdog-unavailable"
    assert halts == []
    assert worker._gap_watchdog_fail_closed(
        "SOLUSDT", 75.0, **kwargs
    ) == "gap-watchdog-unavailable"
    assert halts[0][1]["control"] == "gap-watchdog"


def test_supervisor_dry_cancel_never_reaches_transport(monkeypatch):
    ai_supervisor.LIVE_MODE = False
    monkeypatch.setattr(
        ai_supervisor,
        "_canonical_signed_request",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("transport called")),
    )
    assert ai_supervisor.cancel_order("SOLUSDT", 123) is False


def test_worker_dry_blocks_every_mutating_signed_request():
    worker = load_worker()
    worker.LIVE_MODE = False
    try:
        worker._signed_request("DELETE", "/api/v3/order", {})
    except RuntimeError as exc:
        assert "DRY mode blocked" in str(exc)
    else:
        raise AssertionError("mutating request was not blocked")


def test_worker_hard_cap_uses_smallest_authority(monkeypatch):
    worker = load_worker()
    monkeypatch.setenv("BOT_OPERATOR_CAP_PER_ORDER_USDT", "10")
    monkeypatch.setenv("BOT_CAP_PER_ORDER", "9.63")
    monkeypatch.setenv("RISK_SYMBOL_CAP_SOLUSDT", "9.62")

    cap, limits = worker.hard_buy_cap("SOLUSDT", "12.51")

    assert cap == Decimal("9.62")
    assert limits == {
        "strategy": Decimal("12.51"),
        "operator": Decimal("10"),
        "risk": Decimal("9.63"),
        "symbol": Decimal("9.62"),
    }


def test_worker_hard_cap_rejects_non_finite_value(monkeypatch):
    worker = load_worker()
    monkeypatch.setenv("BOT_CAP_PER_ORDER", "NaN")

    with pytest.raises(ValueError, match="finite"):
        worker.hard_buy_cap("SOLUSDT", "10")


def test_worker_live_remainder_policy_never_bypasses_cap():
    worker = load_worker()

    assert worker.effective_remainder_policy(requested=True, live_mode=True) is False
    assert worker.effective_remainder_policy(requested=True, live_mode=False) is True
    assert worker.effective_remainder_policy(requested=False, live_mode=False) is False


def test_worker_exchange_filters_fail_closed_on_malformed_metadata(monkeypatch):
    worker = load_worker()
    worker.symbol_filters.clear()
    worker.symbol_exchange_info.clear()
    monkeypatch.setattr(worker, "exchange_info", lambda symbol: {"symbols": []})

    with pytest.raises(RuntimeError, match="invalid exchange filters"):
        worker.pull_filters("SOLUSDT")


def test_holdings_sell_percent_filter_blocks_exchange_mutation(monkeypatch):
    worker = load_worker()
    monkeypatch.setattr(worker, "get_symbol_assets", lambda symbol: ("SOL", "USDT"))
    worker.symbol_filters["SOLUSDT"] = {
        "tickSize": 0.01, "stepSize": 0.001,
        "minQty": 0.001, "minNotional": 5.0,
    }
    worker.symbol_exchange_info["SOLUSDT"] = {
        "symbol": "SOLUSDT",
        "filters": [{
            "filterType": "PERCENT_PRICE_BY_SIDE",
            "askMultiplierDown": "0.8",
            "askMultiplierUp": "1.2",
        }],
    }
    monkeypatch.setattr(worker, "pull_filters", lambda symbol: None)
    monkeypatch.setattr(
        worker,
        "_holdings_cost_basis_covered",
        lambda *args: Decimal("90"),
    )
    monkeypatch.setattr(
        worker, "get_balances", lambda: {"SOL": {"free": 1, "locked": 0}}
    )
    monkeypatch.setattr(worker, "get_price", lambda symbol: 100.0)
    monkeypatch.setattr(worker, "get_price_exact", lambda symbol: Decimal("100"))
    monkeypatch.setattr(
        worker, "_public_get", lambda path, params=None: {"price": "100"}
    )
    monkeypatch.setattr(worker, "_record_safety_control_failure", lambda *args: None)
    monkeypatch.setattr(
        worker, "place_limit_order",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("out-of-band holdings SELL reached exchange mutation")
        ),
    )

    assert place_holdings(worker,
        "SOLUSDT", [150.0], avg_entry_px=90.0,
    ) == 0


def test_panic_flatten_uses_full_step_aligned_free_balance(monkeypatch):
    worker = load_worker()
    worker.symbol_filters["SOLUSDT"] = {
        "tickSize": 0.01,
        "tickSizeExact": "0.01",
        "stepSize": 0.001,
        "stepSizeExact": "0.001",
        "minQty": 0.001,
        "minQtyExact": "0.001",
        "minNotional": 5.0,
        "minNotionalExact": "5",
    }
    sold = []
    monkeypatch.setenv("PANIC_FLATTEN_HOLDINGS", "1")
    monkeypatch.setattr(
        worker,
        "get_symbol_assets",
        lambda symbol: ("SOL", "USDT"),
    )
    monkeypatch.setattr(
        worker,
        "get_balances",
        lambda: {"SOL": {"free": "1.000", "locked": "0"}},
    )
    monkeypatch.setattr(worker, "pull_filters", lambda symbol: None)
    monkeypatch.setattr(
        worker,
        "get_price_exact",
        lambda symbol: Decimal("100"),
    )
    monkeypatch.setattr(
        worker,
        "place_market_order",
        lambda *args, **kwargs: (
            sold.append((args, kwargs))
            or {"orderId": 99, "status": "FILLED", "executedQty": "1.000"}
        ),
    )

    assert place_holdings(worker,
        "SOLUSDT",
        [110.0],
        panic_active=True,
    ) == 1
    assert sold[0][0][:3] == ("SOLUSDT", "SELL", Decimal("1.000"))


def test_holdings_sell_leaves_only_sub_step_exchange_dust(monkeypatch):
    worker = load_worker()
    worker.symbol_filters["SOLUSDT"] = {
        "tickSize": 0.01,
        "tickSizeExact": "0.01",
        "stepSize": 0.001,
        "stepSizeExact": "0.001",
        "minQty": 0.001,
        "minQtyExact": "0.001",
        "minNotional": 5.0,
        "minNotionalExact": "5",
    }
    placed = []
    monkeypatch.setattr(
        worker,
        "get_symbol_assets",
        lambda symbol: ("SOL", "USDT"),
    )
    monkeypatch.setattr(
        worker,
        "get_balances",
        lambda: {"SOL": {"free": "1.0004", "locked": "0"}},
    )
    monkeypatch.setattr(worker, "pull_filters", lambda symbol: None)
    monkeypatch.setattr(
        worker,
        "_holdings_cost_basis_covered",
        lambda *args: Decimal("90"),
    )
    monkeypatch.setattr(
        worker,
        "get_price_exact",
        lambda symbol: Decimal("100"),
    )
    monkeypatch.setattr(
        worker,
        "validate_limit_sell_prices",
        lambda symbol, prices: None,
    )
    monkeypatch.setattr(
        worker,
        "place_limit_order",
        lambda *args, **kwargs: (
            placed.append((args, kwargs))
            or {"orderId": 100, "status": "NEW"}
        ),
    )

    assert place_holdings(worker,
        "SOLUSDT",
        [110.0],
    ) == 1
    assert placed[0][0][2] == Decimal("1.000")


def test_worker_blocks_oversized_plan_before_exchange_mutation(monkeypatch):
    worker = load_worker()
    worker.RUN = True
    monkeypatch.setattr(worker, "get_symbol_assets", lambda symbol: ("SOL", "USDT"))
    worker.symbol_filters["SOLUSDT"] = {
        "tickSize": 0.01,
        "stepSize": 0.001,
        "minQty": 0.001,
        "minNotional": 5.0,
    }
    monkeypatch.setattr(worker, "pull_filters", lambda symbol: None)
    monkeypatch.setattr(
        worker,
        "get_balances",
        lambda: {"USDT": {"free": 100.0, "locked": 0.0}},
    )
    monkeypatch.setattr(worker, "get_price", lambda symbol: 100.0)
    monkeypatch.setattr(worker, "get_price_exact", lambda symbol: Decimal("100"))
    monkeypatch.setattr(
        worker,
        "plan_buy_order_decimal",
        lambda *args, **kwargs: SimpleNamespace(
            price=Decimal("90"),
            quantity=Decimal("0.2"),
            notional=Decimal("18"),
        ),
    )
    monkeypatch.setattr(
        worker,
        "place_limit_order",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("oversized BUY reached exchange mutation")
        ),
    )

    assert place_buys(worker,
        "SOLUSDT",
        [90.0],
        10.0,
        target_buy_per_symbol=1,
        enforce_limit=False,
        use_remainder_in_last=True,
        live_mode=True,
    ) == []


def test_fast_market_apply_blocks_stale_buy_before_exchange_mutation(
    tmp_path,
    monkeypatch,
):
    from ladder_dragon.execution.market_data_stream import (
        DecisionFreshnessPolicy,
        MarketSnapshotStore,
    )

    worker = load_worker()
    worker.RUN = True
    monkeypatch.setenv("BOT_LATENCY_TRACE_LOG", str(tmp_path / "latency.ndjson"))
    monkeypatch.setattr(worker, "get_symbol_assets", lambda symbol: ("SOL", "USDT"))
    worker.symbol_filters["SOLUSDT"] = {
        "tickSize": 0.01,
        "stepSize": 0.001,
        "minQty": 0.001,
        "minNotional": 5.0,
    }
    monkeypatch.setattr(worker, "pull_filters", lambda symbol: None)
    monkeypatch.setattr(
        worker,
        "get_balances",
        lambda: {"USDT": {"free": 100.0, "locked": 0.0}},
    )
    monkeypatch.setattr(worker, "get_price_exact", lambda symbol: Decimal("100"))
    monkeypatch.setattr(
        worker,
        "place_limit_order",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("stale BUY reached exchange mutation")
        ),
    )
    ticks = iter((1_000_000_000, 1_100_000_000))
    store = MarketSnapshotStore(
        "SOLUSDT",
        monotonic_ns=lambda: next(ticks),
    )
    store.update({"b": "100", "B": "2", "a": "100.01", "A": "2"})
    store.update({
        "lastUpdateId": 10,
        "bids": [["100", "2"]],
        "asks": [["100.01", "2"]],
    })
    monkeypatch.setattr(worker.time, "monotonic_ns", lambda: 2_000_000_000)

    assert place_buys(worker,
        "SOLUSDT",
        [90.0, 110.0],
        10.0,
        target_buy_per_symbol=1,
        market_store=store,
        market_policy=DecisionFreshnessPolicy(max_age_ms=100),
        market_mode="APPLY",
    ) == []


def test_worker_blocks_buy_when_open_order_state_is_unavailable(monkeypatch):
    worker = load_worker()
    worker.RUN = True
    monkeypatch.setattr(worker, "get_symbol_assets", lambda symbol: ("SOL", "USDT"))
    worker.symbol_filters["SOLUSDT"] = {
        "tickSize": 0.01,
        "stepSize": 0.001,
        "minQty": 0.001,
        "minNotional": 5.0,
    }
    monkeypatch.setattr(worker, "pull_filters", lambda symbol: None)
    monkeypatch.setattr(
        worker,
        "get_balances",
        lambda: {"USDT": {"free": 100.0, "locked": 0.0}},
    )
    monkeypatch.setattr(worker, "get_price", lambda symbol: 100.0)
    monkeypatch.setattr(worker, "get_price_exact", lambda symbol: Decimal("100"))
    monkeypatch.setattr(
        worker,
        "list_open_orders",
        lambda symbol: (_ for _ in ()).throw(requests.ConnectionError("offline")),
    )
    monkeypatch.setattr(
        worker,
        "place_limit_order",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("BUY reached exchange mutation without order state")
        ),
    )

    assert place_buys(worker,
        "SOLUSDT",
        [90.0],
        10.0,
        target_buy_per_symbol=1,
        enforce_limit=True,
    ) == []


def test_worker_symbol_lock_respects_bot_run_dir(tmp_path, monkeypatch):
    worker = load_worker()
    monkeypatch.setenv("BOT_RUN_DIR", str(tmp_path))
    lock = worker.SymbolLock("SOLUSDT")

    assert lock.acquire() is True
    assert Path(lock.path).parent == tmp_path
    lock.release()
    assert not Path(lock.path).exists()


def test_worker_signal_stops_buy_loop_before_exchange_post(monkeypatch):
    worker = load_worker()
    worker.RUN = False
    worker.symbol_filters["SOLUSDT"] = {
        "tickSize": 0.01,
        "stepSize": 0.001,
        "minQty": 0.001,
        "minNotional": 5.0,
    }
    monkeypatch.setattr(worker, "pull_filters", lambda symbol: None)
    monkeypatch.setattr(
        worker,
        "get_balances",
        lambda: {"USDT": {"free": 100.0, "locked": 0.0}},
    )
    monkeypatch.setattr(worker, "get_price", lambda symbol: 100.0)
    monkeypatch.setattr(worker, "get_price_exact", lambda symbol: Decimal("100"))
    monkeypatch.setattr(
        worker,
        "place_limit_order",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("exchange POST reached after stop signal")
        ),
    )

    assert place_buys(worker,
        "SOLUSDT",
        [90.0, 80.0],
        10.0,
        target_buy_per_symbol=1,
        enforce_limit=True,
    ) == []


def test_supervisor_auth_backoff_is_bounded_and_keeps_heartbeat_fresh(
    tmp_path, monkeypatch
):
    clock = [0.0]
    sleeps = []
    published = []
    messages = []
    attempts = [0]

    def preflight(*_args):
        attempts[0] += 1
        if attempts[0] <= 2:
            raise ai_supervisor.TM.BinanceHttpError(
                "HTTP 401: {'code': -2015, "
                "'msg': 'Invalid API-key=secret-value'}"
            )

    def sleep(seconds):
        sleeps.append(seconds)
        clock[0] += seconds

    monkeypatch.setattr(ai_supervisor, "_preflight_live", preflight)
    monkeypatch.setattr(
        ai_supervisor,
        "_pre_running_recovery_gate",
        lambda *_args: {"checked": 0, "blocked": False},
    )
    monkeypatch.setenv(
        "BINANCE_AUTH_STATE_FILE", str(tmp_path / "auth.json")
    )
    monkeypatch.setenv("BINANCE_PUBLIC_IP_ENDPOINT", "")
    monkeypatch.setattr(ai_supervisor.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(ai_supervisor.time, "sleep", sleep)
    monkeypatch.setattr(
        ai_supervisor,
        "_publish_ai_runtime_status",
        lambda **updates: published.append(updates),
    )
    monkeypatch.setattr(ai_supervisor, "log", messages.append)
    args = SimpleNamespace(
        live=True,
        binance_auth_backoff_initial_sec=60,
        binance_auth_backoff_max_sec=120,
    )
    limits = SimpleNamespace(halt_file=tmp_path / "halt.json")

    ai_supervisor._preflight_with_auth_backoff(
        args, ["SOLUSDT"], limits
    )

    assert attempts[0] == 3
    assert sleeps == [30, 30, 30, 30, 30, 30]
    backoff_rows = [
        row for row in published if row.get("state") == "AUTH_BACKOFF"
    ]
    assert backoff_rows
    assert all(row["risk"]["buy_blocked"] for row in backoff_rows)
    recovered = [
        row for row in published if row.get("state") == "STARTING"
    ][-1]
    assert recovered["auth_backoff"]["active"] is False
    assert published[-1]["recovery"]["blocked"] is False
    assert "secret-value" not in str(published)
    assert "secret-value" not in str(messages)
