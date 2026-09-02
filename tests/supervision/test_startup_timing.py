"""Bounded startup timing regressions."""

from ladder_dragon.supervision.startup_timing import StartupTimeline


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
