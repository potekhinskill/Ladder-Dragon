# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: reject incomplete open-order evidence before risk valuation.
"""Validate complete exchange collections without inventing empty state."""

from decimal import Decimal, InvalidOperation
import re


def checked_open_orders(payload):
    """Require identities, active states, and exact remaining commitments."""
    message = "invalid open-orders snapshot"
    if not isinstance(payload, list):
        raise ValueError(message)
    seen = set()
    result = []
    for row in payload:
        if not isinstance(row, dict):
            raise ValueError(message)
        symbol = row.get("symbol")
        order_id = row.get("orderId")
        list_id = row.get("orderListId")
        if (not isinstance(symbol, str) or not re.fullmatch(r"[A-Z0-9]{5,30}", symbol)
                or type(order_id) is not int or order_id < 0
                or type(list_id) is not int or list_id < -1
                or not isinstance(row.get("clientOrderId"), str) or not row["clientOrderId"]
                or row.get("side") not in {"BUY", "SELL"}
                or row.get("status") not in {"NEW", "PARTIALLY_FILLED"}
                or row.get("type") not in {"LIMIT", "LIMIT_MAKER", "MARKET", "STOP_LOSS",
                                            "STOP_LOSS_LIMIT", "TAKE_PROFIT", "TAKE_PROFIT_LIMIT"}):
            raise ValueError(message)
        identity = (symbol, order_id)
        if identity in seen:
            raise ValueError(message)
        seen.add(identity)
        values = []
        for field in ("price", "origQty", "executedQty"):
            raw = row.get(field)
            if not isinstance(raw, str) or not raw or len(raw) > 128:
                raise ValueError(message)
            try:
                value = Decimal(raw)
            except InvalidOperation:
                raise ValueError(message) from None
            if not value.is_finite() or value < 0:
                raise ValueError(message)
            values.append(value)
        price, original, executed = values
        if (original <= 0 or executed >= original
                or (row["status"] == "NEW" and executed != 0)
                or (row["status"] == "PARTIALLY_FILLED" and executed <= 0)
                or (row["side"] == "BUY" and price <= 0)):
            # An unpriced open BUY has no proved upper commitment here.
            raise ValueError(message)
        result.append(dict(row))
    return result
