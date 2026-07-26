#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: produce a fail-closed exact PnL/benchmark report by market regime.
"""Report strategy, buy-and-hold and USDT results by historical regime."""

from __future__ import annotations

import argparse
from dataclasses import asdict
from decimal import Decimal
import json
from pathlib import Path
import sqlite3

from bin.pnl_24h import _execution, detect_ts_div, iter_trades_until
from ladder_dragon.strategy.regime_attribution import (
    RegimeSnapshot,
    TimedExecution,
    attribute_fifo_by_regime,
)


def _snapshots(path: Path, end_ms: int) -> list[RegimeSnapshot]:
    uri = f"file:{path.resolve()}?mode=ro"
    output: list[RegimeSnapshot] = []
    with sqlite3.connect(uri, uri=True, timeout=15) as connection:
        rows = connection.execute(
            """SELECT symbol,snapshot_ts_ms,feature_json
               FROM prediction_decisions
               WHERE snapshot_ts_ms<? ORDER BY snapshot_ts_ms""",
            (end_ms,),
        ).fetchall()
    for symbol, timestamp, feature_json in rows:
        payload = json.loads(feature_json)
        output.append(RegimeSnapshot(
            symbol=str(symbol).upper(),
            timestamp_ms=int(timestamp),
            regime=str(payload["regime"]).upper(),
            price=Decimal(str(payload["price"])),
        ))
    return output


def _fill_observations(
    path: Path,
    *,
    start_ms: int,
    end_ms: int,
) -> dict[str, tuple[int, int]]:
    uri = f"file:{path.resolve()}?mode=ro"
    totals: dict[str, list[int]] = {}
    with sqlite3.connect(uri, uri=True, timeout=15) as connection:
        rows = connection.execute(
            """SELECT d.feature_json,o.outcome_json
               FROM prediction_decisions d
               JOIN prediction_outcomes o
                 ON o.decision_id=d.decision_id
               WHERE d.kind='STRATEGY' AND o.horizon_min=15
                 AND d.snapshot_ts_ms>=? AND d.snapshot_ts_ms<?
                 AND o.outcome_json IS NOT NULL""",
            (start_ms, end_ms),
        ).fetchall()
    for feature_json, outcome_json in rows:
        feature = json.loads(feature_json)
        outcome = json.loads(outcome_json)
        regime = str(feature.get("regime") or "").upper()
        if regime not in {"RANGE", "TREND_UP", "TREND_DOWN", "PANIC"}:
            continue
        bucket = totals.setdefault(regime, [0, 0])
        bucket[0] += int(bool(outcome.get("buy_filled")))
        bucket[1] += 1
    return {
        regime: (values[0], values[1])
        for regime, values in totals.items()
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stats-db", type=Path, required=True)
    parser.add_argument("--prediction-db", type=Path, required=True)
    parser.add_argument("--start-ms", type=int, required=True)
    parser.add_argument("--end-ms", type=int, required=True)
    parser.add_argument(
        "--benchmark-exit-fee-pct",
        type=Decimal,
        required=True,
    )
    parser.add_argument(
        "--max-snapshot-age-ms",
        type=int,
        default=15 * 60_000,
    )
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    snapshots = _snapshots(args.prediction_db, args.end_ms)
    if not snapshots:
        raise SystemExit("no eligible regime snapshots")
    if args.max_snapshot_age_ms <= 0:
        raise SystemExit("max snapshot age must be positive")
    end_prices = {}
    for symbol in {item.symbol for item in snapshots}:
        latest = max(
            (
                item
                for item in snapshots
                if item.symbol == symbol and item.timestamp_ms < args.end_ms
            ),
            key=lambda item: item.timestamp_ms,
        )
        if args.end_ms - latest.timestamp_ms > args.max_snapshot_age_ms:
            raise SystemExit(f"stale report-end price for {symbol}")
        end_prices[symbol] = latest.price
    uri = f"file:{args.stats_db.resolve()}?mode=ro"
    with sqlite3.connect(uri, uri=True, timeout=15) as connection:
        connection.row_factory = sqlite3.Row
        divisor = detect_ts_div(connection)
        rows = list(iter_trades_until(
            connection,
            args.end_ms * divisor // 1000 - 1,
            None,
        ))
    executions = [
        TimedExecution(
            timestamp_ms=int(row["ts"]) * 1000 // divisor,
            trade=_execution(row),
        )
        for row in rows
    ]
    results = attribute_fifo_by_regime(
        executions,
        snapshots,
        window_start_ms=args.start_ms,
        window_end_ms=args.end_ms,
        end_prices=end_prices,
        benchmark_exit_fee_pct=args.benchmark_exit_fee_pct,
        max_snapshot_age_ms=args.max_snapshot_age_ms,
        fill_observations=_fill_observations(
            args.prediction_db,
            start_ms=args.start_ms,
            end_ms=args.end_ms,
        ),
    )
    payload = {
        "schema_version": 1,
        "window_start_ms": args.start_ms,
        "window_end_ms": args.end_ms,
        "benchmark": {
            "buy_hold_exit_fee_pct": str(args.benchmark_exit_fee_pct),
            "usdt_pnl": "0",
        },
        "regimes": [
            {
                key: str(value) if isinstance(value, Decimal) else value
                for key, value in asdict(item).items()
            }
            for item in results
        ],
    }
    encoded = json.dumps(payload, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(encoded, encoding="utf-8")
    else:
        print(encoded, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
