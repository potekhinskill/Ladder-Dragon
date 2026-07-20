import importlib.util
import fcntl
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
from bin import ai_supervisor


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


def load_worker():
    path = Path("bin/autosize_universal.py").resolve()
    spec = importlib.util.spec_from_file_location("ladder_worker", path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


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

    assert worker.maybe_place_sells_from_holdings(
        "SOLUSDT", [150.0], avg_entry_px=90.0,
    ) == 0


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

    assert worker.maybe_place_buys(
        "SOLUSDT",
        [90.0],
        10.0,
        target_buy_per_symbol=1,
        enforce_limit=False,
        use_remainder_in_last=True,
        live_mode=True,
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

    assert worker.maybe_place_buys(
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

    assert worker.maybe_place_buys(
        "SOLUSDT",
        [90.0, 80.0],
        10.0,
        target_buy_per_symbol=1,
        enforce_limit=True,
    ) == []


def test_supervisor_exponentially_backs_off_crashing_children(monkeypatch):
    monkeypatch.setenv("BOT_CHILD_RESTART_BASE_SEC", "2")
    monkeypatch.setenv("BOT_CHILD_RESTART_MAX_SEC", "10")
    monkeypatch.setenv("BOT_CHILD_STABLE_SEC", "30")
    ai_supervisor._CHILD_FAILURES.clear()
    ai_supervisor._CHILD_RESTART_AFTER.clear()

    assert ai_supervisor._schedule_child_restart("SOLUSDT", 1, 1, now=100) == 2
    assert ai_supervisor._schedule_child_restart("SOLUSDT", 1, 1, now=101) == 4
    assert ai_supervisor._schedule_child_restart("SOLUSDT", 0, 60, now=102) == 0
    assert ai_supervisor._CHILD_FAILURES["SOLUSDT"] == 0


def test_cleanup_layers_keep_fresh_off_ladder_order(monkeypatch):
    now_ms = int(time.time() * 1000)
    orders = [
        {
            "symbol": "SOLUSDT",
            "orderId": 42,
            "side": "BUY",
            "type": "LIMIT",
            "price": "99.00",
            "updateTime": now_ms - 60_000,
        }
    ]
    canceled = []
    monkeypatch.setenv("START_CLEANUP_OFFLADDER_GRACE_SEC", "900")
    monkeypatch.setenv("CLEANUP_OFFLADDER_GRACE_SEC", "900")
    monkeypatch.setattr(ai_supervisor, "list_open_orders", lambda symbol: orders)
    monkeypatch.setattr(
        ai_supervisor,
        "cancel_order",
        lambda symbol, order_id: canceled.append(order_id) or True,
    )

    result = ai_supervisor.startup_cleanup_orders(
        "SOLUSDT",
        now_price=100.0,
        ladder_prices=[98.0],
        tick_size=0.01,
        grace_sec=900,
    )

    assert result == {"reviewed": 1, "canceled": 0}
    assert canceled == []

    periodic = ai_supervisor.smart_cleanup_orders(
        "SOLUSDT",
        now_price=100.0,
        ladder_prices=[98.0],
        tick_size=0.01,
        near_ttl_sec=900,
        far_ttl_sec=7200,
    )
    assert periodic == {"reviewed": 1, "canceled": 0}
    assert canceled == []


def test_supervisor_deduplicates_ladder_with_exact_tick_formatting(monkeypatch):
    monkeypatch.setattr(ai_supervisor, "PRICE_ROUND_MODE", "nearest")

    prices = ai_supervisor._deduplicate_ladder_prices(
        ["75.124", "75.125", "75.126", "76.001"],
        76.0,
        "0.01",
    )

    assert prices == [75.12, 75.13, 76.0]

def test_startup_cleanup_reports_ttl_distance_and_observed_market(monkeypatch):
    now_ms = int(time.time() * 1000)
    order = {
        "symbol": "SOLUSDT",
        "orderId": 77,
        "side": "BUY",
        "type": "LIMIT",
        "price": "75.00",
        "executedQty": "0",
        "updateTime": now_ms - 901_000,
    }
    messages = []
    monkeypatch.setattr(ai_supervisor, "list_open_orders", lambda symbol: [order])
    monkeypatch.setattr(ai_supervisor, "cancel_order", lambda *args: True)
    monkeypatch.setattr(ai_supervisor, "log", messages.append)
    monkeypatch.setattr(
        ai_supervisor,
        "read_order_observation",
        lambda path, order_id: {
            "market_min_price": "75.40",
            "market_observation_count": 12,
        },
    )

    result = ai_supervisor.startup_cleanup_orders(
        "SOLUSDT",
        now_price=76.0,
        ladder_prices=[75.0],
        tick_size=0.01,
        grace_sec=900,
    )

    assert result == {"reviewed": 1, "canceled": 1}
    lifetime = next(message for message in messages if message.startswith("[ORDER-LIFETIME]"))
    assert '"cancel_reason":"age>900s"' in lifetime
    assert '"ttl_sec":900' in lifetime
    assert '"limit_below_market_pct":"1.3158"' in lifetime
    assert '"minimum_observed_market_price":"75.40"' in lifetime


def test_reconciliation_retries_recent_fill_and_allows_exchange_dust(tmp_path, monkeypatch):
    db_path = tmp_path / "stats.db"
    with sqlite3.connect(db_path) as con:
        con.execute("CREATE TABLE inventory(symbol TEXT PRIMARY KEY, qty REAL NOT NULL)")
        con.execute("INSERT INTO inventory(symbol, qty) VALUES('SOLUSDT', 0.000871)")

    monkeypatch.setenv("BOT_STATS_DB", str(db_path))
    monkeypatch.setenv("RISK_RECONCILE_STRICT", "1")
    monkeypatch.setenv("RISK_RECONCILE_SYNC_FILLS", "0")
    monkeypatch.setenv("RISK_RECONCILE_GRACE_SEC", "0.2")
    monkeypatch.setenv("RISK_RECONCILE_RETRY_SEC", "0.01")
    monkeypatch.setenv("RISK_RECONCILE_DUST_STEPS", "1")
    ai_supervisor._FILTERS_CACHE["SOLUSDT"] = {
        "tickSize": 0.01,
        "stepSize": 0.001,
        "minQty": 0.001,
        "minNotional": 5.0,
    }

    balances = [
        {"SOL": {"free": 0.129742, "locked": 0.0}, "USDT": {"free": 1000.0, "locked": 0.0}},
        {"SOL": {"free": 0.000742, "locked": 0.0}, "USDT": {"free": 1000.0, "locked": 0.0}},
    ]
    monkeypatch.setattr(ai_supervisor, "get_balances_full", lambda: balances.pop(0))
    monkeypatch.setattr(ai_supervisor, "get_last_price", lambda symbol: 77.0)
    monkeypatch.setattr(ai_supervisor.TM, "_signed_get", lambda *args, **kwargs: [])
    monkeypatch.setattr(
        ai_supervisor,
        "load_daily_trade_metrics",
        lambda *args, **kwargs: {
            "daily_turnover_usdt": 0,
            "daily_buy_usdt": 0,
            "daily_trade_count": 0,
            "consecutive_losses": 0,
        },
    )

    limits = ai_supervisor.RiskLimits.from_env()
    snapshot, orders, _ = ai_supervisor._build_risk_snapshot(["SOLUSDT"], limits)

    assert snapshot.exposure_usdt == ai_supervisor.money("0.057134")
    assert orders == []


def test_reconciliation_imports_new_binance_fill_before_risk_gate(tmp_path, monkeypatch):
    db_path = tmp_path / "stats.db"
    con = ai_supervisor.tools_stats.init_db(str(db_path))
    ai_supervisor.tools_stats.apply_trade(
        con, "SOLUSDT", "BUY", 70.0, 5.863,
        ts=1_700_000_000_000, trade_id=100,
        commission_asset="USDT", commission_amount=0,
        commission_quote=0, commission_value_status="exact",
    )
    con.close()

    monkeypatch.setenv("BOT_STATS_DB", str(db_path))
    monkeypatch.setenv("RISK_RECONCILE_STRICT", "1")
    monkeypatch.setenv("RISK_RECONCILE_SYNC_FILLS", "1")
    monkeypatch.setenv("RISK_RECONCILE_GRACE_SEC", "0")
    ai_supervisor._FILTERS_CACHE["SOLUSDT"] = {
        "tickSize": 0.01,
        "stepSize": 0.001,
        "minQty": 0.001,
        "minNotional": 5.0,
    }
    monkeypatch.setattr(
        ai_supervisor,
        "get_balances_full",
        lambda: {
            "SOL": {"free": 3.778, "locked": 0.0},
            "USDT": {"free": 1000.0, "locked": 0.0},
        },
    )
    monkeypatch.setattr(ai_supervisor, "get_last_price", lambda symbol: 75.0)

    def signed(path, params=None):
        if path == "/api/v3/myTrades":
            return [{
                "id": 101,
                "orderId": 17517152455,
                "isBuyer": False,
                "price": "75.0",
                "qty": "2.085",
                "commission": "0",
                "commissionAsset": "USDT",
                "time": 1_700_000_010_000,
            }]
        return []

    monkeypatch.setattr(ai_supervisor.TM, "_signed_get", signed)
    monkeypatch.setattr(
        ai_supervisor,
        "load_daily_trade_metrics",
        lambda *args, **kwargs: {
            "daily_turnover_usdt": 0,
            "daily_buy_usdt": 0,
            "daily_trade_count": 0,
            "consecutive_losses": 0,
        },
    )

    limits = ai_supervisor.RiskLimits.from_env()
    snapshot, orders, _ = ai_supervisor._build_risk_snapshot(["SOLUSDT"], limits)

    assert snapshot.exposure_usdt == ai_supervisor.money("283.35")
    assert orders == []
    with sqlite3.connect(db_path) as check:
        qty = check.execute(
            "SELECT qty_text FROM inventory WHERE symbol='SOLUSDT'"
        ).fetchone()[0]
    assert Decimal(qty) == Decimal("3.778")


def test_reconciliation_fill_import_failure_is_fail_closed(tmp_path, monkeypatch):
    db_path = tmp_path / "stats.db"
    con = ai_supervisor.tools_stats.init_db(str(db_path))
    con.close()
    monkeypatch.setenv("BOT_STATS_DB", str(db_path))

    def unavailable(*args, **kwargs):
        raise RuntimeError("Binance myTrades unavailable")

    monkeypatch.setattr(ai_supervisor.TM, "_signed_get", unavailable)

    with pytest.raises(RuntimeError, match="fresh fill import failed"):
        ai_supervisor._sync_recent_account_fills(["SOLUSDT"])


def test_unvalued_asset_requires_exact_ack_and_is_excluded_from_equity(tmp_path, monkeypatch):
    db_path = tmp_path / "stats.db"
    with sqlite3.connect(db_path) as con:
        con.execute("CREATE TABLE inventory(symbol TEXT PRIMARY KEY, qty REAL NOT NULL)")
        con.execute("INSERT INTO inventory(symbol, qty) VALUES('SOLUSDT', 0.129742)")

    monkeypatch.setenv("BOT_STATS_DB", str(db_path))
    monkeypatch.setenv("RISK_RECONCILE_STRICT", "1")
    monkeypatch.setenv("RISK_RECONCILE_SYNC_FILLS", "0")
    monkeypatch.setenv("RISK_RECONCILE_GRACE_SEC", "0")
    monkeypatch.setenv("RISK_UNVALUED_ASSETS", "MONKY")
    monkeypatch.setenv("RISK_UNVALUED_ASSETS_ACK", "MONKY")
    ai_supervisor._FILTERS_CACHE["SOLUSDT"] = {
        "tickSize": 0.01,
        "stepSize": 0.001,
        "minQty": 0.001,
        "minNotional": 5.0,
    }

    monkeypatch.setattr(
        ai_supervisor,
        "get_balances_full",
        lambda: {
            "SOL": {"free": 0.129742, "locked": 0.0},
            "USDT": {"free": 1000.0, "locked": 0.0},
            "MONKY": {"free": 74339.03, "locked": 0.0},
        },
    )

    def price(symbol):
        if symbol == "SOLUSDT":
            return 77.0
        raise RuntimeError("missing non-tradable pair")

    monkeypatch.setattr(ai_supervisor, "get_last_price", price)
    monkeypatch.setattr(
        ai_supervisor,
        "get_last_price_decimal",
        lambda symbol: Decimal(str(price(symbol))),
    )
    monkeypatch.setattr(ai_supervisor.TM, "_signed_get", lambda *args, **kwargs: [])
    monkeypatch.setattr(
        ai_supervisor,
        "load_daily_trade_metrics",
        lambda *args, **kwargs: {
            "daily_turnover_usdt": 0,
            "daily_buy_usdt": 0,
            "daily_trade_count": 0,
            "consecutive_losses": 0,
        },
    )

    limits = ai_supervisor.RiskLimits.from_env()
    snapshot, orders, _ = ai_supervisor._build_risk_snapshot(["SOLUSDT"], limits)

    assert snapshot.equity_usdt == ai_supervisor.money("1009.990134")
    assert snapshot.exposure_usdt == ai_supervisor.money("9.990134")
    assert orders == []


def test_unvalued_asset_ack_must_match_exactly(monkeypatch):
    monkeypatch.setenv("RISK_UNVALUED_ASSETS", "MONKY")
    monkeypatch.setenv("RISK_UNVALUED_ASSETS_ACK", "OTHER")
    try:
        ai_supervisor._configured_unvalued_assets()
    except RuntimeError as exc:
        assert "exact matching" in str(exc)
    else:
        raise AssertionError("unvalued asset allowlist accepted without exact ACK")


def test_remaining_order_budget_normalizes_legacy_float_telemetry(tmp_path):
    configured = ai_supervisor.RiskLimits.from_env()
    observed = ai_supervisor.RiskSnapshot(
        equity_usdt=794.25,
        exposure_usdt=463.15,
        free_usdt=331.09,
        daily_buy_usdt=0.0,
        correlated_exposure_usdt=463.15,
    )

    remaining = ai_supervisor._remaining_order_budget_decimal(
        configured,
        observed,
    )

    assert remaining == Decimal("31.09")
    assert isinstance(remaining, Decimal)


def test_risk_shock_detector_handles_mixed_valuation_price_types():
    first_reasons, first = ai_supervisor._configured_price_shocks_decimal(
        ["SOLUSDT"],
        {
            "SOLUSDT": 75.0,
            "ETHUSDT": Decimal("1900.00"),
        },
        {},
        "0.05",
    )
    second_reasons, second = ai_supervisor._configured_price_shocks_decimal(
        ["SOLUSDT"],
        {
            "SOLUSDT": Decimal("75.75"),
            "ETHUSDT": Decimal("1710.00"),
        },
        {
            **first,
            "ETHUSDT": Decimal("1900.00"),
        },
        Decimal("0.05"),
    )

    assert first_reasons == []
    assert second_reasons == []
    assert second == {"SOLUSDT": Decimal("75.75")}


def test_risk_shock_detector_reports_configured_symbol_only():
    reasons, normalized = ai_supervisor._configured_price_shocks_decimal(
        ["SOLUSDT"],
        {
            "SOLUSDT": Decimal("70"),
            "ETHUSDT": Decimal("1000"),
        },
        {
            "SOLUSDT": 75.0,
            "ETHUSDT": Decimal("1900"),
        },
        "0.05",
    )

    assert reasons == ["SOLUSDT moved 6.67%"]
    assert normalized == {"SOLUSDT": Decimal("70")}


def test_testnet_uses_separate_stats_and_order_journals(tmp_path, monkeypatch):
    main_stats = tmp_path / "mainnet.db"
    test_stats = tmp_path / "testnet.db"
    main_journal = tmp_path / "mainnet_orders.db"
    test_journal = tmp_path / "testnet_orders.db"
    test_run_dir = tmp_path / "testnet_run"
    main_run_dir = tmp_path / "mainnet_run"
    monkeypatch.setenv("BOT_STATS_DB", str(main_stats))
    monkeypatch.setenv("BOT_TESTNET_STATS_DB", str(test_stats))
    monkeypatch.setenv("BOT_ORDER_JOURNAL", str(main_journal))
    monkeypatch.setenv("BOT_TESTNET_ORDER_JOURNAL", str(test_journal))
    monkeypatch.setenv("BOT_RUN_DIR", str(main_run_dir))
    monkeypatch.setenv("CB_HALT_FILE", str(main_run_dir / "circuit_halt.json"))
    monkeypatch.setenv("CB_STATE_FILE", str(main_run_dir / "risk_state.json"))
    monkeypatch.setenv("CB_ALERTS_FILE", str(main_run_dir / "risk_alerts.ndjson"))
    monkeypatch.setenv("BOT_TESTNET_RUN_DIR", str(test_run_dir))

    ai_supervisor._configure_venue(SimpleNamespace(testnet=True, live=False))

    assert __import__("os").environ["BOT_STATS_DB"] == str(test_stats)
    assert __import__("os").environ["BOT_ORDER_JOURNAL"] == str(test_journal)
    assert __import__("os").environ["BOT_RUN_DIR"] == str(test_run_dir)
    assert __import__("os").environ["CB_HALT_FILE"] == str(test_run_dir / "circuit_halt.json")


def test_unknown_supervisor_flag_is_fatal():
    result = subprocess.run(
        [sys.executable, "-m", "bin.ai_supervisor", "--definitely-unknown"],
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 2
    assert "unrecognized arguments" in result.stderr


def test_dry_supervisor_refuses_missing_worker_file():
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "bin.ai_supervisor",
            "--base-script",
            "definitely-missing-worker.py",
        ],
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 2
    assert "--base-script does not exist" in result.stderr


def test_live_requires_explicit_confirmation(monkeypatch, tmp_path):
    env = dict(**__import__("os").environ)
    # An explicit empty value prevents python-dotenv from reloading the
    # production confirmation from .env inside the subprocess. Keep every
    # runtime path in the pytest sandbox as an additional fail-closed guard.
    env["BOT_LIVE_CONFIRMED"] = ""
    env["BOT_RUN_DIR"] = str(tmp_path)
    env["BOT_TESTNET_RUN_DIR"] = str(tmp_path / "testnet")
    env["AI_RUNTIME_STATUS_FILE"] = str(tmp_path / "ai_status.json")
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "bin.ai_supervisor",
            "--live",
            "--base-script",
            "bin/autosize_universal.py",
        ],
        text=True,
        capture_output=True,
        check=False,
        env=env,
    )
    assert result.returncode == 2
    assert "BOT_LIVE_CONFIRMED=YES" in result.stderr
    assert "Permission denied" not in result.stderr
