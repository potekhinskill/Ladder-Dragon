"""Compact user-stream dashboard presentation regressions."""

from pathlib import Path

from tests.test_dashboard_security import dashboard_source


def test_user_stream_summary_hides_zero_counters_behind_diagnostics():
    source = dashboard_source()
    index = Path("FRONT/index.html").read_text(encoding="utf-8")
    locales = Path("FRONT/locales.js").read_text(encoding="utf-8")

    assert "userStreamSummary" in source
    assert "userStreamDiagnostics" in source
    assert "not_configured_or_not_started" in source
    assert "user_stream_rest_fallback" in source
    assert ".filter(([key])=>Number(stream[key]||0)>0)" in source
    assert 'id="ops-user-stream-details" hidden' in index
    assert 'id="ops-user-stream-diagnostics"' in index
    for key in (
        "user_stream_not_started",
        "user_stream_rest_fallback",
        "user_stream_connected",
        "user_stream_stale",
        "user_stream_diagnostics",
        "hours_short",
        "stream_counter_sessions",
        "stream_counter_events",
        "stream_counter_reconnects",
        "stream_counter_planned_reconnects",
        "stream_counter_failure_reconnects",
        "stream_counter_legacy_reconnects",
    ):
        assert locales.count(f"{key}:") == 2

    assert "`${label} ${Number(stream[key])}`" not in source
    assert "`${tr(label)} ${Number(stream[key])}`" in source
