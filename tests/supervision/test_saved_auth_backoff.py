"""Saved retry state must not escape the preflight cleanup boundary."""

from decimal import Decimal
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

import pytest

from ladder_dragon.execution.auth_resilience import AuthResilienceState
from ladder_dragon.supervision import runtime
from ladder_dragon.supervision.startup_timing import StartupSubphases, StartupTimeline


@pytest.fixture
def scenario(monkeypatch, tmp_path):
    events, published, phases = [], [], {}
    clock = [100.0]
    state = AuthResilienceState(attempt=1, retry_at_epoch=160)
    monkeypatch.setattr(runtime.time, "time", lambda: clock[0])
    monkeypatch.setattr(runtime.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(runtime, "StartupSubphases", lambda callback: StartupSubphases(callback, lambda: clock[0]))
    monkeypatch.setattr(runtime, "_read_auth_resilience_state", lambda: state)
    monkeypatch.setattr(runtime, "_save_auth_resilience_state", lambda _s: events.append("save"))
    monkeypatch.setattr(runtime, "_PREFLIGHT_STARTUP_PHASES", phases)
    monkeypatch.setattr(runtime, "_STARTUP_TIMELINE", StartupTimeline(lambda: clock[0]))
    monkeypatch.setattr(runtime, "_record_preflight_startup_phase", lambda k,v: phases.update({k:v}))
    monkeypatch.setattr(runtime, "_publish_ai_runtime_status", lambda **kw: published.append(kw))
    monkeypatch.setattr(runtime, "_mark_startup", lambda _p: None)
    monkeypatch.setattr(runtime, "_pre_running_recovery_gate", lambda *_a: {"blocked": False})

    class Future:
        def result(self):
            events.append("join")
            return state, None

    class Executor:
        def __init__(self, **_kw): pass
        def submit(self, *_a):
            events.append("submit")
            return Future()
        def shutdown(self, *, wait):
            assert wait is True
            events.append("shutdown")

    monkeypatch.setattr(runtime, "ThreadPoolExecutor", Executor)

    def wait(kind, delay, **kwargs):
        assert (kind, delay, kwargs) == ("AUTH", 60, {"attempt": 1, "persistent_halt": False})
        events.append("wait")
        clock[0] += delay

    def preflight(_a, _s, _l, join):
        events.append("preflight")
        join()
        clock[0] += 2
        return {"USDT": Decimal("31")}

    monkeypatch.setattr(runtime, "_wait_for_resilience_retry", wait)
    monkeypatch.setattr(runtime, "_preflight_live", preflight)
    return SimpleNamespace(
        events=events, published=published, phases=phases, clock=clock,
        future=Future, args=SimpleNamespace(live=True),
        limits=SimpleNamespace(halt_file=tmp_path / "halt.json"),
    )


def test_saved_wait_then_preflight_preserves_order_and_timing(scenario):
    s = scenario
    assert runtime._preflight_with_auth_backoff(s.args, ["SOLUSDT"], s.limits) == {"USDT": Decimal("31")}
    assert s.events == ["submit", "join", "wait", "save", "preflight", "shutdown", "save"]
    assert s.phases["saved_auth_backoff"]["delta_ms"] == 60000
    assert s.phases["live_preflight"] == {"delta_ms": 2000, "elapsed_ms": 2000, "success": True}


@pytest.mark.parametrize("stage", ["guard", "wait", "save"])
def test_saved_backoff_failure_drains_without_preflight(scenario, monkeypatch, stage):
    s = scenario
    def fail(*_a, **_kw):
        s.clock[0] += 1
        raise OSError("private-marker")
    if stage == "guard":
        monkeypatch.setattr(s.future, "result", fail)
    elif stage == "wait":
        monkeypatch.setattr(runtime, "_wait_for_resilience_retry", fail)
    else:
        monkeypatch.setattr(runtime, "_save_auth_resilience_state", fail)
    with pytest.raises(OSError):
        runtime._preflight_with_auth_backoff(s.args, ["SOLUSDT"], s.limits)
    assert s.events.count("shutdown") == 1
    assert "preflight" not in s.events
    assert s.phases["live_preflight"]["success"] is False
    assert s.phases["live_preflight"]["elapsed_ms"] >= 1000
    assert any("startup_timing" in row for row in s.published)
    assert s.published[-1]["state"] == "PREFLIGHT_FAILED"
    assert "private-marker" not in str(s.published)
    assert "private-marker" not in str(s.phases)


def test_saved_wait_shutdown_signal_still_drains(scenario, monkeypatch):
    s = scenario
    def stop(*_a, **_kw):
        raise SystemExit(0)
    monkeypatch.setattr(runtime, "_wait_for_resilience_retry", stop)
    with pytest.raises(SystemExit):
        runtime._preflight_with_auth_backoff(s.args, ["SOLUSDT"], s.limits)
    assert s.events.count("shutdown") == 1
    assert "preflight" not in s.events
    assert s.phases["live_preflight"]["success"] is False


def test_real_guard_thread_drains_and_preserves_halt(scenario, monkeypatch):
    s = scenario
    executors = []
    class Executor(ThreadPoolExecutor):
        def __init__(self, **kwargs):
            super().__init__(**kwargs)
            executors.append(self)
    def observe(_state):
        raise OSError("private-marker")
    monkeypatch.setattr(runtime, "ThreadPoolExecutor", Executor)
    monkeypatch.setattr(runtime, "_observe_public_ip", observe)
    s.limits.halt_file.write_text('{"halted": true}', encoding="utf-8")
    before = s.limits.halt_file.read_bytes()
    with pytest.raises(OSError):
        runtime._preflight_with_auth_backoff(s.args, ["SOLUSDT"], s.limits)
    assert len(executors) == 1 and executors[0]._threads
    assert all(not thread.is_alive() for thread in executors[0]._threads)
    assert s.limits.halt_file.read_bytes() == before
    assert "preflight" not in s.events
    assert "private-marker" not in str(s.published)
