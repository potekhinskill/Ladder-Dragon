"""Verify bounded and actionable dashboard transport diagnostics."""

from pathlib import Path


def test_refresh_names_each_failed_section_without_exposing_error_text():
    source = Path("FRONT/dashboard.js").read_text(encoding="utf-8")

    assert "FETCH_TIMEOUT_MS = 20000" in source
    assert "Promise.allSettled(sections.map(([,request])=>request))" in source
    for endpoint in (
        "/api/health",
        "/api/history",
        "/api/trades/summary",
        "/api/ai/status",
        "/api/ai/control",
        "/api/account/balances",
        "/api/trading/overview",
    ):
        assert f"['{endpoint}'," in source
    assert "failures.join(', ')" in source
    assert "section(s) unavailable" not in source
    assert "result.reason" not in source
