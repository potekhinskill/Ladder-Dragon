# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: own one daily digest boundary without changing accounting behavior.
"""Daily digest fifo ownership."""

from __future__ import annotations

from datetime import datetime
import sqlite3

from ladder_dragon.execution.pnl_window_command import _execution, detect_ts_div, iter_trades_until
from ladder_dragon.execution.trade_accounting import UnpricedCommission
from ladder_dragon.execution.digest_totals import ZERO, PeriodSummary, _aggregate


def _summaries(
    connection: sqlite3.Connection,
    periods: tuple[tuple[str, datetime, datetime], ...],
) -> tuple[tuple[PeriodSummary, ...], tuple[str, ...]]:
    """Replay symbols independently and exclude incomplete FIFO histories."""
    connection.row_factory = sqlite3.Row
    ts_div = detect_ts_div(connection)
    end_sec = int(max(end for _, _, end in periods).timestamp())
    rows = list(iter_trades_until(connection, end_sec * ts_div - 1, None))
    lots: dict[str, list[list]] = {}
    values = {
        label: {}
        for label, _, _ in periods
    }
    excluded: dict[str, str] = {}

    for row in rows:
        symbol = str(row["symbol"] or "").strip().upper()
        if not symbol or symbol in excluded:
            continue
        try:
            trade = _execution(row)
            fee = trade.valued_commission()
        except (ArithmeticError, TypeError, ValueError, UnpricedCommission):
            excluded[symbol] = "unpriced or invalid exact trade data"
            continue
        if not trade.symbol.endswith("USDT"):
            excluded[symbol] = "non-USDT quote asset"
            continue
        timestamp = datetime.fromtimestamp(int(row["ts"]) / ts_div, periods[0][1].tzinfo)
        matching = [
            label for label, start, end in periods if start <= timestamp < end
        ]
        if matching:
            for label in matching:
                item = values[label].setdefault(
                    symbol,
                    {
                        "realized": ZERO,
                        "cash": ZERO,
                        "fees": ZERO,
                        "fills": 0,
                        "buys": 0,
                        "sells": 0,
                        "fifo_cost": ZERO,
                        "prior_cost": ZERO,
                        "legacy": False,
                    },
                )
                item["fills"] += 1
                item["fees"] += fee
                item["legacy"] |= trade.commission_value_status == "legacy"
                if trade.side == "BUY":
                    item["buys"] += 1
                    item["cash"] -= trade.buy_cost_quote()
                else:
                    item["sells"] += 1
                    item["cash"] += trade.sell_proceeds_quote()

        symbol_lots = lots.setdefault(trade.symbol, [])
        if trade.side == "BUY":
            symbol_lots.append([
                trade.net_qty, trade.buy_cost_quote(), timestamp,
                trade.commission_value_status == "legacy",
            ])
            continue

        remaining = trade.net_qty
        proceeds = trade.sell_proceeds_quote()
        matched_cost = ZERO
        matched_qty = ZERO
        while remaining > ZERO and symbol_lots:
            lot_qty, lot_cost, acquired_at, legacy = symbol_lots[0]
            take = min(remaining, lot_qty)
            cost_take = lot_cost * take / lot_qty
            matched_cost += cost_take
            for label, start, end in periods:
                if label in matching:
                    item = values[label][symbol]
                    item["fifo_cost"] += cost_take
                    if acquired_at < start:
                        item["prior_cost"] += cost_take
                    item["legacy"] |= legacy
            matched_qty += take
            remaining -= take
            lot_qty -= take
            lot_cost -= cost_take
            if lot_qty <= ZERO:
                symbol_lots.pop(0)
            else:
                symbol_lots[0] = [lot_qty, lot_cost, acquired_at, legacy]
        if remaining > ZERO:
            excluded[symbol] = "incomplete FIFO history"
            continue
        realized = proceeds * matched_qty / trade.net_qty - matched_cost
        for label in matching:
            values[label][symbol]["realized"] += realized

    return _aggregate(periods, values, excluded)
