# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: implement the inventory lots component of the execution layer.
"""FIFO-партии с возрастом для live-сверки и backtest."""
from __future__ import annotations

import sqlite3
import time
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Mapping

from ladder_dragon.execution.trade_accounting import TradeExecution


@dataclass(frozen=True)
class InventoryLot:
    """Неизменяемая запись партии, купленной одним уровнем лестницы."""
    lot_id: int
    symbol: str
    qty: Decimal
    price: Decimal
    opened_at: int
    ladder_level: str


@dataclass(frozen=True)
class CostBasisCoverage:
    """Exact quantity coverage of account inventory by priced, sourced lots."""

    symbol: str
    account_qty: Decimal
    covered_qty: Decimal
    average_price: Decimal | None
    uncovered_qty: Decimal
    tolerance_qty: Decimal
    covered: bool
    reason: str


def ensure_schema(connection: sqlite3.Connection) -> None:
    # Store Decimal values as text so SQLite cannot round quantity or price.
    connection.execute("""CREATE TABLE IF NOT EXISTS inventory_lots(
        lot_id INTEGER PRIMARY KEY AUTOINCREMENT, symbol TEXT NOT NULL,
        qty TEXT NOT NULL, price TEXT NOT NULL, opened_at INTEGER NOT NULL,
        updated_at INTEGER NOT NULL, ladder_level TEXT NOT NULL DEFAULT '',
        source_order_id TEXT NOT NULL DEFAULT '', status TEXT NOT NULL DEFAULT 'OPEN'
    )""")
    connection.execute("CREATE INDEX IF NOT EXISTS inventory_lots_fifo ON inventory_lots(symbol,status,opened_at)")
    columns = {
        str(row[1])
        for row in connection.execute("PRAGMA table_info(inventory_lots)")
    }
    if "source_trade_id" not in columns:
        connection.execute(
            "ALTER TABLE inventory_lots ADD COLUMN source_trade_id TEXT NOT NULL DEFAULT ''"
        )
    if "import_batch_id" not in columns:
        connection.execute(
            "ALTER TABLE inventory_lots ADD COLUMN import_batch_id TEXT NOT NULL DEFAULT ''"
        )


def add_lot(connection: sqlite3.Connection, *, symbol: str, qty: Decimal, price: Decimal,
            ladder_level: str = "", opened_at: int | None = None,
            source_order_id: str = "", source_trade_id: str | int = "",
            import_batch_id: str = "") -> int:
    ensure_schema(connection)
    normalized_symbol = symbol.upper()
    normalized_trade_id = str(source_trade_id).strip()
    if normalized_trade_id:
        existing = connection.execute(
            "SELECT lot_id FROM inventory_lots "
            "WHERE symbol=? AND source_trade_id=? ORDER BY lot_id LIMIT 1",
            (normalized_symbol, normalized_trade_id),
        ).fetchone()
        if existing is not None:
            return int(existing[0])
    # Historical imports may provide the original BUY timestamp.
    now = int(opened_at or time.time())
    cur = connection.execute(
        "INSERT INTO inventory_lots("
        "symbol,qty,price,opened_at,updated_at,ladder_level,source_order_id,"
        "source_trade_id,import_batch_id) VALUES(?,?,?,?,?,?,?,?,?)",
        (
            normalized_symbol, str(qty), str(price), now, now, ladder_level,
            source_order_id, normalized_trade_id, import_batch_id,
        ),
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


def cost_basis_coverage(
    connection: sqlite3.Connection,
    symbol: str,
    account_qty: Decimal,
    *,
    tolerance_qty: Decimal = Decimal("0"),
) -> CostBasisCoverage:
    """Prove that account quantity is covered by priced, attributable lots.

    Rows without a positive price or source identifier are deliberately not
    counted. This prevents an arbitrary quantity-only import from authorizing
    legacy holdings management.
    """
    ensure_schema(connection)
    account = Decimal(account_qty)
    tolerance = max(Decimal("0"), Decimal(tolerance_qty))
    if not account.is_finite() or account < 0:
        raise ValueError("account quantity must be finite and non-negative")
    rows = connection.execute(
        "SELECT qty,price,source_order_id,source_trade_id FROM inventory_lots "
        "WHERE symbol=? AND status='OPEN' ORDER BY opened_at,lot_id",
        (symbol.upper(),),
    ).fetchall()
    covered_qty = Decimal("0")
    covered_cost = Decimal("0")
    incomplete_rows = 0
    for qty_text, price_text, source_order_id, source_trade_id in rows:
        qty = Decimal(str(qty_text))
        price = Decimal(str(price_text))
        if qty <= 0:
            continue
        if price <= 0 or not (
            str(source_order_id or "").strip()
            or str(source_trade_id or "").strip()
        ):
            incomplete_rows += 1
            continue
        covered_qty += qty
        covered_cost += qty * price
    delta = account - covered_qty
    covered = incomplete_rows == 0 and abs(delta) <= tolerance
    if incomplete_rows:
        reason = "inventory lots contain missing price or provenance"
    elif delta > tolerance:
        reason = "account inventory contains uncovered legacy quantity"
    elif delta < -tolerance:
        reason = "inventory lots exceed the Binance account quantity"
    else:
        reason = "covered"
    return CostBasisCoverage(
        symbol=symbol.upper(),
        account_qty=account,
        covered_qty=covered_qty,
        average_price=(covered_cost / covered_qty if covered_qty > 0 else None),
        uncovered_qty=max(Decimal("0"), delta),
        tolerance_qty=tolerance,
        covered=covered,
        reason=reason,
    )


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


def sync_exchange_fill(
    connection: sqlite3.Connection, fill: Mapping[str, Any]
) -> int | list[InventoryLot]:
    """Apply one exact Binance fill to age-aware FIFO lots idempotently."""
    symbol = str(fill["symbol"]).upper()
    execution = TradeExecution.create(
        symbol=symbol,
        side=str(fill["side"]),
        price=fill["price"],
        gross_qty=fill["qty"],
        commission_asset=str(fill.get("commission_asset") or ""),
        commission_amount=fill.get("commission_amount") or "0",
        commission_quote=fill.get("fee_quote") or "0",
        commission_value_status="exact",
    )
    if execution.side == "BUY":
        unit_cost = execution.buy_cost_quote() / execution.net_qty
        return add_lot(
            connection,
            symbol=symbol,
            qty=execution.net_qty,
            price=unit_cost,
            source_order_id=str(fill.get("order_id") or ""),
            source_trade_id=str(fill["trade_id"]),
            opened_at=int(int(fill["ts"]) / 1000),
        )
    return consume_fifo(connection, symbol, execution.net_qty)
