import json
import sys

from fastapi.testclient import TestClient
from ladder_dragon.deployment import status as deployment_status
from ladder_dragon.deployment.status import (
    deployment_message,
    read_deployment_status,
    write_deployment_status,
)
from tests.support.module_loaders import load_dashboard


def test_verified_ip_block_status_is_bounded_and_operator_safe(tmp_path):
    path = tmp_path / "deployment-status.json"
    status = write_deployment_status(
        commit="a" * 40,
        version="2.20.112",
        runtime_state="IP_BLOCKED",
        path=path,
    )

    loaded = read_deployment_status(path)
    message = deployment_message(status)

    assert loaded is not None
    assert loaded["status"] == "PASS"
    assert loaded["dashboard_backend_ready"] is True
    assert loaded["sqlite_ready"] is True
    assert message is not None
    assert "IP_BLOCKED" in message
    assert "public IP" in message
    assert "a" * 40 not in message
    assert path.stat().st_size < 4096
    assert path.stat().st_mode & 0o777 == 0o644


def test_invalid_or_unverified_status_is_not_exposed(tmp_path):
    path = tmp_path / "deployment-status.json"
    path.write_text(json.dumps({"commit": "bad"}), encoding="utf-8")

    assert read_deployment_status(path) is None
    assert deployment_message({"runtime_state": "RUNNING"}) is None

    path.write_text(json.dumps({
        "schema_version": 1,
        "status": "PASS",
        "commit": "b" * 40,
        "version": "2.20.112",
        "dashboard_backend_ready": True,
        "sqlite_ready": True,
        "runtime_state": "IP_BLOCKED\nsecret",
    }), encoding="utf-8")
    assert read_deployment_status(path) is None


def test_cli_sends_verified_english_notice(tmp_path, monkeypatch):
    path = tmp_path / "deployment-status.json"
    messages = []
    monkeypatch.setattr(
        deployment_status,
        "send_message",
        lambda text: messages.append(text) or True,
    )
    monkeypatch.setattr(sys, "argv", [
        "deployment-status",
        "--commit", "c" * 40,
        "--version", "2.20.112",
        "--runtime-state", "IP_BLOCKED",
        "--status-file", str(path),
    ])

    assert deployment_status.main() == 0
    assert len(messages) == 1
    assert "readiness checks passed" in messages[0]
    assert "New BUY orders and trading mutations are blocked" in messages[0]
    assert read_deployment_status(path) is not None


def test_ip_block_notice_uses_verified_local_deployment_status(monkeypatch):
    module = load_dashboard(monkeypatch)
    monkeypatch.setattr(module, "read_deployment_status", lambda: {
        "status": "PASS",
        "dashboard_backend_ready": True,
        "sqlite_ready": True,
        "runtime_state": "IP_BLOCKED",
    })
    swap_snapshot = type("SwapSnapshot", (), {"total": 0, "used": 0, "percent": 0})()
    monkeypatch.setattr(module.psutil, "swap_memory", lambda: swap_snapshot)
    monkeypatch.setattr(module.psutil, "boot_time", lambda: 0)

    with TestClient(module.app) as client:
        response = client.get(
            "/api/health",
            headers={"Authorization": "Bearer test-secret-token"},
        )

    assert response.status_code == 200
    assert response.json()["deployment"]["status"] == "PASS"
