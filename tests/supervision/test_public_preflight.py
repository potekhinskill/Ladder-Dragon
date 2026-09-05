"""Concurrent public LIVE-preflight regressions."""

import threading
from types import SimpleNamespace

import pytest

from ladder_dragon.supervision.public_preflight import read_clock_and_filters


def test_clock_and_filters_overlap_on_separate_public_sessions():
    barrier = threading.Barrier(2)
    clock_session = object()
    filters_session = object()
    calls = []

    def refresh(**kwargs):
        calls.append(("clock", kwargs["session"]))
        barrier.wait(timeout=2)

    def filters(symbol, *, session):
        calls.append((symbol, session))
        barrier.wait(timeout=2)
        return {"tickSize": 1}

    market = SimpleNamespace(
        _refresh_time_offset=refresh,
        PREFLIGHT_CLOCK_SESSION=clock_session,
        PREFLIGHT_FILTERS_SESSION=filters_session,
    )
    phases = []

    result = read_clock_and_filters(
        ["SOLUSDT"], market=market, get_filters=filters,
        max_offset_ms=1000, max_round_trip_ms=5000,
        mark=phases.append,
    )

    assert result == {"SOLUSDT": {"tickSize": 1}}
    assert set(calls) == {("clock", clock_session), ("SOLUSDT", filters_session)}
    assert phases == ["clock", "filters"]


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

    with pytest.raises(RuntimeError, match="clock unavailable"):
        read_clock_and_filters(
            ["SOLUSDT"], market=market, get_filters=filters,
            max_offset_ms=1000, max_round_trip_ms=5000,
            mark=lambda _phase: None,
        )

    assert filters_finished.is_set()
