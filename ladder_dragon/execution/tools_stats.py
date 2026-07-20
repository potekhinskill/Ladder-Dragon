#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: implement the tools stats component of the execution layer.
"""Ladder Dragon tools stats support."""

import sqlite3, os, time
from decimal import Decimal
from typing import Optional, Tuple, Dict, Iterable, Any

from bin.db_migrate import migrate
from ladder_dragon.execution.trade_accounting import TradeExecution, decimal, decimal_text, replay_average_cost

# ==========================
# Configuration from environment variables
# ==========================
DB_PATH = os.getenv("BOT_STATS_DB", "/home/bot/stats/bot_stats.db")
BUSY_TRIES  = int(os.getenv("STATS_BUSY_TRIES", "7"))
BUSY_BASE_S = float(os.getenv("STATS_BUSY_BASE", "0.25"))

SCHEMA = """
CREATE TABLE IF NOT EXISTS trades(
  id         INTEGER PRIMARY KEY AUTOINCREMENT,
  symbol     TEXT NOT NULL,
  side       TEXT CHECK(side IN ('BUY','SELL')) NOT NULL,
  price      REAL NOT NULL CHECK(price > 0.0),
  qty        REAL NOT NULL CHECK(qty > 0.0),
  fee_quote  REAL NOT NULL DEFAULT 0.0 CHECK(fee_quote >= 0.0),
  ts         INTEGER NOT NULL CHECK(ts > 0),
  trade_id   INTEGER,
  price_text TEXT,
  gross_qty TEXT,
  net_qty TEXT,
  commission_asset TEXT NOT NULL DEFAULT '',
  commission_amount TEXT,
  commission_quote TEXT,
  commission_value_status TEXT NOT NULL DEFAULT 'legacy'
);
-- Base and covering indexes for symbol/time queries and reports
CREATE INDEX IF NOT EXISTS trades_idx ON trades(symbol, ts);
CREATE INDEX IF NOT EXISTS trades_monthly_cover
ON trades(symbol, ts, side, price, qty, fee_quote);
-- Keep trade_id unique within each symbol when it is present
CREATE UNIQUE INDEX IF NOT EXISTS trades_sym_tradeid_uq
ON trades(symbol, trade_id) WHERE trade_id IS NOT NULL;

CREATE TABLE IF NOT EXISTS inventory(
  symbol        TEXT PRIMARY KEY,
  qty           REAL NOT NULL DEFAULT 0.0,
  avg_cost      REAL NOT NULL DEFAULT 0.0,
  realized_pnl  REAL NOT NULL DEFAULT 0.0,
  last_trade_id INTEGER,
  qty_text TEXT,
  avg_cost_text TEXT,
  realized_pnl_text TEXT
);

CREATE VIEW IF NOT EXISTS trades_exact AS
SELECT id, symbol, side,
       COALESCE(NULLIF(price_text, ''), CAST(price AS TEXT)) AS price_text,
       COALESCE(NULLIF(gross_qty, ''), CAST(qty AS TEXT)) AS gross_qty_text,
       COALESCE(NULLIF(net_qty, ''), CAST(qty AS TEXT)) AS net_qty_text,
       COALESCE(commission_asset, '') AS commission_asset,
       COALESCE(NULLIF(commission_amount, ''), '0') AS commission_amount_text,
       CASE WHEN commission_value_status = 'unpriced' THEN NULL
            ELSE COALESCE(NULLIF(commission_quote, ''), CAST(fee_quote AS TEXT))
       END AS commission_quote_text,
       COALESCE(NULLIF(commission_value_status, ''), 'legacy')
         AS commission_value_status,
       ts, trade_id
FROM trades;

CREATE VIEW IF NOT EXISTS inventory_exact AS
SELECT symbol,
       COALESCE(NULLIF(qty_text, ''), CAST(qty AS TEXT)) AS qty_text,
       COALESCE(NULLIF(avg_cost_text, ''), CAST(avg_cost AS TEXT)) AS avg_cost_text,
       COALESCE(NULLIF(realized_pnl_text, ''), CAST(realized_pnl AS TEXT))
         AS realized_pnl_text,
       last_trade_id
FROM inventory;
"""

# ==========================
# Helper functions
# ==========================

def _apply_pragmas(con: sqlite3.Connection, read_only: bool = False) -> None:
    cur = con.cursor()
    try:
        cur.execute("PRAGMA busy_timeout=7000;")
        cur.execute("PRAGMA synchronous=NORMAL;")
        if not read_only:
            cur.execute("PRAGMA journal_mode=WAL;")
            cur.execute("PRAGMA wal_autocheckpoint=2000;")
    except sqlite3.OperationalError:
        # Some PRAGMA statements may be unavailable in read-only mode; ignore them safely.
        pass
    finally:
        cur.close()

def connect_ro(db_path: str = DB_PATH) -> sqlite3.Connection:
    con = sqlite3.connect(
        f"file:{db_path}?mode=ro",
        uri=True,
        timeout=10.0,
        check_same_thread=False,
        isolation_level=None
    )
    _apply_pragmas(con, read_only=True)
    return con

def connect_rw(db_path: str = DB_PATH) -> sqlite3.Connection:
    con = sqlite3.connect(
        db_path,
        timeout=15.0,
        check_same_thread=False,
        isolation_level=None
    )
    _apply_pragmas(con, read_only=False)
    return con

def _retry_op(fn, *a, **kw):
    """Handle retry op."""
    tries = BUSY_TRIES
    delay = BUSY_BASE_S
    for i in range(tries):
        try:
            return fn(*a, **kw)
        except sqlite3.OperationalError as e:
            msg = str(e).lower()
            if ("locked" in msg or "busy" in msg) and i < tries - 1:
                time.sleep(delay)
                delay *= 2.0
                continue
            raise

def exec_with_retry(con: sqlite3.Connection, sql: str, params: Iterable[Any] = ()):
    cur = _retry_op(con.execute, sql, params)
    try:
        return cur.rowcount
    finally:
        cur.close()

def query_with_retry(con: sqlite3.Connection, sql: str, params: Iterable[Any] = ()) -> list:
    cur = _retry_op(con.execute, sql, params)
    rows = cur.fetchall()
    cur.close()
    return rows

# ==========================
# Database initialization
# ==========================

def init_db(db_path: str) -> sqlite3.Connection:
    """Handle init db."""
    os.makedirs(os.path.dirname(db_path) or ".", exist_ok=True)
    migrate(db_path)
    con = connect_rw(db_path)
    return con

# ==========================
# Inventory recalculation
# ==========================

def _recalc_inventory(db: sqlite3.Connection, symbol: str):
    """Handle recalc inventory."""
    sym = symbol.upper()
    imported_basis = None
    try:
        imported_basis = db.execute(
            "SELECT reconstructed_qty,weighted_average,last_trade_id,"
            "baseline_realized_pnl FROM inventory_lot_imports "
            "WHERE symbol=? AND status='APPLIED' ORDER BY created_at DESC LIMIT 1",
            (sym,),
        ).fetchone()
    except sqlite3.OperationalError as exc:
        if "no such table" not in str(exc).lower():
            raise
    trade_filter = ""
    trade_params: tuple[object, ...] = (sym,)
    if imported_basis is not None:
        trade_filter = " AND trade_id IS NOT NULL AND trade_id > ?"
        trade_params = (sym, int(imported_basis[2]))
    rows = query_with_retry(db, f"""
        SELECT side,
               price_text, gross_qty_text, net_qty_text,
               commission_asset, commission_amount_text,
               commission_quote_text, commission_value_status
        FROM trades_exact
        WHERE symbol=?{trade_filter} ORDER BY ts ASC, id ASC
    """, trade_params)
    executions = []
    baseline_realized = Decimal("0")
    if imported_basis is not None:
        baseline_qty = decimal(imported_basis[0])
        baseline_average = decimal(imported_basis[1])
        baseline_realized = decimal(imported_basis[3])
        if baseline_qty > 0 and baseline_average > 0:
            executions.append(TradeExecution.create(
                symbol=sym,
                side="BUY",
                price=baseline_average,
                gross_qty=baseline_qty,
                commission_quote=Decimal("0"),
                commission_value_status="basis-import",
            ))
    executions.extend([
        TradeExecution.create(
            symbol=sym,
            side=side,
            price=price,
            gross_qty=gross_qty,
            net_qty=net_qty,
            commission_asset=commission_asset,
            commission_amount=commission_amount,
            commission_quote=commission_quote,
            commission_value_status=status,
        )
        for (
            side, price, gross_qty, net_qty, commission_asset,
            commission_amount, commission_quote, status,
        ) in rows
    ])
    result = replay_average_cost(executions, allow_unpriced=True)
    realized_pnl = baseline_realized + result.realized_pnl

    exec_with_retry(db, """
        INSERT INTO inventory(
            symbol, qty, avg_cost, realized_pnl,
            qty_text, avg_cost_text, realized_pnl_text
        ) VALUES(?,?,?,?,?,?,?)
        ON CONFLICT(symbol)
        DO UPDATE SET qty=excluded.qty,
                      avg_cost=excluded.avg_cost,
                      realized_pnl=excluded.realized_pnl,
                      qty_text=excluded.qty_text,
                      avg_cost_text=excluded.avg_cost_text,
                      realized_pnl_text=excluded.realized_pnl_text
    """, (
        sym,
        float(result.qty), float(result.avg_cost), float(realized_pnl),
        decimal_text(result.qty), decimal_text(result.avg_cost),
        decimal_text(realized_pnl),
    ))

# ==========================
# Public functions
# ==========================

def apply_trade(con: sqlite3.Connection,
                symbol: str,
                side: str,
                price: object,
                qty: object,
                fee_quote: object = 0.0,
                ts: Optional[int] = None,
                trade_id: Optional[int] = None,
                *,
                gross_qty: object | None = None,
                net_qty: object | None = None,
                commission_asset: str = "",
                commission_amount: object = 0,
                commission_quote: object | None = None,
                commission_value_status: str | None = None):
    """Apply trade."""
    sym = symbol.upper()
    ts = int(ts or time.time() * 1000)
    gross = qty if gross_qty is None else gross_qty
    status = (commission_value_status or ("legacy" if not commission_asset else "exact")).lower()
    quote_value = None if status == "unpriced" else (
        fee_quote if commission_quote is None else commission_quote
    )
    execution = TradeExecution.create(
        symbol=sym,
        side=side,
        price=price,
        gross_qty=gross,
        net_qty=net_qty,
        commission_asset=commission_asset,
        commission_amount=commission_amount,
        commission_quote=quote_value,
        commission_value_status=status,
    )
    legacy_fee = execution.commission_quote or Decimal("0")

    with con:
        inserted = exec_with_retry(con, """
            INSERT INTO trades(
                symbol, side, price, qty, fee_quote, ts, trade_id,
                price_text, gross_qty, net_qty, commission_asset,
                commission_amount, commission_quote, commission_value_status
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(symbol, trade_id) WHERE trade_id IS NOT NULL DO UPDATE SET
                fee_quote=excluded.fee_quote,
                commission_quote=excluded.commission_quote,
                commission_value_status=excluded.commission_value_status
            WHERE trades.commission_value_status = 'unpriced'
              AND excluded.commission_value_status != 'unpriced'
        """, (
            sym, execution.side, float(execution.price), float(execution.gross_qty),
            float(legacy_fee), ts, trade_id, decimal_text(execution.price),
            decimal_text(execution.gross_qty), decimal_text(execution.net_qty),
            execution.commission_asset, decimal_text(execution.commission_amount),
            None if execution.commission_quote is None else decimal_text(execution.commission_quote),
            execution.commission_value_status,
        ))
        _recalc_inventory(con, sym)
    return inserted == 1


def get_inventory_decimal(con: sqlite3.Connection, symbol: str) -> Tuple[Decimal, Decimal, Decimal]:
    sym = symbol.upper()
    rows = query_with_retry(con, """
        SELECT qty_text, avg_cost_text, realized_pnl_text
        FROM inventory_exact WHERE symbol=?
    """, (sym,))
    if not rows:
        return (Decimal("0"), Decimal("0"), Decimal("0"))
    q, a, r = rows[0]
    return (decimal(q), decimal(a), decimal(r))

def get_inventory(con: sqlite3.Connection, symbol: str) -> Tuple[float, float, float]:
    """Return inventory."""
    q, a, r = get_inventory_decimal(con, symbol)
    return (float(q), float(a), float(r))

def get_last_trade_id(con: sqlite3.Connection, symbol: str) -> Optional[int]:
    sym = symbol.upper()
    rows = query_with_retry(con, "SELECT last_trade_id FROM inventory WHERE symbol=?", (sym,))
    if not rows:
        return None
    return rows[0][0]

def set_last_trade_id(con: sqlite3.Connection, symbol: str, last_id: int):
    sym = symbol.upper()
    with con:
        exec_with_retry(con, """
            INSERT INTO inventory(symbol, last_trade_id)
            VALUES(?,?)
            ON CONFLICT(symbol)
            DO UPDATE SET last_trade_id=excluded.last_trade_id
        """, (sym, int(last_id)))


def get_executions_between(
    con: sqlite3.Connection, symbol: str, start_ms: int, end_ms: int
) -> list[TradeExecution]:
    rows = query_with_retry(con, """
        SELECT side,
               price_text, gross_qty_text, net_qty_text,
               commission_asset, commission_amount_text,
               commission_quote_text, commission_value_status
        FROM trades_exact
        WHERE symbol=? AND ts BETWEEN ? AND ?
        ORDER BY ts ASC, id ASC
    """, (symbol.upper(), start_ms, end_ms))
    return [
        TradeExecution.create(
            symbol=symbol,
            side=side,
            price=price,
            gross_qty=gross,
            net_qty=net,
            commission_asset=asset,
            commission_amount=amount,
            commission_quote=quote_value,
            commission_value_status=status,
        )
        for side, price, gross, net, asset, amount, quote_value, status in rows
    ]


def _period_summary(executions: list[TradeExecution], realized_key: str) -> Dict:
    result = replay_average_cost(executions)
    buys = [trade for trade in executions if trade.side == "BUY"]
    sells = [trade for trade in executions if trade.side == "SELL"]
    buys_base = sum((trade.gross_qty for trade in buys), Decimal("0"))
    sells_base = sum((trade.gross_qty for trade in sells), Decimal("0"))
    spent_quote = sum((trade.buy_cost_quote() for trade in buys), Decimal("0"))
    received_quote = sum(
        (trade.sell_proceeds_quote() for trade in sells), Decimal("0")
    )
    return {
        "buys_base": float(buys_base),
        "buys_base_text": decimal_text(buys_base),
        "sells_base": float(sells_base),
        "sells_base_text": decimal_text(sells_base),
        "spent_quote": float(spent_quote),
        "spent_quote_text": decimal_text(spent_quote),
        "received_quote": float(received_quote),
        "received_quote_text": decimal_text(received_quote),
        realized_key: float(result.realized_pnl),
        f"{realized_key}_text": decimal_text(result.realized_pnl),
    }

def monthly_summary(con: sqlite3.Connection, symbol: str, year: int, month: int) -> Dict:
    import calendar
    import datetime as dt

    sym = symbol.upper()
    first = dt.datetime(year, month, 1)
    last_day = calendar.monthrange(year, month)[1]
    last = dt.datetime(year, month, last_day, 23, 59, 59, 999000)

    t1 = int(first.timestamp() * 1000)
    t2 = int(last.timestamp() * 1000)

    return _period_summary(get_executions_between(con, sym, t1, t2), "realized_month")

def daily_summary(con: sqlite3.Connection, symbol: str, utc: bool = True) -> Dict:
    """Handle daily summary."""
    import datetime as dt

    sym = symbol.upper()
    now = dt.datetime.utcnow() if utc else dt.datetime.now()
    start = dt.datetime(now.year, now.month, now.day, 0, 0, 0)
    end = dt.datetime(now.year, now.month, now.day, 23, 59, 59, 999000)

    t1 = int(start.timestamp() * 1000)
    t2 = int(end.timestamp() * 1000)

    return _period_summary(get_executions_between(con, sym, t1, t2), "realized_day")
