#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: provide one fail-closed interface for project verification profiles.
"""Run a versioned, non-secret Ladder Dragon verification profile."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import subprocess
import sys

from ladder_dragon.verification.models import (
    EXIT_CODES,
    HarnessContext,
    HarnessOptions,
)
from ladder_dragon.verification.report import build_report, write_report
from ladder_dragon.verification.runner import HarnessRunner


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SYMBOL_RE = re.compile(r"^[A-Z0-9]{5,20}$")
PROFILE_RE = re.compile(r"^[a-z0-9-]{1,64}$")


def _commit_sha() -> str:
    try:
        value = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=PROJECT_ROOT,
            check=True,
            capture_output=True,
            text=True,
            timeout=10,
        ).stdout.strip().lower()
    except (OSError, subprocess.SubprocessError):
        return "0" * 40
    return value if re.fullmatch(r"[0-9a-f]{40}", value) else "0" * 40


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", required=True)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--expected-sha")
    parser.add_argument("--github-sha")
    parser.add_argument("--symbol", default="SOLUSDT")
    parser.add_argument("--confirm-authenticated-testnet", action="store_true")
    parser.add_argument("--confirm-testnet-mutation", action="store_true")
    parser.add_argument("--confirm-mainnet-canary", action="store_true")
    parser.add_argument("--release-report", type=Path)
    parser.add_argument("--replay-validation", type=Path)
    parser.add_argument("--latency-log", type=Path)
    parser.add_argument("--source", type=Path, action="append", default=[])
    parser.add_argument(
        "--runtime-status",
        type=Path,
        default=Path("/run/mybot/ai_status.json"),
    )
    parser.add_argument(
        "--user-stream-status",
        type=Path,
        default=Path("/run/mybot/user_stream_SOLUSDT.json"),
    )
    parser.add_argument(
        "--risk-status",
        type=Path,
        default=Path("/run/mybot/risk_state.json"),
    )
    parser.add_argument(
        "--order-journal",
        type=Path,
        default=Path("db/order_intents.sqlite3"),
    )
    parser.add_argument(
        "--prediction-db",
        type=Path,
        default=Path("db/prediction_shadow.sqlite3"),
    )
    parser.add_argument(
        "--ai-decisions-db",
        type=Path,
        default=Path("db/ai_decisions.sqlite3"),
    )
    parser.add_argument(
        "--web-root",
        type=Path,
        default=Path("/var/www/bot"),
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    requested_profile = args.profile.strip().lower()
    profile = (
        requested_profile
        if PROFILE_RE.fullmatch(requested_profile)
        else "invalid"
    )
    symbol = args.symbol.strip().upper()
    if not SYMBOL_RE.fullmatch(symbol):
        raise SystemExit("--symbol must be a valid uppercase Binance symbol")
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
        user_stream_status=args.user_stream_status,
        risk_status=args.risk_status,
        order_journal=args.order_journal,
        prediction_db=args.prediction_db,
        ai_decisions_db=args.ai_decisions_db,
        web_root=args.web_root,
    )
    context = HarnessContext(
        root=PROJECT_ROOT,
        python=sys.executable,
        options=options,
    )
    checks = HarnessRunner(context).run()
    report = build_report(context, checks, _commit_sha())
    write_report(output, report)
    print(json.dumps(report.as_dict(), indent=2, sort_keys=True))
    return EXIT_CODES[report.status]


if __name__ == "__main__":
    raise SystemExit(main())
