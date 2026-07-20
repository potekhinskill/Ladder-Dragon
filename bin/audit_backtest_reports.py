#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: identify backtest reports invalidated by execution-model changes.
"""Classify saved backtest JSON reports without modifying them."""

from __future__ import annotations

import argparse
from decimal import Decimal, InvalidOperation
import json
from pathlib import Path
from typing import Any, Iterable


CURRENT_SCHEMA = 2
CURRENT_IMPACT_DIVISOR = "10000"


def _impact_bps(payload: dict[str, Any]) -> Decimal:
    config = payload.get("config") or {}
    if "market_impact_bps" in config:
        value: object = config.get("market_impact_bps")
    else:
        value = (
            ((payload.get("calibration") or {}).get("parameters") or {}).get(
                "market_impact_bps", "0"
            )
        )
    try:
        impact = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValueError("invalid market_impact_bps") from exc
    if not impact.is_finite() or impact < 0:
        raise ValueError("invalid market_impact_bps")
    return impact


def classify_report(payload: dict[str, Any]) -> dict[str, object]:
    if not {"final_equity", "realized_pnl", "trades"} <= payload.keys():
        raise ValueError("not a Ladder Dragon backtest report")
    impact = _impact_bps(payload)
    divisor = str(
        (payload.get("execution_model") or {}).get(
            "market_impact_bps_divisor", ""
        )
    )
    current = (
        int(payload.get("report_schema_version", 0)) >= CURRENT_SCHEMA
        and divisor == CURRENT_IMPACT_DIVISOR
    )
    return {
        "current": current,
        "market_impact_bps": format(impact, "f"),
        "rerun_required": not current and impact > 0,
        "reason": (
            "current execution model"
            if current
            else "legacy report with non-zero market impact"
            if impact > 0
            else "legacy report unaffected by market impact correction"
        ),
    }


def _paths(inputs: Iterable[str]) -> list[Path]:
    found: list[Path] = []
    for raw in inputs:
        path = Path(raw)
        if path.is_dir():
            found.extend(sorted(path.rglob("*.json")))
        else:
            found.append(path)
    return found


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("paths", nargs="+", help="report files or directories")
    args = parser.parse_args()
    rows = []
    invalid = 0
    rerun = 0
    for path in _paths(args.paths):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(payload, dict):
                raise ValueError("JSON root is not an object")
            result = classify_report(payload)
            rerun += int(bool(result["rerun_required"]))
            rows.append({"path": str(path), **result})
        except (OSError, json.JSONDecodeError, TypeError, ValueError) as exc:
            invalid += 1
            rows.append({
                "path": str(path),
                "current": False,
                "rerun_required": False,
                "reason": f"invalid: {type(exc).__name__}",
            })
    print(json.dumps({
        "reports": rows,
        "rerun_required": rerun,
        "invalid": invalid,
    }, indent=2, sort_keys=True))
    return 2 if rerun else 1 if invalid else 0


if __name__ == "__main__":
    raise SystemExit(main())
