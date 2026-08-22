# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: resolve pre-POST timestamps for direct orders and verified OCO legs.
"""Read exact journal timestamps without adding OCO pseudo-intents."""

from __future__ import annotations

from decimal import Decimal
import sqlite3


def created_at_ms_for_order(
    connection: sqlite3.Connection,
    *,
    venue: str,
    exchange_order_id: int,
) -> int | None:
    """Resolve a direct intent or its verified parent protection intent."""
    row = connection.execute(
        "SELECT COALESCE((SELECT created_at FROM order_intents WHERE "
        "exchange_order_id=? ORDER BY created_at DESC LIMIT 1), "
        "(SELECT intents.created_at FROM order_intent_legs AS legs "
        "JOIN order_intents AS intents ON intents.venue=legs.venue AND "
        "intents.client_order_id=legs.protection_client_order_id "
        "WHERE legs.venue=? AND "
        "legs.order_id=? ORDER BY intents.created_at DESC LIMIT 1)) "
        "AS created_at",
        (int(exchange_order_id), venue, int(exchange_order_id)),
    ).fetchone()
    try:
        created_at = Decimal(str(row["created_at"]))
    except (ArithmeticError, TypeError, ValueError):
        return None
    if not created_at.is_finite() or created_at <= 0:
        return None
    return int(created_at * Decimal("1000"))


__all__ = ["created_at_ms_for_order"]
