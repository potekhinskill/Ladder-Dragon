# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: execute an explicitly approved bounded Mainnet validation sequence.
"""Run a fixed Mainnet validation batch under immutable limits."""

import json

from ladder_dragon.verification.live.validation_batch import (
    build_run_parser,
    run_validation_batch,
)


def main() -> int:
    """Validate the explicit operator confirmation and run the batch."""
    args = build_run_parser().parse_args()
    if args.confirm != "RUN_VALIDATION_BATCH":
        raise SystemExit("--confirm must equal RUN_VALIDATION_BATCH")
    result = run_validation_batch(
        args.manifest, notional_usdt=args.notional_usdt
    )
    print(json.dumps({"status": "PASS" if result == 0 else "FAILED"}))
    return result


if __name__ == "__main__":
    raise SystemExit(main())
