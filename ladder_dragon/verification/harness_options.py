# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: validate and normalize verification request options.
'Validated verification options without execution.'

from __future__ import annotations

from pathlib import Path
import re

from ladder_dragon.verification.models import HarnessOptions

SYMBOL_RE = re.compile(r"^[A-Z0-9]{5,20}$")
PROFILE_RE = re.compile(r"^[a-z0-9-]{1,64}$")


def prepare_options(args) -> HarnessOptions:
    requested_profile = args.profile.strip().lower()
    profile = (
        requested_profile
        if PROFILE_RE.fullmatch(requested_profile)
        else "invalid"
    )
    symbol = args.symbol.strip().upper()
    if not SYMBOL_RE.fullmatch(symbol):
        raise SystemExit("--symbol must be a valid uppercase Binance symbol")
    user_stream_status = args.user_stream_status or Path(
        f"/var/lib/ladder-dragon/user-stream/user_stream_{symbol}.json"
    )
    output = args.output or Path(
        f".runtime/verification-{profile}.json"
    )
    options = HarnessOptions(
        profile=profile,
        output=output,
        expected_sha=args.expected_sha,
        github_sha=args.github_sha,
        symbol=symbol,
        confirm_authenticated_testnet=args.confirm_authenticated_testnet,
        confirm_testnet_mutation=args.confirm_testnet_mutation,
        confirm_mainnet_canary=args.confirm_mainnet_canary,
        release_report=args.release_report,
        replay_validation=args.replay_validation,
        latency_log=args.latency_log,
        source_paths=tuple(args.source),
        runtime_status=args.runtime_status,
        user_stream_status=user_stream_status,
        risk_status=args.risk_status,
        order_journal=args.order_journal,
        prediction_db=args.prediction_db,
        ai_decisions_db=args.ai_decisions_db,
        web_root=args.web_root,
    )
    return options
