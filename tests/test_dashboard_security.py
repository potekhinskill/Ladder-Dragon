import importlib.util
from pathlib import Path

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
