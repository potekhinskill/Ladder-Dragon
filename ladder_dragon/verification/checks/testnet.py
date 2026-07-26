# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: define explicitly gated Binance Testnet verification checks.
"""Testnet checks with separate read and mutation confirmations."""

from __future__ import annotations

import os

from ladder_dragon.verification.models import CheckSpec, HarnessContext


def testnet_checks(context: HarnessContext) -> list[CheckSpec]:
    python = context.python
    options = context.options
    checks = [
        CheckSpec(
            name="testnet_safety_regression",
            argv=(python, "-m", "pytest", "tests/test_testnet_smoke.py"),
            timeout_sec=900,
        ),
        CheckSpec(
            name="testnet_public",
            argv=(
                python,
                "-m",
                "bin.binance_testnet_smoke",
                "--mode",
                "public",
                "--symbol",
                options.symbol,
            ),
            timeout_sec=120,
        ),
        CheckSpec(
            name="testnet_gap_drill",
            argv=(
                python,
                "-m",
                "bin.binance_testnet_smoke",
                "--mode",
                "gap-drill",
                "--symbol",
                options.symbol,
            ),
            timeout_sec=120,
        ),
    ]
    authenticated_reason = None
    if not options.confirm_authenticated_testnet:
        authenticated_reason = (
            "authenticated Testnet requires "
            "--confirm-authenticated-testnet"
        )
    checks.append(
        CheckSpec(
            name="testnet_authenticated",
            argv=(
                python,
                "-m",
                "bin.binance_testnet_smoke",
                "--mode",
                "authenticated",
                "--symbol",
                options.symbol,
            ),
            blocked_reason=authenticated_reason,
            timeout_sec=120,
        )
    )
    mutation_reason = None
    if not options.confirm_testnet_mutation:
        mutation_reason = (
            "Testnet lifecycle requires --confirm-testnet-mutation"
        )
    elif os.getenv("BOT_TESTNET_BUY_OCO_CONFIRMED") != "YES":
        mutation_reason = (
            "Testnet lifecycle requires "
            "BOT_TESTNET_BUY_OCO_CONFIRMED=YES"
        )
    checks.append(
        CheckSpec(
            name="testnet_buy_oco_restart",
            argv=(
                python,
                "-m",
                "bin.binance_testnet_smoke",
                "--mode",
                "buy-oco-restart",
                "--symbol",
                options.symbol,
            ),
            blocked_reason=mutation_reason,
            timeout_sec=600,
        )
    )
    return checks
