# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: maintain bounded derived FIFO SELL outcomes for the risk loss-streak gate.
"""Maintain the bounded risk loss-streak index."""

from __future__ import annotations

from decimal import Decimal
import sqlite3
import time
from typing import Iterable

from ladder_dragon.execution.trade_accounting import (
    FifoLotCost,
    InventoryShortfall,
    TradeExecution,
    fifo_sell_consumption,
)


MAX_RETAINED_SELL_OUTCOMES = 4096
MAX_OPEN_FIFO_LOTS = 65_536


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


def _apply_fifo_sell(
    lots: list[tuple[int, int | None, int, Decimal, Decimal]],
    trade: TradeExecution,
    *,
    strict_inventory: bool = True,
) -> Decimal:
    """Apply one canonical FIFO SELL to an in-memory derived lot queue."""
    consumption = fifo_sell_consumption(
        (FifoLotCost(lot[3], lot[4]) for lot in lots),
        trade,
        strict_inventory=strict_inventory,
    )
    for used in consumption.allocations:
        trade_row_id, exchange_trade_id, opened_at, qty, unit_cost = lots[0]
        remaining = qty - used
        if remaining <= 0:
            lots.pop(0)
        else:
            lots[0] = (
                trade_row_id,
                exchange_trade_id,
                opened_at,
                remaining,
                unit_cost,
            )
    return consumption.result


def rebuild_sell_outcomes(connection: sqlite3.Connection) -> int:
    """Rebuild derived FIFO lots and SELL outcomes from trade history."""
    if not _table_exists(connection, "risk_sell_outcomes"):
        return 0
    source, columns = _accounting_source(connection)
    rows = connection.execute(
        f"SELECT id,symbol,side,{columns},ts,trade_id "
        f"FROM {source} ORDER BY ts,id"
    ).fetchall()
    inventory: dict[
        str, list[tuple[int, int | None, int, Decimal, Decimal]]
    ] = {}
    outcomes: list[tuple[int, str, object, int, str]] = []
    global_streak = 0
    symbol_streaks: dict[str, int] = {}
    last_global = (0, 0)
    last_symbol: dict[str, tuple[int, int]] = {}
    last_trade_by_symbol: dict[str, tuple[int, int]] = {}
    last_trade = (0, 0)
    incomplete: dict[str, str] = {}
    for row in rows:
        trade = _execution(row)
        trade.valued_commission()
        lots = inventory.setdefault(trade.symbol, [])
        if trade.side == "BUY":
            lots.append(
                (
                    int(row[0]),
                    None if row[11] is None else int(row[11]),
                    int(row[10]),
                    trade.net_qty,
                    trade.buy_cost_quote() / trade.net_qty,
                )
            )
        else:
            try:
                result = _apply_fifo_sell(lots, trade)
            except InventoryShortfall:
                _apply_fifo_sell(lots, trade, strict_inventory=False)
                incomplete[trade.symbol] = "SELL exceeds available FIFO history"
                last_trade = (int(row[10]), int(row[0]))
                last_trade_by_symbol[trade.symbol] = last_trade
                continue
            outcomes.append(
                (int(row[0]), trade.symbol, row[11], int(row[10]), str(result))
            )
            global_streak = global_streak + 1 if result < 0 else 0
            symbol_streaks[trade.symbol] = (
                symbol_streaks.get(trade.symbol, 0) + 1 if result < 0 else 0
            )
            last_global = (int(row[10]), int(row[0]))
            last_symbol[trade.symbol] = last_global
            if result >= 0:
                incomplete.pop(trade.symbol, None)
        last_trade = (int(row[10]), int(row[0]))
        last_trade_by_symbol[trade.symbol] = last_trade
    open_lots = [
        (row_id, symbol, exchange_id, opened_at, str(qty), str(unit_cost))
        for symbol, lots in inventory.items()
        for row_id, exchange_id, opened_at, qty, unit_cost in lots
    ]
    if len(open_lots) > MAX_OPEN_FIFO_LOTS:
        raise RuntimeError("risk FIFO open-lot limit exceeded")
    connection.execute("DELETE FROM risk_fifo_lots")
    connection.executemany(
        "INSERT INTO risk_fifo_lots("
        "source_trade_row_id,symbol,exchange_trade_id,opened_at,"
        "remaining_qty_text,unit_cost_quote_text) VALUES(?,?,?,?,?,?)",
        open_lots,
    )
    # An applied import is the authoritative current FIFO boundary. Historical
    # rows can be incomplete, so retain the current lots and block the streak
    # until a later non-loss SELL establishes a new exact boundary.
    if (
        _table_exists(connection, "inventory_lot_imports")
        and _table_exists(connection, "inventory_lots")
    ):
        imported_symbols = tuple(
            str(row[0]).upper()
            for row in connection.execute(
                "SELECT DISTINCT symbol FROM inventory_lot_imports "
                "WHERE status='APPLIED'"
            )
        )
        for symbol in imported_symbols:
            connection.execute(
                "DELETE FROM risk_fifo_lots WHERE symbol=?", (symbol,)
            )
            imported_lots = connection.execute(
                "SELECT source_trade_id,opened_at,qty,price "
                "FROM inventory_lots WHERE symbol=? AND status='OPEN' "
                "ORDER BY opened_at,lot_id",
                (symbol,),
            ).fetchall()
            connection.executemany(
                "INSERT INTO risk_fifo_lots("
                "source_trade_row_id,symbol,exchange_trade_id,opened_at,"
                "remaining_qty_text,unit_cost_quote_text) "
                "VALUES(NULL,?,?,?,?,?)",
                (
                    (
                        symbol,
                        int(str(row[0])) if str(row[0]).strip() else None,
                        int(row[1]),
                        str(Decimal(str(row[2]))),
                        str(Decimal(str(row[3]))),
                    )
                    for row in imported_lots
                ),
            )
            incomplete[symbol] = "cost basis import resets prior streak provenance"
    connection.execute("DELETE FROM risk_fifo_incomplete_symbols")
    connection.executemany(
        "INSERT INTO risk_fifo_incomplete_symbols(symbol,reason,updated_at) "
        "VALUES(?,?,?)",
        (
            (symbol, reason, int(time.time()))
            for symbol, reason in incomplete.items()
        ),
    )
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
    connection.execute("DELETE FROM risk_fifo_symbol_state")
    connection.executemany(
        "INSERT INTO risk_fifo_symbol_state("
        "symbol,last_trade_at,last_trade_row_id) VALUES(?,?,?)",
        (
            (symbol, trade_key[0], trade_key[1])
            for symbol, trade_key in last_trade_by_symbol.items()
        ),
    )
    open_lot_count = int(
        connection.execute("SELECT COUNT(*) FROM risk_fifo_lots").fetchone()[0]
    )
    if open_lot_count > MAX_OPEN_FIFO_LOTS:
        raise RuntimeError("risk FIFO open-lot limit exceeded")
    connection.execute(
        "UPDATE risk_sell_outcome_state SET backfill_complete=1,updated_at=?,"
        "last_trade_at=?,last_trade_row_id=?,open_fifo_lot_count=? "
        "WHERE singleton=1",
        (int(time.time()), *last_trade, open_lot_count),
    )
    return len(outcomes)


def _record_sell_result(
    connection: sqlite3.Connection,
    *,
    trade_row_id: int,
    symbol: str,
    exchange_trade_id: int | None,
    executed_at: int,
    net_pnl_quote: Decimal,
) -> None:
    latest_global = connection.execute(
        "SELECT last_executed_at,last_trade_row_id FROM risk_sell_streaks "
        "WHERE scope='*'"
    ).fetchone()
    out_of_order_global = latest_global is not None and (
        executed_at, trade_row_id
    ) <= (int(latest_global[0]), int(latest_global[1]))
    connection.execute(
        "INSERT INTO risk_sell_outcomes("
        "trade_row_id,symbol,exchange_trade_id,executed_at,net_pnl_quote_text"
        ") VALUES(?,?,?,?,?)",
        (
            trade_row_id,
            symbol,
            exchange_trade_id,
            executed_at,
            str(net_pnl_quote),
        ),
    )
    connection.execute(
        "DELETE FROM risk_sell_outcomes WHERE trade_row_id NOT IN ("
        "SELECT trade_row_id FROM risk_sell_outcomes "
        "ORDER BY executed_at DESC,trade_row_id DESC LIMIT ?)",
        (MAX_RETAINED_SELL_OUTCOMES,),
    )
    if out_of_order_global:
        _rebuild_streak_counters(connection)
        return
    is_loss = net_pnl_quote < 0
    for scope in ("*", symbol):
        current = connection.execute(
            "SELECT consecutive_losses FROM risk_sell_streaks WHERE scope=?",
            (scope,),
        ).fetchone()
        streak = int(current[0]) + 1 if is_loss and current else (
            1 if is_loss else 0
        )
        connection.execute(
            "INSERT INTO risk_sell_streaks("
            "scope,consecutive_losses,last_executed_at,last_trade_row_id"
            ") VALUES(?,?,?,?) ON CONFLICT(scope) DO UPDATE SET "
            "consecutive_losses=excluded.consecutive_losses,"
            "last_executed_at=excluded.last_executed_at,"
            "last_trade_row_id=excluded.last_trade_row_id",
            (scope, streak, executed_at, trade_row_id),
        )


def _rebuild_streak_counters(connection: sqlite3.Connection) -> None:
    """Rebuild bounded counters after a cross-symbol ordering change."""
    rows = connection.execute(
        "SELECT trade_row_id,symbol,executed_at,net_pnl_quote_text "
        "FROM risk_sell_outcomes ORDER BY executed_at,trade_row_id"
    ).fetchall()
    global_streak = 0
    symbol_streaks: dict[str, int] = {}
    last_global = (0, 0)
    last_symbol: dict[str, tuple[int, int]] = {}
    for trade_row_id, symbol, executed_at, result_text in rows:
        result = Decimal(str(result_text))
        normalized = str(symbol).upper()
        global_streak = global_streak + 1 if result < 0 else 0
        symbol_streaks[normalized] = (
            symbol_streaks.get(normalized, 0) + 1 if result < 0 else 0
        )
        last_global = (int(executed_at), int(trade_row_id))
        last_symbol[normalized] = last_global
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


def record_trade_outcome(
    connection: sqlite3.Connection,
    *,
    trade_row_id: int,
    exchange_trade_id: int | None,
    executed_at: int,
    trade: TradeExecution,
) -> None:
    """Apply one valued trade to the bounded derived FIFO risk index."""
    state = connection.execute(
        "SELECT backfill_complete,last_trade_at,last_trade_row_id,"
        "open_fifo_lot_count "
        "FROM risk_sell_outcome_state WHERE singleton=1"
    ).fetchone()
    if state is None or int(state[0]) != 1:
        raise RuntimeError("risk SELL outcome backfill is incomplete")
    trade_key = (int(executed_at), int(trade_row_id))
    symbol = trade.symbol.upper()
    symbol_state = connection.execute(
        "SELECT last_trade_at,last_trade_row_id FROM risk_fifo_symbol_state "
        "WHERE symbol=?",
        (symbol,),
    ).fetchone()
    if symbol_state is not None and trade_key <= (
        int(symbol_state[0]), int(symbol_state[1])
    ):
        rebuild_sell_outcomes(connection)
        return
    open_lot_count = int(state[3])
    if trade.side == "BUY":
        if open_lot_count >= MAX_OPEN_FIFO_LOTS:
            raise RuntimeError("risk FIFO open-lot limit exceeded")
        connection.execute(
            "INSERT INTO risk_fifo_lots("
            "source_trade_row_id,symbol,exchange_trade_id,opened_at,"
            "remaining_qty_text,unit_cost_quote_text) VALUES(?,?,?,?,?,?)",
            (
                int(trade_row_id),
                symbol,
                exchange_trade_id,
                int(executed_at),
                str(trade.net_qty),
                str(trade.buy_cost_quote() / trade.net_qty),
            ),
        )
        open_lot_count += 1
    else:
        rows = connection.execute(
            "SELECT lot_id,remaining_qty_text,unit_cost_quote_text "
            "FROM risk_fifo_lots WHERE symbol=? ORDER BY opened_at,lot_id",
            (symbol,),
        ).fetchall()
        missing_coverage = False
        try:
            consumption = fifo_sell_consumption(
                (
                    FifoLotCost(Decimal(str(row[1])), Decimal(str(row[2])))
                    for row in rows
                ),
                trade,
            )
        except InventoryShortfall:
            missing_coverage = True
            consumption = fifo_sell_consumption(
                (
                    FifoLotCost(Decimal(str(row[1])), Decimal(str(row[2])))
                    for row in rows
                ),
                trade,
                strict_inventory=False,
            )
        for row, used in zip(rows, consumption.allocations):
            remaining = Decimal(str(row[1])) - used
            if remaining <= 0:
                connection.execute(
                    "DELETE FROM risk_fifo_lots WHERE lot_id=?",
                    (int(row[0]),),
                )
                open_lot_count -= 1
            else:
                connection.execute(
                    "UPDATE risk_fifo_lots SET remaining_qty_text=? "
                    "WHERE lot_id=?",
                    (str(remaining), int(row[0])),
                )
        if missing_coverage:
            connection.execute(
                "INSERT INTO risk_fifo_incomplete_symbols("
                "symbol,reason,updated_at) VALUES(?,?,?) "
                "ON CONFLICT(symbol) DO UPDATE SET "
                "reason=excluded.reason,updated_at=excluded.updated_at",
                (symbol, "SELL exceeds available FIFO history", int(time.time())),
            )
        else:
            _record_sell_result(
                connection,
                trade_row_id=int(trade_row_id),
                symbol=symbol,
                exchange_trade_id=exchange_trade_id,
                executed_at=int(executed_at),
                net_pnl_quote=consumption.result,
            )
            if consumption.result >= 0:
                connection.execute(
                    "DELETE FROM risk_fifo_incomplete_symbols WHERE symbol=?",
                    (symbol,),
                )
    connection.execute(
        "UPDATE risk_sell_outcome_state SET updated_at=?,last_trade_at=?,"
        "last_trade_row_id=?,open_fifo_lot_count=? WHERE singleton=1",
        (
            int(time.time()),
            int(executed_at),
            int(trade_row_id),
            open_lot_count,
        ),
    )
    connection.execute(
        "INSERT INTO risk_fifo_symbol_state("
        "symbol,last_trade_at,last_trade_row_id) VALUES(?,?,?) "
        "ON CONFLICT(symbol) DO UPDATE SET "
        "last_trade_at=excluded.last_trade_at,"
        "last_trade_row_id=excluded.last_trade_row_id",
        (symbol, int(executed_at), int(trade_row_id)),
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
    incomplete_placeholders = ",".join("?" for _ in wanted)
    incomplete = connection.execute(
        "SELECT symbol FROM risk_fifo_incomplete_symbols "
        f"WHERE symbol IN ({incomplete_placeholders}) ORDER BY symbol LIMIT 1",
        wanted,
    ).fetchone()
    if incomplete is not None:
        raise RuntimeError(
            f"risk FIFO history is incomplete for {str(incomplete[0])}"
        )
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


def replace_symbol_fifo_basis(
    connection: sqlite3.Connection,
    *,
    symbol: str,
    lots: Iterable[tuple[int, int, Decimal, Decimal]],
) -> None:
    """Replace one symbol's derived FIFO basis inside an operator transaction."""
    normalized = symbol.upper()
    prepared = tuple(lots)
    for exchange_trade_id, opened_at, qty, unit_cost in prepared:
        if int(exchange_trade_id) < 0 or int(opened_at) < 0:
            raise ValueError("risk FIFO basis provenance must be non-negative")
        if Decimal(qty) <= 0 or Decimal(unit_cost) <= 0:
            raise ValueError("risk FIFO basis values must be positive")
    state = connection.execute(
        "SELECT backfill_complete,open_fifo_lot_count "
        "FROM risk_sell_outcome_state WHERE singleton=1"
    ).fetchone()
    if state is None or int(state[0]) != 1:
        raise RuntimeError("risk SELL outcome backfill is incomplete")
    old_count = int(
        connection.execute(
            "SELECT COUNT(*) FROM risk_fifo_lots WHERE symbol=?",
            (normalized,),
        ).fetchone()[0]
    )
    new_count = int(state[1]) - old_count + len(prepared)
    if new_count > MAX_OPEN_FIFO_LOTS:
        raise RuntimeError("risk FIFO open-lot limit exceeded")
    connection.execute("DELETE FROM risk_fifo_lots WHERE symbol=?", (normalized,))
    connection.executemany(
        "INSERT INTO risk_fifo_lots("
        "source_trade_row_id,symbol,exchange_trade_id,opened_at,"
        "remaining_qty_text,unit_cost_quote_text) VALUES(NULL,?,?,?,?,?)",
        (
            (
                normalized,
                int(exchange_trade_id),
                int(opened_at),
                str(Decimal(qty)),
                str(Decimal(unit_cost)),
            )
            for exchange_trade_id, opened_at, qty, unit_cost in prepared
        ),
    )
    connection.execute(
        "UPDATE risk_sell_outcome_state SET open_fifo_lot_count=?,updated_at=? "
        "WHERE singleton=1",
        (new_count, int(time.time())),
    )
    connection.execute(
        "INSERT INTO risk_fifo_incomplete_symbols(symbol,reason,updated_at) "
        "VALUES(?,?,?) ON CONFLICT(symbol) DO UPDATE SET "
        "reason=excluded.reason,updated_at=excluded.updated_at",
        (normalized, "cost basis import resets prior streak provenance", int(time.time())),
    )
    latest = connection.execute(
        "SELECT ts,id FROM trades WHERE symbol=? ORDER BY ts DESC,id DESC LIMIT 1",
        (normalized,),
    ).fetchone()
    connection.execute(
        "INSERT INTO risk_fifo_symbol_state("
        "symbol,last_trade_at,last_trade_row_id) VALUES(?,?,?) "
        "ON CONFLICT(symbol) DO UPDATE SET "
        "last_trade_at=excluded.last_trade_at,"
        "last_trade_row_id=excluded.last_trade_row_id",
        (
            normalized,
            int(latest[0]) if latest else 0,
            int(latest[1]) if latest else 0,
        ),
    )
