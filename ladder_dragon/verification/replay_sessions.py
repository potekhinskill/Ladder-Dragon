# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: validate execution outcomes across separate contiguous depth sessions.
"""Build one replay artifact without joining gaps between public archives."""

from __future__ import annotations

import argparse
from dataclasses import replace
from decimal import Decimal
import json
from pathlib import Path

from ladder_dragon.execution.execution_latency import load_execution_outcomes
from ladder_dragon.strategy.market_replay import (
    load_jsonl_archive,
    read_calibration,
)
from ladder_dragon.strategy.replay_validation import (
    ReplayValidationSession,
    validate_replay_sessions,
    write_replay_validation,
)
from ladder_dragon.strategy.replay_readiness import audit_replay_readiness


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--session",
        nargs=2,
        action="append",
        metavar=("ARCHIVE", "CALIBRATION"),
        required=True,
    )
    parser.add_argument("--execution-log", required=True)
    parser.add_argument("--output")
    parser.add_argument("--minimum-orders", type=int, default=10)
    parser.add_argument("--prediction-db", type=Path)
    parser.add_argument("--experiment-id")
    parser.add_argument("--symbol")
    parser.add_argument("--execution-model-rule")
    parser.add_argument("--confirm-import")
    for name, value in (
        ("minimum-classification-accuracy", "0.80"),
        ("maximum-fill-ratio-mae", "0.25"),
        ("maximum-price-error-bps-mae", "10"),
        ("maximum-latency-error-ms-mae", "1000"),
        ("maximum-fee-error-quote-mae", "0.02"),
        ("maximum-slippage-error-bps-mae", "10"),
    ):
        parser.add_argument(f"--{name}", type=Decimal, default=Decimal(value))
    for name in (
        "maker-buy-fee-pct",
        "maker-sell-fee-pct",
        "taker-buy-fee-pct",
        "taker-sell-fee-pct",
    ):
        parser.add_argument(f"--{name}", type=Decimal, required=True)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    import_values = (
        args.prediction_db,
        args.experiment_id,
        args.symbol,
        args.execution_model_rule,
        args.confirm_import,
    )
    if any(value is not None for value in import_values) and (
        any(value is None for value in import_values)
        or args.confirm_import != "IMPORT_PASS"
    ):
        raise SystemExit(
            "replay import requires all identity arguments and IMPORT_PASS"
        )
    sessions = [
        ReplayValidationSession(
            events=tuple(load_jsonl_archive(archive)),
            calibration=read_calibration(calibration),
        )
        for archive, calibration in args.session
    ]
    report = validate_replay_sessions(
        sessions,
        load_execution_outcomes(args.execution_log),
        minimum_orders=args.minimum_orders,
        minimum_classification_accuracy=args.minimum_classification_accuracy,
        maximum_fill_ratio_mae=args.maximum_fill_ratio_mae,
        maximum_price_error_bps_mae=args.maximum_price_error_bps_mae,
        maximum_latency_error_ms_mae=args.maximum_latency_error_ms_mae,
        maximum_fee_error_quote_mae=args.maximum_fee_error_quote_mae,
        maximum_slippage_error_bps_mae=args.maximum_slippage_error_bps_mae,
        maker_buy_fee_pct=args.maker_buy_fee_pct,
        maker_sell_fee_pct=args.maker_sell_fee_pct,
        taker_buy_fee_pct=args.taker_buy_fee_pct,
        taker_sell_fee_pct=args.taker_sell_fee_pct,
    )
    readiness = audit_replay_readiness(
        [session.calibration for session in sessions],
        validations=[report],
        minimum_validation_reports=1,
        minimum_validated_orders=args.minimum_orders,
    )
    report = replace(report, replay_readiness=readiness.as_dict())
    if args.output:
        write_replay_validation(args.output, report)
    payload = report.as_dict()
    if args.prediction_db is not None:
        from ladder_dragon.strategy.prediction.episode_evidence import (
            record_model_validation,
        )
        from ladder_dragon.strategy.prediction.runtime import (
            PredictionShadowStore,
        )
        payload["imported_validation_id"] = record_model_validation(
            PredictionShadowStore(args.prediction_db),
            symbol=args.symbol,
            execution_model_rule=args.execution_model_rule,
            experiment_id=args.experiment_id,
            report=payload,
        )
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0 if report.ready and readiness.ready else 2


__all__ = ["build_parser", "main"]
