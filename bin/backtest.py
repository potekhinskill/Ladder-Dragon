#!/usr/bin/env python3
# Copyright (c) 2026 IURII Potekhin / Ladder Dragon. All rights reserved.
# Purpose: keep the file role and safety boundaries clear during maintenance.
"""CSV backtest with fees, slippage, latency and buy-and-hold comparison."""

import argparse
import csv
from decimal import Decimal
import json

from ladder_dragon.strategy.simulation import Candle, SimulationConfig, simulate_grid


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("csv_file", help="CSV columns: ts,open,high,low,close")
    parser.add_argument("--cash", type=Decimal, default=Decimal("1000"))
    parser.add_argument("--order", type=Decimal, default=Decimal("50"))
    parser.add_argument("--fee", type=Decimal, default=Decimal("0.00075"))
    parser.add_argument("--slippage", type=Decimal, default=Decimal("0.0005"))
    parser.add_argument("--latency-bars", type=int, default=1)
    args = parser.parse_args()
    with open(args.csv_file, newline="", encoding="utf-8") as handle:
        candles = [
            Candle(int(row["ts"]), *(Decimal(row[name]) for name in ("open", "high", "low", "close")))
            for row in csv.DictReader(handle)
        ]
    result = simulate_grid(candles, SimulationConfig(
        initial_cash=args.cash,
        order_notional=args.order,
        fee_pct=args.fee,
        slippage_pct=args.slippage,
        latency_bars=args.latency_bars,
    ))
    print(json.dumps({key: str(value) for key, value in result.__dict__.items()}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
