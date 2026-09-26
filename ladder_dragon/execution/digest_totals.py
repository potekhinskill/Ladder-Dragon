# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: own one daily digest boundary without changing accounting behavior.
"""Daily digest totals ownership."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation

ZERO = Decimal("0")


@dataclass(frozen=True)
class PeriodSummary:
    """Exact accounting totals for one half-open reporting window."""

    label: str
    start: datetime
    end: datetime
    realized_net_pnl: Decimal
    cash_flow: Decimal
    fees_quote: Decimal
    fills: int
    buys: int
    sells: int
    fifo_cost: Decimal
    prior_period_cost: Decimal
    legacy_source: bool


def _as_decimal(value: object, *, field: str) -> Decimal:
    try:
        result = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValueError(f"{field} is not an exact decimal") from exc
    if not result.is_finite():
        raise ValueError(f"{field} must be finite")
    return result


def _aggregate(periods, values, excluded):
    summaries = []
    for label, start, end in periods:
        included = [
            item
            for symbol, item in values[label].items()
            if symbol not in excluded
        ]
        summaries.append(
            PeriodSummary(
                label=label,
                start=start,
                end=end,
                realized_net_pnl=_as_decimal(
                    sum(
                        (item["realized"] for item in included),
                        ZERO,
                    ),
                    field="realized PnL",
                ),
                cash_flow=_as_decimal(
                    sum((item["cash"] for item in included), ZERO),
                    field="cash flow",
                ),
                fees_quote=_as_decimal(
                    sum((item["fees"] for item in included), ZERO),
                    field="fees",
                ),
                fills=sum(int(item["fills"]) for item in included),
                buys=sum(int(item["buys"]) for item in included),
                sells=sum(int(item["sells"]) for item in included),
                fifo_cost=sum((item["fifo_cost"] for item in included), ZERO),
                prior_period_cost=sum((item["prior_cost"] for item in included), ZERO),
                legacy_source=any(item["legacy"] for item in included),
            )
        )
    exclusions = tuple(
        f"{symbol} — {excluded[symbol]}"
        for symbol in sorted(excluded)
    )
    return tuple(summaries), exclusions
