# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: isolate concurrent public exchange checks from signed preflight I/O.

"""Concurrent public checks for the supervisor LIVE preflight."""

from concurrent.futures import ThreadPoolExecutor
from typing import Callable, Iterable


def read_clock_and_filters(
    symbols: Iterable[str],
    *,
    market,
    get_filters: Callable[..., dict[str, object]],
    max_offset_ms: int,
    max_round_trip_ms: int,
    mark: Callable[[str], None],
) -> dict[str, dict[str, object]]:
    """Read clock and filters concurrently, then drain both public tasks."""

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

    with ThreadPoolExecutor(
        max_workers=2, thread_name_prefix="preflight-public"
    ) as executor:
        clock_future = executor.submit(verify_clock)
        filters_future = executor.submit(load_filters)
        clock_future.result()
        mark("clock")
        filters = filters_future.result()
        mark("filters")
    return filters


__all__ = ["read_clock_and_filters"]
