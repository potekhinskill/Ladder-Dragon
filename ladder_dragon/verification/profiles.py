# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: compose explicit verification profiles from existing checks.
"""Verification profile registry with fail-closed unknown profiles."""

from __future__ import annotations

import os

from ladder_dragon.verification.checks.evidence import evidence_checks
from ladder_dragon.verification.checks.raspberry import raspberry_checks
from ladder_dragon.verification.checks.recovery import release_recovery_checks
from ladder_dragon.verification.checks.replay import release_replay_checks
from ladder_dragon.verification.checks.testnet import testnet_checks
from ladder_dragon.verification.checks.unit import local_checks
from ladder_dragon.verification.models import CheckSpec, HarnessContext


KNOWN_PROFILES = ("local", "release", "testnet", "pi", "mainnet-canary")


def _mainnet_checks(context: HarnessContext) -> list[CheckSpec]:
    options = context.options
    required = (
        "BOT_LIVE_CONFIRMED",
        "BOT_MAINNET_CANARY_CONFIRMED",
        "BOT_MAINNET_CANARY_CLEANUP_CONFIRMED",
    )
    reason = None
    if not options.confirm_mainnet_canary:
        reason = "Mainnet canary requires --confirm-mainnet-canary"
    elif any(os.getenv(name) != "YES" for name in required):
        reason = "Mainnet canary environment confirmations are incomplete"
    return [
        CheckSpec(
            name="mainnet_canary",
            argv=(
                context.python,
                "-m",
                "bin.binance_mainnet_canary",
                "--symbol",
                options.symbol,
            ),
            blocked_reason=reason,
            timeout_sec=900,
        )
    ]


def checks_for_profile(context: HarnessContext) -> list[CheckSpec]:
    profile = context.options.profile
    if profile == "local":
        return evidence_checks(context) + local_checks(context)
    if profile == "release":
        return (
            evidence_checks(context)
            + local_checks(context)
            + release_replay_checks(context)
            + release_recovery_checks(context)
        )
    if profile == "testnet":
        return evidence_checks(context) + testnet_checks(context)
    if profile == "pi":
        return evidence_checks(context) + raspberry_checks(context)
    if profile == "mainnet-canary":
        return evidence_checks(context) + _mainnet_checks(context)
    return [
        CheckSpec(
            name="profile_resolution",
            blocked_reason=f"unknown verification profile: {profile}",
        )
    ]
