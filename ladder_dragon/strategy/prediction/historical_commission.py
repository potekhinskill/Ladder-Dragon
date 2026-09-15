# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: model explicit fee-asset scenarios without claiming actual exchange fees.
"""Scenario assumptions are not account attestations or promotion evidence."""

from decimal import Decimal, localcontext
from functools import wraps
from collections.abc import Mapping

from ladder_dragon.execution.trade_accounting import TradeExecution, symbol_assets


def require_non_scenario_report(report):
    """A renamed status cannot turn declared fee assumptions into evidence."""
    policy = report.get("policy")
    if isinstance(policy, Mapping) and "commission_asset_scenario" in policy:
        raise ValueError("commission scenarios cannot qualify as selection evidence")
    episodes = report.get("episodes")
    if isinstance(episodes, Mapping):
        for rows in episodes.values():
            if isinstance(rows, list) and any(
                isinstance(row, Mapping) and (
                    "commission_asset_scenario" in row or "commission_asset_evidence" in row
                ) for row in rows
            ):
                raise ValueError("commission scenarios cannot qualify as selection evidence")


def exact_arithmetic(function):
    @wraps(function)
    def wrapped(*args, **kwargs):
        with localcontext() as context:
            context.prec = 512
            return function(*args, **kwargs)
    return wrapped


@exact_arithmetic
def buy_inventory(symbol, price, quantity, rate, scenario):
    """Return net base quantity and the base-paid commission's quote value."""
    if scenario not in {"QUOTE", "BASE_BUY_QUOTE_SELL"}:
        raise ValueError("historical commission asset is unspecified")
    if not rate.is_finite() or not Decimal("0") <= rate < 1:
        raise ValueError("historical commission rate is invalid")
    base, quote = symbol_assets(symbol)
    base_paid = scenario == "BASE_BUY_QUOTE_SELL"
    commission = quantity * rate if base_paid else price * quantity * rate
    execution = TradeExecution.create(
        symbol=symbol, side="BUY", price=price, gross_qty=quantity,
        commission_asset=base if base_paid else quote, commission_amount=commission,
    )
    return execution.net_qty, commission * price if base_paid else Decimal("0")
