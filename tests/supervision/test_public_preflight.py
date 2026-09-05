"""Concurrent public LIVE-preflight regressions."""

import threading
import time
from types import SimpleNamespace

import pytest

from ladder_dragon.supervision.public_preflight import read_clock_and_filters


def test_clock_and_filters_overlap_on_separate_public_sessions():
    barrier = threading.Barrier(2)
    filters_finished = threading.Event()
    clock_session = object()
    filters_session = object()
    calls = []
    guard_calls = []

    def refresh(**kwargs):
        calls.append(("clock", kwargs["session"]))
        barrier.wait(timeout=2)
        assert filters_finished.wait(timeout=2)
        time.sleep(0.02)

    def filters(symbol, *, session):
        calls.append((symbol, session))
        barrier.wait(timeout=2)
        time.sleep(0.02)
        filters_finished.set()
        return {"tickSize": 1}

    market = SimpleNamespace(
        _refresh_time_offset=refresh,
        PREFLIGHT_CLOCK_SESSION=clock_session,
        PREFLIGHT_FILTERS_SESSION=filters_session,
    )
    reports = []

    result = read_clock_and_filters(
        ["SOLUSDT"], market=market, get_filters=filters,
        max_offset_ms=1000, max_round_trip_ms=5000,
        record=lambda phase, value: reports.append((phase, value)),
        join_guard=lambda: guard_calls.append(tuple(call[0] for call in calls)),
    )

    assert result == {"SOLUSDT": {"tickSize": 1}}
    assert set(calls) == {("clock", clock_session), ("SOLUSDT", filters_session)}
    assert [phase for phase, _value in reports] == [
        "clock", "filters", "public_join",
    ]
    timings = dict(reports)
    assert timings["clock"]["duration_ms"] >= 30
    assert timings["filters"]["duration_ms"] >= 10
    assert timings["public_join"]["duration_ms"] >= 30
    assert all(value["success"] is True for _phase, value in reports)
    assert len(guard_calls) == 1
    assert set(guard_calls[0]) == {"clock", "SOLUSDT"}


def test_clock_failure_drains_started_filter_read():
    barrier = threading.Barrier(2)
    filters_finished = threading.Event()

    def refresh(**_kwargs):
        barrier.wait(timeout=2)
        raise RuntimeError("clock unavailable")

    def filters(_symbol, *, session):
        assert session is market.PREFLIGHT_FILTERS_SESSION
        barrier.wait(timeout=2)
        filters_finished.set()
        return {"tickSize": 1}

    market = SimpleNamespace(
        _refresh_time_offset=refresh,
        PREFLIGHT_CLOCK_SESSION=object(),
        PREFLIGHT_FILTERS_SESSION=object(),
    )
    reports = []
    guard_calls = []

    with pytest.raises(RuntimeError, match="clock unavailable"):
        read_clock_and_filters(
            ["SOLUSDT"], market=market, get_filters=filters,
            max_offset_ms=1000, max_round_trip_ms=5000,
            record=lambda phase, value: reports.append((phase, value)),
            join_guard=lambda: guard_calls.append("joined"),
        )

    assert filters_finished.is_set()
    timings = dict(reports)
    assert timings["clock"]["success"] is False
    assert timings["filters"]["success"] is True
    assert timings["public_join"]["success"] is False
    assert all(set(value) == {"duration_ms", "success"} for _, value in reports)
    assert "clock unavailable" not in repr(reports)
    assert guard_calls == ["joined"]


def test_guard_failure_precedes_public_failure_after_complete_drain():
    barrier = threading.Barrier(2)
    filters_finished = threading.Event()

    def refresh(**_kwargs):
        barrier.wait(timeout=2)
        raise RuntimeError("clock unavailable")

    def filters(_symbol, *, session):
        assert session is market.PREFLIGHT_FILTERS_SESSION
        barrier.wait(timeout=2)
        filters_finished.set()
        return {"tickSize": 1}

    def join_guard():
        assert filters_finished.is_set()
        raise ValueError("guard unavailable")

    market = SimpleNamespace(
        _refresh_time_offset=refresh,
        PREFLIGHT_CLOCK_SESSION=object(),
        PREFLIGHT_FILTERS_SESSION=object(),
    )

    with pytest.raises(ValueError, match="guard unavailable"):
        read_clock_and_filters(
            ["SOLUSDT"], market=market, get_filters=filters,
            max_offset_ms=1000, max_round_trip_ms=5000,
            record=lambda _phase, _value: None,
            join_guard=join_guard,
        )

    assert filters_finished.is_set()
