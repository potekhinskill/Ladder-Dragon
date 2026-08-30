#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: import reviewed exact L2 reports into frozen v23 confirmation.
"""Import post-cutoff v23 confirmation without exchange capability."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sqlite3

from ladder_dragon.strategy.prediction.runtime import PredictionShadowStore
from ladder_dragon.strategy.prediction.v23_confirmation import (
    import_v23_confirmation_reports,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prediction-db", required=True, type=Path)
    parser.add_argument(
        "--report", action="append", nargs=2,
        metavar=("PATH", "SHA256"), required=True,
    )
    parser.add_argument("--confirm", required=True)
    args = parser.parse_args()
    if args.confirm != "IMPORT-V23-DISJOINT-CONFIRMATION":
        parser.error(
            "--confirm must be IMPORT-V23-DISJOINT-CONFIRMATION"
        )
    try:
        payload = import_v23_confirmation_reports(
            PredictionShadowStore(args.prediction_db),
            [(Path(path), digest) for path, digest in args.report],
        )
    except (
        OSError, RuntimeError, ValueError, KeyError, TypeError,
        ArithmeticError, sqlite3.Error,
    ) as exc:
        print(
            f"[V23-CONFIRMATION] status=BLOCKED error={type(exc).__name__}"
        )
        return 2
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
