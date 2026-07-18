# Copyright (c) 2026 IURII Potekhin / Ladder Dragon. All rights reserved.
# Purpose: implement the executor runtime component of the execution layer.
"""Планировщик жизненного цикла долгоживущего символьного исполнителя."""

from __future__ import annotations

import time
from collections.abc import Callable, Iterator


def trading_seconds(
    duration_seconds: int,
    *,
    running: Callable[[], bool],
    sleep: Callable[[float], None] = time.sleep,
) -> Iterator[int]:
    """Выдавать оставшиеся секунды, пока воркер активен.

    Биржевые действия намеренно остаются у вызывающего кода. Здесь только
    тайминг жизненного цикла, поэтому модуль тестируется без ключей и сети.
    """
    left = max(0, int(duration_seconds))
    while running() and left > 0:
        sleep(1)
        left -= 1
        yield left


def status_due(left_seconds: int, interval_seconds: int) -> bool:
    """Проверить, пора ли печатать периодический статус на текущем тике."""
    return left_seconds % max(1, int(interval_seconds)) == 0
