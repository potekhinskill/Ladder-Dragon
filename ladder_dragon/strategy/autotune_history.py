# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: own a VWAP autotune boundary with unchanged tuning behavior.
"""VWAP autotune_history implementation."""

from __future__ import annotations

import sqlite3
import time
from decimal import Decimal
from typing import Tuple

from ladder_dragon.execution.trade_accounting import TradeExecution, replay_average_cost


def get_stats(symbol: str,
              conn: sqlite3.Connection,
              hours: int) -> Tuple[Decimal, int]:
    """Calculate window PnL using cost basis from the complete history.

    Replaying only the last N hours makes a position opened earlier look like
    a zero-cost position and can invert the tuning decision.
    """
    cutoff_ms = int((time.time() - hours * 3600) * 1000)
    rows = conn.execute(
        """
        SELECT ts, side,
               price_text, gross_qty_text, net_qty_text,
               commission_asset, commission_amount_text,
               commission_quote_text, commission_value_status
        FROM trades_exact WHERE symbol=? AND ts<=? ORDER BY ts, id
        """,
        (symbol.upper(), int(time.time() * 1000)),
    ).fetchall()
    executions: list[TradeExecution] = []
    timestamps: list[int] = []
    for row in rows:
        try:
            executions.append(TradeExecution.create(
                symbol=symbol, side=row[1], price=row[2], gross_qty=row[3],
                net_qty=row[4], commission_asset=row[5] or "",
                commission_amount=row[6] or 0, commission_quote=row[7],
                commission_value_status=row[8] or "legacy",
            ))
            timestamps.append(int(row[0]))
        except (ArithmeticError, TypeError, ValueError):
            continue
    result = replay_average_cost(executions, allow_unpriced=False)
    sell_results = iter(result.sell_results)
    window_pnl = Decimal("0")
    recent_count = 0
    for execution, timestamp in zip(executions, timestamps):
        if timestamp >= cutoff_ms:
            recent_count += 1
        if execution.side == "SELL":
            pnl = next(sell_results)
            if timestamp >= cutoff_ms:
                window_pnl += pnl
    return window_pnl, recent_count
