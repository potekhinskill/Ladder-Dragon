# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: build and atomically apply verified legacy inventory cost-basis plans.
"""Preview-first legacy cost-basis reconstruction from exact Binance fills."""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import tempfile
import time
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Iterable, Mapping

from ladder_dragon.execution.inventory_lots import cost_basis_coverage, ensure_schema
from ladder_dragon.execution.trade_accounting import base_asset


ZERO = Decimal("0")


def _decimal(value: object, *, name: str) -> Decimal:
    try:
        result = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValueError(f"invalid {name}") from exc
    if not result.is_finite():
        raise ValueError(f"non-finite {name}")
    return result


def _canonical_hash(payload: object) -> str:
    encoded = json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True)
class ImportedLot:
    source_trade_id: int
    source_order_id: str
    quantity: Decimal
    unit_cost: Decimal
    opened_at_ms: int

    def as_dict(self) -> dict[str, object]:
        return {
            "source_trade_id": self.source_trade_id,
            "source_order_id": self.source_order_id,
            "quantity": format(self.quantity, "f"),
            "unit_cost": format(self.unit_cost, "f"),
            "opened_at_ms": self.opened_at_ms,
        }


@dataclass(frozen=True)
class CostBasisImportPlan:
    schema_version: int
    symbol: str
    base_asset: str
    quote_asset: str
    account_quantity: Decimal
    reconstructed_quantity: Decimal
    tolerance_quantity: Decimal
    prehistory_quantity: Decimal
    unmanaged_dust_quantity: Decimal
    unmanaged_dust_limit: Decimal
    history_reset_trade_id: int
    weighted_average: Decimal
    first_trade_id: int
    last_trade_id: int
    trade_count: int
    history_sha256: str
    lots: tuple[ImportedLot, ...]
    created_at: int
    plan_sha256: str

    def unsigned_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "symbol": self.symbol,
            "base_asset": self.base_asset,
            "quote_asset": self.quote_asset,
            "account_quantity": format(self.account_quantity, "f"),
            "reconstructed_quantity": format(
                self.reconstructed_quantity, "f"
            ),
            "tolerance_quantity": format(self.tolerance_quantity, "f"),
            "prehistory_quantity": format(self.prehistory_quantity, "f"),
            "unmanaged_dust_quantity": format(
                self.unmanaged_dust_quantity, "f"
            ),
            "unmanaged_dust_limit": format(self.unmanaged_dust_limit, "f"),
            "history_reset_trade_id": self.history_reset_trade_id,
            "weighted_average": format(self.weighted_average, "f"),
            "first_trade_id": self.first_trade_id,
            "last_trade_id": self.last_trade_id,
            "trade_count": self.trade_count,
            "history_sha256": self.history_sha256,
            "lots": [lot.as_dict() for lot in self.lots],
            "created_at": self.created_at,
        }

    def as_dict(self) -> dict[str, object]:
        return {**self.unsigned_dict(), "plan_sha256": self.plan_sha256}

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "CostBasisImportPlan":
        if int(payload.get("schema_version", 0)) != 2:
            raise ValueError("unsupported cost-basis plan schema")
        lots = tuple(
            ImportedLot(
                source_trade_id=int(row["source_trade_id"]),
                source_order_id=str(row["source_order_id"]),
                quantity=_decimal(row["quantity"], name="lot quantity"),
                unit_cost=_decimal(row["unit_cost"], name="lot unit cost"),
                opened_at_ms=int(row["opened_at_ms"]),
            )
            for row in payload.get("lots", [])
        )
        plan = cls(
            schema_version=2,
            symbol=str(payload["symbol"]).upper(),
            base_asset=str(payload["base_asset"]).upper(),
            quote_asset=str(payload["quote_asset"]).upper(),
            account_quantity=_decimal(
                payload["account_quantity"], name="account quantity"
            ),
            reconstructed_quantity=_decimal(
                payload["reconstructed_quantity"],
                name="reconstructed quantity",
            ),
            tolerance_quantity=_decimal(
                payload["tolerance_quantity"], name="tolerance quantity"
            ),
            prehistory_quantity=_decimal(
                payload["prehistory_quantity"], name="prehistory quantity"
            ),
            unmanaged_dust_quantity=_decimal(
                payload["unmanaged_dust_quantity"],
                name="unmanaged dust quantity",
            ),
            unmanaged_dust_limit=_decimal(
                payload["unmanaged_dust_limit"],
                name="unmanaged dust limit",
            ),
            history_reset_trade_id=int(payload["history_reset_trade_id"]),
            weighted_average=_decimal(
                payload["weighted_average"], name="weighted average"
            ),
            first_trade_id=int(payload["first_trade_id"]),
            last_trade_id=int(payload["last_trade_id"]),
            trade_count=int(payload["trade_count"]),
            history_sha256=str(payload["history_sha256"]),
            lots=lots,
            created_at=int(payload["created_at"]),
            plan_sha256=str(payload["plan_sha256"]),
        )
        if _canonical_hash(plan.unsigned_dict()) != plan.plan_sha256:
            raise ValueError("cost-basis plan hash mismatch")
        return plan


def _normalized_trade(
    symbol: str, row: Mapping[str, Any], base: str, quote: str
) -> dict[str, object]:
    trade_id = int(row["id"])
    order_id = str(row.get("orderId") or "").strip()
    if trade_id < 0 or not order_id:
        raise ValueError("trade has no stable exchange provenance")
    side = "BUY" if bool(row.get("isBuyer")) else "SELL"
    price = _decimal(row["price"], name="trade price")
    gross_qty = _decimal(row["qty"], name="trade quantity")
    commission = _decimal(
        row.get("commission", "0") or "0", name="commission"
    )
    commission_asset = str(row.get("commissionAsset") or "").upper()
    if price <= 0 or gross_qty <= 0 or commission < 0:
        raise ValueError("trade price/quantity/commission is invalid")
    if commission > 0 and not commission_asset:
        raise ValueError("positive commission has no asset")
    if commission_asset == quote:
        commission_quote = commission
        fee_status = "exact"
    elif commission_asset == base:
        commission_quote = commission * price
        fee_status = "exact"
    elif commission == 0:
        commission_quote = ZERO
        fee_status = "none"
    else:
        raw_quote = row.get("commissionQuote")
        if raw_quote is None:
            raise ValueError(
                f"trade {trade_id} has unpriced {commission_asset} commission"
            )
        commission_quote = _decimal(
            raw_quote, name="converted commission quote"
        )
        fee_status = str(row.get("commissionValueStatus") or "converted")
        if commission_quote <= 0:
            raise ValueError(
                f"trade {trade_id} has invalid converted commission"
            )
    return {
        "symbol": symbol,
        "id": trade_id,
        "order_id": order_id,
        "time": int(row["time"]),
        "side": side,
        "price": format(price, "f"),
        "gross_qty": format(gross_qty, "f"),
        "commission": format(commission, "f"),
        "commission_asset": commission_asset,
        "commission_quote": format(commission_quote, "f"),
        "commission_value_status": fee_status,
    }


def build_cost_basis_plan(
    symbol: str,
    *,
    account_quantity: Decimal,
    tolerance_quantity: Decimal,
    unmanaged_dust_limit: Decimal = ZERO,
    trades: Iterable[Mapping[str, Any]],
    quote_asset: str = "USDT",
    created_at: int | None = None,
) -> CostBasisImportPlan:
    """Reconstruct exact remaining FIFO lots and require account agreement."""
    normalized_symbol = symbol.strip().upper()
    base = base_asset(normalized_symbol)
    quote = quote_asset.strip().upper()
    if not normalized_symbol.endswith(quote):
        raise ValueError("symbol does not match the requested quote asset")
    account = _decimal(account_quantity, name="account quantity")
    tolerance = _decimal(tolerance_quantity, name="tolerance quantity")
    dust_limit = _decimal(
        unmanaged_dust_limit, name="unmanaged dust limit"
    )
    if account < 0 or tolerance < 0 or dust_limit < 0:
        raise ValueError("account quantity and tolerance must be non-negative")

    normalized = [
        _normalized_trade(normalized_symbol, row, base, quote) for row in trades
    ]
    normalized.sort(key=lambda row: (int(row["time"]), int(row["id"])))
    if not normalized:
        raise ValueError("Binance trade history is empty")
    ids = [int(row["id"]) for row in normalized]
    if len(ids) != len(set(ids)):
        raise ValueError("duplicate Binance trade IDs")

    running = ZERO
    minimum_running = ZERO
    reset_trade_id = 0
    for trade in normalized:
        gross = Decimal(str(trade["gross_qty"]))
        commission = Decimal(str(trade["commission"]))
        commission_asset = str(trade["commission_asset"])
        inventory_qty = (
            gross - commission
            if trade["side"] == "BUY" and commission_asset == base
            else gross + commission
            if trade["side"] == "SELL" and commission_asset == base
            else gross
        )
        running += inventory_qty if trade["side"] == "BUY" else -inventory_qty
        if running < minimum_running:
            minimum_running = running
            reset_trade_id = int(trade["id"])

    # A negative historical prefix proves that inventory existed before the
    # first returned trade. Seed only that mathematically required quantity.
    # The seed must be fully consumed at the minimum-running trade, so no
    # unknown-price lot can survive into the imported current position.
    prehistory = max(ZERO, -minimum_running)
    reconstructed_target = running + prehistory
    unmanaged_dust = account - reconstructed_target
    if unmanaged_dust < -tolerance:
        raise ValueError(
            "Binance account is below reconstructed history: "
            f"account={account} reconstructed={reconstructed_target} "
            f"delta={unmanaged_dust} tolerance={tolerance}"
        )
    if unmanaged_dust < 0:
        unmanaged_dust = ZERO
    if unmanaged_dust > tolerance and (
        dust_limit <= 0 or unmanaged_dust >= dust_limit
    ):
        raise ValueError(
            "unexplained account quantity is not quarantinable dust: "
            f"quantity={unmanaged_dust} limit={dust_limit}"
        )

    open_lots: list[dict[str, object]] = []
    if prehistory > 0:
        open_lots.append({
            "source_trade_id": 0,
            "source_order_id": "prehistory-unpriced",
            "quantity": prehistory,
            "unit_cost": ZERO,
            "opened_at_ms": int(normalized[0]["time"]) - 1,
            "unpriced_prehistory": True,
        })
    for trade in normalized:
        price = Decimal(str(trade["price"]))
        gross = Decimal(str(trade["gross_qty"]))
        commission = Decimal(str(trade["commission"]))
        commission_quote = Decimal(str(trade["commission_quote"]))
        commission_asset = str(trade["commission_asset"])
        if trade["side"] == "BUY":
            net_qty = gross - commission if commission_asset == base else gross
            if net_qty <= 0:
                raise ValueError(f"trade {trade['id']} BUY net quantity is zero")
            cash_fee = ZERO if commission_asset == base else commission_quote
            unit_cost = (price * gross + cash_fee) / net_qty
            open_lots.append(
                {
                    "source_trade_id": int(trade["id"]),
                    "source_order_id": str(trade["order_id"]),
                    "quantity": net_qty,
                    "unit_cost": unit_cost,
                    "opened_at_ms": int(trade["time"]),
                    "unpriced_prehistory": False,
                }
            )
            continue

        remaining = gross + commission if commission_asset == base else gross
        while remaining > 0 and open_lots:
            lot = open_lots[0]
            lot_qty = Decimal(str(lot["quantity"]))
            used = min(lot_qty, remaining)
            lot["quantity"] = lot_qty - used
            remaining -= used
            if Decimal(str(lot["quantity"])) == 0:
                open_lots.pop(0)
        if remaining > 0:
            raise ValueError(
                f"trade {trade['id']} SELL exceeds reconstructed history by "
                f"{format(remaining, 'f')} {base}"
            )

    surviving_prehistory = sum(
        (
            Decimal(str(row["quantity"]))
            for row in open_lots
            if bool(row.get("unpriced_prehistory"))
        ),
        ZERO,
    )
    if surviving_prehistory > 0:
        raise ValueError(
            "unpriced prehistory inventory survives into the current position: "
            f"quantity={surviving_prehistory}"
        )

    lots = tuple(
        ImportedLot(
            source_trade_id=int(row["source_trade_id"]),
            source_order_id=str(row["source_order_id"]),
            quantity=Decimal(str(row["quantity"])),
            unit_cost=Decimal(str(row["unit_cost"])),
            opened_at_ms=int(row["opened_at_ms"]),
        )
        for row in open_lots
        if Decimal(str(row["quantity"])) > 0
        and not bool(row.get("unpriced_prehistory"))
    )
    reconstructed = sum((lot.quantity for lot in lots), ZERO)
    if reconstructed <= 0 or not lots:
        raise ValueError("no current priced FIFO lots remain after history reset")
    delta = account - reconstructed
    allowed_delta = tolerance + unmanaged_dust
    if abs(delta) > allowed_delta:
        raise ValueError(
            "reconstructed quantity does not match Binance account: "
            f"account={account} reconstructed={reconstructed} delta={delta} "
            f"tolerance={allowed_delta}"
        )
    weighted_average = (
        sum((lot.quantity * lot.unit_cost for lot in lots), ZERO)
        / reconstructed
        if reconstructed > 0
        else ZERO
    )
    history_sha = _canonical_hash(normalized)
    now = int(created_at or time.time())
    provisional = CostBasisImportPlan(
        schema_version=2,
        symbol=normalized_symbol,
        base_asset=base,
        quote_asset=quote,
        account_quantity=account,
        reconstructed_quantity=reconstructed,
        tolerance_quantity=tolerance,
        prehistory_quantity=prehistory,
        unmanaged_dust_quantity=unmanaged_dust,
        unmanaged_dust_limit=dust_limit,
        history_reset_trade_id=reset_trade_id,
        weighted_average=weighted_average,
        first_trade_id=min(ids),
        last_trade_id=max(ids),
        trade_count=len(ids),
        history_sha256=history_sha,
        lots=lots,
        created_at=now,
        plan_sha256="",
    )
    return CostBasisImportPlan(
        **{
            **provisional.__dict__,
            "plan_sha256": _canonical_hash(provisional.unsigned_dict()),
        }
    )


def write_plan(path: str | Path, plan: CostBasisImportPlan) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    temp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=target.parent,
            prefix=f".{target.name}.",
            delete=False,
        ) as handle:
            temp_path = Path(handle.name)
            handle.write(
                json.dumps(plan.as_dict(), indent=2, sort_keys=True) + "\n"
            )
            handle.flush()
            os.fsync(handle.fileno())
        temp_path.chmod(0o600)
        os.replace(temp_path, target)
    except OSError:
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)
        raise


def read_plan(path: str | Path) -> CostBasisImportPlan:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("cost-basis plan must be a JSON object")
    return CostBasisImportPlan.from_dict(payload)


def _ensure_import_schema(connection: sqlite3.Connection) -> None:
    ensure_schema(connection)
    inventory_columns = {
        str(row[1]) for row in connection.execute("PRAGMA table_info(inventory)")
    }
    if not {"qty_text", "avg_cost_text", "realized_pnl_text"} <= inventory_columns:
        raise RuntimeError(
            "statistics database must be migrated before cost-basis import"
        )
    columns = {
        str(row[1]) for row in connection.execute("PRAGMA table_info(inventory_lots)")
    }
    if "source_trade_id" not in columns:
        connection.execute(
            "ALTER TABLE inventory_lots ADD COLUMN source_trade_id TEXT NOT NULL DEFAULT ''"
        )
    if "import_batch_id" not in columns:
        connection.execute(
            "ALTER TABLE inventory_lots ADD COLUMN import_batch_id TEXT NOT NULL DEFAULT ''"
        )
    connection.execute(
        "CREATE TABLE IF NOT EXISTS inventory_lot_imports("
        "batch_id TEXT PRIMARY KEY, symbol TEXT NOT NULL, created_at INTEGER NOT NULL, "
        "plan_sha256 TEXT NOT NULL UNIQUE, history_sha256 TEXT NOT NULL, "
        "account_qty TEXT NOT NULL, reconstructed_qty TEXT NOT NULL, "
        "weighted_average TEXT NOT NULL, last_trade_id INTEGER NOT NULL, "
        "baseline_realized_pnl TEXT NOT NULL DEFAULT '0', "
        "prehistory_qty TEXT NOT NULL DEFAULT '0', "
        "unmanaged_dust_qty TEXT NOT NULL DEFAULT '0', "
        "history_reset_trade_id INTEGER NOT NULL DEFAULT 0, "
        "status TEXT NOT NULL)"
    )
    import_columns = {
        str(row[1])
        for row in connection.execute(
            "PRAGMA table_info(inventory_lot_imports)"
        )
    }
    for name, definition in (
        ("prehistory_qty", "TEXT NOT NULL DEFAULT '0'"),
        ("unmanaged_dust_qty", "TEXT NOT NULL DEFAULT '0'"),
        ("history_reset_trade_id", "INTEGER NOT NULL DEFAULT 0"),
    ):
        if name not in import_columns:
            connection.execute(
                f"ALTER TABLE inventory_lot_imports ADD COLUMN {name} {definition}"
            )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS inventory_lots_import_trade "
        "ON inventory_lots(symbol,source_trade_id,import_batch_id)"
    )


def apply_cost_basis_plan(
    connection: sqlite3.Connection, plan: CostBasisImportPlan
) -> str:
    """Atomically supersede open lots with a revalidated, hashed plan."""
    if _canonical_hash(plan.unsigned_dict()) != plan.plan_sha256:
        raise ValueError("cost-basis plan hash mismatch")
    batch_id = f"basis-{plan.plan_sha256[:24]}"
    _ensure_import_schema(connection)
    connection.execute("BEGIN IMMEDIATE")
    try:
        # Recheck after obtaining the write lock so concurrent operator
        # invocations remain idempotent rather than racing the unique index.
        existing = connection.execute(
            "SELECT batch_id FROM inventory_lot_imports WHERE plan_sha256=?",
            (plan.plan_sha256,),
        ).fetchone()
        if existing:
            connection.commit()
            return str(existing[0])
        exact_inventory_view = connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type='view' "
            "AND name='inventory_exact'"
        ).fetchone()
        if exact_inventory_view:
            inventory_row = connection.execute(
                "SELECT realized_pnl_text FROM inventory_exact WHERE symbol=?",
                (plan.symbol,),
            ).fetchone()
        else:
            inventory_columns = {
                str(row[1])
                for row in connection.execute("PRAGMA table_info(inventory)")
            }
            realized_expression = (
                "COALESCE(NULLIF(realized_pnl_text,''),"
                "CAST(realized_pnl AS TEXT))"
                if "realized_pnl_text" in inventory_columns
                else "CAST(realized_pnl AS TEXT)"
            )
            inventory_row = connection.execute(
                f"SELECT {realized_expression} FROM inventory WHERE symbol=?",
                (plan.symbol,),
            ).fetchone()
        baseline_realized = (
            _decimal(inventory_row[0], name="baseline realized PnL")
            if inventory_row
            else ZERO
        )
        connection.execute(
            "UPDATE inventory_lots SET status='SUPERSEDED',updated_at=? "
            "WHERE symbol=? AND status='OPEN'",
            (int(time.time()), plan.symbol),
        )
        for lot in plan.lots:
            connection.execute(
                "INSERT INTO inventory_lots("
                "symbol,qty,price,opened_at,updated_at,ladder_level,"
                "source_order_id,status,source_trade_id,import_batch_id"
                ") VALUES(?,?,?,?,?,?,?,?,?,?)",
                (
                    plan.symbol,
                    format(lot.quantity, "f"),
                    format(lot.unit_cost, "f"),
                    int(lot.opened_at_ms // 1000),
                    int(time.time()),
                    "legacy-import",
                    lot.source_order_id,
                    "OPEN",
                    str(lot.source_trade_id),
                    batch_id,
                ),
            )
        verified = cost_basis_coverage(
            connection,
            plan.symbol,
            plan.account_quantity,
            tolerance_qty=(
                plan.tolerance_quantity + plan.unmanaged_dust_quantity
            ),
        )
        if not verified.covered or verified.average_price is None:
            raise RuntimeError(
                f"post-import verification failed: {verified.reason}"
            )
        if abs(verified.average_price - plan.weighted_average) > Decimal("1e-18"):
            raise RuntimeError("post-import weighted average mismatch")
        connection.execute(
            "INSERT INTO inventory_lot_imports("
            "batch_id,symbol,created_at,plan_sha256,history_sha256,account_qty,"
            "reconstructed_qty,weighted_average,last_trade_id,"
            "baseline_realized_pnl,prehistory_qty,unmanaged_dust_qty,"
            "history_reset_trade_id,status) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                batch_id,
                plan.symbol,
                int(time.time()),
                plan.plan_sha256,
                plan.history_sha256,
                format(plan.account_quantity, "f"),
                format(plan.reconstructed_quantity, "f"),
                format(plan.weighted_average, "f"),
                plan.last_trade_id,
                format(baseline_realized, "f"),
                format(plan.prehistory_quantity, "f"),
                format(plan.unmanaged_dust_quantity, "f"),
                plan.history_reset_trade_id,
                "APPLIED",
            ),
        )
        inventory_columns = {
            str(row[1]) for row in connection.execute("PRAGMA table_info(inventory)")
        }
        if {"qty", "avg_cost", "realized_pnl"} <= inventory_columns:
            connection.execute(
                "INSERT INTO inventory("
                "symbol,qty,avg_cost,realized_pnl,last_trade_id,"
                "qty_text,avg_cost_text,realized_pnl_text"
                ") VALUES(?,?,?,?,?,?,?,?) "
                "ON CONFLICT(symbol) DO UPDATE SET "
                "qty=excluded.qty,avg_cost=excluded.avg_cost,"
                "last_trade_id=excluded.last_trade_id,"
                "qty_text=excluded.qty_text,avg_cost_text=excluded.avg_cost_text",
                (
                    plan.symbol, float(plan.reconstructed_quantity),
                    float(plan.weighted_average), float(baseline_realized),
                    plan.last_trade_id, format(plan.reconstructed_quantity, "f"),
                    format(plan.weighted_average, "f"),
                    format(baseline_realized, "f"),
                ),
            )
        else:
            connection.execute(
                "INSERT INTO inventory("
                "symbol,qty_text,avg_cost_text,realized_pnl_text,last_trade_id"
                ") VALUES(?,?,?,?,?) ON CONFLICT(symbol) DO UPDATE SET "
                "qty_text=excluded.qty_text,avg_cost_text=excluded.avg_cost_text,"
                "last_trade_id=excluded.last_trade_id",
                (
                    plan.symbol, format(plan.reconstructed_quantity, "f"),
                    format(plan.weighted_average, "f"),
                    format(baseline_realized, "f"), plan.last_trade_id,
                ),
            )
    except (ArithmeticError, RuntimeError, sqlite3.Error, TypeError, ValueError):
        connection.rollback()
        raise
    connection.commit()
    return batch_id
