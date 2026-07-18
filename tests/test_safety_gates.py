import importlib.util
from pathlib import Path
import subprocess
import sys
import time
import sqlite3
from types import SimpleNamespace

import pytest
from bin import ai_supervisor


def load_worker():
    path = Path("bin/autosize_universal.py").resolve()
    spec = importlib.util.spec_from_file_location("ladder_worker", path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


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
            "SELECT qty FROM inventory WHERE symbol='SOLUSDT'"
        ).fetchone()[0]
    assert abs(float(qty) - 3.778) < 1e-9


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
