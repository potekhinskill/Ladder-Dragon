import importlib.util
import json
from pathlib import Path
import sqlite3
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from ai_runtime_status import write_runtime_status


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
    # macOS sandbox может запрещать чтение swap/boot_time(); для проверки
    # контракта health подставляем безопасные значения системного снимка.
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
    assert "Binance unavailable" in response.json()["error"]


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
        disabled = client.post(
            "/api/ai/control", headers=headers, json={"enabled": False}
        )
        enabled = client.post(
            "/api/ai/control", headers=headers, json={"enabled": True}
        )

    assert initial.status_code == 200
    assert initial.json()["enabled"] is True
    assert disabled.status_code == 200
    assert disabled.json()["mode"] == "DISABLED"
    assert enabled.status_code == 200
    assert enabled.json()["mode"] == "APPLY"


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
            "('SOLUSDT',1,'FLAT','UP',1,0.5,.8,0,'SHADOW','shadow_mode','UP',.01,.02,.03)"
        )
    usage.write_text(json.dumps({
        "timestamp": "2026-07-16T10:00:00+00:00",
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
    assert "rationale" not in response.text.lower()


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
