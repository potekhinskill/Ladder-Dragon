# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: enforce exact BUY sizing limits outside the worker event loop.

"""Pure BUY policy used by the execution worker."""

import os
from decimal import Decimal
from typing import Mapping


def cap_decimal(name: str, raw: object) -> Decimal:
    """Parse a non-negative finite CAP or fail closed."""
    try:
        value = Decimal(str(raw))
    except (ArithmeticError, TypeError, ValueError) as exc:
        raise ValueError(f"{name} is not a valid decimal CAP") from exc
    if not value.is_finite() or value < 0:
        raise ValueError(f"{name} must be finite and non-negative")
    return value


def hard_buy_cap(
    symbol: str,
    proposed_cap: object,
    *,
    environment: Mapping[str, str] | None = None,
) -> tuple[Decimal, dict[str, Decimal]]:
    """Clamp strategy CAP by operator, Risk Manager and symbol budgets."""
    source = os.environ if environment is None else environment
    limits = {"strategy": cap_decimal("strategy CAP", proposed_cap)}
    variables = {
        "operator": "BOT_OPERATOR_CAP_PER_ORDER_USDT",
        "risk": "BOT_CAP_PER_ORDER",
        "symbol": f"RISK_SYMBOL_CAP_{symbol.upper()}",
    }
    for label, variable in variables.items():
        raw = source.get(variable)
        if raw is None or not raw.strip():
            continue
        limits[label] = cap_decimal(variable, raw)
    return min(limits.values()), limits
