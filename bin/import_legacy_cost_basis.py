#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: preview and apply a verified legacy holdings cost-basis import.
"""Two-phase Binance history to FIFO cost-basis importer."""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import time
from decimal import Decimal
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

from ladder_dragon.execution.cost_basis_import import (
    apply_cost_basis_plan,
    build_cost_basis_plan,
    read_plan,
    write_plan,
)
from ladder_dragon.execution.exchange_filters import (
    symbol_row as exchange_symbol_row,
)
from ladder_dragon.execution.executor_stats import commission_quote_value
from ladder_dragon.execution import tools_market as market


MAINNET = "https://api.binance.com"


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Preview or atomically apply a legacy FIFO cost basis. Preview is "
            "the default and never writes the trading database."
        )
    )
    parser.add_argument("--symbol", required=True)
    parser.add_argument("--plan", required=True, help="JSON plan path")
    parser.add_argument("--stats-db", default="")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--max-pages", type=int, default=100)
    parser.add_argument(
        "--tolerance-pct", type=Decimal, default=Decimal("0")
    )
    return parser


def fetch_all_trades(symbol: str, *, max_pages: int) -> list[dict[str, Any]]:
    if max_pages < 1 or max_pages > 1000:
        raise ValueError("max-pages must be in [1,1000]")
    rows: list[dict[str, Any]] = []
    cursor = 0
    for page in range(max_pages):
        batch = market._signed_get(
            "/api/v3/myTrades",
            {"symbol": symbol, "fromId": cursor, "limit": 1000},
        )
        if not isinstance(batch, list):
            raise RuntimeError("Binance myTrades returned an invalid payload")
        if not batch:
            return rows
        valid = [dict(row) for row in batch if isinstance(row, dict)]
        if len(valid) != len(batch):
            raise RuntimeError("Binance myTrades contains a non-object row")
        ids = [int(row["id"]) for row in valid]
        if ids != sorted(ids) or ids[0] < cursor:
            raise RuntimeError("Binance myTrades pagination is not monotonic")
        rows.extend(valid)
        next_cursor = ids[-1] + 1
        if next_cursor <= cursor:
            raise RuntimeError("Binance myTrades cursor did not advance")
        cursor = next_cursor
        if len(valid) < 1000:
            return rows
    raise RuntimeError(
        f"trade history exceeds --max-pages={max_pages}; preview is incomplete"
    )


def _account_quantity(symbol: str, account: dict[str, Any]) -> Decimal:
    row = exchange_symbol_row(
        market._public_get("/api/v3/exchangeInfo", {"symbol": symbol}), symbol
    )
    base = str(row["baseAsset"]).upper()
    balance = next(
        (
            item
            for item in account.get("balances", [])
            if isinstance(item, dict) and str(item.get("asset")).upper() == base
        ),
        None,
    )
    if balance is None:
        return Decimal("0")
    return Decimal(str(balance.get("free", "0"))) + Decimal(
        str(balance.get("locked", "0"))
    )


def _unmanaged_dust_limit(symbol: str) -> Decimal:
    row = exchange_symbol_row(
        market._public_get("/api/v3/exchangeInfo", {"symbol": symbol}), symbol
    )
    lot_filter = next(
        (
            item
            for item in row.get("filters", [])
            if isinstance(item, dict) and item.get("filterType") == "LOT_SIZE"
        ),
        None,
    )
    if lot_filter is None:
        raise RuntimeError("LOT_SIZE filter is unavailable")
    step = Decimal(str(lot_filter.get("stepSize", "0")))
    if not step.is_finite() or step <= 0:
        raise RuntimeError("LOT_SIZE stepSize is invalid")
    return step


def _tolerance(symbol: str, account_qty: Decimal, pct: Decimal) -> Decimal:
    del symbol
    if not pct.is_finite() or pct < 0 or pct > Decimal("0.000001"):
        raise ValueError("tolerance-pct must be finite and in [0,0.000001]")
    return account_qty * pct


def _value_commissions(symbol: str, trades: list[dict[str, Any]]) -> None:
    row = exchange_symbol_row(
        market._public_get("/api/v3/exchangeInfo", {"symbol": symbol}), symbol
    )
    assets = (str(row["baseAsset"]).upper(), str(row["quoteAsset"]).upper())
    cache: dict[tuple[str, str, int], Decimal] = {}
    for trade in trades:
        amount = Decimal(str(trade.get("commission", "0") or "0"))
        asset = str(trade.get("commissionAsset") or "").upper()
        price = Decimal(str(trade["price"]))
        fee_quote, status = commission_quote_value(
            symbol,
            asset,
            amount,
            price,
            int(trade["time"]),
            symbol_assets=lambda _: assets,
            public_get=market._public_get,
            cache=cache,
        )
        if fee_quote is None or status == "unpriced":
            raise RuntimeError(
                f"trade {trade.get('id')} has an unpriced {asset} commission"
            )
        trade["commissionQuote"] = format(fee_quote, "f")
        trade["commissionValueStatus"] = status


def build_live_plan(
    symbol: str,
    *,
    tolerance_pct: Decimal,
    max_pages: int,
    created_at: int | None = None,
):
    if market.BASE_URL.rstrip("/") != MAINNET:
        raise RuntimeError("legacy cost-basis import is restricted to Binance mainnet")
    open_before = market._signed_get(
        "/api/v3/openOrders", {"symbol": symbol}
    )
    if not isinstance(open_before, list):
        raise RuntimeError("Binance openOrders returned an invalid payload")
    if open_before:
        raise RuntimeError("cost-basis import requires zero open symbol orders")
    account_before = market._signed_get("/api/v3/account")
    if (
        not isinstance(account_before, dict)
        or account_before.get("canTrade") is not True
    ):
        raise RuntimeError("Binance account is unavailable or cannot trade")
    quantity_before = _account_quantity(symbol, account_before)
    trades = fetch_all_trades(symbol, max_pages=max_pages)
    _value_commissions(symbol, trades)
    account_after = market._signed_get("/api/v3/account")
    open_after = market._signed_get(
        "/api/v3/openOrders", {"symbol": symbol}
    )
    if not isinstance(account_after, dict) or not isinstance(open_after, list):
        raise RuntimeError("Binance verification snapshot is invalid")
    if open_after:
        raise RuntimeError("an order appeared during cost-basis reconstruction")
    account_qty = _account_quantity(symbol, account_after)
    if account_qty != quantity_before:
        raise RuntimeError("account quantity changed during cost-basis reconstruction")
    return build_cost_basis_plan(
        symbol,
        account_quantity=account_qty,
        tolerance_quantity=_tolerance(symbol, account_qty, tolerance_pct),
        unmanaged_dust_limit=_unmanaged_dust_limit(symbol),
        trades=trades,
        quote_asset="USDT",
        created_at=created_at,
    )


def _require_stopped_runtime() -> None:
    if os.getenv("BOT_SERVICE_STOPPED_CONFIRMED") != "YES":
        raise RuntimeError("apply requires BOT_SERVICE_STOPPED_CONFIRMED=YES")
    status_path = Path(os.getenv("BOT_RUN_DIR", "/run/mybot")) / "ai_status.json"
    if not status_path.exists():
        return
    payload = json.loads(status_path.read_text(encoding="utf-8"))
    updated = str(payload.get("updated_at") or "")
    if str(payload.get("state") or "").upper() == "RUNNING":
        try:
            from datetime import datetime

            age = time.time() - datetime.fromisoformat(
                updated.replace("Z", "+00:00")
            ).timestamp()
        except (TypeError, ValueError):
            age = 0
        if age < 120:
            raise RuntimeError("fresh RUNNING heartbeat found; stop mybot before apply")


def main() -> int:
    load_dotenv(override=False)
    args = _parser().parse_args()
    symbol = args.symbol.strip().upper()
    if not symbol.endswith("USDT") or not symbol.isalnum():
        raise SystemExit("[FAIL] only an alphanumeric *USDT symbol is supported")
    plan_path = Path(args.plan)
    try:
        if not args.apply:
            plan = build_live_plan(
                symbol,
                tolerance_pct=args.tolerance_pct,
                max_pages=args.max_pages,
            )
            write_plan(plan_path, plan)
            print(json.dumps({
                "mode": "preview",
                "symbol": plan.symbol,
                "trade_count": plan.trade_count,
                "open_lot_count": len(plan.lots),
                "account_quantity": format(plan.account_quantity, "f"),
                "managed_quantity": format(
                    plan.reconstructed_quantity, "f"
                ),
                "prehistory_quantity": format(
                    plan.prehistory_quantity, "f"
                ),
                "unmanaged_dust_quantity": format(
                    plan.unmanaged_dust_quantity, "f"
                ),
                "history_reset_trade_id": plan.history_reset_trade_id,
                "weighted_average": format(plan.weighted_average, "f"),
                "plan_sha256": plan.plan_sha256,
                "plan": str(plan_path),
                "database_written": False,
            }, indent=2, sort_keys=True))
            return 0

        if os.getenv("BOT_COST_BASIS_IMPORT_CONFIRMED") != "YES":
            raise RuntimeError("apply requires BOT_COST_BASIS_IMPORT_CONFIRMED=YES")
        _require_stopped_runtime()
        saved = read_plan(plan_path)
        if saved.symbol != symbol:
            raise RuntimeError("plan symbol does not match --symbol")
        fresh = build_live_plan(
            symbol,
            tolerance_pct=args.tolerance_pct,
            max_pages=args.max_pages,
            created_at=saved.created_at,
        )
        if fresh.plan_sha256 != saved.plan_sha256:
            raise RuntimeError("Binance state changed after preview; create a new plan")
        db_path = args.stats_db or os.getenv("BOT_STATS_DB", "")
        if not db_path:
            raise RuntimeError("BOT_STATS_DB or --stats-db is required")
        with sqlite3.connect(db_path, timeout=30) as connection:
            batch_id = apply_cost_basis_plan(connection, fresh)
        print(json.dumps({
            "mode": "apply",
            "symbol": fresh.symbol,
            "batch_id": batch_id,
            "plan_sha256": fresh.plan_sha256,
            "account_quantity": format(fresh.account_quantity, "f"),
            "weighted_average": format(fresh.weighted_average, "f"),
            "database_written": True,
        }, indent=2, sort_keys=True))
        return 0
    except (KeyError, OSError, RuntimeError, ValueError, sqlite3.Error) as exc:
        raise SystemExit(f"[FAIL] {type(exc).__name__}: {exc}") from exc


if __name__ == "__main__":
    raise SystemExit(main())
