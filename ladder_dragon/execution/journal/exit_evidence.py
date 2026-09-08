# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: require exact residual exit evidence inside the journal transaction.
"""Every exact closure must prove quantity and identity at the final writer."""

from decimal import Decimal
from ladder_dragon.execution.exchange_evidence import checked_order
from ladder_dragon.execution.protection_quantity import quantity, require_order_id


def require_exact_exit(con, parent, protection, exit_order, exit_order_id, venue):
    if (parent.side != "BUY" or protection.side != "SELL"
            or parent.symbol != protection.symbol
            or protection.parent_client_order_id != parent.client_order_id
            or type(protection.exchange_order_list_id) is not int
            or protection.exchange_order_list_id < 0):
        raise RuntimeError("exact exit parent identity is invalid")
    checked_order(exit_order, protection.symbol, order_id=require_order_id(exit_order_id),
                  list_id=protection.exchange_order_list_id)
    leg = con.execute(
        "SELECT client_order_id, leg_type FROM order_intent_legs "
        "WHERE venue=? AND symbol=? AND order_id=? AND protection_client_order_id=?",
        (venue, protection.symbol, exit_order_id, protection.client_order_id),
    ).fetchone()
    if (leg is None or exit_order.get("clientOrderId") != leg["client_order_id"]
            or exit_order.get("type") != leg["leg_type"]
            or exit_order.get("side") != "SELL" or exit_order.get("status") != "FILLED"):
        raise RuntimeError("exact exit lacks a matched FILLED protection leg")
    rows = con.execute(
        "SELECT executed_qty FROM order_partial_protection_exits "
        "WHERE venue=? AND parent_client_order_id=?",
        (venue, parent.client_order_id),
    ).fetchall()
    prior = sum((quantity(row["executed_qty"]) for row in rows), Decimal("0"))
    residual = quantity(parent.executed_qty) - prior
    intended = quantity(protection.quantity)
    if (residual <= 0 or intended != residual
            or quantity(exit_order.get("origQty")) != residual
            or quantity(exit_order.get("executedQty")) != residual):
        raise RuntimeError("exact exit does not cover the complete residual BUY")
