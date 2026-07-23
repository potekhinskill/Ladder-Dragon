#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: produce a read-only, evidence-based production soak verdict.
"""Build a sanitized production soak report; never changes orders or services."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sqlite3
import tempfile
import time
from typing import Any

from ladder_dragon.execution.order_recovery import read_order_journal_telemetry
from ladder_dragon.execution.telegram_alerts import notify
from product_version import __version__


def _runtime(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("runtime status is not an object")
    return payload


def _prediction_counts(path: Path) -> dict[str, int]:
    if not path.exists():
        return {"resolved": 0, "pending": 0, "expired": 0}
    with sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=2) as con:
        columns = {
            str(row[1])
            for row in con.execute("PRAGMA table_info(prediction_outcomes)")
        }
        if not columns:
            return {"resolved": 0, "pending": 0, "expired": 0}
        resolved = int(con.execute(
            "SELECT COUNT(*) FROM prediction_outcomes "
            "WHERE outcome_json IS NOT NULL"
        ).fetchone()[0])
        pending = int(con.execute(
            "SELECT COUNT(*) FROM prediction_outcomes "
            "WHERE resolved_at_ms IS NULL"
        ).fetchone()[0])
        expired = (
            int(con.execute(
                "SELECT COUNT(*) FROM prediction_outcomes "
                "WHERE terminal_reason='INSUFFICIENT_HISTORY'"
            ).fetchone()[0])
            if "terminal_reason" in columns else 0
        )
    return {"resolved": resolved, "pending": pending, "expired": expired}


def build_report(
    *,
    runtime_path: Path,
    journal_path: Path,
    prediction_path: Path,
    required_hours: int,
    required_lifecycles: int,
    required_predictions: int,
    now_epoch: float | None = None,
) -> dict[str, Any]:
    now = time.time() if now_epoch is None else float(now_epoch)
    try:
        runtime = _runtime(runtime_path)
        started = datetime.fromisoformat(str(runtime["started_at"]))
        updated = datetime.fromisoformat(str(runtime["updated_at"]))
        if started.tzinfo is None:
            started = started.replace(tzinfo=timezone.utc)
        if updated.tzinfo is None:
            updated = updated.replace(tzinfo=timezone.utc)
        elapsed_sec = max(0, int(now - started.timestamp()))
        heartbeat_age_sec = max(0, int(now - updated.timestamp()))
    except (
        OSError,
        KeyError,
        TypeError,
        ValueError,
        json.JSONDecodeError,
    ):
        runtime = {}
        elapsed_sec = 0
        heartbeat_age_sec = 2**31 - 1
    journal = read_order_journal_telemetry(journal_path)
    lifecycle = journal.get("lifecycle", {}) if journal.get("available") else {}
    exact = int(lifecycle.get("closed_exact", 0))
    prediction = _prediction_counts(prediction_path)
    prediction_runtime = runtime.get("prediction")
    prediction_symbols = (
        prediction_runtime.get("symbols", {})
        if isinstance(prediction_runtime, dict) else {}
    )
    gate_rows = [
        row.get("gate")
        for row in prediction_symbols.values()
        if isinstance(row, dict)
    ] if isinstance(prediction_symbols, dict) else []
    prediction_gate_approved = bool(gate_rows) and all(
        isinstance(gate, dict) and gate.get("approved") is True
        for gate in gate_rows
    )
    checks = {
        "runtime_running": runtime.get("state") == "RUNNING",
        "live_mainnet": (
            runtime.get("execution_mode") == "LIVE"
            and runtime.get("venue") == "mainnet"
        ),
        "heartbeat_fresh": heartbeat_age_sec <= 90,
        "duration_met": elapsed_sec >= required_hours * 3600,
        "exact_lifecycles_met": exact >= required_lifecycles,
        "prediction_samples_met": (
            prediction["resolved"] >= required_predictions
        ),
        "prediction_gate_approved": prediction_gate_approved,
        "no_prediction_backlog": prediction["pending"] == 0,
    }
    return {
        "schema_version": 1,
        "product_version": __version__,
        "generated_at": datetime.fromtimestamp(
            now, timezone.utc
        ).isoformat(),
        "approved": all(checks.values()),
        "checks": checks,
        "runtime": {
            "state": runtime.get("state") or "UNAVAILABLE",
            "execution_mode": runtime.get("execution_mode"),
            "venue": runtime.get("venue"),
            "elapsed_sec": elapsed_sec,
            "heartbeat_age_sec": heartbeat_age_sec,
        },
        "order_lifecycle": {
            "closed_exact": exact,
            "required": required_lifecycles,
        },
        "prediction": {
            **prediction,
            "required_resolved": required_predictions,
            "statistical_gate_approved": prediction_gate_approved,
            "gate_symbol_count": len(gate_rows),
        },
    }


def notify_on_transition(
    report: dict[str, Any],
    state_path: Path,
) -> bool:
    """Send one English alert only when the approval/check signature changes."""
    failed = sorted(
        name for name, passed in report["checks"].items() if not passed
    )
    current = {
        "approved": bool(report["approved"]),
        "failed_checks": failed,
    }
    try:
        previous = json.loads(state_path.read_text(encoding="utf-8"))
    except (OSError, TypeError, ValueError, json.JSONDecodeError):
        previous = None
    changed = previous != current
    if changed:
        notify(
            "production soak status changed",
            [
                "approved" if current["approved"] else "approval remains blocked"
            ],
            {
                "failed_checks": ",".join(failed) or "none",
                "product_version": report["product_version"],
            },
        )
        _write_atomic(state_path, current)
    return changed


def _write_atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", dir=str(path.parent), text=True
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, sort_keys=True, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--runtime", type=Path,
        default=Path(os.getenv("AI_RUNTIME_STATUS_FILE", "/run/mybot/ai_status.json")),
    )
    parser.add_argument("--journal", type=Path)
    parser.add_argument("--prediction", type=Path)
    parser.add_argument("--required-hours", type=int, default=24)
    parser.add_argument("--required-lifecycles", type=int, default=3)
    parser.add_argument("--required-predictions", type=int, default=100)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--status-state", type=Path)
    parser.add_argument("--notify-on-change", action="store_true")
    args = parser.parse_args(argv)
    try:
        runtime_paths = _runtime(args.runtime).get("paths", {})
    except (OSError, TypeError, ValueError, json.JSONDecodeError):
        runtime_paths = {}
    if not isinstance(runtime_paths, dict):
        runtime_paths = {}
    journal_path = args.journal or Path(
        str(
            runtime_paths.get("order_journal")
            or os.getenv("BOT_ORDER_JOURNAL", "db/order_intents.sqlite3")
        )
    )
    prediction_path = args.prediction or Path(
        str(
            runtime_paths.get("prediction_shadow_db")
            or os.getenv(
                "PREDICTION_SHADOW_DB", "db/prediction_shadow.sqlite3"
            )
        )
    )
    report = build_report(
        runtime_path=args.runtime,
        journal_path=journal_path,
        prediction_path=prediction_path,
        required_hours=max(1, args.required_hours),
        required_lifecycles=max(1, args.required_lifecycles),
        required_predictions=max(1, args.required_predictions),
    )
    if args.output:
        _write_atomic(args.output, report)
    if args.notify_on_change:
        if args.status_state is None:
            parser.error("--notify-on-change requires --status-state")
        notify_on_transition(report, args.status_state)
    print(json.dumps(report, sort_keys=True))
    return 0 if report["approved"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
