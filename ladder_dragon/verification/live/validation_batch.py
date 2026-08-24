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
import sys
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
    checks = (
        (["git", "status", "--porcelain"], "validation checkout is not clean"),
        (["git", "describe", "--tags", "--exact-match", "HEAD"],
         "validation checkout is not an exact release tag"),
        (["git", "rev-parse", "origin/main"],
         "reviewed origin/main is unavailable"),
    )
    outputs = []
    for command, reason in checks:
        try:
            result = subprocess.run(
                command, check=True, capture_output=True, text=True,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            raise RuntimeError(reason) from exc
        outputs.append(result.stdout.strip())
    if outputs[0]:
        raise RuntimeError("validation checkout is not clean")
    try:
        tag_type = subprocess.run(
            ["git", "cat-file", "-t", f"refs/tags/{outputs[1]}"],
            check=True, capture_output=True, text=True,
        ).stdout.strip()
    except (OSError, subprocess.SubprocessError) as exc:
        raise RuntimeError("validation release tag is unavailable") from exc
    if tag_type != "tag" or outputs[2].lower() != commit:
        raise RuntimeError("validation release identity differs from origin/main")
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
    limit_maker_attempts: int | None = None,
    stop_limit_attempts: int | None = None,
    minimum_cooldown_sec: int = 0,
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
    limit_quota = maximum_attempts if limit_maker_attempts is None else int(
        limit_maker_attempts
    )
    stop_quota = maximum_attempts if stop_limit_attempts is None else int(
        stop_limit_attempts
    )
    if (
        limit_quota < 0 or stop_quota < 0
        or limit_quota + stop_quota < maximum_attempts
        or max(limit_quota, stop_quota) > maximum_attempts
    ):
        raise RuntimeError("validation batch drill quotas are invalid")
    if not 0 <= int(minimum_cooldown_sec) <= 3_600:
        raise RuntimeError("validation batch cooldown is invalid")
    now_ms = int(time.time() * 1000) if created_at_ms is None else int(created_at_ms)
    payload: dict[str, object] = {
        "schema_version": 3,
        "batch_id": uuid.uuid4().hex,
        "symbol": normalized,
        "allowed_drills": list(ALLOWED_DRILLS),
        "maximum_attempts": maximum_attempts,
        "maximum_attempts_by_drill": {
            "LIMIT_MAKER": limit_quota,
            "STOP_LOSS_LIMIT": stop_quota,
        },
        "minimum_cooldown_sec": int(minimum_cooldown_sec),
        "maximum_turnover_usdt": format(turnover, "f"),
        "expires_at_ms": now_ms + duration_hours * 60 * 60_000,
        "created_at_ms": now_ms,
        "product_version": __version__,
        "source_commit": (source_commit or _current_commit()).strip().lower(),
        "persistent_halt_required": True,
        "automatic_stop": True,
    }
    sequence = []
    used = {"LIMIT_MAKER": 0, "STOP_LOSS_LIMIT": 0}
    while len(sequence) < maximum_attempts:
        for drill, quota in (
            ("LIMIT_MAKER", limit_quota),
            ("STOP_LOSS_LIMIT", stop_quota),
        ):
            if len(sequence) < maximum_attempts and used[drill] < quota:
                sequence.append(drill)
                used[drill] += 1
    payload["attempt_sequence"] = sequence
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
        previous_hash = "0" * 64
        try:
            for line in handle:
                if line.strip():
                    row = json.loads(line)
                    if not isinstance(row, dict):
                        raise TypeError("attempt row is not an object")
                    row_hash = str(row.get("entry_sha256", ""))
                    unhashed = dict(row)
                    unhashed.pop("entry_sha256", None)
                    if (
                        row.get("previous_entry_sha256") != previous_hash
                        or not re.fullmatch(r"[0-9a-f]{64}", row_hash)
                        or _sha256(unhashed) != row_hash
                        or row.get("batch_id") != manifest.get("batch_id")
                        or row.get("manifest_sha256")
                        != manifest.get("manifest_sha256")
                    ):
                        raise TypeError("attempt ledger chain differs")
                    rows.append(row)
                    previous_hash = row_hash
        except (UnicodeError, json.JSONDecodeError, TypeError) as exc:
            raise RuntimeError("validation batch ledger is invalid") from exc
        consumed = sum((_decimal(row["turnover_usdt"], field="ledger turnover") for row in rows), Decimal("0"))
        if len(rows) >= int(manifest["maximum_attempts"]):
            raise RuntimeError("validation batch attempt limit reached")
        sequence = manifest.get("attempt_sequence")
        if (
            isinstance(sequence, list)
            and len(rows) < len(sequence)
            and normalized_drill != sequence[len(rows)]
        ):
            raise RuntimeError("validation drill differs from the fixed sequence")
        drill_rows = [row for row in rows if row.get("drill") == normalized_drill]
        quota = int(manifest["maximum_attempts_by_drill"][normalized_drill])
        if len(drill_rows) >= quota:
            raise RuntimeError("validation batch drill quota reached")
        cooldown_ms = int(manifest.get("minimum_cooldown_sec", 0)) * 1_000
        if rows and timestamp - int(rows[-1].get("reserved_at_ms", 0)) < cooldown_ms:
            raise RuntimeError("validation batch cooldown is active")
        if consumed + turnover > _decimal(
            manifest["maximum_turnover_usdt"], field="turnover limit"
        ):
            raise RuntimeError("validation batch turnover limit reached")
        reservation = {
            "schema_version": 2,
            "attempt_id": uuid.uuid4().hex,
            "batch_id": manifest["batch_id"],
            "manifest_sha256": manifest["manifest_sha256"],
            "drill": normalized_drill,
            "symbol": manifest["symbol"],
            "turnover_usdt": format(turnover, "f"),
            "reserved_at_ms": timestamp,
            "status": "RESERVED_BEFORE_MUTATION",
            "previous_entry_sha256": previous_hash,
        }
        reservation["entry_sha256"] = _sha256(reservation)
        handle.seek(0, os.SEEK_END)
        handle.write(_canonical(reservation) + "\n")
        handle.flush()
        os.fsync(handle.fileno())
        return reservation


def run_validation_batch(
    manifest_path: Path, *, notional_usdt: Decimal
) -> int:
    """Run the fixed sequence and stop after the first uncertain result."""
    if os.getenv("BOT_MAINNET_VALIDATION_BATCH_RUN_CONFIRMED", "") != "YES":
        raise RuntimeError("Mainnet validation batch run is not confirmed")
    manifest = _load_manifest(manifest_path)
    sequence = manifest.get("attempt_sequence")
    if not isinstance(sequence, list) or not sequence:
        raise RuntimeError("validation batch fixed sequence is unavailable")
    turnover = _decimal(notional_usdt, field="attempt turnover")
    if turnover > Decimal("6"):
        raise RuntimeError("validation batch attempt exceeds 6 USDT")
    ledger = manifest_path.with_suffix(manifest_path.suffix + ".attempts.ndjson")
    completed = 0
    if ledger.exists():
        completed = sum(
            bool(line.strip())
            for line in ledger.read_text(encoding="utf-8").splitlines()
        )
    child_environment = dict(os.environ)
    child_environment.update({
        "BOT_MAINNET_LIMIT_MAKER_VALIDATION_CONFIRMED": "YES",
        "BOT_MAINNET_LIMIT_MAKER_VALIDATION_CLEANUP_CONFIRMED": "YES",
        "BOT_MAINNET_STOP_LIMIT_VALIDATION_CONFIRMED": "YES",
        "BOT_MAINNET_STOP_LIMIT_VALIDATION_CLEANUP_CONFIRMED": "YES",
    })
    modules = {
        "LIMIT_MAKER": "bin.mainnet_limit_maker_validation",
        "STOP_LOSS_LIMIT": "bin.mainnet_stop_limit_validation",
    }
    pending = sequence[completed:]
    for index, drill in enumerate(pending):
        command = [
            sys.executable,
            "-m",
            modules[str(drill)],
            "--symbol",
            str(manifest["symbol"]),
            "--notional-usdt",
            format(turnover, "f"),
            "--batch-manifest",
            str(manifest_path),
        ]
        result = subprocess.run(command, env=child_environment, check=False)
        if result.returncode != 0:
            return int(result.returncode)
        cooldown = int(manifest.get("minimum_cooldown_sec", 0))
        if cooldown > 0 and index + 1 < len(pending):
            time.sleep(cooldown)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Create a bounded Mainnet validation batch")
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--symbol", default="SOLUSDT")
    parser.add_argument("--maximum-attempts", type=int, required=True)
    parser.add_argument("--maximum-turnover-usdt", type=Decimal, required=True)
    parser.add_argument("--duration-hours", type=int, required=True)
    parser.add_argument("--limit-maker-attempts", type=int)
    parser.add_argument("--stop-limit-attempts", type=int)
    parser.add_argument("--minimum-cooldown-sec", type=int, default=0)
    parser.add_argument("--confirm", required=True)
    return parser


def build_run_parser() -> argparse.ArgumentParser:
    """Build the explicit batch-run parser."""
    parser = argparse.ArgumentParser(description="Run one fixed validation batch")
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--notional-usdt", type=Decimal, default=Decimal("6"))
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
        limit_maker_attempts=args.limit_maker_attempts,
        stop_limit_attempts=args.stop_limit_attempts,
        minimum_cooldown_sec=args.minimum_cooldown_sec,
    )
    print(json.dumps(payload, sort_keys=True))
    return 0


__all__ = [
    "create_batch_manifest",
    "reserve_validation_attempt",
    "run_validation_batch",
]
