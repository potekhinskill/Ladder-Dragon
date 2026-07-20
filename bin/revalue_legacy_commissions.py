#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: preview and apply exact revaluation of legacy commission rows.
"""Repair legacy/unpriced commissions from exact Binance fills."""

from __future__ import annotations

import argparse
from decimal import Decimal
import json
import os
from pathlib import Path
import sqlite3

from dotenv import load_dotenv

from bin.import_legacy_cost_basis import fetch_all_trades, _require_stopped_runtime
from ladder_dragon.execution import tools_market as market
from ladder_dragon.execution import tools_stats
from ladder_dragon.execution.commission_revaluation import (
    apply_revaluation,
    build_revaluation,
    legacy_rows,
)
from ladder_dragon.execution.exchange_filters import symbol_row
from ladder_dragon.execution.executor_stats import commission_quote_value


CONFIRMATION = "REVALUE-LEGACY-COMMISSIONS"
MAINNET = "https://api.binance.com"


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Preview or apply exact Binance commission provenance repairs."
    )
    parser.add_argument("--stats-db", type=Path, required=True)
    parser.add_argument("--max-pages", type=int, default=100)
    parser.add_argument("--backup", type=Path)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--confirm", default="")
    return parser


def main() -> int:
    load_dotenv(override=False)
    args = _parser().parse_args()
    if market.BASE_URL.rstrip("/") != MAINNET:
        raise SystemExit("[FAIL] commission revaluation is restricted to Binance mainnet")
    if not args.stats_db.is_file():
        raise SystemExit(f"[FAIL] statistics database is unavailable: {args.stats_db}")
    try:
        with sqlite3.connect(args.stats_db, timeout=30) as connection:
            rows = legacy_rows(connection)
        symbols = sorted({str(row["symbol"]).upper() for row in rows})
        exchange: dict[str, dict[int, dict[str, object]]] = {}
        assets: dict[str, tuple[str, str]] = {}
        for symbol in symbols:
            trades = fetch_all_trades(symbol, max_pages=args.max_pages)
            exchange[symbol] = {int(trade["id"]): trade for trade in trades}
            info = symbol_row(
                market._public_get("/api/v3/exchangeInfo", {"symbol": symbol}),
                symbol,
            )
            assets[symbol] = (
                str(info["baseAsset"]).upper(),
                str(info["quoteAsset"]).upper(),
            )
        cache: dict[tuple[str, str, int], Decimal] = {}

        def value(symbol, asset, amount, price, timestamp):
            return commission_quote_value(
                symbol,
                asset,
                amount,
                price,
                timestamp,
                symbol_assets=lambda current: assets[current],
                public_get=market._public_get,
                cache=cache,
            )

        revaluation = build_revaluation(rows, exchange, value_commission=value)
        report = {
            "mode": "apply" if args.apply else "preview",
            "database": str(args.stats_db),
            "legacy_rows": len(rows),
            "resolved_rows": len(revaluation.repairs),
            "unresolved_rows": len(revaluation.unresolved),
            "unresolved": list(revaluation.unresolved),
            "database_written": False,
        }
        if not args.apply:
            print(json.dumps(report, indent=2, sort_keys=True))
            return 0 if not revaluation.unresolved else 2
        if args.confirm != CONFIRMATION:
            raise RuntimeError(f"--apply requires --confirm {CONFIRMATION}")
        if os.getenv("BOT_COMMISSION_REVALUATION_CONFIRMED") != "YES":
            raise RuntimeError("apply requires BOT_COMMISSION_REVALUATION_CONFIRMED=YES")
        if args.backup is None:
            raise RuntimeError("--apply requires a separate --backup path")
        if args.backup.resolve() == args.stats_db.resolve():
            raise RuntimeError("backup path must differ from the statistics database")
        if args.backup.exists():
            raise RuntimeError(f"backup already exists: {args.backup}")
        _require_stopped_runtime()
        with sqlite3.connect(args.stats_db, timeout=30) as connection:
            args.backup.parent.mkdir(parents=True, exist_ok=True)
            with sqlite3.connect(args.backup) as destination:
                connection.backup(destination)
            os.chmod(args.backup, 0o600)
            applied = apply_revaluation(
                connection,
                revaluation,
                recalculate_inventory=tools_stats.recalculate_inventory,
            )
        report["applied_rows"] = applied
        report["database_written"] = True
        print(json.dumps(report, indent=2, sort_keys=True))
        return 0
    except (KeyError, OSError, RuntimeError, ValueError, sqlite3.Error) as exc:
        raise SystemExit(f"[FAIL] {type(exc).__name__}: {exc}") from exc


if __name__ == "__main__":
    raise SystemExit(main())
