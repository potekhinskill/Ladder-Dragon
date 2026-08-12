# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: archive terminal telemetry before bounded SQLite retention.
"""Safe retention for derived telemetry databases.

This module never prunes accounting, fills, inventory, unresolved records, or
order-journal evidence. It only archives terminal prediction observations.
"""

from __future__ import annotations

from datetime import datetime, timezone
import gzip
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import tempfile
import time
from typing import Any


REPORT_SCHEMA = "ladder-dragon-database-retention-v1"
SECONDS_PER_DAY = 86_400


def _backup_is_fresh(path: Path, *, now: float, maximum_age_hours: int) -> tuple[bool, str]:
    """Require evidence that a recent encrypted backup completed."""
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict) or payload.get("status") != "success":
            return False, "latest encrypted backup is not successful"
        updated = datetime.strptime(
            str(payload["updated_at"]), "%Y-%m-%dT%H:%M:%S UTC"
        ).replace(tzinfo=timezone.utc)
    except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError):
        return False, "encrypted backup status is missing or invalid"
    age_sec = now - updated.timestamp()
    if age_sec < 0 or age_sec > maximum_age_hours * 3_600:
        return False, "latest encrypted backup is stale"
    return True, "fresh encrypted backup confirmed"


def _table_rows(connection: sqlite3.Connection, table: str, key: str, values: list[str]) -> list[dict[str, Any]]:
    """Read complete rows for a fixed internal table and key."""
    if table not in {"prediction_decisions", "prediction_outcomes"}:
        raise ValueError("unsupported retention table")
    if key != "decision_id":
        raise ValueError("unsupported retention key")
    if not values:
        return []
    columns = [str(row[1]) for row in connection.execute(f"PRAGMA table_info({table})")]
    placeholders = ",".join("?" for _ in values)
    order = "decision_id,horizon_min" if table == "prediction_outcomes" else "decision_id"
    rows = connection.execute(
        f"SELECT * FROM {table} WHERE {key} IN ({placeholders}) ORDER BY {order}",
        values,
    ).fetchall()
    return [dict(zip(columns, row)) for row in rows]


def _archive_payload(
    decisions: list[dict[str, Any]], outcomes: list[dict[str, Any]]
) -> bytes:
    by_decision: dict[str, list[dict[str, Any]]] = {}
    for outcome in outcomes:
        by_decision.setdefault(str(outcome["decision_id"]), []).append(outcome)
    lines = []
    for decision in decisions:
        item = {
            "schema": REPORT_SCHEMA,
            "decision": decision,
            "outcomes": by_decision.get(str(decision["decision_id"]), []),
        }
        lines.append(json.dumps(item, sort_keys=True, separators=(",", ":")))
    return (("\n".join(lines) + "\n") if lines else "").encode("utf-8")


def _write_archive(directory: Path, payload: bytes) -> tuple[Path, str]:
    """Publish one content-addressed gzip archive with an atomic rename."""
    digest = hashlib.sha256(payload).hexdigest()
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    target = directory / f"prediction-terminal-{digest}.jsonl.gz"
    if target.exists():
        try:
            with gzip.open(target, "rb") as stream:
                existing_digest = hashlib.sha256(stream.read()).hexdigest()
        except (OSError, EOFError) as exc:
            raise RuntimeError("existing retention archive is invalid") from exc
        if existing_digest != digest:
            raise RuntimeError("existing retention archive hash mismatch")
        return target, digest
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=".prediction-terminal-", suffix=".tmp", dir=directory
    )
    try:
        with os.fdopen(descriptor, "wb") as raw:
            with gzip.GzipFile(fileobj=raw, mode="wb", mtime=0) as compressed:
                compressed.write(payload)
            raw.flush()
            os.fsync(raw.fileno())
        os.chmod(temporary_name, 0o600)
        os.replace(temporary_name, target)
    finally:
        try:
            os.unlink(temporary_name)
        except FileNotFoundError:
            pass
    return target, digest


def rotate_prediction_shadow(
    database: Path,
    archive_directory: Path,
    backup_status: Path,
    *,
    retention_days: int = 365,
    maximum_rows: int = 2_000,
    maximum_backup_age_hours: int = 36,
    now: float | None = None,
) -> dict[str, Any]:
    """Archive and prune a bounded batch of fully terminal predictions."""
    if not 30 <= retention_days <= 3_650:
        raise ValueError("prediction retention days must be between 30 and 3650")
    if not 1 <= maximum_rows <= 10_000:
        raise ValueError("maximum rows must be between 1 and 10000")
    current = time.time() if now is None else float(now)
    backup_ok, backup_reason = _backup_is_fresh(
        backup_status, now=current, maximum_age_hours=maximum_backup_age_hours
    )
    result: dict[str, Any] = {
        "database": database.name,
        "classification": "derived_terminal_shadow_telemetry",
        "retention_days": retention_days,
        "status": "BLOCKED" if not backup_ok else "PASS",
        "reason": backup_reason,
        "archived_decisions": 0,
        "archived_outcomes": 0,
        "deleted_decisions": 0,
        "deleted_outcomes": 0,
    }
    if not database.exists() or not backup_ok:
        if not database.exists():
            result.update(status="BLOCKED", reason="prediction database does not exist")
        return result

    # Install role columns before retention filters classified evidence.
    from ladder_dragon.strategy.prediction.runtime import PredictionShadowStore
    PredictionShadowStore(database)

    cutoff_ms = int((current - retention_days * SECONDS_PER_DAY) * 1_000)
    with sqlite3.connect(database, timeout=30) as connection:
        connection.execute("PRAGMA busy_timeout=30000")
        ids = [
            str(row[0])
            for row in connection.execute(
                """SELECT d.decision_id
                   FROM prediction_decisions AS d
                   WHERE d.created_at_ms < ?
                     AND COALESCE(d.evidence_role,'LEGACY')='LEGACY'
                     AND EXISTS(
                         SELECT 1 FROM prediction_outcomes AS o
                         WHERE o.decision_id=d.decision_id
                     )
                     AND NOT EXISTS(
                         SELECT 1 FROM prediction_outcomes AS o
                         WHERE o.decision_id=d.decision_id
                           AND (o.resolved_at_ms IS NULL OR o.resolved_at_ms>=?)
                     )
                   ORDER BY d.created_at_ms,d.decision_id
                   LIMIT ?""",
                (cutoff_ms, cutoff_ms, maximum_rows),
            ).fetchall()
        ]
        if not ids:
            result["reason"] = "no terminal prediction rows exceed retention"
            return result
        decisions = _table_rows(connection, "prediction_decisions", "decision_id", ids)
        outcomes = _table_rows(connection, "prediction_outcomes", "decision_id", ids)

    payload = _archive_payload(decisions, outcomes)
    archive, digest = _write_archive(archive_directory, payload)
    placeholders = ",".join("?" for _ in ids)
    with sqlite3.connect(database, timeout=30, isolation_level=None) as connection:
        connection.execute("PRAGMA busy_timeout=30000")
        connection.execute("BEGIN IMMEDIATE")
        try:
            still_terminal = int(connection.execute(
                f"""SELECT COUNT(*) FROM prediction_decisions AS d
                    WHERE d.decision_id IN ({placeholders})
                      AND d.created_at_ms < ?
                      AND COALESCE(d.evidence_role,'LEGACY')='LEGACY'
                      AND NOT EXISTS(
                          SELECT 1 FROM prediction_outcomes AS o
                          WHERE o.decision_id=d.decision_id
                            AND (o.resolved_at_ms IS NULL OR o.resolved_at_ms>=?)
                      )""",
                [*ids, cutoff_ms, cutoff_ms],
            ).fetchone()[0])
            if still_terminal != len(ids):
                raise RuntimeError("prediction state changed before retention commit")
            deleted_outcomes = connection.execute(
                f"DELETE FROM prediction_outcomes WHERE decision_id IN ({placeholders})",
                ids,
            ).rowcount
            deleted_decisions = connection.execute(
                f"DELETE FROM prediction_decisions WHERE decision_id IN ({placeholders})",
                ids,
            ).rowcount
            if deleted_decisions != len(ids) or deleted_outcomes != len(outcomes):
                raise RuntimeError("retention delete count does not match archive")
            connection.execute("COMMIT")
        except Exception:
            connection.execute("ROLLBACK")
            raise
        connection.execute("PRAGMA wal_checkpoint(PASSIVE)")

    result.update(
        reason="terminal predictions archived and pruned",
        archive=archive.name,
        archive_sha256=digest,
        archived_decisions=len(decisions),
        archived_outcomes=len(outcomes),
        deleted_decisions=deleted_decisions,
        deleted_outcomes=deleted_outcomes,
    )
    return result


def protected_database_inventory(paths: list[Path]) -> list[dict[str, Any]]:
    """Report protected databases without opening or modifying them."""
    output = []
    for path in paths:
        output.append({
            "database": path.name,
            "bytes": path.stat().st_size if path.exists() else 0,
            "classification": "authoritative_no_automatic_deletion",
        })
    return output
