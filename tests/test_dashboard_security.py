import json
import os
from pathlib import Path
import sqlite3
import time
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from ladder_dragon.ai.ai_runtime_status import write_runtime_status
from ladder_dragon.ai.context.runtime import AdvisorDecisionStore
from ladder_dragon.execution.order_recovery import OrderJournal
from ladder_dragon.persistence.migrations import migrate
from tests.support.module_loaders import load_dashboard


def dashboard_source() -> str:
    return (
        Path("FRONT/index.html").read_text(encoding="utf-8")
        + "\n"
        + Path("FRONT/dashboard.js").read_text(encoding="utf-8")
    )


def test_api_is_closed_without_authentication(monkeypatch):
    module = load_dashboard(monkeypatch)
    with TestClient(module.app) as client:
        response = client.get("/api/health")
    assert response.status_code == 401


def test_health_exposes_product_version_and_changelog(monkeypatch):
    module = load_dashboard(monkeypatch)
    # The macOS sandbox may block swap/boot_time(); use safe system-snapshot
    # values to verify the health contract.
    swap_snapshot = type("SwapSnapshot", (), {"total": 0, "used": 0, "percent": 0})()
    monkeypatch.setattr(module.psutil, "swap_memory", lambda: swap_snapshot)
    monkeypatch.setattr(module.psutil, "boot_time", lambda: 0)
    with TestClient(module.app) as client:
        response = client.get(
            "/api/health",
            headers={"Authorization": "Bearer test-secret-token"},
        )
    assert response.status_code == 200
    payload = response.json()
    assert payload["product"]["name"] == "Ladder Dragon"
    assert payload["product"]["version"]
    assert payload["changelog_url"] == "/CHANGELOG.md"


def test_dashboard_read_only_database_waits_for_short_wal_contention(
    tmp_path,
    monkeypatch,
):
    database = tmp_path / "stats.db"
    sqlite3.connect(database).close()
    monkeypatch.setenv("BOT_STATS_DB", str(database))
    module = load_dashboard(monkeypatch)

    connection, resolved_path = module._open_db()
    try:
        busy_timeout_ms = connection.execute(
            "PRAGMA busy_timeout"
        ).fetchone()[0]
        query_only = connection.execute("PRAGMA query_only").fetchone()[0]
    finally:
        connection.close()

    assert resolved_path == str(database)
    assert busy_timeout_ms == 5000
    assert query_only == 1


def test_dashboard_read_only_open_never_creates_missing_stats_database(
    tmp_path,
    monkeypatch,
):
    database = tmp_path / "stats-not-created-yet.db"
    monkeypatch.setenv("BOT_STATS_DB", str(database))
    module = load_dashboard(monkeypatch)

    with TestClient(module.app, raise_server_exceptions=False) as client:
        response = client.get(
            "/api/trades/symbols",
            headers={"Authorization": "Bearer test-secret-token"},
        )

    assert response.status_code == 503
    assert response.json()["error"] == "DATABASE_TEMPORARILY_UNAVAILABLE"
    assert response.headers["Retry-After"] == "2"
    assert database.exists() is False


@pytest.mark.parametrize(
    "endpoint",
    (
        "/api/trades/symbols",
        "/api/trades/summary",
        "/api/trades/recent",
        "/api/trades/filled",
        "/api/orders/filled",
        "/api/fills",
    ),
)
def test_dashboard_sqlite_startup_race_is_retryable_not_500(
    tmp_path,
    monkeypatch,
    endpoint,
):
    database = tmp_path / "not-yet-migrated.db"
    sqlite3.connect(database).close()
    monkeypatch.setenv("BOT_STATS_DB", str(database))
    module = load_dashboard(monkeypatch)

    with TestClient(module.app, raise_server_exceptions=False) as client:
        response = client.get(
            endpoint,
            headers={"Authorization": "Bearer test-secret-token"},
        )

    assert response.status_code == 503
    assert response.headers["Retry-After"] == "2"
    assert response.json() == {
        "ok": False,
        "error": "DATABASE_TEMPORARILY_UNAVAILABLE",
        "retryable": True,
    }
    assert "sqlite" not in response.text.lower()


def test_user_stream_health_is_sanitized_and_rest_authoritative(
    tmp_path, monkeypatch
):
    status = tmp_path / "ai_status.json"
    stream = tmp_path / "user_stream_SOLUSDT.json"
    stream.write_text(json.dumps({
        "state": "connected",
        "order_events": 3,
        "duplicates": 1,
        "out_of_order_events": 4,
        "bad_frames": 2,
        "reconnects": 2,
        "connection_attempts": 5,
        "sessions": 4,
        "disconnects": 2,
        "first_observed_at": time.time() - 7200,
        "connected_at": time.time() - 900,
        "last_error": None,
        "last_event_at": 100.0,
        "last_order_event_at": 99.0,
    }), encoding="utf-8")
    monkeypatch.setenv("AI_RUNTIME_STATUS_FILE", str(status))
    monkeypatch.setenv("USER_STREAM_STATUS_DIR", str(tmp_path))
    module = load_dashboard(monkeypatch)

    payload = module._user_stream_snapshot({"symbols": ["SOLUSDT"]})

    assert payload["rest_authoritative"] is True
    assert payload["mode"] == "shadow_notification_only"
    row = payload["streams"][0]
    assert row["state"] == "connected"
    assert row["stale"] is False
    assert row["order_events"] == 3
    assert row["duplicates"] == 1
    assert row["out_of_order_events"] == 4
    assert row["bad_frames"] == 2
    assert row["reconnects"] == 2
    assert row["connection_attempts"] == 5
    assert row["sessions"] == 4
    assert row["disconnects"] == 2
    assert row["soak_hours"] >= 2
    assert row["cumulative_observation_hours"] >= 2
    assert 0.24 <= row["current_session_hours"] <= 0.26
    assert "api" not in json.dumps(payload).lower()


def test_user_stream_snapshot_becomes_stale_after_threshold(tmp_path, monkeypatch):
    status = tmp_path / "ai_status.json"
    stream = tmp_path / "user_stream_SOLUSDT.json"
    stream.write_text(json.dumps({"state": "connected"}), encoding="utf-8")
    os.utime(stream, (100.0, 100.0))
    monkeypatch.setenv("AI_RUNTIME_STATUS_FILE", str(status))
    monkeypatch.setenv("USER_STREAM_STATUS_DIR", str(tmp_path))
    monkeypatch.setenv("DASHBOARD_USER_STREAM_STALE_SEC", "30")
    module = load_dashboard(monkeypatch)

    row = module._user_stream_snapshot({"symbols": ["SOLUSDT"]})["streams"][0]

    assert row["state"] == "stale"
    assert row["reported_state"] == "connected"
    assert row["stale"] is True


def test_user_stream_transport_activity_overrides_old_snapshot_mtime(
    tmp_path, monkeypatch
):
    status = tmp_path / "ai_status.json"
    stream = tmp_path / "user_stream_SOLUSDT.json"
    transport_activity = time.time()
    stream.write_text(json.dumps({
        "state": "connected",
        "last_transport_activity_at": transport_activity,
    }), encoding="utf-8")
    os.utime(stream, (100.0, 100.0))
    monkeypatch.setenv("AI_RUNTIME_STATUS_FILE", str(status))
    monkeypatch.setenv("USER_STREAM_STATUS_DIR", str(tmp_path))
    monkeypatch.setenv("DASHBOARD_USER_STREAM_STALE_SEC", "30")
    module = load_dashboard(monkeypatch)

    row = module._user_stream_snapshot({"symbols": ["SOLUSDT"]})["streams"][0]

    assert row["state"] == "connected"
    assert row["stale"] is False
    assert row["last_transport_activity_at"] == transport_activity


def test_trade_api_reads_authoritative_exact_accounting_values(tmp_path, monkeypatch):
    database = tmp_path / "stats.db"
    migrate(str(database))
    now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
    with sqlite3.connect(database) as connection:
        connection.execute(
            "INSERT INTO trades(symbol,side,ts,trade_id,"
            "price_text,gross_qty,net_qty,commission_asset,"
            "commission_amount,commission_quote,commission_value_status) "
            "VALUES('SOLUSDT','BUY',?,1,'75.125','0.125','0.125',"
            "'USDT','0.01','0.01','exact')",
            (now_ms,),
        )
    monkeypatch.setenv("BOT_STATS_DB", str(database))
    module = load_dashboard(monkeypatch)

    with TestClient(module.app) as client:
        response = client.get(
            "/api/trades/recent?limit=1",
            headers={"Authorization": "Bearer test-secret-token"},
        )

    assert response.status_code == 200
    row = response.json()["rows"][0]
    assert row["price"] == 75.125
    assert row["qty"] == 0.125
    assert row["fee_quote"] == 0.01


def test_throttling_uses_fresh_sanitized_watchdog_probe(tmp_path, monkeypatch):
    status = tmp_path / "host-health.json"
    status.write_text(
        json.dumps({
            "schema_version": 1,
            "updated_at_epoch": 1000,
            "throttled_raw": "throttled=0x0",
            "temperature_c": 54.0,
        }),
        encoding="utf-8",
    )
    monkeypatch.setenv("DASHBOARD_HOST_HEALTH_STATUS_FILE", str(status))
    module = load_dashboard(monkeypatch)
    monkeypatch.setattr(module.time, "time", lambda: 1010)
    monkeypatch.setattr(module, "run_command", lambda *args, **kwargs: (1, ""))

    payload = module.parse_throttled()

    assert payload["supported"] is True
    assert payload["raw"] == "throttled=0x0"
    assert payload["source"] == "sanitized_watchdog_probe"
    assert payload["age_sec"] == 10.0


def test_dashboard_update_branch_cannot_be_redirected_by_environment(monkeypatch):
    monkeypatch.setenv("DASHBOARD_GITHUB_BRANCH", "untrusted/branch")
    module = load_dashboard(monkeypatch)
    assert module.GITHUB_BRANCH == "main"


def test_account_balances_exposes_read_only_assets_without_secrets(monkeypatch):
    monkeypatch.setenv("DASHBOARD_BINANCE_API_KEY", "read-only-key")
    monkeypatch.setenv("DASHBOARD_BINANCE_API_SECRET", "read-only-secret")
    module = load_dashboard(monkeypatch)
    monkeypatch.setattr(module, "_signed", lambda method, path, params=None: {
        "balances": [
            {"asset": "USDT", "free": "331.09", "locked": "0"},
            {"asset": "SOL", "free": "3.75", "locked": "0.01"},
            {"asset": "MONKY", "free": "74339", "locked": "0"},
        ]
    })
    monkeypatch.setattr(module, "_pub_get", lambda path, params=None: [
        {"symbol": "SOLUSDT", "price": "75.0"},
    ])
    with TestClient(module.app) as client:
        response = client.get(
            "/api/account/balances",
            headers={"Authorization": "Bearer test-secret-token"},
        )

    assert response.status_code == 200
    payload = response.json()
    assert abs(payload["total_value_usdt"] - (331.09 + round(3.76 * 75.0, 2))) < 1e-9
    assert payload["assets"][0]["asset"] == "USDT"
    sol = next(row for row in payload["assets"] if row["asset"] == "SOL")
    assert sol["free"] == 3.75
    assert sol["locked"] == 0.01
    assert sol["valuation_status"] == "priced"
    assert "MONKY" in payload["unvalued_assets"]
    assert "read-only-secret" not in response.text


def test_account_balances_uses_short_cache_and_never_posts(monkeypatch):
    monkeypatch.setenv("DASHBOARD_BINANCE_API_KEY", "read-only-key")
    monkeypatch.setenv("DASHBOARD_BINANCE_API_SECRET", "read-only-secret")
    module = load_dashboard(monkeypatch)
    readonly_signed = module._signed
    calls = {"signed": 0, "public": 0}

    def signed(method, path, params=None):
        calls["signed"] += 1
        assert method == "GET"
        return {"balances": [{"asset": "USDT", "free": "10", "locked": "2"}]}

    def public(path, params=None):
        calls["public"] += 1
        return []

    monkeypatch.setattr(module, "_signed", signed)
    monkeypatch.setattr(module, "_pub_get", public)

    first = module.account_balances_snapshot()
    second = module.account_balances_snapshot()

    assert first == second
    assert calls == {"signed": 1, "public": 1}
    with pytest.raises(RuntimeError, match="read-only"):
        readonly_signed("POST", "/api/v3/order", {})


def test_fifo_realized_pnl_deducts_buy_and_sell_fees(monkeypatch):
    module = load_dashboard(monkeypatch)
    rows = [
        {"symbol": "SOLUSDT", "side": "BUY", "price": 100.0, "qty": 1.0,
         "fee_quote": 1.0, "ts_s": 100},
        {"symbol": "SOLUSDT", "side": "SELL", "price": 110.0, "qty": 0.5,
         "fee_quote": 0.55, "ts_s": 300},
    ]

    result = module._fifo_realized_pnl(rows, cutoff_s=200, fee_pct=0.001)

    assert result["fees_usdt"] == 0.55
    assert result["realized_pnl_usdt"] == 3.95
    assert result["realized_pnl_status"] == "exact"


def test_fifo_realized_pnl_fails_closed_for_window_sell_with_incomplete_history(
    monkeypatch,
):
    module = load_dashboard(monkeypatch)
    rows = [
        {
            "symbol": "SOLUSDT",
            "side": "SELL",
            "price": 74.4,
            "qty": 0.124,
            "fee_quote": 0.006,
            "commission_status": "converted",
            "ts_s": 300,
        }
    ]

    result = module._fifo_realized_pnl(
        rows,
        cutoff_s=200,
        fee_pct=0.001,
    )

    assert result["realized_pnl_usdt"] is None
    assert result["realized_pnl_status"] == "incomplete_fifo_history"
    assert result["realized_pnl_excluded_symbols"] == ["SOLUSDT"]


def test_trade_summary_separates_net_earnings_from_portfolio_change(monkeypatch):
    module = load_dashboard(monkeypatch)

    class Connection:
        def close(self):
            return None

    monkeypatch.setattr(module, "_open_db", lambda: (Connection(), "test.db"))
    monkeypatch.setattr(module, "_load_trades", lambda con, syms: [])
    monkeypatch.setattr(module, "_fifo_realized_pnl", lambda rows, cutoff, fee: {
        "total_trades": 2,
        "buy_volume_usdt": 10.0,
        "sell_volume_usdt": 11.0,
        "fees_usdt": 0.02,
        "cashflow_pnl_usdt": 0.98,
        "realized_pnl_usdt": -12.26,
    })
    monkeypatch.setattr(module, "equity_pnl_usdt", lambda cutoff, rows, fee, syms: {
        "equity_pnl_usdt": 6.02,
        "equity_now_usdt": 794.66,
        "equity_then_usdt": 788.64,
        "equity_pct": 0.76,
        "method": "balances+klines",
        "equity_assets": ["SOL", "USDT"],
    })

    payload = json.loads(module.trades_summary().body)

    assert payload["net_pnl_usdt"] == -12.26
    assert payload["realized_pnl_usdt"] == -12.26
    assert payload["realized_pnl_method"] == "fifo-net-fees"
    assert payload["cashflow_pnl_usdt"] == 0.98
    assert payload["portfolio_change_usdt"] == 6.02
    assert payload["equity_pnl_usdt"] == 6.02


def test_account_balances_returns_service_unavailable_on_binance_error(monkeypatch):
    monkeypatch.setenv("DASHBOARD_BINANCE_API_KEY", "read-only-key")
    monkeypatch.setenv("DASHBOARD_BINANCE_API_SECRET", "read-only-secret")
    module = load_dashboard(monkeypatch)
    monkeypatch.setattr(module, "_signed", lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("Binance unavailable")))

    with TestClient(module.app) as client:
        response = client.get(
            "/api/account/balances",
            headers={"Authorization": "Bearer test-secret-token"},
        )

    assert response.status_code == 503
    assert response.json()["ok"] is False
    assert response.json()["error"] == "ACCOUNT_BALANCE_FAILED"
    assert "Binance unavailable" not in response.text


def test_account_balances_returns_marked_stale_snapshot_on_transient_error(monkeypatch):
    monkeypatch.setenv("DASHBOARD_BINANCE_API_KEY", "read-only-key")
    monkeypatch.setenv("DASHBOARD_BINANCE_API_SECRET", "read-only-secret")
    module = load_dashboard(monkeypatch)
    module._BALANCE_CACHE.update({
        "ts": module.time.monotonic() - module._BALANCE_CACHE_TTL_SEC - 1,
        "payload": {
            "ok": True, "stale": False, "updated_at": "2026-07-20 01:00:00",
            "assets": [], "total_value_usdt": 10.0, "unvalued_assets": [],
        },
    })
    monkeypatch.setattr(
        module, "_signed",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("Binance unavailable")),
    )

    with TestClient(module.app) as client:
        response = client.get(
            "/api/account/balances",
            headers={"Authorization": "Bearer test-secret-token"},
        )

    assert response.status_code == 200
    assert response.headers["warning"].startswith("110 ")
    payload = response.json()
    assert payload["stale"] is True
    assert payload["warning"] == "ACCOUNT_BALANCE_STALE"
    assert payload["stale_age_sec"] > module._BALANCE_CACHE_TTL_SEC
    assert "Binance unavailable" not in response.text


def test_stopped_bot_uses_only_configured_symbols(tmp_path, monkeypatch):
    service_env = tmp_path / ".env.service"
    service_env.write_text(
        "BOT_SERVICE_VENUE=mainnet\n"
        "BOT_SERVICE_EXECUTION=live\n"
        "BOT_SERVICE_SYMBOLS=SOLUSDT\n"
        "BOT_SERVICE_EXTRA_ARGS=--cap-floor-usdt 10 --cap-ceil-usdt 10\n"
        "BINANCE_API_SECRET=must-not-be-read\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("DASHBOARD_BOT_SERVICE_ENV", str(service_env))
    module = load_dashboard(monkeypatch)
    monkeypatch.setattr(module, "service_active", lambda name: "inactive")

    context = module._bot_execution_context({})

    assert context == {
        "service_state": "inactive",
        "execution_mode": "STOPPED",
        "configured_execution_mode": "LIVE",
        "venue": "mainnet",
        "symbols": ["SOLUSDT"],
        "cap_floor_usdt": 10.0,
        "cap_ceil_usdt": 10.0,
        "auto_oco_holdings": False,
    }
    assert "BINANCE_API_SECRET" not in module._bot_service_config()


def test_missing_runtime_never_converts_account_dust_to_symbols(monkeypatch):
    module = load_dashboard(monkeypatch)
    monkeypatch.setattr(module, "_bot_service_config", lambda: {})
    monkeypatch.setattr(module, "service_active", lambda name: "inactive")
    monkeypatch.setattr(module, "_load_ai_runtime_status", lambda: {})
    monkeypatch.setattr(module, "account_balances_snapshot", lambda: {
        "assets": [
            {"asset": "USDT", "free": 331.09, "total": 331.09},
            {"asset": "MONKY", "free": 74339.0, "total": 74339.0},
            {"asset": "PEPE", "free": 1000.0, "total": 1000.0},
        ]
    })
    monkeypatch.setattr(module, "account_open_orders_snapshot", lambda: {"count": 0, "orders": []})
    monkeypatch.setattr(module, "_order_journal_snapshot", lambda runtime: {"cancelled": 0, "pending": 0, "latest": None})

    snapshot = module.trading_overview_snapshot()

    assert snapshot["execution_mode"] == "STOPPED"
    assert snapshot["symbols"] == []
    assert snapshot["positions"] == []


def test_runtime_heartbeat_uses_status_timestamp(monkeypatch):
    module = load_dashboard(monkeypatch)
    now = datetime.now(timezone.utc)
    monkeypatch.setattr(module, "_load_ai_runtime_status", lambda: {
        "state": "RUNNING",
        "updated_at": (now - timedelta(seconds=25)).isoformat(),
    })

    heartbeat = module._runtime_heartbeat_snapshot()

    assert heartbeat["state"] == "RUNNING"
    assert 20 <= heartbeat["age_sec"] <= 30
    assert heartbeat["fresh"] is True


def test_runtime_heartbeat_labels_live_fail_closed_state(monkeypatch):
    module = load_dashboard(monkeypatch)
    now = datetime.now(timezone.utc)
    monkeypatch.setattr(module, "_load_ai_runtime_status", lambda: {
        "state": "IP_BLOCKED",
        "updated_at": (now - timedelta(seconds=5)).isoformat(),
    })

    heartbeat = module._runtime_heartbeat_snapshot()

    assert heartbeat["fresh"] is False
    assert heartbeat["alive_fail_closed"] is True
    assert "operator attention" in heartbeat["warning"]


def test_dashboard_distinguishes_intentional_stop(
    tmp_path, monkeypatch
):
    from ladder_dragon.execution.maintenance_state import set_maintenance

    maintenance = tmp_path / "maintenance.json"
    set_maintenance(
        maintenance,
        "Operator intentionally stopped trading",
        now_epoch=int(time.time()) - 5,
    )
    module = load_dashboard(monkeypatch)
    monkeypatch.setattr(module, "BOT_MAINTENANCE_FILE", maintenance)
    monkeypatch.setattr(module, "_load_ai_runtime_status", lambda: {})

    heartbeat = module._runtime_heartbeat_snapshot()

    assert heartbeat["state"] == "INTENTIONALLY_STOPPED"
    assert heartbeat["fresh"] is False
    assert heartbeat["alive_fail_closed"] is True
    assert heartbeat["warning"] == "Operator intentionally stopped trading"


def test_trading_overview_prefers_current_open_order(monkeypatch):
    module = load_dashboard(monkeypatch)
    monkeypatch.setattr(module, "_load_ai_runtime_status", lambda: {
        "symbols": ["SOLUSDT"],
        "execution_mode": "LIVE",
        "risk": {},
        "reanchor": {
            "mode": "SHADOW",
            "trigger_pct": "0.0005",
            "totals": {"shadow_candidates": 3, "apply_cancels": 0},
        },
        "prediction": {
            "mode": "SHADOW",
            "can_change_orders": False,
            "horizons_min": [1, 5, 15],
        },
    })
    monkeypatch.setattr(module, "_bot_service_config", lambda: {
        "symbols": ["SOLUSDT"], "execution_mode": "LIVE", "venue": "mainnet",
    })
    monkeypatch.setattr(module, "service_active", lambda name: "active")
    monkeypatch.setattr(module, "account_balances_snapshot", lambda: {
        "assets": [
            {"asset": "USDT", "free": 321.5, "total": 321.5},
            {"asset": "SOL", "free": 3.75, "total": 3.75, "price_usdt": 76.0},
        ]
    })
    monkeypatch.setattr(module, "account_open_orders_snapshot", lambda: {
        "count": 1,
        "orders": [{
            "symbol": "SOLUSDT", "side": "BUY", "status": "NEW",
            "order_id": 123, "orig_qty": 0.126, "executed_qty": 0.0,
            "remaining_qty": 0.126, "updated_at": 1_784_459_676,
            "type": "LIMIT", "price": 75.93, "stop_price": 0.0,
        }],
    })
    monkeypatch.setattr(
        module,
        "_verified_cost_basis_from_lots",
        lambda _symbol, _quantity: {
            "covered": True,
            "average_price": Decimal("100"),
            "covered_quantity": "3.75",
            "uncovered_quantity": "0",
            "status": "verified_full_inventory",
            "reason": "covered",
        },
    )
    monkeypatch.setattr(module, "_order_journal_snapshot", lambda runtime: {
        "available": True,
        "cancelled": 1, "pending": 1,
        "latest": {"symbol": "SOLUSDT", "side": "SELL", "status": "UNKNOWN"},
    })

    snapshot = module.trading_overview_snapshot()

    assert snapshot["last_order"]["order_id"] == 123
    assert snapshot["last_order"]["status"] == "NEW"
    assert snapshot["orders"]["journal_available"] is True
    assert snapshot["reanchor"]["mode"] == "SHADOW"
    assert snapshot["reanchor"]["totals"]["shadow_candidates"] == 3
    assert snapshot["prediction"]["mode"] == "SHADOW"
    assert snapshot["prediction"]["can_change_orders"] is False


def test_trading_overview_classifies_preexisting_inventory_as_legacy(monkeypatch):
    module = load_dashboard(monkeypatch)
    monkeypatch.setattr(module, "_load_ai_runtime_status", lambda: {
        "symbols": ["SOLUSDT"], "execution_mode": "LIVE", "risk": {},
    })
    monkeypatch.setattr(module, "_bot_service_config", lambda: {
        "symbols": ["SOLUSDT"],
        "execution_mode": "LIVE",
        "venue": "mainnet",
        "auto_oco_holdings": False,
    })
    monkeypatch.setattr(module, "service_active", lambda name: "active")
    monkeypatch.setattr(module, "account_balances_snapshot", lambda: {
        "assets": [
            {"asset": "USDT", "free": 331.0, "total": 331.0},
            {"asset": "SOL", "free": 3.75, "total": 3.75, "price_usdt": 76.0},
        ]
    })
    monkeypatch.setattr(
        module,
        "account_open_orders_snapshot",
        lambda: {"count": 0, "orders": []},
    )
    monkeypatch.setattr(
        module,
        "_verified_cost_basis_from_lots",
        lambda _symbol, _quantity: {
            "covered": False,
            "average_price": None,
            "covered_quantity": "0",
            "uncovered_quantity": "3.75",
            "status": "unverified_inventory_history",
            "reason": "account quantity exceeds sourced lots",
        },
    )
    monkeypatch.setattr(module, "_order_journal_snapshot", lambda runtime: {
        "available": True,
        "cancelled": 0,
        "pending": 0,
        "latest": {"symbol": "SOLUSDT", "side": "BUY", "status": "CANCELED"},
    })

    snapshot = module.trading_overview_snapshot()
    protection = snapshot["positions"][0]["protection"]

    assert protection["state"] == "legacy_unmanaged"
    assert protection["classification"] == "legacy_inventory"
    assert protection["managed_by_bot"] is False
    assert protection["gap_watchdog"] == "not_applicable_legacy_inventory"
    assert protection["cost_basis_status"] == "unverified_inventory_history"
    assert protection["cost_basis_action"] == "preview_only_import_required"


def test_dashboard_cost_basis_requires_sourced_lots_for_full_account_quantity(
    tmp_path,
    monkeypatch,
):
    database = tmp_path / "stats.db"
    with sqlite3.connect(database) as connection:
        connection.execute(
            "CREATE TABLE inventory_lots("
            "lot_id INTEGER PRIMARY KEY, symbol TEXT, qty TEXT, price TEXT,"
            "opened_at INTEGER, source_order_id TEXT, source_trade_id TEXT,"
            "status TEXT)"
        )
        connection.execute(
            "INSERT INTO inventory_lots VALUES("
            "1,'SOLUSDT','0.124','77.33',1,'501','601','OPEN')"
        )
    module = load_dashboard(monkeypatch)
    monkeypatch.setattr(module, "get_db_path", lambda: str(database))

    partial = module._verified_cost_basis_from_lots(
        "SOLUSDT",
        Decimal("3.8802313"),
    )
    covered = module._verified_cost_basis_from_lots(
        "SOLUSDT",
        Decimal("0.124"),
    )

    assert partial["covered"] is False
    assert partial["status"] == "partial_inventory_lots"
    assert partial["covered_quantity"] == "0.124"
    assert partial["uncovered_quantity"] == "3.7562313"
    assert covered["covered"] is True
    assert covered["average_price"] == Decimal("77.33")
    assert "501" not in json.dumps(partial)
    assert "601" not in json.dumps(partial)


def test_dashboard_cost_basis_fails_closed_without_lot_provenance(
    tmp_path,
    monkeypatch,
):
    database = tmp_path / "stats.db"
    with sqlite3.connect(database) as connection:
        connection.execute(
            "CREATE TABLE inventory_lots("
            "lot_id INTEGER PRIMARY KEY, symbol TEXT, qty TEXT, price TEXT,"
            "opened_at INTEGER, source_order_id TEXT, source_trade_id TEXT,"
            "status TEXT)"
        )
        connection.execute(
            "INSERT INTO inventory_lots VALUES("
            "1,'SOLUSDT','0.124','77.33',1,'','','OPEN')"
        )
    module = load_dashboard(monkeypatch)
    monkeypatch.setattr(module, "get_db_path", lambda: str(database))

    result = module._verified_cost_basis_from_lots(
        "SOLUSDT",
        Decimal("0.124"),
    )

    assert result["covered"] is False
    assert result["average_price"] is None
    assert result["reason"] == "inventory lots contain invalid provenance"


def test_mixed_position_scopes_oco_to_managed_lot_and_hides_unverified_pnl(
    monkeypatch,
):
    module = load_dashboard(monkeypatch)
    monkeypatch.setattr(module, "_load_ai_runtime_status", lambda: {
        "symbols": ["SOLUSDT"], "execution_mode": "LIVE", "risk": {},
    })
    monkeypatch.setattr(module, "_bot_service_config", lambda: {
        "symbols": ["SOLUSDT"], "execution_mode": "LIVE",
        "venue": "mainnet", "auto_oco_holdings": False,
    })
    monkeypatch.setattr(module, "service_active", lambda _name: "active")
    monkeypatch.setattr(module, "account_balances_snapshot", lambda: {
        "assets": [
            {"asset": "USDT", "free": 320, "total": 320},
            {
                "asset": "SOL",
                "free": 3.7562313,
                "total": 3.8802313,
                "price_usdt": 74.92,
            },
        ]
    })
    monkeypatch.setattr(module, "account_open_orders_snapshot", lambda: {
        "count": 2,
        "orders": [
            {
                "symbol": "SOLUSDT", "side": "SELL",
                "type": "LIMIT_MAKER", "remaining_qty": 0.124,
                "price": 77.91, "stop_price": 0,
            },
            {
                "symbol": "SOLUSDT", "side": "SELL",
                "type": "STOP_LOSS_LIMIT", "remaining_qty": 0.124,
                "price": 74.32, "stop_price": 74.4,
            },
        ],
    })
    monkeypatch.setattr(
        module,
        "_verified_cost_basis_from_lots",
        lambda _symbol, _quantity: {
            "covered": False,
            "average_price": None,
            "covered_quantity": "0.124",
            "uncovered_quantity": "3.7562313",
            "status": "partial_inventory_lots",
            "reason": "account quantity exceeds sourced lots",
        },
    )
    monkeypatch.setattr(module, "_order_journal_snapshot", lambda _runtime: {
        "available": True, "cancelled": 1, "pending": 0,
        "managed_buys": [{
            "symbol": "SOLUSDT", "quantity": "0.124",
            "protected_buys": 1,
        }],
        "latest": {"symbol": "SOLUSDT", "side": "BUY", "status": "SUBMITTED"},
    })

    position = module.trading_overview_snapshot()["positions"][0]
    protection = position["protection"]

    assert position["base_asset"] == "SOL"
    assert protection["state"] == "managed_confirmed_legacy_unmanaged"
    assert protection["managed_state"] == "confirmed"
    assert protection["legacy_state"] == "unmanaged_unprotected"
    assert protection["locked_quantity"] == 0.124
    assert protection["gap_watchdog"] == "managed_lot_armed_only"
    assert position["unrealized_pnl_usdt"] is None
    assert position["drawdown_pct"] is None


def test_trading_overview_exposes_stale_protected_lot_mismatch(monkeypatch):
    module = load_dashboard(monkeypatch)
    monkeypatch.setattr(module, "_load_ai_runtime_status", lambda: {
        "symbols": ["SOLUSDT"], "execution_mode": "LIVE", "risk": {},
    })
    monkeypatch.setattr(module, "_bot_service_config", lambda: {
        "symbols": ["SOLUSDT"], "execution_mode": "LIVE",
        "venue": "mainnet", "auto_oco_holdings": False,
    })
    monkeypatch.setattr(module, "service_active", lambda _name: "active")
    monkeypatch.setattr(module, "account_balances_snapshot", lambda: {
        "assets": [
            {"asset": "USDT", "free": 320.0, "total": 320.0},
            {"asset": "SOL", "free": 3.8802313, "total": 3.8802313,
             "price_usdt": 77.0},
        ]
    })
    monkeypatch.setattr(
        module,
        "account_open_orders_snapshot",
        lambda: {"count": 0, "orders": []},
    )
    monkeypatch.setattr(
        module,
        "_verified_cost_basis_from_lots",
        lambda _symbol, _quantity: {
            "covered": False,
            "average_price": None,
            "covered_quantity": "0.124",
            "uncovered_quantity": "3.7562313",
            "status": "partial_inventory_lots",
            "reason": "account quantity exceeds sourced lots",
        },
    )
    monkeypatch.setattr(module, "_order_journal_snapshot", lambda _runtime: {
        "available": True, "cancelled": 1, "pending": 0,
        "managed_buys": [{
            "symbol": "SOLUSDT", "quantity": "0.124", "protected_buys": 1,
        }],
        "latest": {"symbol": "SOLUSDT", "side": "BUY", "status": "SUBMITTED"},
    })

    snapshot = module.trading_overview_snapshot()
    position = snapshot["positions"][0]

    assert position["managed_quantity"] == 0.124
    assert position["legacy_quantity"] == 3.7562313
    assert position["average_entry_usdt"] is None
    assert position["unrealized_pnl_usdt"] is None
    assert position["drawdown_pct"] is None
    assert position["pnl_scope"] == "unavailable"
    assert position["protection"]["state"] == "journal_exchange_mismatch"
    assert position["protection"]["classification"] == (
        "managed_and_legacy_inventory"
    )
    assert snapshot["orders"]["journal_exchange_mismatches"] == [{
        "symbol": "SOLUSDT",
        "journal_state": "PROTECTED",
        "exchange_state": "MISSING_OR_INCOMPLETE_OCO",
        "managed_quantity": 0.124,
        "protected_quantity": 0,
    }]


def test_trading_overview_preserves_unavailable_order_journal(monkeypatch):
    module = load_dashboard(monkeypatch)
    monkeypatch.setattr(module, "_load_ai_runtime_status", lambda: {
        "symbols": [], "execution_mode": "LIVE", "risk": {},
    })
    monkeypatch.setattr(module, "_bot_service_config", lambda: {
        "symbols": [], "execution_mode": "LIVE", "venue": "mainnet",
    })
    monkeypatch.setattr(module, "service_active", lambda name: "active")
    monkeypatch.setattr(module, "account_balances_snapshot", lambda: {"assets": []})
    monkeypatch.setattr(module, "account_open_orders_snapshot", lambda: {
        "count": 1, "orders": [],
    })
    monkeypatch.setattr(module, "_order_journal_snapshot", lambda runtime: {
        "available": False, "reason": "OperationalError",
    })

    snapshot = module.trading_overview_snapshot()

    assert snapshot["orders"] == {
        "open": 1,
        "cancelled": None,
        "pending": None,
        "journal_available": False,
        "journal_reason": "OperationalError",
            "journal_source": None,
            "lifecycle": {},
            "journal_exchange_mismatches": [],
        }


def test_dashboard_does_not_render_missing_journal_counts_as_zero():
    index = dashboard_source()

    assert "orders.journal_available===false" in index
    assert "`${orders.open??0} / — / — · ${tr('unavailable')}`" in index


def test_dashboard_renders_reanchor_mode_activity_and_proposal():
    index = dashboard_source()

    assert 'id="trade-reanchor"' in index
    assert 'id="trade-reanchor-activity"' in index
    assert "reanchorTotals.shadow_candidates??0" in index
    assert "latestProposal.old_price" in index
