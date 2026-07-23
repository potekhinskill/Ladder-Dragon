# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: implement the executor runtime component of the execution layer.
"""Ladder Dragon executor runtime support."""

from __future__ import annotations

import math
import time
from collections.abc import Callable, Iterator


def trading_seconds(
    duration_seconds: int,
    *,
    running: Callable[[], bool],
    sleep: Callable[[float], None] = time.sleep,
) -> Iterator[int]:
    """Handle trading seconds."""
    left = max(0, int(duration_seconds))
    while running() and left > 0:
        sleep(1)
        left -= 1
        yield left


def status_due(left_seconds: int, interval_seconds: int) -> bool:
    """Handle status due."""
    return left_seconds % max(1, int(interval_seconds)) == 0


def trading_wakeups(
    duration_seconds: int,
    *,
    running: Callable[[], bool],
    wait: Callable[[float], object],
    monotonic: Callable[[], float] = time.monotonic,
    housekeeping_interval_sec: float = 1.0,
) -> Iterator[int]:
    """Yield immediately on events while preserving a monotonic deadline."""
    duration = max(0.0, float(duration_seconds))
    deadline = monotonic() + duration
    interval = max(0.01, float(housekeeping_interval_sec))
    while running():
        remaining = deadline - monotonic()
        if remaining <= 0:
            break
        wait(min(interval, remaining))
        remaining = deadline - monotonic()
        if remaining < 0:
            remaining = 0
        yield int(math.ceil(remaining))
