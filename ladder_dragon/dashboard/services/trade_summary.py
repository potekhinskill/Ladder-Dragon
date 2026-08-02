# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: calculate exact dashboard trade summaries from canonical accounting.

"""Exact trade-summary calculations for the read-only dashboard."""

from collections.abc import Mapping, Sequence
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Any

from ladder_dragon.execution.trade_accounting import (
    InventoryShortfall,
    TradeExecution,
    UnpricedCommission,
    replay_fifo,
)


ZERO = Decimal("0")


def _value(row: Mapping[str, Any], key: str, default: object = None) -> object:
    try:
        return row[key]
    except (IndexError, KeyError):
        return default


def _decimal(value: object, *, field: str) -> Decimal:
    try:
        result = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValueError(f"{field} is not an exact decimal") from exc
    if not result.is_finite():
        raise ValueError(f"{field} must be finite")
    return result


def _timestamp_seconds(value: object) -> int:
    timestamp = int(value)
    return timestamp // 1000 if timestamp > 10_000_000_000 else timestamp


def _rounded_money(value: Decimal) -> float:
    return float(value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def fifo_realized_pnl(
    rows: Sequence[Mapping[str, Any]],
    cutoff_s: int,
    fee_pct: float,
    *,
    end_s: int | None = None,
) -> dict[str, object]:
    """Return one exact FIFO summary while replaying all earlier lot history."""
    fallback_fee_rate = _decimal(fee_pct, field="fallback fee rate")
    if fallback_fee_rate < ZERO:
        raise ValueError("fallback fee rate must be non-negative")
    executions: dict[str, list[tuple[int, TradeExecution]]] = {}
    incomplete_symbols: set[str] = set()
    window_sell_symbols: set[str] = set()
    total_trades = 0
    buy_volume = ZERO
    sell_volume = ZERO
    fees = ZERO

    for row in rows:
        symbol = str(_value(row, "symbol", "") or "").strip().upper()
        side = str(_value(row, "side", "") or "").strip().upper()
        if not symbol or side not in {"BUY", "SELL"}:
            continue
        try:
            timestamp = _timestamp_seconds(_value(row, "ts_s", 0))
        except (ArithmeticError, TypeError, ValueError):
            incomplete_symbols.add(symbol)
            continue
        if end_s is not None and timestamp > end_s:
            continue
        in_window = timestamp >= cutoff_s
        if side == "SELL" and in_window:
            window_sell_symbols.add(symbol)
        try:
            price = _decimal(_value(row, "price"), field="trade price")
            gross_qty = _decimal(_value(row, "qty"), field="gross quantity")
            status_present = "commission_status" in row.keys()
            status = str(
                _value(row, "commission_status", "legacy") or "legacy"
            ).lower()
            quote_raw = _value(row, "fee_quote", 0)
            quote_value = (
                ZERO
                if quote_raw is None
                else _decimal(quote_raw, field="commission quote")
            )
            display_fee = (
                quote_value
                if status_present and status != "unpriced"
                else quote_value or price * gross_qty * fallback_fee_rate
            )
            if in_window:
                total_trades += 1
                fees += display_fee
                if side == "BUY":
                    buy_volume += price * gross_qty
                else:
                    sell_volume += price * gross_qty
            if status == "unpriced":
                incomplete_symbols.add(symbol)
                continue
            # Rows without status predate exact views. Keep their historical
            # fallback behavior while exact-view rows use their stored value.
            commission_quote = (
                display_fee
                if not status_present
                else None if quote_raw is None else quote_value
            )
            trade = TradeExecution.create(
                symbol=symbol,
                side=side,
                price=price,
                gross_qty=gross_qty,
                net_qty=_value(row, "net_qty", gross_qty),
                commission_asset=str(
                    _value(row, "commission_asset", "") or ""
                ),
                commission_amount=_value(row, "commission_amount", 0),
                commission_quote=commission_quote,
                commission_value_status=status,
            )
            trade.valued_commission()
        except (ArithmeticError, TypeError, UnpricedCommission, ValueError):
            incomplete_symbols.add(symbol)
            continue
        executions.setdefault(symbol, []).append((timestamp, trade))

    realized = ZERO
    for symbol, timed_trades in executions.items():
        if symbol in incomplete_symbols:
            continue
        try:
            result = replay_fifo(trade for _, trade in timed_trades)
        except (ArithmeticError, InventoryShortfall, UnpricedCommission, ValueError):
            incomplete_symbols.add(symbol)
            continue
        sell_index = 0
        for timestamp, trade in timed_trades:
            if trade.side != "SELL":
                continue
            if timestamp >= cutoff_s:
                realized += result.sell_results[sell_index]
            sell_index += 1

    blocked_symbols = sorted(incomplete_symbols & window_sell_symbols)
    cashflow = sell_volume - buy_volume - fees
    return {
        "total_trades": total_trades,
        "buy_volume_usdt": _rounded_money(buy_volume),
        "sell_volume_usdt": _rounded_money(sell_volume),
        "fees_usdt": _rounded_money(fees),
        "cashflow_pnl_usdt": _rounded_money(cashflow),
        "realized_pnl_usdt": (
            None if blocked_symbols else _rounded_money(realized)
        ),
        "realized_pnl_status": (
            "incomplete_fifo_history" if blocked_symbols else "exact"
        ),
        "realized_pnl_excluded_symbols": blocked_symbols,
    }
