"""Attempt-local telemetry must not inherit earlier successful phases."""

from types import SimpleNamespace

import pytest

from ladder_dragon.execution.auth_resilience import AuthResilienceState
from ladder_dragon.supervision import runtime
from ladder_dragon.supervision.startup_timing import StartupTimeline


def test_early_retry_failure_clears_old_phases_but_retains_aggregate(monkeypatch, tmp_path):
    phases, published = {}, []
    attempt = [0]
    monkeypatch.setattr(runtime, "_PREFLIGHT_STARTUP_PHASES", phases)
    monkeypatch.setattr(runtime, "_STARTUP_TIMELINE", StartupTimeline())
    monkeypatch.setattr(runtime, "_read_auth_resilience_state", AuthResilienceState)
    monkeypatch.setattr(runtime, "_save_auth_resilience_state", lambda _s: None)
    monkeypatch.setattr(runtime, "_observe_public_ip", lambda s: (s, None))
    monkeypatch.setattr(runtime, "_wait_for_resilience_retry", lambda *a, **kw: None)
    monkeypatch.setattr(runtime, "_publish_ai_runtime_status", lambda **kw: published.append(kw))
    monkeypatch.setattr(runtime, "log", lambda *a: None)
    phases["failed_attempts"] = {"count": 999, "elapsed_ms": 999}

    def preflight(*_args):
        attempt[0] += 1
        if attempt[0] == 1:
            for name in ("clock", "filters", "account", "public_join"):
                runtime._record_preflight_startup_phase(name, {"duration_ms": 123, "success": True})
            raise RuntimeError("Binance time RTT 5660 ms exceeds 5000 ms")
        if attempt[0] == 2:
            raise RuntimeError("Binance time RTT 5660 ms exceeds 5000 ms")
        raise ValueError("synthetic-private-marker")

    monkeypatch.setattr(runtime, "_preflight_live", preflight)
    with pytest.raises(ValueError):
        runtime._preflight_with_auth_backoff(
            SimpleNamespace(live=True), ["SOLUSDT"], SimpleNamespace(halt_file=tmp_path / "halt"),
        )
    assert attempt[0] == 3
    assert not {"clock", "filters", "account", "public_join"}.intersection(phases)
    assert phases["failed_attempts"]["count"] == 2
    assert phases["failed_attempts"]["backoff_ms"] > 0
    assert phases["live_preflight"]["success"] is False
    last = [row["startup_timing"] for row in published if "startup_timing" in row][-1]
    assert not {"clock", "filters", "account", "public_join"}.intersection(last["preflight_phases"])
    assert "synthetic-private-marker" not in repr(published)
