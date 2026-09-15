# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: obtain bounded order-specific settlement before sizing protection.
"""Read-only exchange evidence collection; journal owns persistence."""

from decimal import Decimal, localcontext

from ladder_dragon.execution.journal.buy_inventory import SETTLEMENT_KEY, acquired_quantity, verified_settlement


def settle_inventory(journal, parent_id, order, *, read_fills):
    """Require complete terminal BUY evidence without using account-wide balances."""
    if journal is None or not parent_id:
        raise RuntimeError("BUY settlement requires a durable parent")
    parent = journal.get(parent_id)
    if parent is None:
        raise RuntimeError("BUY settlement parent is unavailable")
    if SETTLEMENT_KEY in (parent.metadata or {}):
        evidence = parent.metadata[SETTLEMENT_KEY]
        acquired_quantity(parent)
        return verified_settlement(parent, {"order": order, "fills": evidence["fills"]}).net_quantity
    rows, cursor = [], 0
    for _ in range(10):
        page = read_fills(parent.symbol, parent.exchange_order_id, cursor)
        if not isinstance(page, list) or len(page) > 1000:
            raise RuntimeError("BUY settlement trade page is malformed")
        ids = [row.get("id") if isinstance(row, dict) else None for row in page]
        if (any(type(value) is not int or value < cursor for value in ids)
                or ids != sorted(set(ids))):
            raise RuntimeError("BUY settlement trade cursor is invalid")
        rows.extend(page)
        if len(page) < 1000:
            break
        cursor = ids[-1] + 1
    # Exact gross and quote sums prove completeness even at the page bound.
    settled = journal.record_buy_settlement(parent_id, order, rows)
    return acquired_quantity(settled)


def remaining_inventory(journal, parent_client_id, acquired):
    """Subtract durable partial exits with the same exact arithmetic boundary."""
    exited_quantity = Decimal("0")
    if journal is not None and parent_client_id:
        partial_exit_reader = getattr(
            journal,
            "partial_protection_exit_quantity",
            None,
        )
        if callable(partial_exit_reader):
            with localcontext() as context:
                context.prec = 512
                exited_quantity = partial_exit_reader(parent_client_id)
    return residual_inventory(acquired, exited_quantity)


def residual_inventory(acquired, exited):
    """Do not round away a fee or an over-exit through ambient precision."""
    if (not isinstance(acquired, Decimal) or not acquired.is_finite() or acquired <= 0
            or not isinstance(exited, Decimal) or not exited.is_finite()
            or exited < 0 or exited > acquired):
        raise RuntimeError("confirmed protection exits exceed net BUY inventory")
    with localcontext() as context:
        context.prec = 512
        return acquired - exited
