#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: generate the offline monthly defensive prediction artifact.

"""Build a monthly SHADOW prediction report from sanitized JSONL evidence."""

from __future__ import annotations

import argparse
from datetime import datetime
from decimal import Decimal
import json
import os
from pathlib import Path
from zoneinfo import ZoneInfo

from ladder_dragon.strategy.prediction.advanced_features import (
    ExtendedRegimeFeatures,
)
from ladder_dragon.strategy.prediction.decision_value import (
    DecisionValueObservation,
)
from ladder_dragon.strategy.prediction.challengers import ChallengerObservation
from ladder_dragon.strategy.prediction.historical_dataset import (
    HistoricalRegimeSample,
)
from ladder_dragon.strategy.prediction.monthly_contour import (
    compact_report_state,
    monthly_prediction_report,
    report_status_changed,
)
from ladder_dragon.execution.telegram_alerts import send_message


def _features(payload: dict[str, object]) -> ExtendedRegimeFeatures:
    decimal_fields = {
        "realized_volatility_short",
        "realized_volatility_long",
        "volatility_ratio",
        "vwap_deviation_pct",
        "vwap_slope_pct",
        "hour_sin",
        "hour_cos",
        "weekday_sin",
        "weekday_cos",
        "agg_trade_imbalance",
    }
    nullable_decimal_fields = {"funding_rate", "open_interest_change_pct"}
    values = dict(payload)
    for name in decimal_fields:
        values[name] = Decimal(str(values[name]))
    for name in nullable_decimal_fields:
        if values.get(name) is not None:
            values[name] = Decimal(str(values[name]))
    return ExtendedRegimeFeatures(**values)  # type: ignore[arg-type]


def _load(
    path: Path,
) -> tuple[
    list[HistoricalRegimeSample],
    list[DecisionValueObservation],
    list[ChallengerObservation],
]:
    samples = []
    values = []
    challengers = []
    for line_number, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not raw.strip():
            continue
        payload = json.loads(raw)
        kind = payload.get("kind")
        if kind == "historical_sample":
            samples.append(HistoricalRegimeSample(
                symbol=str(payload["symbol"]),
                snapshot_ts_ms=int(payload["snapshot_ts_ms"]),
                label_ts_ms=int(payload["label_ts_ms"]),
                horizon_min=int(payload["horizon_min"]),
                features=_features(payload["features"]),
                realized_return=Decimal(str(payload["realized_return"])),
                label=str(payload["label"]),
            ))
        elif kind == "decision_value":
            values.append(DecisionValueObservation(
                snapshot_ts_ms=int(payload["snapshot_ts_ms"]),
                resolved_at_ms=int(payload["resolved_at_ms"]),
                predicted_label=str(payload["predicted_label"]),
                realized_return=Decimal(str(payload["realized_return"])),
                always_trade_net_pnl_quote=Decimal(
                    str(payload["always_trade_net_pnl_quote"])
                ),
                buy_allowed=bool(payload["buy_allowed"]),
            ))
        elif kind == "challenger":
            predictions = payload.get("predictions")
            if not isinstance(predictions, dict):
                raise ValueError(
                    f"line {line_number}: challenger predictions must be an object"
                )
            challengers.append(ChallengerObservation(
                snapshot_ts_ms=int(payload["snapshot_ts_ms"]),
                resolved_at_ms=int(payload["resolved_at_ms"]),
                actual_label=str(payload["actual_label"]),
                realized_return=Decimal(str(payload["realized_return"])),
                predictions={
                    str(source): str(label)
                    for source, label in predictions.items()
                },
            ))
        else:
            raise ValueError(f"line {line_number}: unsupported evidence kind")
    return samples, values, challengers


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence-jsonl", type=Path, required=True)
    parser.add_argument("--cutoff-ts-ms", type=int)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--min-train-samples", type=int, default=120)
    parser.add_argument("--status-state", type=Path)
    parser.add_argument("--notify-on-change", action="store_true")
    args = parser.parse_args()
    if args.notify_on_change and args.status_state is None:
        parser.error("--notify-on-change requires --status-state")
    cutoff_ts_ms = args.cutoff_ts_ms
    if cutoff_ts_ms is None:
        now = datetime.now(ZoneInfo("Asia/Almaty"))
        cutoff_ts_ms = int(
            now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
            .timestamp() * 1000
        ) - 1
    samples, values, challengers = _load(args.evidence_jsonl)
    report = monthly_prediction_report(
        samples,
        values,
        cutoff_ts_ms=cutoff_ts_ms,
        min_train_samples=args.min_train_samples,
        challengers=challengers,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    if args.status_state is not None:
        previous = None
        try:
            previous = json.loads(args.status_state.read_text(encoding="utf-8"))
        except FileNotFoundError:
            pass
        if args.notify_on_change and report_status_changed(report, previous):
            decision_value = report["decision_value"]
            send_message(
                "Ladder Dragon monthly prediction SHADOW\n"
                f"status: {report['status']}\n"
                f"samples: {report['samples_before_cutoff']}\n"
                f"decision value vs always trade: "
                f"{decision_value['decision_value_quote']} quote\n"
                "risk expansion: disabled"
            )
        args.status_state.parent.mkdir(parents=True, exist_ok=True)
        temporary = args.status_state.with_suffix(".tmp")
        temporary.write_text(
            json.dumps(compact_report_state(report), sort_keys=True) + "\n",
            encoding="utf-8",
        )
        os.replace(temporary, args.status_state)
    print(json.dumps({
        "status": report["status"],
        "report_sha256": report["report_sha256"],
        "output": str(args.output),
    }, sort_keys=True))
    return 0 if report["status"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
