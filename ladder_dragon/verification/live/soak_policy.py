# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: own a Testnet soak boundary without changing monitoring behavior.
"""Testnet soak_policy implementation."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from ladder_dragon.execution.exchange_math import decimal


@dataclass(frozen=True)
class SoakSample:
    ts: float
    account_qty: Decimal
    ledger_qty: Decimal
    market_price: Decimal
    holdings_exposure: Decimal
    total_exposure: Decimal
    open_buy_count: int
    open_sell_count: int
    protected_sell_legs: int
    protected_sell_qty: Decimal
    protection_complete: bool
    halted: bool


def evaluate_sample(
    sample: SoakSample,
    *,
    max_open_buys: int,
    max_exposure: Decimal,
    min_notional: Decimal,
    quantity_tolerance: Decimal,
) -> tuple[list[str], bool, bool]:
    violations: list[str] = []
    if sample.open_buy_count > max_open_buys:
        violations.append(
            f"open BUY count {sample.open_buy_count} exceeds {max_open_buys}"
        )
    if sample.total_exposure > max_exposure:
        violations.append(
            f"exposure {sample.total_exposure} exceeds {max_exposure} USDT"
        )
    if sample.halted:
        violations.append("persistent Testnet circuit halt exists")
    unprotected = (
        sample.holdings_exposure >= min_notional
        and (
            not sample.protection_complete
            or sample.protected_sell_qty + quantity_tolerance < sample.account_qty
        )
    )
    mismatch = abs(sample.account_qty - sample.ledger_qty) > quantity_tolerance
    return violations, unprotected, mismatch


def oco_protection_coverage(
    open_sells: list[dict[str, Any]],
    *,
    quantity_tolerance: Decimal,
) -> tuple[int, Decimal, bool]:
    """Return OCO leg count, protected quantity, and structural completeness."""
    groups: dict[int, list[dict[str, Any]]] = {}
    protected_legs = 0
    for row in open_sells:
        order_list_id = int(row.get("orderListId", -1))
        if order_list_id < 0:
            continue
        protected_legs += 1
        groups.setdefault(order_list_id, []).append(row)

    covered = Decimal("0")
    complete = bool(groups)
    for legs in groups.values():
        if len(legs) != 2:
            complete = False
            continue
        remaining = [
            decimal(row.get("origQty")) - decimal(row.get("executedQty"))
            for row in legs
        ]
        if any(qty <= 0 for qty in remaining):
            complete = False
            continue
        if abs(remaining[0] - remaining[1]) > quantity_tolerance:
            complete = False
            continue
        # Two OCO legs protect one shared quantity. Never add both legs.
        covered += min(remaining)
    return protected_legs, covered, complete


def _advance_grace(unprotected, mismatch, unprotected_since, mismatch_since, now, immediate, args):
    if unprotected:
        unprotected_since = unprotected_since if unprotected_since is not None else now
    else:
        unprotected_since = None
    if mismatch:
        mismatch_since = mismatch_since if mismatch_since is not None else now
    else:
        mismatch_since = None
    reasons = list(immediate)
    if unprotected_since is not None and now - unprotected_since > args.grace_sec:
        reasons.append("tradable position remained without two verified OCO legs")
    if mismatch_since is not None and now - mismatch_since > args.grace_sec:
        reasons.append("exchange account and SQLite inventory remained inconsistent")
    return unprotected_since, mismatch_since, reasons
