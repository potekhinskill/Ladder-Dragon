# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: maintain bounded derived SELL outcomes for the risk loss-streak gate.
"""Maintain the bounded risk loss-streak index."""

from __future__ import annotations

from decimal import Decimal
import sqlite3
import time
from typing import Iterable

from ladder_dragon.execution.trade_accounting import TradeExecution


MAX_RETAINED_SELL_OUTCOMES = 4096


def _table_exists(connection: sqlite3.Connection, name: str) -> bool:
    return connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
        (name,),
    ).fetchone() is not None


def _accounting_source(connection: sqlite3.Connection) -> tuple[str, str]:
    exact_view = connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type='view' AND name='trades_exact'"
    ).fetchone()
    if exact_view:
        return (
            "trades_exact",
            "price_text,gross_qty_text,net_qty_text,commission_asset,"
            "commission_amount_text,commission_quote_text,"
            "commission_value_status",
        )
    return (
        "trades",
        "CAST(price AS TEXT),CAST(qty AS TEXT),CAST(qty AS TEXT),"
        "'', '0',CAST(COALESCE(fee_quote,0) AS TEXT),'legacy'",
    )


def _execution(row: tuple[object, ...]) -> TradeExecution:
    _, symbol, side, price, gross, net, asset, amount, quote, status, _, _ = row
    return TradeExecution.create(
        symbol=str(symbol),
        side=str(side),
        price=price,
        gross_qty=gross,
        net_qty=net,
        commission_asset=str(asset),
        commission_amount=amount,
        commission_quote=quote,
        commission_value_status=str(status),
    )


def _sell_result(
    trade: TradeExecution,
    quantity: Decimal,
    average: Decimal,
) -> tuple[Decimal, Decimal, Decimal]:
    used = min(quantity, trade.net_qty)
    ratio = used / trade.net_qty if trade.net_qty > 0 else Decimal("0")
    result = trade.sell_proceeds_quote() * ratio - average * used
    remaining = quantity - used
    return result, max(Decimal("0"), remaining), (
        average if remaining > 0 else Decimal("0")
    )


def rebuild_sell_outcomes(connection: sqlite3.Connection) -> int:
    """Rebuild the derived SELL index from authoritative trade history."""
    if not _table_exists(connection, "risk_sell_outcomes"):
        return 0
    source, columns = _accounting_source(connection)
    rows = connection.execute(
        f"SELECT id,symbol,side,{columns},ts,trade_id "
        f"FROM {source} ORDER BY ts,id"
    ).fetchall()
    inventory: dict[str, tuple[Decimal, Decimal]] = {}
    outcomes: list[tuple[int, str, object, int, str]] = []
    global_streak = 0
    symbol_streaks: dict[str, int] = {}
    last_global = (0, 0)
    last_symbol: dict[str, tuple[int, int]] = {}
    for row in rows:
        trade = _execution(row)
        trade.valued_commission()
        quantity, average = inventory.get(
            trade.symbol, (Decimal("0"), Decimal("0"))
        )
        if trade.side == "BUY":
            new_quantity = quantity + trade.net_qty
            average = (
                ((average * quantity) + trade.buy_cost_quote()) / new_quantity
                if new_quantity > 0
                else Decimal("0")
            )
            quantity = new_quantity
        else:
            result, quantity, average = _sell_result(
                trade, quantity, average
            )
            outcomes.append(
                (int(row[0]), trade.symbol, row[11], int(row[10]), str(result))
            )
            global_streak = global_streak + 1 if result < 0 else 0
            symbol_streaks[trade.symbol] = (
                symbol_streaks.get(trade.symbol, 0) + 1
                if result < 0
                else 0
            )
            last_global = (int(row[10]), int(row[0]))
            last_symbol[trade.symbol] = last_global
        inventory[trade.symbol] = (quantity, average)
    connection.execute("DELETE FROM risk_sell_outcomes")
    connection.executemany(
        "INSERT INTO risk_sell_outcomes("
        "trade_row_id,symbol,exchange_trade_id,executed_at,net_pnl_quote_text"
        ") VALUES(?,?,?,?,?)",
        outcomes[-MAX_RETAINED_SELL_OUTCOMES:],
    )
    connection.execute("DELETE FROM risk_sell_streaks")
    connection.execute(
        "INSERT INTO risk_sell_streaks("
        "scope,consecutive_losses,last_executed_at,last_trade_row_id"
        ") VALUES(?,?,?,?)",
        ("*", global_streak, *last_global),
    )
    connection.executemany(
        "INSERT INTO risk_sell_streaks("
        "scope,consecutive_losses,last_executed_at,last_trade_row_id"
        ") VALUES(?,?,?,?)",
        (
            (symbol, streak, *last_symbol[symbol])
            for symbol, streak in symbol_streaks.items()
        ),
    )
    connection.execute(
        "UPDATE risk_sell_outcome_state SET backfill_complete=1,updated_at=? "
        "WHERE singleton=1",
        (int(time.time()),),
    )
    return len(outcomes)


def record_sell_outcome(
    connection: sqlite3.Connection,
    *,
    trade_row_id: int,
    symbol: str,
    exchange_trade_id: int | None,
    executed_at: int,
    net_pnl_quote: Decimal,
) -> None:
    """Record one derived SELL result and enforce a fixed growth bound."""
    state = connection.execute(
        "SELECT backfill_complete FROM risk_sell_outcome_state WHERE singleton=1"
    ).fetchone()
    if state is None or int(state[0]) != 1:
        raise RuntimeError("risk SELL outcome backfill is incomplete")
    existing = connection.execute(
        "SELECT executed_at,net_pnl_quote_text FROM risk_sell_outcomes "
        "WHERE trade_row_id=?",
        (int(trade_row_id),),
    ).fetchone()
    latest = connection.execute(
        "SELECT last_executed_at,last_trade_row_id FROM risk_sell_streaks "
        "WHERE scope='*'"
    ).fetchone()
    if existing is not None or (
        latest is not None
        and (int(executed_at), int(trade_row_id))
        <= (int(latest[0]), int(latest[1]))
    ):
        rebuild_sell_outcomes(connection)
        return
    connection.execute(
        "INSERT INTO risk_sell_outcomes("
        "trade_row_id,symbol,exchange_trade_id,executed_at,net_pnl_quote_text"
        ") VALUES(?,?,?,?,?) "
        "ON CONFLICT(trade_row_id) DO UPDATE SET "
        "symbol=excluded.symbol,exchange_trade_id=excluded.exchange_trade_id,"
        "executed_at=excluded.executed_at,"
        "net_pnl_quote_text=excluded.net_pnl_quote_text",
        (
            int(trade_row_id),
            symbol.upper(),
            exchange_trade_id,
            int(executed_at),
            str(Decimal(net_pnl_quote)),
        ),
    )
    connection.execute(
        "DELETE FROM risk_sell_outcomes WHERE trade_row_id NOT IN ("
        "SELECT trade_row_id FROM risk_sell_outcomes "
        "ORDER BY executed_at DESC,trade_row_id DESC LIMIT ?)",
        (MAX_RETAINED_SELL_OUTCOMES,),
    )
    is_loss = Decimal(net_pnl_quote) < 0
    for scope in ("*", symbol.upper()):
        current = connection.execute(
            "SELECT consecutive_losses FROM risk_sell_streaks WHERE scope=?",
            (scope,),
        ).fetchone()
        streak = (int(current[0]) + 1) if is_loss and current else (
            1 if is_loss else 0
        )
        connection.execute(
            "INSERT INTO risk_sell_streaks("
            "scope,consecutive_losses,last_executed_at,last_trade_row_id"
            ") VALUES(?,?,?,?) ON CONFLICT(scope) DO UPDATE SET "
            "consecutive_losses=excluded.consecutive_losses,"
            "last_executed_at=excluded.last_executed_at,"
            "last_trade_row_id=excluded.last_trade_row_id",
            (scope, streak, int(executed_at), int(trade_row_id)),
        )
    connection.execute(
        "UPDATE risk_sell_outcome_state SET updated_at=? WHERE singleton=1",
        (int(time.time()),),
    )


def read_loss_streaks(
    connection: sqlite3.Connection,
    symbols: Iterable[str],
    *,
    limit: int,
) -> tuple[int, dict[str, int]] | None:
    """Read only enough recent SELL outcomes to enforce the configured gate."""
    wanted = tuple(dict.fromkeys(str(symbol).upper() for symbol in symbols))
    if not wanted or not _table_exists(connection, "risk_sell_outcomes"):
        return None
    state = connection.execute(
        "SELECT backfill_complete FROM risk_sell_outcome_state WHERE singleton=1"
    ).fetchone()
    if state is None or int(state[0]) != 1:
        raise RuntimeError("risk SELL outcome backfill is incomplete")
    bounded_limit = max(1, min(int(limit), MAX_RETAINED_SELL_OUTCOMES))
    scopes = ("*", *wanted)
    scope_placeholders = ",".join("?" for _ in scopes)
    values = {
        str(scope): min(int(streak), bounded_limit)
        for scope, streak in connection.execute(
            "SELECT scope,consecutive_losses FROM risk_sell_streaks "
            f"WHERE scope IN ({scope_placeholders})",
            scopes,
        )
    }
    return values.get("*", 0), {
        symbol: values.get(symbol, 0) for symbol in wanted
    }
