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
    parser.add_argument("--require-reconnect", action="store_true")
    parser.add_argument("--require-order-event", action="store_true")
    args = parser.parse_args()
    report = audit_user_stream_soak(
        args.snapshots,
        minimum_hours=args.minimum_hours,
        maximum_stale_sec=args.maximum_stale_sec,
        require_reconnect=args.require_reconnect,
        require_order_event=args.require_order_event,
    )
    print(json.dumps(report.as_dict(), indent=2, sort_keys=True))
    return 0 if report.ready else 2


if __name__ == "__main__":
    raise SystemExit(main())
