#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: convert verified Binance kline archives to chronological SHADOW samples.

"""Build source-hashed multi-symbol prediction samples from Binance JSONL bars."""

from __future__ import annotations

import argparse
from dataclasses import asdict
from decimal import Decimal
import hashlib
import json
from pathlib import Path

from ladder_dragon.strategy.prediction.historical_dataset import (
    SymbolAuxiliaryHistory,
    build_historical_samples,
)
from ladder_dragon.strategy.prediction.advanced_features import TimedMarketValue
from ladder_dragon.strategy.prediction.models import PredictionBar


def _json_value(value: object) -> object:
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, dict):
        return {str(key): _json_value(item) for key, item in value.items()}
    return value


def _load(
    path: Path,
) -> tuple[dict[str, list[PredictionBar]], dict[str, SymbolAuxiliaryHistory]]:
    by_symbol: dict[str, list[PredictionBar]] = {}
    flows: dict[str, dict[int, Decimal]] = {}
    funding: dict[str, list[TimedMarketValue]] = {}
    interest: dict[str, list[TimedMarketValue]] = {}
    for line_number, line in enumerate(
        path.read_text(encoding="utf-8").splitlines(),
        1,
    ):
        if not line.strip():
            continue
        payload = json.loads(line)
        try:
            symbol = str(payload["symbol"]).upper()
            row = payload["kline"]
            if not isinstance(row, list) or len(row) < 7:
                raise ValueError("kline must contain the seven Binance fields")
            bar = PredictionBar(
                open_time_ms=int(row[0]),
                open=Decimal(str(row[1])),
                high=Decimal(str(row[2])),
                low=Decimal(str(row[3])),
                close=Decimal(str(row[4])),
                volume=Decimal(str(row[5])),
                close_time_ms=int(row[6]),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError(f"line {line_number}: invalid Binance kline") from exc
        if (
            not symbol.isalnum()
            or bar.close_time_ms <= bar.open_time_ms
            or bar.low <= 0
            or bar.low > bar.high
            or bar.volume < 0
        ):
            raise ValueError(f"line {line_number}: invalid closed-bar values")
        by_symbol.setdefault(symbol, []).append(bar)
        if payload.get("agg_trade_imbalance") is not None:
            flows.setdefault(symbol, {})[bar.close_time_ms] = Decimal(
                str(payload["agg_trade_imbalance"])
            )
        if payload.get("funding_rate") is not None:
            funding.setdefault(symbol, []).append(TimedMarketValue(
                int(payload.get("funding_time_ms", bar.close_time_ms)),
                Decimal(str(payload["funding_rate"])),
            ))
        if payload.get("open_interest") is not None:
            interest.setdefault(symbol, []).append(TimedMarketValue(
                int(payload.get("open_interest_time_ms", bar.close_time_ms)),
                Decimal(str(payload["open_interest"])),
            ))
    auxiliary = {
        symbol: SymbolAuxiliaryHistory(
            agg_trade_imbalance_by_close_ms=flows.get(symbol, {}),
            funding=tuple(funding.get(symbol, ())),
            open_interest=tuple(interest.get(symbol, ())),
        )
        for symbol in by_symbol
    }
    return by_symbol, auxiliary


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binance-klines-jsonl", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--flat-threshold", type=Decimal, default=Decimal("0.001"))
    args = parser.parse_args()
    source_bytes = args.binance_klines_jsonl.read_bytes()
    source_sha256 = hashlib.sha256(source_bytes).hexdigest()
    bars, auxiliary = _load(args.binance_klines_jsonl)
    samples = build_historical_samples(
        bars,
        auxiliary=auxiliary,
        flat_threshold=args.flat_threshold,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8") as handle:
        for sample in samples:
            payload = _json_value(asdict(sample))
            payload["kind"] = "historical_sample"
            payload["source_sha256"] = source_sha256
            handle.write(json.dumps(payload, sort_keys=True) + "\n")
    print(json.dumps({
        "samples": len(samples),
        "symbols": sorted({sample.symbol for sample in samples}),
        "source_sha256": source_sha256,
        "output": str(args.output),
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
