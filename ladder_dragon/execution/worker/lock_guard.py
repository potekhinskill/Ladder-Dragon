# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: release an acquired worker lock when preflight exits abnormally.

"""Worker lock ownership across fail-closed preflight."""

from __future__ import annotations

from contextlib import contextmanager
from typing import Any, Iterator


@contextmanager
def release_lock_on_error(lock: Any) -> Iterator[None]:
    """Retain the lock on success and release it on every abnormal exit."""
    completed = False
    try:
        yield
        completed = True
    finally:
        if not completed:
            lock.release()


__all__ = ["release_lock_on_error"]
