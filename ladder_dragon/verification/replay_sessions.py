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
from ladder_dragon.strategy.replay_policy import (
    PRODUCTION_REPLAY_ACCEPTANCE_POLICY,
    ReplayAcceptancePolicy,
)
from ladder_dragon.strategy.replay_cohorts import calibration_context_evidence
from ladder_dragon.strategy.replay_readiness import audit_replay_readiness
from ladder_dragon.strategy.volatility_policy import (
    confirmed_volatility_scope,
    read_volatility_policy,
)
from ladder_dragon.verification.live.validation_batch import (
    validation_batch_evidence,
)


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
    parser.add_argument("--batch-manifest", type=Path)
    parser.add_argument(
        "--calibration-context",
        action="append",
        type=Path,
        metavar="CALIBRATION",
        help="add one read-only calibration outside the order cohort",
    )
    parser.add_argument("--volatility-policy", type=Path)
    parser.add_argument("--prediction-db", type=Path)
    parser.add_argument("--experiment-id")
    parser.add_argument("--symbol")
    parser.add_argument("--execution-model-rule")
    parser.add_argument("--confirm-import")
    for name in (
        "maker-buy-fee-pct",
        "maker-sell-fee-pct",
        "taker-buy-fee-pct",
        "taker-sell-fee-pct",
    ):
        parser.add_argument(f"--{name}", required=True)
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
        or args.batch_manifest is None
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
    outcomes = load_execution_outcomes(args.execution_log)
    order_cohort = None
    context_cohort = None
    context_calibrations = [
        read_calibration(path) for path in (args.calibration_context or [])
    ]
    volatility_policy = (
        read_volatility_policy(args.volatility_policy)
        if args.volatility_policy is not None else None
    )
    volatility_scope = None
    required_volatility_regimes = ("low", "normal", "high")
    if args.batch_manifest is not None:
        order_cohort = validation_batch_evidence(args.batch_manifest)
        expected_archives = set(order_cohort["archive_sha256s"])
        observed_archives = {
            session.calibration.archive_sha256 for session in sessions
        }
        if observed_archives != expected_archives:
            raise SystemExit("replay sessions differ from the fixed batch cohort")
        expected_refs = set(order_cohort["order_refs"])
        outcome_refs = {row.order_ref for row in outcomes}
        if outcome_refs != expected_refs:
            raise SystemExit("execution outcomes differ from the fixed batch cohort")
        for session in sessions:
            policy = session.calibration.acceptance_policy
            if not isinstance(policy, dict):
                raise SystemExit("calibration acceptance policy is unavailable")
            parsed = ReplayAcceptancePolicy.from_dict(policy)
            if (
                parsed != PRODUCTION_REPLAY_ACCEPTANCE_POLICY
                or session.calibration.acceptance_policy_sha256
                != PRODUCTION_REPLAY_ACCEPTANCE_POLICY.fingerprint
            ):
                raise SystemExit("calibration acceptance policy differs")
        context_hashes = {
            calibration.archive_sha256 for calibration in context_calibrations
        }
        if not context_calibrations:
            raise SystemExit("read-only calibration context is unavailable")
        if context_hashes & observed_archives:
            raise SystemExit("replay calibration cohorts overlap")
        if volatility_policy is not None:
            volatility_scope = confirmed_volatility_scope(
                volatility_policy, context_calibrations
            )
            required_volatility_regimes = tuple(
                volatility_scope["confirmed_buckets"]
            )
        context_readiness = audit_replay_readiness(
            context_calibrations,
            minimum_measured_latency_archives=0,
            minimum_execution_samples=0,
            minimum_validation_reports=0,
            minimum_validated_orders=0,
            required_regimes=required_volatility_regimes,
            volatility_policy=volatility_policy,
        )
        context_cohort = calibration_context_evidence(
            context_calibrations,
            readiness=context_readiness.as_dict(),
            volatility_policy=volatility_policy,
            volatility_scope=volatility_scope,
        )
    report = validate_replay_sessions(
        sessions,
        outcomes,
        minimum_orders=PRODUCTION_REPLAY_ACCEPTANCE_POLICY.minimum_orders,
        minimum_classification_accuracy=(
            PRODUCTION_REPLAY_ACCEPTANCE_POLICY.minimum_classification_accuracy
        ),
        maximum_fill_ratio_mae=(
            PRODUCTION_REPLAY_ACCEPTANCE_POLICY.maximum_fill_ratio_mae
        ),
        maximum_price_error_bps_mae=(
            PRODUCTION_REPLAY_ACCEPTANCE_POLICY.maximum_price_error_bps_mae
        ),
        maximum_latency_error_ms_mae=(
            PRODUCTION_REPLAY_ACCEPTANCE_POLICY.maximum_latency_error_ms_mae
        ),
        maximum_fee_error_quote_mae=(
            PRODUCTION_REPLAY_ACCEPTANCE_POLICY.maximum_fee_error_quote_mae
        ),
        maximum_slippage_error_bps_mae=(
            PRODUCTION_REPLAY_ACCEPTANCE_POLICY.maximum_slippage_error_bps_mae
        ),
        maker_buy_fee_pct=Decimal(args.maker_buy_fee_pct),
        maker_sell_fee_pct=Decimal(args.maker_sell_fee_pct),
        taker_buy_fee_pct=Decimal(args.taker_buy_fee_pct),
        taker_sell_fee_pct=Decimal(args.taker_sell_fee_pct),
    )
    readiness = audit_replay_readiness(
        [session.calibration for session in sessions] + context_calibrations,
        validations=[report],
        minimum_validation_reports=1,
        minimum_validated_orders=(
            PRODUCTION_REPLAY_ACCEPTANCE_POLICY.minimum_orders
        ),
        required_regimes=required_volatility_regimes,
        low_max_bps=(
            Decimal(str(volatility_policy["low_max_bps"]))
            if volatility_policy is not None else Decimal("0.5")
        ),
        high_min_bps=(
            Decimal(str(volatility_policy["high_min_bps"]))
            if volatility_policy is not None else Decimal("2")
        ),
    )
    report = replace(
        report,
        replay_readiness=readiness.as_dict(),
        order_validation_cohort=order_cohort,
        calibration_context_cohort=context_cohort,
    )
    if args.prediction_db is not None:
        from ladder_dragon.strategy.prediction.episode_semantics import (
            execution_engine_validation_domain,
        )
        from ladder_dragon.strategy.prediction.experiment_lifecycle import (
            load_manifest,
        )
        from ladder_dragon.strategy.prediction.runtime import (
            PredictionShadowStore,
        )

        manifest = load_manifest(
            PredictionShadowStore(args.prediction_db), args.experiment_id
        )
        parameters = manifest.get("candidate_parameters")
        if not isinstance(parameters, dict):
            raise SystemExit("candidate parameters are unavailable")
        entry_veto_rule = (
            parameters.get("entry_veto_rule")
            if parameters.get("candidate_rule_version") == 8 else None
        )
        report = replace(
            report,
            validation_domain=execution_engine_validation_domain(
                execution_model_rule=args.execution_model_rule,
                fee_schedule={
                    "maker_buy_fee_pct": Decimal(args.maker_buy_fee_pct),
                    "maker_sell_fee_pct": Decimal(args.maker_sell_fee_pct),
                    "taker_buy_fee_pct": Decimal(args.taker_buy_fee_pct),
                    "taker_sell_fee_pct": Decimal(args.taker_sell_fee_pct),
                },
                entry_veto_rule=entry_veto_rule,
            ),
        )
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
