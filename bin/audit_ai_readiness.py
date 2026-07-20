#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: expose the read-only AI and RAG production gate audit.
"""Audit exact real AI evidence; return 2 while APPLY is unsafe."""

from __future__ import annotations

import argparse
from decimal import Decimal
import json

from ladder_dragon.ai.ai_readiness import audit_ai_readiness


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", required=True)
    parser.add_argument("--symbol", required=True)
    parser.add_argument("--minimum-closed-decisions", type=int, default=5)
    parser.add_argument("--minimum-real-rag-episodes", type=int, default=5)
    parser.add_argument(
        "--maximum-stop-rate", type=Decimal, default=Decimal("0.60")
    )
    args = parser.parse_args()
    report = audit_ai_readiness(
        args.db,
        args.symbol,
        minimum_closed_decisions=args.minimum_closed_decisions,
        minimum_real_rag_episodes=args.minimum_real_rag_episodes,
        maximum_stop_rate=args.maximum_stop_rate,
    )
    print(json.dumps(report.as_dict(), indent=2, sort_keys=True))
    return 0 if report.ready else 2


if __name__ == "__main__":
    raise SystemExit(main())
