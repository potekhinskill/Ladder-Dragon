# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: identify evidence eligible for real-only RAG retrieval.

"""RAG evidence policy."""

from collections.abc import Mapping
from decimal import Decimal, InvalidOperation


def verified_real_closure(row: Mapping[str, object]) -> bool:
    """Require a real closure, SELL fill and exact net PnL."""
    try:
        sell_qty = Decimal(str(row.get("sell_qty", "0")))
        net_pnl = Decimal(str(row["net_pnl_quote"]))
    except (KeyError, InvalidOperation, TypeError, ValueError):
        return False
    return (
        str(row.get("source", "")).upper() == "REAL"
        and sell_qty.is_finite()
        and sell_qty > 0
        and net_pnl.is_finite()
    )
