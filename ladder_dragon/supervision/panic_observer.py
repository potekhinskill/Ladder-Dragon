# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: observe market PANIC without worker or order authority.
"""Supervisor-owned, public-market PANIC evidence for HALT-safe selection."""

from __future__ import annotations

import hashlib
import json
import math
import os
from pathlib import Path
import re
from typing import Callable, Mapping

from ladder_dragon.strategy.strategy_math import (
    atr_from_klines,
    ema_value,
    panic_triggered,
)


PANIC_OBSERVER_CONTRACT = {
    "schema_version": 1,
    "source": "SUPERVISOR_PUBLIC_MARKET_PANIC_V1",
    "interval": "1m",
    "ema_length": 20,
    "atr_length": 14,
    "drop_pct": "0.02",
    "atr_multiplier": "2.0",
    "debounce_checks": 2,
    "cooldown_ms": 180_000,
    "recovery": "CURRENT_PRICE_AT_OR_ABOVE_EMA20_MINUS_ATR",
}
MAXIMUM_OBSERVATION_AGE_MS = 120_000
MAXIMUM_STATE_BYTES = 16_384
KLINE_INTERVAL_MS = 60_000
CLOCK_TOLERANCE_MS = 5_000


def _canonical(payload: Mapping[str, object]) -> bytes:
    return json.dumps(
        dict(payload), sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def panic_observer_fingerprint() -> str:
    """Identify the complete public PANIC observation contract."""
    return hashlib.sha256(_canonical(PANIC_OBSERVER_CONTRACT)).hexdigest()


def panic_observer_path(symbol: str, *, run_dir: str | Path | None = None) -> Path:
    """Return one bounded, non-secret state path for a validated symbol."""
    safe_symbol = str(symbol).strip().upper()
    if not re.fullmatch(r"[A-Z0-9]{5,20}", safe_symbol):
        raise ValueError("PANIC observer symbol is invalid")
    root = Path(
        run_dir
        if run_dir is not None
        else os.getenv("BOT_RUN_DIR", "/run/mybot")
    )
    return root / f"supervisor_panic_state_{safe_symbol}.json"


def read_panic_observation(
    symbol: str,
    *,
    now_ms: int,
    run_dir: str | Path | None = None,
) -> dict[str, object] | None:
    """Read only a fresh state with the exact observer fingerprint."""
    path = panic_observer_path(symbol, run_dir=run_dir)
    try:
        if not path.is_file() or path.stat().st_size > MAXIMUM_STATE_BYTES:
            return None
        payload = json.loads(path.read_text(encoding="utf-8"))
        return validate_panic_observation(symbol, payload, now_ms=now_ms)
    except (OSError, TypeError, ValueError, json.JSONDecodeError):
        return None


def validate_panic_observation(
    symbol: str, payload: object, *, now_ms: int,
) -> dict[str, object] | None:
    """Validate a detached observation with the same rules as the state reader."""
    try:
        expected = {
            "schema_version", "symbol", "on", "hits", "since_ms",
            "last_trigger_ms", "updated_at_ms", "source_fingerprint",
        }
        if not isinstance(payload, dict) or set(payload) != expected:
            return None
        updated = payload["updated_at_ms"]
        if (
            payload["schema_version"] != 1
            or payload["symbol"] != str(symbol).strip().upper()
            or type(payload["on"]) is not bool
            or type(payload["hits"]) is not int
            or type(updated) is not int
            or not 0 <= payload["hits"] <= 1_000_000
            or not now_ms - MAXIMUM_OBSERVATION_AGE_MS <= updated <= now_ms + 5_000
            or payload["source_fingerprint"] != panic_observer_fingerprint()
        ):
            return None
        for field in ("since_ms", "last_trigger_ms"):
            if type(payload[field]) is not int or payload[field] < 0:
                return None
        return dict(payload)
    except (TypeError, ValueError):
        return None


def _indicators(klines: object) -> tuple[float, float, float, float]:
    """Calculate the same closed-bar inputs from one bounded public response."""
    if not isinstance(klines, list) or not 30 <= len(klines) <= 120:
        raise ValueError("PANIC observer klines are incomplete")
    if any(not isinstance(row, list) or len(row) < 7 for row in klines):
        raise ValueError("PANIC observer kline schema is invalid")
    # Validate every price before indicator math or any persisted transition.
    # A non-finite current price must never clear PANIC through recovery.
    validated_closes = []
    for row in klines:
        try:
            prices = [float(value) for value in row[1:5]]
        except (TypeError, ValueError, OverflowError):
            raise ValueError("PANIC observer price is invalid") from None
        if any(isinstance(value, bool) for value in row[1:5]) or any(
            not math.isfinite(value) or value <= 0 for value in prices
        ):
            raise ValueError("PANIC observer price is invalid")
        validated_closes.append(prices[3])
    closes = validated_closes[:-1]
    ema20 = ema_value(closes[-60:], 20)
    # Keep original decimal strings for the exact Wilder ATR implementation.
    atr14 = atr_from_klines(klines, 14)
    if any(not math.isfinite(value) or value <= 0 for value in (ema20, atr14)):
        raise ValueError("PANIC observer indicators are unavailable")
    return validated_closes[-1], ema20, atr14, closes[-1]


def _validate_kline_times(klines: list, now_ms: int) -> None:
    """Reject stale, future, or discontinuous source bars before publication."""
    previous_open = None
    for row in klines:
        opened, closed = row[0], row[6]
        if (
            type(opened) is not int or type(closed) is not int
            or opened % KLINE_INTERVAL_MS != 0
            or closed != opened + KLINE_INTERVAL_MS - 1
            or (previous_open is not None and opened != previous_open + KLINE_INTERVAL_MS)
        ):
            raise ValueError("PANIC observer candle chronology is invalid")
        previous_open = opened
    # The final candle can still be forming; its close need not precede now.
    if not -CLOCK_TOLERANCE_MS <= now_ms - klines[-1][0] < KLINE_INTERVAL_MS + CLOCK_TOLERANCE_MS:
        raise ValueError("PANIC observer candle freshness is invalid")


def refresh_panic_observation(
    symbol: str,
    *,
    public_get: Callable[[str, dict[str, object]], object],
    now_ms: int,
    run_dir: str | Path | None = None,
    clock: Callable[[], int] | None = None,
) -> dict[str, object]:
    """Refresh public PANIC state without worker, account, or order access."""
    path = panic_observer_path(symbol, run_dir=run_dir)
    previous = read_panic_observation(symbol, now_ms=now_ms, run_dir=run_dir)
    klines = public_get(
        "/api/v3/klines",
        {"symbol": str(symbol).strip().upper(), "interval": "1m", "limit": 120},
    )
    received_at = clock() if clock is not None else now_ms
    if type(received_at) is not int or not 0 <= received_at - now_ms < MAXIMUM_OBSERVATION_AGE_MS:
        raise ValueError("PANIC observer response clock is invalid")
    now_ms = received_at
    now_price, ema20, atr14, previous_close = _indicators(klines)
    _validate_kline_times(klines, now_ms)
    triggered = panic_triggered(
        now_price, ema20, atr14, previous_close, 0.02, 2.0
    )
    on = bool(previous and previous["on"])
    hits = int(previous["hits"]) if previous else 0
    since_ms = int(previous["since_ms"]) if previous else 0
    last_trigger_ms = int(previous["last_trigger_ms"]) if previous else 0
    if triggered:
        hits = min(2, hits + 1)
        last_trigger_ms = now_ms
        if not on and hits >= 2:
            on, since_ms = True, now_ms
    else:
        hits = 0
    # Market-only recovery is conservative. Account inventory cannot relax it.
    if (
        on
        and now_ms - since_ms >= 180_000
        and now_price >= ema20 - atr14
    ):
        on, hits = False, 0
    payload = {
        "schema_version": 1,
        "symbol": str(symbol).strip().upper(),
        "on": on,
        "hits": hits,
        "since_ms": since_ms,
        "last_trigger_ms": last_trigger_ms,
        "updated_at_ms": now_ms,
        "source_fingerprint": panic_observer_fingerprint(),
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(_canonical(payload))
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        os.chmod(path, 0o600)
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass
    return payload


__all__ = [
    "MAXIMUM_OBSERVATION_AGE_MS",
    "PANIC_OBSERVER_CONTRACT",
    "panic_observer_fingerprint",
    "panic_observer_path",
    "read_panic_observation",
    "validate_panic_observation",
    "refresh_panic_observation",
]
