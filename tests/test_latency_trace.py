import json

import pytest

from ladder_dragon.execution.latency_trace import LatencyTrace


def test_latency_trace_records_only_allowlisted_sanitized_phases(tmp_path):
    ticks = iter((1_000_000_000, 1_001_500_000, 1_003_000_000))
    trace = LatencyTrace(
        "solusdt",
        "buy-submit",
        monotonic_ns=lambda: next(ticks),
        wall_time_ms=lambda: 1_700_000_000_000,
        trace_id="trace-safe",
    )

    assert trace.mark("journal_commit") == 1500
    assert trace.mark("request_sent") == 3000
    payload = trace.append(tmp_path / "latency.ndjson")

    persisted = json.loads((tmp_path / "latency.ndjson").read_text())
    assert payload == persisted
    assert persisted["symbol"] == "SOLUSDT"
    assert persisted["operation"] == "BUY-SUBMIT"
    assert persisted["phases_us"] == {
        "journal_commit": 1500,
        "request_sent": 3000,
    }
    assert "order" not in persisted
    assert "key" not in persisted


def test_latency_trace_rejects_unbounded_phase_names():
    trace = LatencyTrace("SOLUSDT", "BUY", monotonic_ns=lambda: 1)

    with pytest.raises(ValueError, match="unsupported latency phase"):
        trace.mark("api_key")
