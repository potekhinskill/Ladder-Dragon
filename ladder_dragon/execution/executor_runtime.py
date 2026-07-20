# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: implement the executor runtime component of the execution layer.
"""Ladder Dragon executor runtime support."""

from __future__ import annotations

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
