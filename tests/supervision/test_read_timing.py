"""Physical retry telemetry stays bounded and excludes request identity."""

import requests
import pytest

from ladder_dragon.execution import tools_market as market
from ladder_dragon.execution.read_timing import record_read
from ladder_dragon.supervision.valuation_metrics import ValuationMetrics


@pytest.mark.parametrize("first", ["timeout", "server"])
def test_attempt_timing(monkeypatch, first):
    clock = [0.0]
    calls = []
    responses = []
    monkeypatch.setattr(market.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(market.time, "sleep", lambda seconds: clock.__setitem__(0, clock[0] + seconds))
    monkeypatch.setattr(market, "_rate_limit_until", 0)
    def request(*args, **kwargs):
        calls.append(True)
        clock[0] += .1
        if len(calls) == 1 and first == "timeout":
            raise requests.Timeout("private-marker")
        response = requests.Response()
        response.status_code = 503 if len(calls) == 1 else 200
        response._content_consumed = True
        responses.append(response)
        return response
    def body(*args, **kwargs):
        clock[0] += .2
        return b'{}'
    monkeypatch.setattr(market.SESSION, "request", request)
    monkeypatch.setattr(market, "read_body", body)
    metrics = ValuationMetrics()
    metrics.read("cross_btc", market._do_request, "GET", "https://example.invalid/private-marker")
    values = metrics.snapshot(failed=False)
    assert values["cross_btc_http_attempts"] == 2
    assert values["cross_btc_headers_ms"] == 200
    assert values["cross_btc_retry_wait_ms"] == 500
    assert values["cross_btc_body_ms"] == (200 if first == "timeout" else 400)
    assert values["cross_btc_transport_errors"] == int(first == "timeout")
    assert values["cross_btc_http_5xx"] == int(first == "server")
    assert "private-marker" not in repr(values)
    record_read("http_attempts")
    assert metrics.snapshot(failed=False) == values


@pytest.mark.parametrize("stage", ["close", "json_decode", "batch_validate"])
@pytest.mark.parametrize("failed", [False, True])
def test_wall_and_cpu_stages_include_failures(monkeypatch, stage, failed):
    from ladder_dragon.execution import read_timing
    clock, cpu = [0.0], [0.0]
    monkeypatch.setattr(read_timing.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(read_timing.time, "thread_time", lambda: cpu[0])
    metrics = ValuationMetrics()
    def work():
        clock[0] += 3.35
        cpu[0] += .008
        if failed:
            raise ValueError("private-payload")
        return "private-payload"
    if failed:
        with pytest.raises(ValueError):
            metrics.read("batch", read_timing.measured_read, stage, work)
    else:
        assert metrics.read("batch", read_timing.measured_read, stage, work) == "private-payload"
    values = metrics.snapshot(failed=failed)
    assert values[f"batch_{stage}_ms"] == 3350
    assert values[f"batch_{stage}_cpu_ms"] == 8
    assert values["batch_read_cpu_ms"] == 8
    assert "private-payload" not in repr(values)
    read_timing.record_read(stage + "_ms", 123)
    assert metrics.snapshot(failed=failed) == values


def test_physical_timings_reach_startup_status(monkeypatch):
    from ladder_dragon.supervision import runtime
    from ladder_dragon.supervision.startup_timing import StartupTimeline

    published = []
    monkeypatch.setattr(runtime, "_STARTUP_TIMELINE", StartupTimeline())
    monkeypatch.setattr(runtime, "_RISK_STARTUP_PHASES", {})
    monkeypatch.setattr(runtime, "_publish_ai_runtime_status", lambda **kw: published.append(kw))
    monkeypatch.setattr(runtime, "log", lambda *args: None)
    metrics = ValuationMetrics()
    metrics.read("cross_btc", lambda: record_read("http_attempts", 2))
    runtime._record_risk_startup_phase("valuation_routes", metrics.snapshot(failed=False))
    runtime._mark_startup("risk_snapshot")
    values = published[-1]["startup_timing"]["risk_snapshot_phases"]["valuation_routes"]
    assert values["cross_btc_http_attempts"] == 2
