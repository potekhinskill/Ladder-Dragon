#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: freeze selection-only volatility boundaries for later confirmation.
"""Create one immutable volatility policy without order authority."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from ladder_dragon.strategy.volatility_policy import select_volatility_policy


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("calibration", nargs="+", type=Path)
    parser.add_argument("--cutoff-ts-ms", required=True, type=int)
    parser.add_argument("--created-at-ms", required=True, type=int)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--confirm", required=True)
    args = parser.parse_args()
    if args.confirm != "FREEZE-VOLATILITY-SELECTION":
        parser.error("--confirm must be FREEZE-VOLATILITY-SELECTION")
    payload = select_volatility_policy(
        args.calibration,
        cutoff_ts_ms=args.cutoff_ts_ms,
        created_at_ms=args.created_at_ms,
    )
    descriptor = os.open(args.output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as target:
        json.dump(payload, target, indent=2, sort_keys=True)
        target.write("\n")
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
