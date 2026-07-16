import importlib.util
import json
from pathlib import Path
import sqlite3

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
