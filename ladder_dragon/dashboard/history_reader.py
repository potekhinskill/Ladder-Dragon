# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: own the filled-order presentation query and connection lifecycle.
"""Filled-order presentation queries; no exchange access or mutations."""

import sqlite3
from typing import Dict, List, Optional
from ladder_dragon.dashboard.history_dependencies import HistoryRouteState


def select_filled_orders(
    state: HistoryRouteState,
    hours: int,
    syms: Optional[List[str]],
    limit: int,
    offset: int = 0,
) -> List[Dict]:
    """Handle select filled orders."""
    hours = max(1, min(int(hours), 168))
    limit = max(1, min(int(limit), 500))
    offset = max(0, min(int(offset), 50000))
    cutoff_s = int(state.time.time()) - hours * 3600

    con, _ = state._open_db()

    try:
        sym_filter = ""
        args: List = []
        if syms:
            qs = ",".join("?" for _ in syms)
            sym_filter = f" AND symbol IN ({qs})"
            args.extend(syms)

        sql = f"""
        SELECT
          symbol, side, price_text AS price, gross_qty_text AS qty,
          COALESCE(commission_quote_text, '0') AS fee_quote,
          CASE WHEN ts>1000000000000 THEN CAST(ts/1000 AS INTEGER) ELSE CAST(ts AS INTEGER) END AS ts_s
        FROM trades_exact
        WHERE 1=1 {sym_filter}
          AND (CASE WHEN ts>1000000000000 THEN CAST(ts/1000 AS INTEGER) ELSE CAST(ts AS INTEGER) END) >= ?
        ORDER BY ts_s DESC
        LIMIT ? OFFSET ?
        """
        args.extend([cutoff_s, limit, offset])
        rows = con.execute(sql, args).fetchall()

        fee_pct = state._fee_pct_default()
        out: List[Dict] = []
        for r in rows:
            price = float(r["price"])
            qty = float(r["qty"])
            fee_q = float(r["fee_quote"])
            # If fee_quote is zero (BNB), estimate the fee in USDT by percentage.
            fee_usdt = fee_q if fee_q > 0 else (price * qty * fee_pct)
            out.append({
                "time": int(r["ts_s"]) * 1000,
                "symbol": r["symbol"],
                "side": str(r["side"]).upper(),
                "price": round(price, 8),
                "qty": round(qty, 8),
                "quoteQty": round(price * qty, 8),
                "commission": round(fee_usdt, 8),
                "commissionAsset": "USDT"
            })
        return out
    finally:
        try:
            if con: con.close()
        except sqlite3.Error:
            pass
