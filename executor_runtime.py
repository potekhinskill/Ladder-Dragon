"""Runtime scheduler for the long-lived symbol executor."""

from __future__ import annotations

import time
from collections.abc import Callable, Iterator


def trading_seconds(
    duration_seconds: int,
    *,
    running: Callable[[], bool],
    sleep: Callable[[float], None] = time.sleep,
) -> Iterator[int]:
    """Yield remaining seconds while the worker is active.

    Exchange work deliberately stays in the caller: this scheduler owns only
    lifecycle timing, so it can be tested without credentials or network I/O.
    """
    left = max(0, int(duration_seconds))
    while running() and left > 0:
        sleep(1)
        left -= 1
        yield left


def status_due(left_seconds: int, interval_seconds: int) -> bool:
    """Return whether a periodic status line is due for this runtime tick."""
    return left_seconds % max(1, int(interval_seconds)) == 0
