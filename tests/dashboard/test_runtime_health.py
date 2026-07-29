# Purpose: verify precise sanitized dashboard runtime diagnostics.

from fastapi.testclient import TestClient

from ladder_dragon.ai.ai_runtime_status import write_runtime_status
from ladder_dragon.dashboard.services.runtime_health import runtime_degraded_reason
from tests.support.module_loaders import load_dashboard


def test_runtime_degraded_reason_distinguishes_safe_states():
    assert runtime_degraded_reason(
        {}, follow_bot_paths=True, stale=False
    ) == "runtime:unavailable"
    assert runtime_degraded_reason(
        {"state": "RUNNING"}, follow_bot_paths=True, stale=False
    ) is None
    assert runtime_degraded_reason(
        {"state": "RECOVERY_BLOCKED"}, follow_bot_paths=True, stale=False
    ) == "runtime:recovery_blocked"
    assert runtime_degraded_reason(
        {"state": "RUNNING"}, follow_bot_paths=True, stale=True
    ) == "runtime:stale"


def test_ai_status_exposes_exact_fail_closed_runtime_state(
    tmp_path, monkeypatch
):
    status_file = tmp_path / "ai_status.json"
    write_runtime_status(
        status_file,
        {
            "state": "RECOVERY_BLOCKED",
            "ai": {
                "enabled": True,
                "mode": "SHADOW",
                "configured_mode": "SHADOW",
            },
        },
    )
    monkeypatch.setenv("AI_RUNTIME_STATUS_FILE", str(status_file))
    monkeypatch.setenv("DASHBOARD_FOLLOW_BOT_PATHS", "1")
    module = load_dashboard(monkeypatch)

    with TestClient(module.app) as client:
        response = client.get(
            "/api/ai/status",
            headers={"Authorization": "Bearer test-secret-token"},
        )

    payload = response.json()
    assert response.status_code == 200
    assert payload["state"] == "DEGRADED"
    assert payload["runtime"]["process_state"] == "RECOVERY_BLOCKED"
    assert payload["degraded_reasons"] == ["runtime:recovery_blocked"]
