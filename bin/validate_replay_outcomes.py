#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: validate replay predictions against sanitized execution reports.
"""Produce a fail-closed empirical replay validation report."""

from __future__ import annotations

import argparse
from decimal import Decimal
import json

from ladder_dragon.execution.execution_latency import load_execution_outcomes
from ladder_dragon.strategy.market_replay import (
    load_jsonl_archive,
    read_calibration,
)
from ladder_dragon.strategy.replay_validation import (
    validate_replay_outcomes,
    write_replay_validation,
)
from ladder_dragon.strategy.replay_policy import (
    PRODUCTION_REPLAY_ACCEPTANCE_POLICY,
    ReplayAcceptancePolicy,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("archive")
    parser.add_argument("--execution-log", required=True)
    parser.add_argument("--calibration", required=True)
    parser.add_argument("--output")
    for name in (
        "maker-buy-fee-pct",
        "maker-sell-fee-pct",
        "taker-buy-fee-pct",
        "taker-sell-fee-pct",
    ):
        parser.add_argument(f"--{name}", type=Decimal, required=True)
    args = parser.parse_args()
    calibration = read_calibration(args.calibration)
    observed_policy = calibration.acceptance_policy
    if not isinstance(observed_policy, dict):
        parser.error("calibration acceptance policy is unavailable")
    if (
        ReplayAcceptancePolicy.from_dict(observed_policy)
        != PRODUCTION_REPLAY_ACCEPTANCE_POLICY
        or calibration.acceptance_policy_sha256
        != PRODUCTION_REPLAY_ACCEPTANCE_POLICY.fingerprint
    ):
        parser.error("calibration acceptance policy differs")
    report = validate_replay_outcomes(
        load_jsonl_archive(args.archive),
        load_execution_outcomes(args.execution_log),
        calibration,
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
        maker_buy_fee_pct=args.maker_buy_fee_pct,
        maker_sell_fee_pct=args.maker_sell_fee_pct,
        taker_buy_fee_pct=args.taker_buy_fee_pct,
        taker_sell_fee_pct=args.taker_sell_fee_pct,
    )
    rendered = json.dumps(report.as_dict(), indent=2, sort_keys=True) + "\n"
    if args.output:
        write_replay_validation(args.output, report)
    print(rendered, end="")
    return 0 if report.ready else 2


if __name__ == "__main__":
    raise SystemExit(main())
