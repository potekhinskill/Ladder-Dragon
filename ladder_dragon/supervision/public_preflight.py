# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: isolate concurrent public exchange checks from signed preflight I/O.

"""Concurrent public checks for the supervisor LIVE preflight."""

import time
from concurrent.futures import ThreadPoolExecutor
from threading import Lock
from typing import Callable, Iterable, TypeVar


_Result = TypeVar("_Result")


def read_clock_and_filters(
    symbols: Iterable[str],
    *,
    market,
    get_filters: Callable[..., dict[str, object]],
    max_offset_ms: int,
    max_round_trip_ms: int,
    record: Callable[[str, dict[str, object]], None],
    join_guard: Callable[[], None] | None = None,
    monotonic: Callable[[], float] = time.monotonic,
) -> dict[str, dict[str, object]]:
    """Drain public state and an external guard before returning results."""

    durations: dict[str, int] = {}
    duration_lock = Lock()

    def timed(phase: str, operation: Callable[[], _Result]) -> _Result:
        started = monotonic()
        try:
            return operation()
        finally:
            duration_ms = max(0, round((monotonic() - started) * 1000))
            with duration_lock:
                durations[phase] = duration_ms

    def verify_clock() -> None:
        market._refresh_time_offset(
            timeout=15,
            max_offset_ms=max_offset_ms,
            max_round_trip_ms=max_round_trip_ms,
            session=market.PREFLIGHT_CLOCK_SESSION,
        )

    def load_filters() -> dict[str, dict[str, object]]:
        return {
            symbol: get_filters(
                symbol, session=market.PREFLIGHT_FILTERS_SESSION
            )
            for symbol in symbols
        }

    joined_started = monotonic()
    with ThreadPoolExecutor(
        max_workers=2, thread_name_prefix="preflight-public"
    ) as executor:
        clock_future = executor.submit(timed, "clock", verify_clock)
        filters_future = executor.submit(timed, "filters", load_filters)
    joined_ms = max(0, round((monotonic() - joined_started) * 1000))
    clock_success = clock_future.exception() is None
    filters_success = filters_future.exception() is None
    record("clock", {
        "duration_ms": durations["clock"], "success": clock_success,
    })
    record("filters", {
        "duration_ms": durations["filters"], "success": filters_success,
    })
    record("public_join", {
        "duration_ms": joined_ms,
        "success": clock_success and filters_success,
    })
    if join_guard is not None:
        join_guard()
    clock_future.result()
    return filters_future.result()


__all__ = ["read_clock_and_filters"]
