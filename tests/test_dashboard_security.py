import importlib.util
import json
from pathlib import Path
import sqlite3
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from ladder_dragon.ai.ai_runtime_status import write_runtime_status
from ladder_dragon.ai.ai_context import AdvisorDecisionStore
from ladder_dragon.execution.order_recovery import OrderJournal


def load_dashboard(monkeypatch):
    monkeypatch.setenv("DASHBOARD_AUTH_TOKEN", "test-secret-token")
    monkeypatch.setenv("DASHBOARD_ENABLE_LOGS", "0")
    path = Path("FastAPI/pi-dashboard/app.py").resolve()
    spec = importlib.util.spec_from_file_location("secure_dashboard", path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


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


def test_user_stream_health_is_sanitized_and_rest_authoritative(
    tmp_path, monkeypatch
):
    status = tmp_path / "ai_status.json"
    stream = tmp_path / "user_stream_SOLUSDT.json"
    stream.write_text(json.dumps({
        "state": "connected",
        "order_events": 3,
        "duplicates": 1,
        "reconnects": 2,
        "last_error": None,
        "last_event_at": 100.0,
        "last_order_event_at": 99.0,
    }), encoding="utf-8")
    monkeypatch.setenv("AI_RUNTIME_STATUS_FILE", str(status))
    module = load_dashboard(monkeypatch)

    payload = module._user_stream_snapshot({"symbols": ["SOLUSDT"]})

    assert payload["rest_authoritative"] is True
    assert payload["mode"] == "shadow_notification_only"
    row = payload["streams"][0]
    assert row["state"] == "connected"
    assert row["order_events"] == 3
    assert row["duplicates"] == 1
    assert row["reconnects"] == 2
    assert "api" not in json.dumps(payload).lower()


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


def test_trading_overview_prefers_current_open_order(monkeypatch):
    module = load_dashboard(monkeypatch)
    monkeypatch.setattr(module, "_load_ai_runtime_status", lambda: {
        "symbols": ["SOLUSDT"],
        "execution_mode": "LIVE",
        "risk": {},
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
    monkeypatch.setattr(module, "_average_entry_from_ledger", lambda symbol: 100.0)
    monkeypatch.setattr(module, "_order_journal_snapshot", lambda runtime: {
        "available": True,
        "cancelled": 1, "pending": 1,
        "latest": {"symbol": "SOLUSDT", "side": "SELL", "status": "UNKNOWN"},
    })

    snapshot = module.trading_overview_snapshot()

    assert snapshot["last_order"]["order_id"] == 123
    assert snapshot["last_order"]["status"] == "NEW"
    assert snapshot["orders"]["journal_available"] is True


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
    monkeypatch.setattr(module, "_average_entry_from_ledger", lambda symbol: 100.0)
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
        }


def test_dashboard_does_not_render_missing_journal_counts_as_zero():
    index = Path("FRONT/index.html").read_text(encoding="utf-8")

    assert "orders.journal_available===false" in index
    assert "`${orders.open??0} / — / — · ${tr('unavailable')}`" in index


def test_order_journal_pending_excludes_terminal_failures(tmp_path, monkeypatch):
    module = load_dashboard(monkeypatch)
    journal_path = tmp_path / "order_intents.sqlite3"
    journal = OrderJournal(journal_path, venue="mainnet")
    failed = journal.prepare(
        client_order_id="LDSLAD-failed",
        symbol="SOLUSDT",
        side="SELL",
        purpose="ladder",
        order_type="LIMIT",
        quantity="1",
        price="100",
    )
    journal.mark_failed(failed.client_order_id, "exchange confirmed order absent")
    journal.prepare(
        client_order_id="LDBLAD-pending",
        symbol="SOLUSDT",
        side="BUY",
        purpose="ladder",
        order_type="LIMIT",
        quantity="0.1",
        price="90",
    )

    snapshot = module._order_journal_snapshot({
        "paths": {"order_journal": str(journal_path)}
    })

    assert snapshot["counts"] == {"FAILED": 1, "PREPARED": 1}
    assert snapshot["cancelled"] == 0
    assert snapshot["pending"] == 1


def test_order_journal_prefers_sanitized_runtime_snapshot(monkeypatch):
    module = load_dashboard(monkeypatch)
    runtime = {
        "order_journal": {
            "available": True,
            "counts": {"CANCELED": 39, "FAILED": 2, "SUBMITTED": 1},
            "cancelled": 39,
            "pending": 1,
            "latest": {
                "symbol": "SOLUSDT",
                "side": "BUY",
                "status": "SUBMITTED",
                "order_id": 123,
                "executed_qty": "0",
                "quantity": "0.127",
                "partial_fill": False,
                "latency_ms": None,
                "commission_usdt": None,
                "updated_at_epoch": 1_784_466_426,
            },
        },
        "paths": {"order_journal": "/path/dashboard/must/not/open.sqlite3"},
    }

    snapshot = module._order_journal_snapshot(runtime)

    assert snapshot["source"] == "runtime"
    assert snapshot["cancelled"] == 39
    assert snapshot["pending"] == 1
    assert snapshot["latest"]["order_id"] == 123
    assert snapshot["latest"]["updated_at"]


def test_open_orders_exposes_read_only_order_fields_without_secrets(monkeypatch):
    monkeypatch.setenv("DASHBOARD_BINANCE_API_KEY", "read-only-key")
    monkeypatch.setenv("DASHBOARD_BINANCE_API_SECRET", "read-only-secret")
    module = load_dashboard(monkeypatch)
    monkeypatch.setattr(module, "_signed", lambda method, path, params=None: [
        {
            "orderId": 123,
            "clientOrderId": "LDBLAD-example",
            "symbol": "SOLUSDT",
            "side": "BUY",
            "type": "LIMIT",
            "timeInForce": "GTC",
            "price": "74.60",
            "stopPrice": "0.00",
            "origQty": "0.133",
            "executedQty": "0.033",
            "status": "NEW",
            "time": 1784319000000,
            "updateTime": 1784319001000,
        },
    ])
    with TestClient(module.app) as client:
        response = client.get(
            "/api/account/open-orders",
            headers={"Authorization": "Bearer test-secret-token"},
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["count"] == 1
    order = payload["orders"][0]
    assert order["symbol"] == "SOLUSDT"
    assert order["remaining_qty"] == pytest.approx(0.1)
    assert order["status"] == "NEW"
    assert "read-only-secret" not in response.text


def test_open_orders_uses_short_cache_and_never_posts(monkeypatch):
    monkeypatch.setenv("DASHBOARD_BINANCE_API_KEY", "read-only-key")
    monkeypatch.setenv("DASHBOARD_BINANCE_API_SECRET", "read-only-secret")
    module = load_dashboard(monkeypatch)
    readonly_signed = module._signed
    calls = {"signed": 0}

    def signed(method, path, params=None):
        calls["signed"] += 1
        assert method == "GET"
        assert path == "/api/v3/openOrders"
        return []

    monkeypatch.setattr(module, "_signed", signed)
    first = module.account_open_orders_snapshot()
    second = module.account_open_orders_snapshot()

    assert first == second
    assert calls == {"signed": 1}
    with pytest.raises(RuntimeError, match="read-only"):
        readonly_signed("POST", "/api/v3/order", {})


def test_open_orders_returns_marked_stale_snapshot_on_transient_error(monkeypatch):
    monkeypatch.setenv("DASHBOARD_BINANCE_API_KEY", "read-only-key")
    monkeypatch.setenv("DASHBOARD_BINANCE_API_SECRET", "read-only-secret")
    module = load_dashboard(monkeypatch)
    module._OPEN_ORDERS_CACHE.update({
        "ts": module.time.monotonic() - module._OPEN_ORDERS_CACHE_TTL_SEC - 1,
        "payload": {
            "ok": True, "stale": False, "updated_at": "2026-07-20 01:00:00",
            "venue": "https://api.binance.com", "count": 1,
            "orders": [{"order_id": 123, "status": "NEW"}],
        },
    })
    monkeypatch.setattr(
        module, "_signed",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("Binance unavailable")),
    )

    with TestClient(module.app) as client:
        response = client.get(
            "/api/account/open-orders",
            headers={"Authorization": "Bearer test-secret-token"},
        )

    assert response.status_code == 200
    assert response.headers["warning"].startswith("110 ")
    payload = response.json()
    assert payload["stale"] is True
    assert payload["warning"] == "OPEN_ORDERS_STALE"
    assert payload["count"] == 1
    assert "Binance unavailable" not in response.text


def test_ai_status_exposes_decision_rationale_and_realized_summary(tmp_path, monkeypatch):
    db = tmp_path / "ai.db"
    store = AdvisorDecisionStore(str(db))
    decision = store.record(
        symbol="SOLUSDT", price=100, deterministic_mode="FLAT",
        recommended_mode="UP", width_scale=1, cap_scale=1, confidence=.8,
        applied=True, rationale="Тестовый rationale", policy_status="APPLIED",
    )
    store.record_fill(decision, symbol="SOLUSDT", side="BUY", price=100, qty=1, ts=10)
    store.record_fill(decision, symbol="SOLUSDT", side="SELL", price=101, qty=1,
                      exit_reason="TP", ts=20)
    store.evaluate_execution(decision)
    monkeypatch.setenv("AI_DECISIONS_DB", str(db))
    module = load_dashboard(monkeypatch)
    with TestClient(module.app) as client:
        response = client.get(
            "/api/ai/status",
            headers={"Authorization": "Bearer test-secret-token"},
        )
    assert response.status_code == 200
    payload = response.json()
    assert payload["recent"][0]["decision_id"] == decision
    assert payload["recent"][0]["rationale"] == "Тестовый rationale"
    assert payload["knowledge_base"]["closed_decisions"] == 1
    assert payload["knowledge_base"]["realized_net_pnl_quote"] > 0


def test_ai_control_button_changes_only_advisory_mode(tmp_path, monkeypatch):
    status_file = tmp_path / "ai_status.json"
    control_file = tmp_path / "ai_control.json"
    write_runtime_status(status_file, {
        "state": "RUNNING",
        "ai": {
            "enabled": True,
            "mode": "APPLY",
            "configured_mode": "APPLY",
        },
    })
    monkeypatch.setenv("AI_RUNTIME_STATUS_FILE", str(status_file))
    monkeypatch.setenv("AI_CONTROL_FILE", str(control_file))
    module = load_dashboard(monkeypatch)
    headers = {"Authorization": "Bearer test-secret-token"}
    with TestClient(module.app) as client:
        initial = client.get("/api/ai/control", headers=headers)
        csrf = client.get("/api/security/csrf", headers=headers).json()["csrf_token"]
        write_headers = {
            **headers,
            "Origin": "http://testserver",
            "X-CSRF-Token": csrf,
        }
        disabled = client.post(
            "/api/ai/control", headers=write_headers, json={"enabled": False}
        )
        enabled = client.post(
            "/api/ai/control", headers=write_headers, json={"enabled": True}
        )

    assert initial.status_code == 200
    assert initial.json()["enabled"] is True
    assert disabled.status_code == 200
    assert disabled.json()["mode"] == "DISABLED"
    assert enabled.status_code == 200
    assert enabled.json()["mode"] == "APPLY"


def test_ai_control_rejects_missing_csrf_and_cross_origin(tmp_path, monkeypatch):
    monkeypatch.setenv("AI_CONTROL_FILE", str(tmp_path / "ai_control.json"))
    module = load_dashboard(monkeypatch)
    auth = {"Authorization": "Bearer test-secret-token"}
    with TestClient(module.app) as client:
        token = client.get("/api/security/csrf", headers=auth).json()["csrf_token"]
        missing = client.post("/api/ai/control", headers=auth, json={"enabled": False})
        cross_origin = client.post(
            "/api/ai/control",
            headers={**auth, "Origin": "https://evil.invalid", "X-CSRF-Token": token},
            json={"enabled": False},
        )
    assert missing.status_code == 403
    assert cross_origin.status_code == 403


def test_log_api_is_disabled_by_default(monkeypatch):
    module = load_dashboard(monkeypatch)
    with TestClient(module.app) as client:
        response = client.get(
            "/api/bot/logs",
            headers={"Authorization": "Bearer test-secret-token"},
        )
    assert response.status_code == 404


def test_proxy_auth_requires_shared_secret(monkeypatch):
    monkeypatch.setenv("DASHBOARD_AUTH_TOKEN", "")
    monkeypatch.setenv("DASHBOARD_TRUST_PROXY_AUTH", "1")
    monkeypatch.setenv("DASHBOARD_PROXY_AUTH_SECRET", "a" * 64)
    path = Path("FastAPI/pi-dashboard/app.py").resolve()
    spec = importlib.util.spec_from_file_location("proxy_dashboard", path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)

    with TestClient(module.app) as client:
        forged = client.get(
            "/api/does-not-exist",
            headers={"X-Authenticated-User": "dashboard"},
        )
        trusted = client.get(
            "/api/does-not-exist",
            headers={
                "X-Authenticated-User": "dashboard",
                "X-Dashboard-Proxy-Secret": "a" * 64,
            },
        )

    assert forged.status_code == 401
    assert trusted.status_code == 404


def test_raw_log_routes_are_not_registered(monkeypatch):
    module = load_dashboard(monkeypatch)
    paths = {route.path for route in module.app.routes}
    assert "/api/bot/logs" not in paths
    assert "/api/bot/logs/stream" not in paths


def test_dashboard_cannot_scrape_bot_process_secrets(monkeypatch):
    module = load_dashboard(monkeypatch)
    assert not hasattr(module, "_read_environ_of_pid")
    assert not hasattr(module, "_load_api_keys_from_systemd")


def test_dashboard_rate_limit_is_enforced(monkeypatch):
    monkeypatch.setenv("DASHBOARD_RATE_LIMIT_PER_MIN", "2")
    module = load_dashboard(monkeypatch)
    headers = {"Authorization": "Bearer test-secret-token"}
    with TestClient(module.app) as client:
        assert client.get("/api/bot/logs", headers=headers).status_code == 404
        assert client.get("/api/bot/logs", headers=headers).status_code == 404
        assert client.get("/api/bot/logs", headers=headers).status_code == 429


def test_ai_status_is_authenticated_and_contains_no_secrets(tmp_path, monkeypatch):
    db = tmp_path / "ai.db"
    usage = tmp_path / "usage.ndjson"
    now = datetime.now(timezone.utc)
    with sqlite3.connect(db) as connection:
        connection.execute(
            """
            CREATE TABLE ai_decisions(
                symbol TEXT,created_at INTEGER,deterministic_mode TEXT,
                recommended_mode TEXT,width_scale REAL,cap_scale REAL,
                confidence REAL,applied INTEGER,policy_status TEXT,
                policy_reasons TEXT,benchmark_mode TEXT,return_15m REAL,
                return_1h REAL,return_4h REAL
            )
            """
        )
        connection.execute(
            "INSERT INTO ai_decisions VALUES"
            "('SOLUSDT',?,'FLAT','UP',1,0.5,.8,0,'SHADOW','shadow_mode','UP',.01,.02,.03)",
            (int(now.timestamp()),),
        )
    usage.write_text(json.dumps({
        "timestamp": now.isoformat(),
        "total_tokens": 100,
        "estimated_cost_usd": "0.001",
        "outcome": "applied",
    }) + "\n")
    monkeypatch.setenv("AI_DECISIONS_DB", str(db))
    monkeypatch.setenv("AI_USAGE_LOG", str(usage))
    monkeypatch.setenv("AI_MODE", "SHADOW")
    module = load_dashboard(monkeypatch)
    headers = {"Authorization": "Bearer test-secret-token"}

    with TestClient(module.app) as client:
        response = client.get("/api/ai/status", headers=headers)

    assert response.status_code == 200
    payload = response.json()
    assert payload["state"] == "SHADOW"
    assert payload["recent"][0]["recommended_mode"] == "UP"
    assert "api_key" not in response.text.lower()
    assert payload["recent"][0]["rationale"] == ""
    assert "deepseek_api_key" not in response.text.lower()


def test_dashboard_follows_active_bot_venue_and_ai_paths(tmp_path, monkeypatch):
    stats_db = tmp_path / "testnet_stats.db"
    decisions_db = tmp_path / "testnet_ai.db"
    usage_log = tmp_path / "ai_usage.ndjson"
    status_file = tmp_path / "ai_status.json"
    with sqlite3.connect(decisions_db) as connection:
        connection.execute(
            """
            CREATE TABLE ai_decisions(
                symbol TEXT,created_at INTEGER,deterministic_mode TEXT,
                recommended_mode TEXT,width_scale REAL,cap_scale REAL,
                confidence REAL,applied INTEGER,policy_status TEXT,
                policy_reasons TEXT,benchmark_mode TEXT,return_15m REAL,
                return_1h REAL,return_4h REAL
            )
            """
        )
        connection.execute(
            "INSERT INTO ai_decisions VALUES"
            "('ETHUSDT',2,'FLAT','DOWN',1.1,0.6,.9,1,'APPLIED','','DOWN',-.01,-.02,-.03)"
        )
    write_runtime_status(status_file, {
        "state": "RUNNING",
        "venue": "testnet",
        "execution_mode": "LIVE",
        "product": {"name": "Ladder Dragon", "version": "2.7.0"},
        "ai": {
            "mode": "APPLY",
            "provider": "deepseek",
            "model": "deepseek-v4-flash",
            "budgets": {
                "max_requests_per_day": 10,
                "max_tokens_per_day": 1000,
                "max_cost_usd_per_day": "0.05",
            },
        },
        "paths": {
            "stats_db": str(stats_db),
            "ai_decisions_db": str(decisions_db),
            "ai_usage_log": str(usage_log),
        },
    })
    monkeypatch.setenv("AI_RUNTIME_STATUS_FILE", str(status_file))
    monkeypatch.setenv("DASHBOARD_FOLLOW_BOT_PATHS", "1")
    module = load_dashboard(monkeypatch)
    headers = {"Authorization": "Bearer test-secret-token"}

    with TestClient(module.app) as client:
        response = client.get("/api/ai/status", headers=headers)

    payload = response.json()
    assert response.status_code == 200
    assert payload["mode"] == "APPLY"
    assert payload["state"] == "ACTIVE"
    assert payload["runtime"]["connected"] is True
    assert payload["runtime"]["venue"] == "testnet"
    assert payload["runtime"]["execution_mode"] == "LIVE"
    assert payload["runtime"]["provider"] == "deepseek"
    assert payload["runtime"]["budgets"] == {
        "max_requests_per_day": 10,
        "max_tokens_per_day": 1000,
        "max_cost_usd_per_day": "0.05",
    }
    assert payload["recent"][0]["symbol"] == "ETHUSDT"
    assert payload["data_sources"]["decisions_db"] == str(decisions_db)
    assert module.get_db_path() == str(stats_db)


def test_old_daily_ai_errors_do_not_keep_dashboard_degraded(tmp_path, monkeypatch):
    now = datetime.now(timezone.utc)
    usage_log = tmp_path / "ai_usage.ndjson"
    old_timestamp = (now - timedelta(hours=1)).isoformat()
    usage_log.write_text(
        "".join(
            json.dumps(
                {
                    "timestamp": old_timestamp,
                    "total_tokens": 10,
                    "estimated_cost_usd": "0.001",
                    "outcome": "error",
                }
            )
            + "\n"
            for _ in range(3)
        ),
        encoding="utf-8",
    )
    status_file = tmp_path / "ai_status.json"
    write_runtime_status(
        status_file,
        {"state": "RUNNING", "ai": {"mode": "SHADOW", "enabled": True}},
    )
    monkeypatch.setenv("AI_USAGE_LOG", str(usage_log))
    monkeypatch.setenv("AI_RUNTIME_STATUS_FILE", str(status_file))
    monkeypatch.setenv("AI_ERROR_DEGRADED_WINDOW_SEC", "900")
    module = load_dashboard(monkeypatch)

    with TestClient(module.app) as client:
        response = client.get(
            "/api/ai/status",
            headers={"Authorization": "Bearer test-secret-token"},
        )

    payload = response.json()
    assert response.status_code == 200
    assert payload["state"] == "SHADOW"
    assert payload["usage_today"]["errors"] == 3
    assert payload["usage_today"]["recent_errors"] == 0
    assert payload["degraded_reasons"] == []


def test_github_update_check_is_cached_and_compares_commits(monkeypatch):
    monkeypatch.setenv("DASHBOARD_GITHUB_REPOSITORY", "owner/repo")
    module = load_dashboard(monkeypatch)
    local_commit = "a" * 40
    remote_commit = "b" * 40
    monkeypatch.setattr(module, "_git_head_commit", lambda: local_commit)

    class Response:
        status_code = 200

        def json(self):
            return {
                "sha": remote_commit,
                "html_url": "https://github.com/owner/repo/commit/" + remote_commit,
            }

    class Session:
        def __init__(self):
            self.calls = 0

        def get(self, *args, **kwargs):
            self.calls += 1
            return Response()

    session = Session()
    monkeypatch.setattr(module, "SESSION", session)
    with TestClient(module.app) as client:
        headers = {"Authorization": "Bearer test-secret-token"}
        first = client.get("/api/update/check", headers=headers)
        second = client.get("/api/update/check", headers=headers)

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()["update_available"] is True
    assert first.json()["current_commit"] == local_commit
    assert first.json()["remote_commit"] == remote_commit
    assert first.json()["remote_url"] == "https://github.com/owner/repo/commit/" + remote_commit
    assert session.calls == 1
