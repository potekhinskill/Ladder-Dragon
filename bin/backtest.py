#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: run historical strategy simulations.
"""CSV backtest with fees, slippage, latency and buy-and-hold comparison."""

import argparse
import csv
from decimal import Decimal
import json
import math

from ladder_dragon.strategy.simulation import Candle, SimulationConfig, simulate_grid
from ladder_dragon.strategy.market_replay import (
    archive_sha256,
    load_jsonl_archive,
    read_calibration,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("csv_file", help="CSV columns: ts,open,high,low,close")
    parser.add_argument("--cash", type=Decimal, default=Decimal("1000"))
    parser.add_argument("--order", type=Decimal, default=Decimal("50"))
    parser.add_argument("--fee", type=Decimal, default=Decimal("0.00075"))
    parser.add_argument("--slippage", type=Decimal, default=Decimal("0.0005"))
    parser.add_argument("--latency-bars", type=int, default=1)
    parser.add_argument("--archive", help="optional Binance replay JSONL")
    parser.add_argument("--calibration", help="eligible calibration JSON")
    args = parser.parse_args()
    with open(args.csv_file, newline="", encoding="utf-8") as handle:
        candles = [
            Candle(int(row["ts"]), *(Decimal(row[name]) for name in ("open", "high", "low", "close")))
            for row in csv.DictReader(handle)
        ]
    events = load_jsonl_archive(args.archive) if args.archive else None
    config_values = {
        "initial_cash": args.cash,
        "order_notional": args.order,
        "fee_pct": args.fee,
        "slippage_pct": args.slippage,
        "latency_bars": args.latency_bars,
    }
    calibration = None
    if args.calibration:
        calibration = read_calibration(args.calibration)
        if not calibration.eligible:
            parser.error(
                "calibration is not eligible: " + "; ".join(calibration.reasons)
            )
        if len(candles) < 2:
            parser.error("at least two candles are required for latency calibration")
        if args.archive and archive_sha256(args.archive) != calibration.archive_sha256:
            parser.error("calibration archive hash does not match --archive")
        bar_ms = max(1, abs(int(candles[1].ts) - int(candles[0].ts)))
        # Unix timestamps below this boundary are seconds, regardless of bar
        # duration (daily bars must not be mistaken for 86-second bars).
        if max(abs(int(candles[0].ts)), abs(int(candles[1].ts))) < 10_000_000_000:
            bar_ms *= 1000
        config_values.update({
            "spread_pct": calibration.spread_pct,
            "slippage_pct": calibration.slippage_pct,
            "participation_rate": calibration.participation_rate,
            "partial_fill_ratio": calibration.partial_fill_ratio,
            "market_impact_bps": calibration.market_impact_bps,
            "latency_bars": max(1, math.ceil(calibration.latency_ms_p95 / bar_ms)),
        })
    result = simulate_grid(candles, SimulationConfig(
        **config_values,
    ), market_events=events)
    output = {key: str(value) for key, value in result.__dict__.items()}
    output["calibration"] = (
        calibration.as_dict() if calibration is not None else None
    )
    print(json.dumps(output, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
