# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: select bounded AI settlement work and validate historical prices.

"""Fail-closed helpers for AI decision settlement."""

from __future__ import annotations

import sqlite3
from typing import Any, Callable, Sequence


SETTLEMENT_BATCH_SIZE = 32
_HORIZONS_SEC = (900, 3_600, 14_400)
_SELECT_COLUMNS = """
    decision_id, created_at,
    COALESCE(NULLIF(price_text,''),CAST(price AS TEXT)),recommended_mode,
    deterministic_mode,width_scale,cap_scale,evaluation_json,
    COALESCE(NULLIF(return_15m_text,''),CAST(return_15m AS TEXT)),
    COALESCE(NULLIF(return_1h_text,''),CAST(return_1h AS TEXT)),
    COALESCE(NULLIF(return_4h_text,''),CAST(return_4h AS TEXT))
"""
_DUE_WHERE = """
    symbol=? AND (
        (return_15m IS NULL AND created_at<=?) OR
        (return_1h IS NULL AND created_at<=?) OR
        (return_4h IS NULL AND created_at<=?)
    )
"""


def select_due_settlements(
    connection: sqlite3.Connection,
    symbol: str,
    now: int,
    *,
    batch_size: int = SETTLEMENT_BATCH_SIZE,
) -> list[tuple[Any, ...]]:
    """Select bounded oldest and newest due decisions without starvation."""
    if batch_size < 2:
        raise ValueError("settlement batch size must be at least two")
    params = (
        symbol.upper(),
        now - _HORIZONS_SEC[0],
        now - _HORIZONS_SEC[1],
        now - _HORIZONS_SEC[2],
    )
    oldest_limit = batch_size // 2
    newest_limit = batch_size - oldest_limit
    query = f"SELECT {_SELECT_COLUMNS} FROM ai_decisions WHERE {_DUE_WHERE}"
    oldest = connection.execute(
        f"{query} ORDER BY created_at ASC, decision_id ASC LIMIT ?",
        (*params, oldest_limit),
    ).fetchall()
    newest = connection.execute(
        f"{query} ORDER BY created_at DESC, decision_id DESC LIMIT ?",
        (*params, newest_limit),
    ).fetchall()
    # A dictionary removes overlap when the due queue is smaller than the batch.
    selected = {str(row[0]): tuple(row) for row in (*oldest, *newest)}
    return sorted(selected.values(), key=lambda row: (int(row[1]), str(row[0])))


def exact_horizon_open(
    get_klines: Callable[..., Sequence[Sequence[Any]]],
    symbol: str,
    target_ms: int,
) -> object:
    """Return the open price only for the minute containing the horizon."""
    minute_ms = int(target_ms) - int(target_ms) % 60_000
    candles = get_klines(symbol, "1m", limit=1, startTime=minute_ms)
    if not candles:
        raise ValueError("missing horizon candle")
    candle = candles[0]
    if len(candle) < 2:
        raise ValueError("invalid horizon candle")
    try:
        candle_open_ms = int(candle[0])
    except (TypeError, ValueError) as exc:
        raise ValueError("invalid horizon candle timestamp") from exc
    # Binance can return the first later candle when the requested minute is absent.
    if candle_open_ms != minute_ms:
        raise ValueError("horizon candle does not match the requested minute")
    return candle[1]
