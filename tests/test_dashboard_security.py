import importlib.util
import json
from pathlib import Path
import sqlite3

from fastapi.testclient import TestClient


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
