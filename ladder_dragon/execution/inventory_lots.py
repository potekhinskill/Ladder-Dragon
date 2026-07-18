# Copyright (c) 2026 IURII Potekhin / Ladder Dragon. All rights reserved.
# Purpose: keep the file role and safety boundaries clear during maintenance.
"""FIFO-партии с возрастом для live-сверки и backtest."""
from __future__ import annotations

import sqlite3
import time
from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True)
class InventoryLot:
    """Неизменяемая запись партии, купленной одним уровнем лестницы."""
    lot_id: int
    symbol: str
    qty: Decimal
    price: Decimal
    opened_at: int
    ladder_level: str


def ensure_schema(connection: sqlite3.Connection) -> None:
    # Store Decimal values as text so SQLite cannot round quantity or price.
    connection.execute("""CREATE TABLE IF NOT EXISTS inventory_lots(
        lot_id INTEGER PRIMARY KEY AUTOINCREMENT, symbol TEXT NOT NULL,
        qty TEXT NOT NULL, price TEXT NOT NULL, opened_at INTEGER NOT NULL,
        updated_at INTEGER NOT NULL, ladder_level TEXT NOT NULL DEFAULT '',
        source_order_id TEXT NOT NULL DEFAULT '', status TEXT NOT NULL DEFAULT 'OPEN'
    )""")
    connection.execute("CREATE INDEX IF NOT EXISTS inventory_lots_fifo ON inventory_lots(symbol,status,opened_at)")


def add_lot(connection: sqlite3.Connection, *, symbol: str, qty: Decimal, price: Decimal,
            ladder_level: str = "", opened_at: int | None = None, source_order_id: str = "") -> int:
    ensure_schema(connection)
    # Historical imports may provide the original BUY timestamp.
    now = int(opened_at or time.time())
    cur = connection.execute(
        "INSERT INTO inventory_lots(symbol,qty,price,opened_at,updated_at,ladder_level,source_order_id) VALUES(?,?,?,?,?,?,?)",
        (symbol.upper(), str(qty), str(price), now, now, ladder_level, source_order_id),
    )
    return int(cur.lastrowid)


def oldest_lots(connection: sqlite3.Connection, symbol: str) -> list[InventoryLot]:
    # Sorting by opened_at guarantees FIFO and enables time-stop handling.
    ensure_schema(connection)
    rows = connection.execute(
        "SELECT lot_id,symbol,qty,price,opened_at,ladder_level FROM inventory_lots WHERE symbol=? AND status='OPEN' ORDER BY opened_at,lot_id",
        (symbol.upper(),),
    ).fetchall()
    return [InventoryLot(int(r[0]), str(r[1]), Decimal(r[2]), Decimal(r[3]), int(r[4]), str(r[5])) for r in rows]


def lot_for_order(connection: sqlite3.Connection, symbol: str, order_id: str | int) -> InventoryLot | None:
    """Найти конкретную FIFO-партию по исходному exchange order/trade ID."""
    ensure_schema(connection)
    row = connection.execute(
        "SELECT lot_id,symbol,qty,price,opened_at,ladder_level FROM inventory_lots "
        "WHERE symbol=? AND source_order_id=? AND status='OPEN' ORDER BY opened_at,lot_id LIMIT 1",
        (symbol.upper(), str(order_id)),
    ).fetchone()
    return InventoryLot(int(row[0]), str(row[1]), Decimal(row[2]), Decimal(row[3]), int(row[4]), str(row[5])) if row else None


def consume_fifo(connection: sqlite3.Connection, symbol: str, qty: Decimal) -> list[InventoryLot]:
    """Списать SELL из старейших партий и вернуть использованные доли."""
    consumed: list[InventoryLot] = []
    remaining = qty
    for lot in oldest_lots(connection, symbol):
        if remaining <= 0:
            break
        used = min(remaining, lot.qty)
        consumed.append(InventoryLot(lot.lot_id, lot.symbol, used, lot.price, lot.opened_at, lot.ladder_level))
        # A partial sale leaves the same lot open with a reduced quantity.
        left = lot.qty - used
        connection.execute("UPDATE inventory_lots SET qty=?,updated_at=?,status=? WHERE lot_id=?",
                           (str(left), int(time.time()), "OPEN" if left > 0 else "CLOSED", lot.lot_id))
        remaining -= used
    if remaining > 0:
        raise ValueError("SELL exceeds FIFO inventory lots")
    return consumed
