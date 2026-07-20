#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: audit sanitized User Data Stream soak evidence.
"""Print a read-only User Data Stream soak report."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from ladder_dragon.execution.user_stream_soak import audit_user_stream_soak


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("snapshots", nargs="+", type=Path)
    parser.add_argument("--minimum-hours", type=float, default=24.0)
    parser.add_argument("--maximum-stale-sec", type=float, default=180.0)
    parser.add_argument(
        "--allow-no-reconnect", action="store_true",
        help="diagnostic only; production readiness requires a real reconnect",
    )
    parser.add_argument(
        "--allow-no-order-event", action="store_true",
        help="diagnostic only; production readiness requires a real order event",
    )
    parser.add_argument(
        "--allow-no-event-rest", action="store_true",
        help="diagnostic only; production readiness requires WS-to-REST evidence",
    )
    args = parser.parse_args()
    report = audit_user_stream_soak(
        args.snapshots,
        minimum_hours=args.minimum_hours,
        maximum_stale_sec=args.maximum_stale_sec,
        require_reconnect=not args.allow_no_reconnect,
        require_order_event=not args.allow_no_order_event,
        require_event_woken_rest=not args.allow_no_event_rest,
    )
    print(json.dumps(report.as_dict(), indent=2, sort_keys=True))
    return 0 if report.ready else 2


if __name__ == "__main__":
    raise SystemExit(main())
