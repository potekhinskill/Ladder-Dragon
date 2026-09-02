# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: record bounded startup-phase timings without persistent growth.

"""Monotonic startup timing for supervisor status and structured logs."""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any


class StartupTimeline:
    """Record each startup phase once using a monotonic clock."""

    def __init__(self, monotonic: Callable[[], float] = time.monotonic) -> None:
        self._monotonic = monotonic
        self._started = monotonic()
        self._previous = self._started
        self._phases: dict[str, dict[str, int]] = {}

    def mark(self, phase: str) -> dict[str, int] | None:
        """Record one phase and return its bounded duration payload."""
        if phase in self._phases:
            return None
        now = self._monotonic()
        payload = {
            "delta_ms": max(0, round((now - self._previous) * 1000)),
            "elapsed_ms": max(0, round((now - self._started) * 1000)),
        }
        self._phases[phase] = payload
        self._previous = now
        return dict(payload)

    def snapshot(self) -> dict[str, Any]:
        """Return disposable bounded status data for one process start."""
        return {"phases": {key: dict(value) for key, value in self._phases.items()}}


__all__ = ["StartupTimeline"]
