# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: isolate read-only multi-symbol SHADOW collection from execution scope.
"""Validate and schedule observation-only prediction symbols."""

from __future__ import annotations

import re
from typing import Callable, MutableMapping, Sequence


def resolve_prediction_shadow_symbols(
    execution_symbols: Sequence[str], configured: str
) -> tuple[list[str], list[str]]:
    """Return configured symbols and the observation-only subset."""
    if not configured.strip():
        requested = []
    else:
        requested = [
            item.strip().upper()
            for item in configured.split(",")
            if item.strip()
        ]
    if len(requested) != len(set(requested)):
        raise ValueError("BOT_PREDICTION_SHADOW_SYMBOLS contains duplicates")
    for symbol in requested:
        if re.fullmatch(r"[A-Z0-9]{5,20}", symbol) is None:
            raise ValueError(
                "invalid BOT_PREDICTION_SHADOW_SYMBOLS symbol: "
                f"{symbol!r}"
            )
    execution = set(execution_symbols)
    symbols = list(dict.fromkeys([*execution_symbols, *requested]))
    return symbols, [symbol for symbol in symbols if symbol not in execution]


def collect_read_only_shadow(
    symbols: Sequence[str],
    args: object,
    *,
    enabled: bool,
    now_monotonic: float,
    interval_sec: int,
    last_attempts: MutableMapping[str, float],
    run_symbol: Callable[..., None],
    logger: Callable[[str], None],
    operation_errors: tuple[type[BaseException], ...],
) -> None:
    """Rate-limit SHADOW plans and keep every call outside execution."""
    if not enabled:
        return
    for symbol in symbols:
        last_attempt = last_attempts.get(symbol)
        if last_attempt is not None and now_monotonic - last_attempt < interval_sec:
            continue
        last_attempts[symbol] = now_monotonic
        try:
            run_symbol(symbol, args, execution_allowed=False)
        except operation_errors as exc:
            logger(
                f"[BLOCKED-SHADOW] {symbol} unavailable="
                f"{type(exc).__name__}"
            )
