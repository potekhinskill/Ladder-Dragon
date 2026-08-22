# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: enforce preregistered Mainnet validation attempt and turnover limits.
"""Immutable validation-batch manifests with append-only attempt reservations."""

from __future__ import annotations

import argparse
from decimal import Decimal, InvalidOperation
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import time
import uuid
from typing import Mapping

from product_version import __version__


ALLOWED_DRILLS = ("LIMIT_MAKER", "STOP_LOSS_LIMIT")
HARD_MAX_ATTEMPTS = 10
HARD_MAX_TURNOVER_USDT = Decimal("120")
HARD_MAX_DURATION_HOURS = 24


def _canonical(payload: Mapping[str, object]) -> str:
    return json.dumps(dict(payload), sort_keys=True, separators=(",", ":"))


def _sha256(payload: Mapping[str, object]) -> str:
    return hashlib.sha256(_canonical(payload).encode("utf-8")).hexdigest()


def _decimal(value: object, *, field: str) -> Decimal:
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise RuntimeError(f"validation batch {field} is invalid") from exc
    if not parsed.is_finite() or parsed <= 0:
        raise RuntimeError(f"validation batch {field} must be positive")
    return parsed


def _current_commit() -> str:
    try:
        completed = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise RuntimeError("validation batch source commit is unavailable") from exc
    commit = completed.stdout.strip().lower()
    if not re.fullmatch(r"[0-9a-f]{40}", commit):
        raise RuntimeError("validation batch source commit is invalid")
    return commit


def create_batch_manifest(
    path: Path,
    *,
    symbol: str,
    maximum_attempts: int,
    maximum_turnover_usdt: Decimal,
    duration_hours: int,
    created_at_ms: int | None = None,
    source_commit: str | None = None,
) -> dict[str, object]:
    """Create one immutable authorization envelope without placing an order."""
    normalized = symbol.strip().upper()
    if normalized != "SOLUSDT":
        raise RuntimeError("validation batch is restricted to SOLUSDT")
    if not 1 <= maximum_attempts <= HARD_MAX_ATTEMPTS:
        raise RuntimeError("validation batch attempt limit is outside the hard cap")
    turnover = _decimal(maximum_turnover_usdt, field="turnover limit")
    if turnover > HARD_MAX_TURNOVER_USDT:
        raise RuntimeError("validation batch turnover exceeds the hard cap")
    if not 1 <= duration_hours <= HARD_MAX_DURATION_HOURS:
        raise RuntimeError("validation batch duration is outside the hard cap")
    now_ms = int(time.time() * 1000) if created_at_ms is None else int(created_at_ms)
    payload: dict[str, object] = {
        "schema_version": 1,
        "batch_id": uuid.uuid4().hex,
        "symbol": normalized,
        "allowed_drills": list(ALLOWED_DRILLS),
        "maximum_attempts": maximum_attempts,
        "maximum_turnover_usdt": format(turnover, "f"),
        "expires_at_ms": now_ms + duration_hours * 60 * 60_000,
        "created_at_ms": now_ms,
        "product_version": __version__,
        "source_commit": (source_commit or _current_commit()).strip().lower(),
        "persistent_halt_required": True,
        "automatic_stop": True,
    }
    payload["manifest_sha256"] = _sha256(payload)
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        handle.write(_canonical(payload) + "\n")
        handle.flush()
        os.fsync(handle.fileno())
    return payload


def _load_manifest(path: Path) -> dict[str, object]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise RuntimeError("validation batch manifest is unreadable") from exc
    if not isinstance(payload, dict):
        raise RuntimeError("validation batch manifest is invalid")
    fingerprint = str(payload.pop("manifest_sha256", ""))
    if not re.fullmatch(r"[0-9a-f]{64}", fingerprint) or _sha256(payload) != fingerprint:
        raise RuntimeError("validation batch manifest fingerprint differs")
    payload["manifest_sha256"] = fingerprint
    return payload


def reserve_validation_attempt(
    manifest_path: Path,
    *,
    drill: str,
    symbol: str,
    turnover_usdt: Decimal,
    now_ms: int | None = None,
) -> dict[str, object]:
    """Durably consume one bounded attempt before an exchange mutation."""
    manifest = _load_manifest(manifest_path)
    timestamp = int(time.time() * 1000) if now_ms is None else int(now_ms)
    if manifest.get("product_version") != __version__:
        raise RuntimeError("validation batch product version differs")
    if manifest.get("source_commit") != _current_commit():
        raise RuntimeError("validation batch source commit differs")
    if timestamp > int(manifest.get("expires_at_ms", 0)):
        raise RuntimeError("validation batch expired")
    normalized_drill = drill.strip().upper()
    if normalized_drill not in manifest.get("allowed_drills", []):
        raise RuntimeError("validation drill is not authorized by the batch")
    if symbol.strip().upper() != manifest.get("symbol"):
        raise RuntimeError("validation batch symbol differs")
    turnover = _decimal(turnover_usdt, field="attempt turnover")
    ledger = manifest_path.with_suffix(manifest_path.suffix + ".attempts.ndjson")
    ledger.parent.mkdir(parents=True, exist_ok=True)
    with ledger.open("a+", encoding="utf-8") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        handle.seek(0)
        rows = []
        try:
            for line in handle:
                if line.strip():
                    row = json.loads(line)
                    if not isinstance(row, dict):
                        raise TypeError("attempt row is not an object")
                    rows.append(row)
        except (UnicodeError, json.JSONDecodeError, TypeError) as exc:
            raise RuntimeError("validation batch ledger is invalid") from exc
        consumed = sum((_decimal(row["turnover_usdt"], field="ledger turnover") for row in rows), Decimal("0"))
        if len(rows) >= int(manifest["maximum_attempts"]):
            raise RuntimeError("validation batch attempt limit reached")
        if consumed + turnover > _decimal(
            manifest["maximum_turnover_usdt"], field="turnover limit"
        ):
            raise RuntimeError("validation batch turnover limit reached")
        reservation = {
            "schema_version": 1,
            "attempt_id": uuid.uuid4().hex,
            "batch_id": manifest["batch_id"],
            "manifest_sha256": manifest["manifest_sha256"],
            "drill": normalized_drill,
            "symbol": manifest["symbol"],
            "turnover_usdt": format(turnover, "f"),
            "reserved_at_ms": timestamp,
            "status": "RESERVED_BEFORE_MUTATION",
        }
        handle.seek(0, os.SEEK_END)
        handle.write(_canonical(reservation) + "\n")
        handle.flush()
        os.fsync(handle.fileno())
        return reservation


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Create a bounded Mainnet validation batch")
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--symbol", default="SOLUSDT")
    parser.add_argument("--maximum-attempts", type=int, required=True)
    parser.add_argument("--maximum-turnover-usdt", type=Decimal, required=True)
    parser.add_argument("--duration-hours", type=int, required=True)
    parser.add_argument("--confirm", required=True)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    if args.confirm != "CREATE_VALIDATION_BATCH":
        raise SystemExit("--confirm must equal CREATE_VALIDATION_BATCH")
    payload = create_batch_manifest(
        args.manifest,
        symbol=args.symbol,
        maximum_attempts=args.maximum_attempts,
        maximum_turnover_usdt=args.maximum_turnover_usdt,
        duration_hours=args.duration_hours,
    )
    print(json.dumps(payload, sort_keys=True))
    return 0


__all__ = ["create_batch_manifest", "reserve_validation_attempt"]
