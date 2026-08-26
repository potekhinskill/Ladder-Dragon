#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: import public L2 entry features into the SHADOW evidence database.
"""Attach source-hashed public L2 features to covered entry diagnostics."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from ladder_dragon.strategy.prediction.entry_diagnostics import (
    import_entry_veto_l2_archive,
    import_entry_veto_l2_history,
)
from ladder_dragon.strategy.prediction.runtime import PredictionShadowStore


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--prediction-db", type=Path, required=True)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--archive", type=Path)
    source.add_argument("--archive-directory", type=Path)
    args = parser.parse_args()
    try:
        store = PredictionShadowStore(args.prediction_db)
        report = (
            import_entry_veto_l2_archive(store, args.archive)
            if args.archive is not None
            else import_entry_veto_l2_history(store, args.archive_directory)
        )
    except (OSError, RuntimeError, ValueError) as exc:
        parser.error(f"L2 entry-feature import failed: {type(exc).__name__}: {exc}")
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
