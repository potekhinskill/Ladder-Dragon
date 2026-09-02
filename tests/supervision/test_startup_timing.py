"""Bounded startup timing regressions."""

from ladder_dragon.supervision.startup_timing import (
    StartupTimeline,
    log_worker_startup,
)


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
