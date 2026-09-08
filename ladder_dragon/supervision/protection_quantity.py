# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: prove protection coverage from exact journal and exchange quantities.
"""Reject incomplete quantity evidence before protection state changes."""

from decimal import Decimal, InvalidOperation


def quantity(value):
    """Read an exact nonnegative quantity without provider text in errors."""
    if not isinstance(value, str) or not value or len(value) > 128:
        raise RuntimeError("protection quantity evidence is invalid")
    try:
        result = Decimal(value)
    except InvalidOperation:
        raise RuntimeError("protection quantity evidence is invalid") from None
    if not result.is_finite() or result < 0:
        raise RuntimeError("protection quantity evidence is invalid")
    return result


def verify_quantities(journal, parent_id, protection, legs, *, closing=False):
    """Do not infer dust, fees, or complete inventory exit from order status."""
    parent = journal.get(parent_id)
    if (parent is None or parent.side != "BUY" or parent.symbol != protection.symbol
            or protection.parent_client_order_id != parent_id):
        raise RuntimeError("protection parent identity differs from journal")
    acquired = quantity(parent.executed_qty)
    intended = quantity(protection.quantity)
    if acquired <= 0 or intended <= 0 or intended > acquired:
        raise RuntimeError("protection quantity exceeds acquired inventory or is zero")
    executed = Decimal("0")
    for leg in legs:
        original = quantity(leg.get("origQty"))
        filled = quantity(leg.get("executedQty"))
        status = leg.get("status")
        if status not in {"NEW", "PARTIALLY_FILLED", "FILLED", "CANCELED", "EXPIRED",
                          "EXPIRED_IN_MATCH", "REJECTED"}:
            raise RuntimeError("protection quantity status is invalid")
        if original != intended or filled > original:
            raise RuntimeError("protection quantity differs from durable intent")
        if ((status == "FILLED" and filled != original)
                or (status == "NEW" and filled != 0)
                or (status == "PARTIALLY_FILLED" and not 0 < filled < original)):
            raise RuntimeError("protection quantity contradicts exchange status")
        executed += filled
    if executed > intended:
        raise RuntimeError("protection executions exceed durable intent")
    # Terminal partial retries already have a durable exit row. They must not
    # subtract that row twice or claim complete coverage before replacement.
    active = all(leg.get("status") in {"NEW", "PARTIALLY_FILLED"} for leg in legs)
    if active or closing:
        prior = journal.partial_protection_exit_quantity(parent_id)
        if not isinstance(prior, Decimal) or not prior.is_finite() or prior < 0:
            raise RuntimeError("prior protection exit quantity is invalid")
        if intended != acquired - prior:
            raise RuntimeError("residual protection quantity is not completely covered")
        if closing and executed != intended:
            raise RuntimeError("residual protection exit is incomplete")


def require_order_id(value):
    """Reject Boolean, fractional, and missing exchange order identities."""
    if type(value) is not int or value < 0:
        raise RuntimeError("protection order ID is invalid")
    return value
