# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: define the stable verification command arguments.
'Run a versioned, non-secret Ladder Dragon verification profile.'

from __future__ import annotations

import argparse
from pathlib import Path


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
        default=None,
    )
    parser.add_argument(
        "--risk-status",
        type=Path,
        default=Path("/var/lib/ladder-dragon/control/risk_state.json"),
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
