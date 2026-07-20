#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: run historical strategy simulations.
"""CSV backtest with fees, slippage, latency and buy-and-hold comparison."""

import argparse
import csv
from decimal import Decimal
from dataclasses import fields
import hashlib
import json
import math
from pathlib import Path
import time

from ladder_dragon.strategy.simulation import Candle, SimulationConfig, simulate_grid
from ladder_dragon.strategy.market_replay import (
    archive_sha256,
    load_jsonl_archive,
    read_calibration,
)
from product_version import __version__


REPORT_SCHEMA_VERSION = 2
MARKET_IMPACT_BPS_DIVISOR = Decimal("10000")


def _file_sha256(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _config_dict(config: SimulationConfig) -> dict[str, object]:
    return {
        field.name: (
            format(value, "f") if isinstance(value, Decimal) else value
        )
        for field in fields(config)
        for value in (getattr(config, field.name),)
    }


def build_report(
    result,
    config: SimulationConfig,
    *,
    csv_sha256: str,
    archive_hash: str | None,
    calibration_hash: str | None,
    calibration,
    generated_at: int | None = None,
) -> dict[str, object]:
    output = {key: str(value) for key, value in result.__dict__.items()}
    output.update({
        "report_schema_version": REPORT_SCHEMA_VERSION,
        "engine_version": __version__,
        "generated_at": int(generated_at or time.time()),
        "execution_model": {
            "market_impact_bps_divisor": format(
                MARKET_IMPACT_BPS_DIVISOR, "f"
            ),
            "matching": "ohlc-conservative-v2",
            "latency": "whole-bars-minimum-one",
        },
        "inputs": {
            "candles_sha256": csv_sha256,
            "archive_sha256": archive_hash,
            "calibration_sha256": calibration_hash,
        },
        "config": _config_dict(config),
        "calibration": (
            calibration.as_dict() if calibration is not None else None
        ),
    })
    return output


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
    parser.add_argument(
        "--market-impact-bps", type=Decimal, default=Decimal("0")
    )
    parser.add_argument("--output", help="optional JSON report path")
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
        "market_impact_bps": args.market_impact_bps,
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
    config = SimulationConfig(**config_values)
    result = simulate_grid(candles, config, market_events=events)
    output = build_report(
        result,
        config,
        csv_sha256=_file_sha256(args.csv_file),
        archive_hash=(archive_sha256(args.archive) if args.archive else None),
        calibration_hash=(
            _file_sha256(args.calibration) if args.calibration else None
        ),
        calibration=calibration,
    )
    encoded = json.dumps(output, indent=2, sort_keys=True) + "\n"
    if args.output:
        Path(args.output).write_text(encoded, encoding="utf-8")
    print(encoded, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
