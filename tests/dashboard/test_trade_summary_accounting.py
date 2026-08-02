# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: verify exact dashboard FIFO trade summaries.

from ladder_dragon.dashboard.services.trade_summary import fifo_realized_pnl


def _row(side, price, qty, timestamp, *, status="exact", fee="0"):
    return {
        "symbol": "SOLUSDT",
        "side": side,
        "price": price,
        "qty": qty,
        "net_qty": qty,
        "commission_asset": "USDT",
        "commission_amount": fee,
        "fee_quote": fee,
        "commission_status": status,
        "ts_s": timestamp,
    }


def test_legacy_commission_status_remains_exact_with_zero_fee():
    rows = [
        _row("BUY", "100", "1", 100, status="legacy"),
        _row("SELL", "110", "1", 300, status="legacy"),
    ]

    result = fifo_realized_pnl(rows, cutoff_s=200, fee_pct=0.01)

    assert result["fees_usdt"] == 0.0
    assert result["realized_pnl_usdt"] == 10.0
    assert result["realized_pnl_status"] == "exact"
    assert result["realized_pnl_excluded_symbols"] == []


def test_dashboard_uses_fifo_instead_of_average_cost():
    rows = [
        _row("BUY", "100", "1", 100),
        _row("BUY", "200", "1", 150),
        _row("SELL", "300", "1", 300),
    ]

    result = fifo_realized_pnl(rows, cutoff_s=200, fee_pct=0.001)

    assert result["realized_pnl_usdt"] == 200.0


def test_historical_sell_consumes_fifo_before_report_window():
    rows = [
        _row("BUY", "100", "1", 50),
        _row("BUY", "200", "1", 60),
        _row("SELL", "150", "1", 100),
        _row("SELL", "300", "1", 300),
    ]

    result = fifo_realized_pnl(rows, cutoff_s=200, fee_pct=0.001)

    assert result["total_trades"] == 1
    assert result["realized_pnl_usdt"] == 100.0


def test_unpriced_history_blocks_window_sell():
    rows = [
        _row("BUY", "100", "1", 100, status="unpriced"),
        _row("SELL", "110", "1", 300),
    ]

    result = fifo_realized_pnl(rows, cutoff_s=200, fee_pct=0.001)

    assert result["realized_pnl_usdt"] is None
    assert result["realized_pnl_status"] == "incomplete_fifo_history"
    assert result["realized_pnl_excluded_symbols"] == ["SOLUSDT"]


def test_future_trade_cannot_enter_current_summary_or_fifo_history():
    rows = [
        _row("BUY", "100", "1", 100),
        _row("SELL", "110", "1", 300),
        _row("BUY", "1", "10", 500),
        _row("SELL", "1000", "10", 501),
    ]

    result = fifo_realized_pnl(
        rows,
        cutoff_s=200,
        fee_pct=0.001,
        end_s=400,
    )

    assert result["total_trades"] == 1
    assert result["realized_pnl_usdt"] == 10.0
