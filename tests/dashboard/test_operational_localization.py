"""Verify localized dashboard summaries for operational evidence."""

from pathlib import Path

from tests.test_dashboard_security import dashboard_source


def test_dashboard_localizes_dynamic_operational_summaries():
    source = dashboard_source()
    locales = Path("FRONT/locales.js").read_text(encoding="utf-8")

    assert "pending · attribution" not in source
    assert " recent · " not in source
    assert " applied / " not in source
    assert "tr('unresolved_fill_summary'" in source
    assert "tr('ai_budget_summary'" in source
    assert "tr('api_error_summary'" in source
    assert "tr('ai_decision_summary'" in source
    assert "risk.reasons.map(riskReasonText)" in source
    assert "return normalized||tr('unavailable')" in source
    assert 'unresolved:"\u041d\u0435\u0440\u0430\u0437\u043e\u0431\u0440\u0430\u043d\u043d\u044b\u0435 \u0438\u0441\u043f\u043e\u043b\u043d\u0435\u043d\u0438\u044f"' in locales
    for key in (
        "unresolved_fill_summary",
        "ai_budget_summary",
        "api_error_summary",
        "ai_decision_summary",
        "risk_halted",
        "cap_hard",
        "risk_reason_post_emergency_approval",
    ):
        assert locales.count(f"{key}:") == 2
