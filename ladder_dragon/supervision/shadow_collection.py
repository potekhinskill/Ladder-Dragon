# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: isolate read-only multi-symbol SHADOW collection from execution scope.
"""Validate and schedule observation-only prediction symbols."""

from __future__ import annotations

import re
from typing import Callable, MutableMapping, Sequence


def execution_control_scope(
    symbol: str, execution_symbols: object
) -> tuple[bool, str]:
    """Classify execution-only controls for one prediction symbol."""
    if isinstance(execution_symbols, str):
        execution_symbols = tuple(
            item.strip().upper()
            for item in execution_symbols.split(",")
            if item.strip()
        )
    applicable = (
        isinstance(execution_symbols, (list, tuple))
        and symbol.upper() in execution_symbols
    )
    status = "active" if applicable else "not_applicable_shadow_only"
    return applicable, status


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
    priority_symbols: Sequence[str] = (),
    maximum_nonpriority_per_call: int | None = None,
) -> None:
    """Rate-limit SHADOW plans while preserving priority evidence cadence."""
    if not enabled:
        return
    if (
        maximum_nonpriority_per_call is not None
        and maximum_nonpriority_per_call < 0
    ):
        raise ValueError("maximum non-priority SHADOW symbols is invalid")
    priority = {item.upper() for item in priority_symbols}
    due_priority = []
    due_nonpriority = []
    for symbol in symbols:
        last_attempt = last_attempts.get(symbol)
        if last_attempt is not None and now_monotonic - last_attempt < interval_sec:
            continue
        if symbol.upper() in priority:
            due_priority.append(symbol)
        else:
            due_nonpriority.append(symbol)
    # Rotate observation-only symbols by oldest attempt. Slow external reads
    # must not delay the next promotion-symbol evidence interval indefinitely.
    due_nonpriority.sort(
        key=lambda item: (last_attempts.get(item, float("-inf")), item)
    )
    if maximum_nonpriority_per_call is not None:
        due_nonpriority = due_nonpriority[:maximum_nonpriority_per_call]
    for symbol in [*due_priority, *due_nonpriority]:
        last_attempts[symbol] = now_monotonic
        try:
            run_symbol(symbol, args, execution_allowed=False)
        except operation_errors as exc:
            logger(
                f"[BLOCKED-SHADOW] {symbol} unavailable="
                f"{type(exc).__name__}"
            )
