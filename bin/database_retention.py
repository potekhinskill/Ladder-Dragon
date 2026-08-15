#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: run scheduled, evidence-preserving database retention.
"""Archive bounded terminal telemetry and publish a retention report."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import tempfile

from ladder_dragon.persistence.retention import (
    REPORT_SCHEMA,
    protected_database_inventory,
    rotate_market_scenarios,
    rotate_prediction_shadow,
)
from product_version import __version__


def _write_report(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=".retention-", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(payload, stream, indent=2, sort_keys=True)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary, 0o600)
        os.replace(temporary, path)
    finally:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prediction-db", type=Path, required=True)
    parser.add_argument("--market-analysis-db", type=Path, required=True)
    parser.add_argument("--stats-db", type=Path, required=True)
    parser.add_argument("--order-journal", type=Path, required=True)
    parser.add_argument("--ai-db", type=Path, required=True)
    parser.add_argument("--archive-dir", type=Path, required=True)
    parser.add_argument("--backup-status", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--retention-days", type=int, default=365)
    parser.add_argument("--maximum-rows", type=int, default=2000)
    args = parser.parse_args()

    rotation = rotate_prediction_shadow(
        args.prediction_db,
        args.archive_dir,
        args.backup_status,
        retention_days=args.retention_days,
        maximum_rows=args.maximum_rows,
    )
    market_rotation = rotate_market_scenarios(
        args.market_analysis_db,
        args.archive_dir,
        args.backup_status,
        retention_days=args.retention_days,
        maximum_rows=args.maximum_rows,
    )
    report: dict[str, object] = {
        "schema": REPORT_SCHEMA,
        "version": __version__,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "status": (
            "PASS" if rotation["status"] == market_rotation["status"] == "PASS"
            else "BLOCKED"
        ),
        "prediction": rotation,
        "market_analysis": market_rotation,
        "protected": protected_database_inventory(
            [args.stats_db, args.order_journal, args.ai_db]
        ),
    }
    _write_report(args.report, report)
    print(json.dumps(report, sort_keys=True))
    return 0 if report["status"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
