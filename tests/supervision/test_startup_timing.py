"""Bounded startup timing regressions."""

from ladder_dragon.supervision.startup_timing import (
    StartupSubphases,
    StartupTimeline,
    log_worker_startup,
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


def test_supervisor_status_includes_preflight_subphases(monkeypatch):
    published = []
    values = iter((40.0, 40.1))
    monkeypatch.setattr(runtime, "_STARTUP_TIMELINE", StartupTimeline(lambda: next(values)))
    monkeypatch.setattr(runtime, "_PREFLIGHT_STARTUP_PHASES", {
        "clock": {"delta_ms": 300, "elapsed_ms": 500}})
    monkeypatch.setattr(runtime, "_RISK_STARTUP_PHASES", {})
    monkeypatch.setattr(runtime, "_publish_ai_runtime_status",
                        lambda **updates: published.append(updates))
    monkeypatch.setattr(runtime, "log", lambda _message: None)

    runtime._mark_startup("preflight")

    assert published[0]["startup_timing"]["preflight_phases"] == {
        "clock": {"delta_ms": 300, "elapsed_ms": 500}}
