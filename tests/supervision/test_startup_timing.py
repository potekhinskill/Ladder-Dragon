"""Bounded startup timing regressions."""

import inspect

from ladder_dragon.supervision.startup_timing import (
    StartupSubphases,
    StartupTimeline,
    first_subphase_callback,
    log_worker_startup,
    record_failed_startup_attempt,
)
from ladder_dragon.supervision import runtime


def test_startup_timeline_records_each_phase_once():
    values = iter((10.0, 10.1, 10.4, 10.9))
    timeline = StartupTimeline(lambda: next(values))

    assert timeline.mark("preflight") == {"delta_ms": 100, "elapsed_ms": 100}
    assert timeline.mark("preflight") is None
    assert timeline.mark("recovery") == {"delta_ms": 300, "elapsed_ms": 400}
    assert timeline.snapshot() == {
        "phases": {
            "preflight": {"delta_ms": 100, "elapsed_ms": 100},
            "recovery": {"delta_ms": 300, "elapsed_ms": 400},
        }
    }


def test_worker_timing_logs_each_safe_phase_once_without_runtime_state():
    values = iter((20.0, 20.2, 20.5))
    timeline = StartupTimeline(lambda: next(values))
    messages = []

    log_worker_startup(timeline, messages.append, "SOLUSDT", "champion")
    log_worker_startup(timeline, messages.append, "SOLUSDT", "champion")
    log_worker_startup(timeline, messages.append, "SOLUSDT", "clock")

    assert messages == [
        "[STARTUP-TIMING] component=worker phase=champion symbol=SOLUSDT "
        "delta_ms=200 elapsed_ms=200",
        "[STARTUP-TIMING] component=worker phase=clock symbol=SOLUSDT "
        "delta_ms=300 elapsed_ms=500",
    ]


def test_startup_subphases_report_ordered_delta_and_elapsed_time():
    values = iter((30.0, 30.2, 30.7))
    reported = []
    timing = StartupSubphases(lambda phase, value: reported.append((phase, value)),
                              lambda: next(values))

    timing.mark("database")
    timing.mark("clock")

    assert reported == [
        ("database", {"delta_ms": 200, "elapsed_ms": 200}),
        ("clock", {"delta_ms": 500, "elapsed_ms": 700}),
    ]


def test_startup_subphases_advance_without_publishing():
    values = iter((30.0, 30.2, 30.7, 31.0))
    reported = []
    timing = StartupSubphases(lambda phase, value: reported.append((phase, value)),
                              lambda: next(values))

    timing.mark("database")
    timing.advance()
    timing.mark("account")

    assert reported == [
        ("database", {"delta_ms": 200, "elapsed_ms": 200}),
        ("account", {"delta_ms": 300, "elapsed_ms": 1000}),
    ]


def test_first_subphase_callback_retains_one_bounded_value():
    phases = {}
    messages = []
    record = first_subphase_callback(phases, messages.append, "loop_setup")

    record("operator_cap", {"delta_ms": 2, "elapsed_ms": 4})
    record("operator_cap", {"delta_ms": 9, "elapsed_ms": 15})

    assert phases == {
        "operator_cap": {"delta_ms": 2, "elapsed_ms": 4}
    }
    assert messages == [
        "[STARTUP-TIMING] component=loop_setup phase=operator_cap "
        "delta_ms=2 elapsed_ms=4"
    ]


def test_failed_attempt_timing_accumulates_without_error_text():
    phases = {"live_preflight": {"elapsed_ms": 6064, "success": False}}
    record_failed_startup_attempt(phases, attempt=1, backoff_sec=5)
    phases["live_preflight"] = {"elapsed_ms": 2507, "success": False}
    record_failed_startup_attempt(phases, attempt=2, backoff_sec=10)

    assert phases["failed_attempts"] == {
        "count": 2, "elapsed_ms": 8571, "backoff_ms": 15000,
    }
    assert "error" not in repr(phases)


def test_supervisor_status_includes_preflight_subphases(monkeypatch):
    published = []
    values = iter((40.0, 40.1))
    monkeypatch.setattr(runtime, "_STARTUP_TIMELINE", StartupTimeline(lambda: next(values)))
    monkeypatch.setattr(runtime, "_PREFLIGHT_STARTUP_PHASES", {
        "clock": {"delta_ms": 300, "elapsed_ms": 500}})
    monkeypatch.setattr(runtime, "_RISK_STARTUP_PHASES", {})
    monkeypatch.setattr(runtime, "_LOOP_SETUP_PHASES", {
        "operator_cap": {"delta_ms": 2, "elapsed_ms": 4}})
    monkeypatch.setattr(runtime, "_publish_ai_runtime_status",
                        lambda **updates: published.append(updates))
    monkeypatch.setattr(runtime, "log", lambda _message: None)

    runtime._mark_startup("preflight")

    assert published[0]["startup_timing"]["preflight_phases"] == {
        "clock": {"delta_ms": 300, "elapsed_ms": 500}}
    assert published[0]["startup_timing"]["loop_setup_phases"] == {
        "operator_cap": {"delta_ms": 2, "elapsed_ms": 4}}


def test_initial_loop_setup_and_heartbeat_are_timed_before_risk_snapshot():
    source = inspect.getsource(runtime.main)
    loop_setup = source.index('_mark_startup("loop_setup")')
    heartbeat = source.index('_mark_startup("initial_heartbeat")')
    snapshot = source.index('_mark_startup("risk_snapshot")')

    assert source.index("shutdown_signal.install()") < loop_setup
    for phase in (
        "risk_gate_publish",
        "operator_cap",
        "vwap_schedule",
        "runtime_state",
        "auth_state",
        "signal_setup",
    ):
        assert source.index(f'loop_timing.mark("{phase}")') < loop_setup
    assert loop_setup < source.index("while True:")
    assert loop_setup < heartbeat < snapshot
