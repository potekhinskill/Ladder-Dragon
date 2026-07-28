# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: classify preflight failures and keep fail-closed retry state fresh.

"""Supervisor preflight resilience policies."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timedelta
import math
from typing import Any

import requests


def is_auth_rejection(exc: BaseException) -> bool:
    """Recognize definitive Binance credential or signature rejections."""
    current: BaseException | None = exc
    seen: set[int] = set()
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        status = getattr(current, "status", None)
        code = getattr(current, "code", None)
        if status in (401, 403) or code in (-2014, -2015, -1022):
            return True
        text = str(current).lower()
        if any(marker in text for marker in (
            "http 401",
            "http 403",
            "code=-2014",
            "code=-2015",
            "code=-1022",
            "'code': -2014",
            "'code': -2015",
            "'code': -1022",
            "invalid api-key",
            "api_key/secret are required",
        )):
            return True
        current = current.__cause__ or current.__context__
    return False


def is_transient_failure(exc: BaseException) -> bool:
    """Recognize temporary read failures that permit fail-closed retry."""
    current: BaseException | None = exc
    seen: set[int] = set()
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        if isinstance(current, requests.RequestException):
            return True
        status = getattr(current, "status", None)
        code = getattr(current, "code", None)
        if status in {418, 429} or (
            isinstance(status, int) and status >= 500
        ):
            return True
        if code in {-1021, -1000, -1001, -1003}:
            return True
        text = str(current).lower()
        if (
            "binance time rtt" in text
            or "timestamp for this request is outside" in text
            or "code=-1021" in text
            or "'code': -1021" in text
        ):
            return True
        current = current.__cause__ or current.__context__
    return False


def retry_delay(
    attempt: int,
    *,
    initial_sec: int,
    max_sec: int,
) -> int:
    """Return a bounded exponential delay for a one-based failure count."""
    exponent = min(max(0, int(attempt) - 1), 16)
    return min(int(max_sec), int(initial_sec) * (2 ** exponent))


def retry_bounds(getenv: Callable[[str, str], str]) -> tuple[int, int]:
    """Read bounded transient-preflight retry settings or safe defaults."""
    try:
        initial = max(
            5,
            min(3600, int(getenv(
                "BINANCE_PREFLIGHT_BACKOFF_INITIAL_SEC", "30"
            ) or 30)),
        )
        maximum = max(
            initial,
            min(3600, int(getenv(
                "BINANCE_PREFLIGHT_BACKOFF_MAX_SEC", "300"
            ) or 300)),
        )
    except ValueError:
        return 30, 300
    return initial, maximum


def retry_schedule(
    attempt: int,
    *,
    initial_sec: int,
    max_sec: int,
    now: float,
) -> tuple[int, float]:
    """Return the retry delay and absolute runtime deadline."""
    delay = retry_delay(
        attempt,
        initial_sec=initial_sec,
        max_sec=max_sec,
    )
    return delay, now + delay


def backoff_active(retry_at: float, *, now: float) -> bool:
    """Return whether a persisted retry deadline remains active."""
    return retry_at > now


def wait_for_retry(
    kind: str,
    delay_sec: int,
    *,
    attempt: int,
    persistent_halt: bool,
    publish: Callable[..., None],
    monotonic: Callable[[], float],
    sleep: Callable[[float], None],
    now_utc: Callable[[], datetime],
) -> None:
    """Publish a fresh fail-closed heartbeat throughout one retry delay."""
    normalized = str(kind).strip().upper()
    if normalized not in {"AUTH", "PREFLIGHT"}:
        raise ValueError("retry kind must be AUTH or PREFLIGHT")
    if normalized == "AUTH":
        error = "Binance authentication unavailable"
        state = "AUTH_BACKOFF"
        field = "auth_backoff"
    else:
        error = "Binance preflight temporarily unavailable"
        state = "PREFLIGHT_BACKOFF"
        field = "preflight_backoff"
    deadline = monotonic() + max(1, int(delay_sec))
    while True:
        remaining = max(0, math.ceil(deadline - monotonic()))
        if remaining <= 0:
            return
        reasons = [error]
        if persistent_halt:
            reasons.insert(0, "persistent circuit halt")
        publish(
            state=state,
            error=error,
            **{
                field: {
                    "active": True,
                    "attempt": int(attempt),
                    "retry_in_sec": remaining,
                    "retry_at": (
                        now_utc() + timedelta(seconds=remaining)
                    ).isoformat(),
                },
                "risk": {
                    "halted": bool(persistent_halt),
                    "buy_blocked": True,
                    "reasons": reasons,
                },
            },
        )
        sleep(min(30, remaining))
