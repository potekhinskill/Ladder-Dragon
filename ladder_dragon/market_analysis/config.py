# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: validate market analysis configuration independently from execution.
"""Configuration for the observation-only scenario service."""

from __future__ import annotations

import re
from typing import Sequence

from ladder_dragon.strategy.scenario_analysis import SUPPORTED_TIMEFRAMES


def _unique_csv(value: str, *, name: str) -> tuple[str, ...]:
    items = tuple(item.strip() for item in value.split(",") if item.strip())
    if len(items) != len(set(items)):
        raise ValueError(f"{name} contains duplicates")
    return items


def resolve_analysis_symbols(configured: str) -> tuple[str, ...]:
    """Validate the dedicated observation scope."""
    symbols = tuple(item.upper() for item in _unique_csv(
        configured, name="BOT_MARKET_ANALYSIS_SYMBOLS"
    ))
    if not symbols:
        raise ValueError("BOT_MARKET_ANALYSIS_SYMBOLS must not be empty")
    for symbol in symbols:
        if re.fullmatch(r"[A-Z0-9]{5,20}", symbol) is None:
            raise ValueError(f"invalid market analysis symbol: {symbol!r}")
    return symbols


def resolve_analysis_timeframes(configured: str) -> tuple[str, ...]:
    """Validate closed-candle intervals from one hour through one month."""
    values = _unique_csv(configured, name="BOT_MARKET_ANALYSIS_TIMEFRAMES")
    if not values:
        raise ValueError("BOT_MARKET_ANALYSIS_TIMEFRAMES must not be empty")
    unsupported = [value for value in values if value not in SUPPORTED_TIMEFRAMES]
    if unsupported:
        raise ValueError(f"unsupported market analysis timeframe: {unsupported[0]}")
    return values


def describe_symbol_scopes(
    execution_symbols: Sequence[str], analysis_symbols: Sequence[str]
) -> dict[str, object]:
    """Describe configured execution and observation symbols."""
    execution = tuple(str(item).upper() for item in execution_symbols)
    analysis = tuple(str(item).upper() for item in analysis_symbols)
    return {
        "execution_symbols": list(execution),
        "analysis_symbols": list(analysis),
        "shadow_only_symbols": [item for item in analysis if item not in execution],
    }
