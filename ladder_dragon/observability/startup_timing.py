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


class StartupSubphases:
    """Measure ordered subphases through one bounded callback."""

    def __init__(self, callback, monotonic: Callable[[], float] = time.monotonic):
        self._callback = callback
        self._monotonic = monotonic
        self._started = self._previous = monotonic()

    def mark(self, phase: str) -> None:
        now = self._monotonic()
        self._callback(phase, {
            "delta_ms": max(0, round((now - self._previous) * 1000)),
            "elapsed_ms": max(0, round((now - self._started) * 1000)),
        })
        self._previous = now

    def advance(self) -> None:
        """Start the next ordered interval without publishing a phase."""
        self._previous = self._monotonic()


def first_subphase_callback(phases, logger, component):
    """Create one bounded first-attempt subphase recorder."""
    def record(phase, timing):
        if phase in phases:
            return
        phases[phase] = dict(timing)
        fields = " ".join(f"{key}={value}" for key, value in timing.items())
        logger(f"[STARTUP-TIMING] component={component} phase={phase} {fields}")

    return record


def record_failed_startup_attempt(
    phases: dict[str, dict[str, Any]], *, attempt: int, backoff_sec: int,
) -> None:
    """Retain bounded aggregate timing for replaced preflight attempts."""
    previous = phases.get("failed_attempts", {})
    current = phases.get("live_preflight", {})
    phases["failed_attempts"] = {
        "count": int(attempt),
        "elapsed_ms": int(previous.get("elapsed_ms", 0))
        + int(current.get("elapsed_ms", 0)),
        "backoff_ms": int(previous.get("backoff_ms", 0))
        + max(0, int(backoff_sec)) * 1000,
    }


def log_worker_startup(
    timeline: StartupTimeline,
    logger: Callable[[str], None],
    symbol: str,
    phase: str,
) -> None:
    """Log one bounded worker startup phase."""
    timing = timeline.mark(phase)
    if timing is None:
        return
    logger(
        "[STARTUP-TIMING] component=worker "
        f"phase={phase} symbol={symbol} "
        f"delta_ms={timing['delta_ms']} elapsed_ms={timing['elapsed_ms']}"
    )


__all__ = [
    "StartupSubphases", "StartupTimeline", "first_subphase_callback",
    "log_worker_startup", "record_failed_startup_attempt",
]
