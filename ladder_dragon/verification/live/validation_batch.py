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

from ladder_dragon.verification.live.validation_archive import (
    validation_archive_capacity,
)
from product_version import __version__


ALLOWED_DRILLS = ("LIMIT_MAKER", "STOP_LOSS_LIMIT")
HARD_MAX_ATTEMPTS = 12
HARD_MINIMUM_COVERED_ATTEMPTS = 10
HARD_MAX_ATTEMPT_NOTIONAL_USDT = Decimal("6")
HARD_MAX_TURNOVER_USDT = Decimal("144")
HARD_MAX_DURATION_HOURS = 24


class PreMutationValidationFailure(RuntimeError):
    """Identify a proven validation failure before any exchange mutation."""

    def __init__(self, error: BaseException) -> None:
        self.reason_code = str(
            getattr(error, "reason_code", "VALIDATION_PRE_MUTATION_FAILED")
        )
        self.cause_type = str(
            getattr(error, "cause_type", type(error).__name__)
        )
        observed_attempts = getattr(error, "attempts", 0)
        self.attempts = (
            observed_attempts
            if type(observed_attempts) is int and 0 <= observed_attempts <= 3
            else 0
        )
        super().__init__(
            "validation failed before exchange mutation: "
            f"code={self.reason_code} attempts={self.attempts} "
            f"cause={self.cause_type}"
        )


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
    archive_directory: Path,
    symbol: str,
    maximum_attempts: int,
    maximum_turnover_usdt: Decimal,
    duration_hours: int,
    created_at_ms: int | None = None,
    source_commit: str | None = None,
    limit_maker_attempts: int | None = None,
    stop_limit_attempts: int | None = None,
    minimum_cooldown_sec: int = 0,
    minimum_successful_attempts: int | None = None,
    attempt_notional_usdt: Decimal = HARD_MAX_ATTEMPT_NOTIONAL_USDT,
) -> dict[str, object]:
    """Create one immutable authorization envelope without placing an order."""
    normalized = symbol.strip().upper()
    if normalized != "SOLUSDT":
        raise RuntimeError("validation batch is restricted to SOLUSDT")
    if not 1 <= maximum_attempts <= HARD_MAX_ATTEMPTS:
        raise RuntimeError("validation batch attempt limit is outside the hard cap")
    archive_root = archive_directory.resolve()
    archive_capacity = validation_archive_capacity(
        archive_root,
        required_sessions=maximum_attempts,
    )
    minimum_successes = (
        min(maximum_attempts, HARD_MINIMUM_COVERED_ATTEMPTS)
        if minimum_successful_attempts is None
        else int(minimum_successful_attempts)
    )
    if not 1 <= minimum_successes <= maximum_attempts:
        raise RuntimeError("validation batch success minimum is invalid")
    turnover = _decimal(maximum_turnover_usdt, field="turnover limit")
    if turnover > HARD_MAX_TURNOVER_USDT:
        raise RuntimeError("validation batch turnover exceeds the hard cap")
    attempt_notional = _decimal(
        attempt_notional_usdt, field="attempt notional"
    )
    if attempt_notional > HARD_MAX_ATTEMPT_NOTIONAL_USDT:
        raise RuntimeError("validation batch attempt notional exceeds the hard cap")
    attempt_turnover = attempt_notional * Decimal("2")
    required_turnover = attempt_turnover * Decimal(maximum_attempts)
    if turnover < required_turnover:
        raise RuntimeError(
            "validation batch turnover cannot fund its fixed attempt sequence"
        )
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
    payload: dict[str, object] = {
        "schema_version": 7,
        "batch_id": uuid.uuid4().hex,
        "symbol": normalized,
        "allowed_drills": list(ALLOWED_DRILLS),
        "maximum_attempts": maximum_attempts,
        "minimum_successful_attempts": minimum_successes,
        "minimum_successful_attempts_by_drill": {
            drill: 1 if drill in sequence else 0 for drill in ALLOWED_DRILLS
        },
        "maximum_attempts_by_drill": {
            "LIMIT_MAKER": limit_quota,
            "STOP_LOSS_LIMIT": stop_quota,
        },
        "minimum_cooldown_sec": int(minimum_cooldown_sec),
        "maximum_turnover_usdt": format(turnover, "f"),
        "attempt_notional_usdt": format(attempt_notional, "f"),
        "attempt_turnover_usdt": format(attempt_turnover, "f"),
        "expires_at_ms": now_ms + duration_hours * 60 * 60_000,
        "created_at_ms": now_ms,
        "product_version": __version__,
        "source_commit": (source_commit or _current_commit()).strip().lower(),
        "persistent_halt_required": True,
        "automatic_stop": True,
        "archive_directory": str(archive_root),
        "archive_capacity": {
            "maximum_sessions": archive_capacity["maximum_sessions"],
            "occupied_sessions_at_creation": archive_capacity[
                "occupied_sessions"
            ],
            "required_sessions": maximum_attempts,
        },
    }
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


def validation_batch_archive_directory(manifest_path: Path) -> Path:
    """Return the absolute archive directory bound by one batch manifest."""
    manifest = _load_manifest(manifest_path)
    raw = manifest.get("archive_directory")
    if not isinstance(raw, str) or not raw or not Path(raw).is_absolute():
        raise RuntimeError("validation batch archive directory is unavailable")
    return Path(raw).resolve()


def _read_ledger(handle, manifest: Mapping[str, object]) -> list[dict[str, object]]:
    """Read and authenticate every append-only attempt state transition."""
    handle.seek(0)
    rows: list[dict[str, object]] = []
    previous_hash = "0" * 64
    try:
        for line in handle:
            if not line.strip():
                continue
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
                or row.get("manifest_sha256") != manifest.get("manifest_sha256")
            ):
                raise TypeError("attempt ledger chain differs")
            rows.append(row)
            previous_hash = row_hash
    except (UnicodeError, json.JSONDecodeError, TypeError) as exc:
        raise RuntimeError("validation batch ledger is invalid") from exc
    return rows


def _attempt_states(rows: list[dict[str, object]]) -> dict[str, list[dict[str, object]]]:
    states: dict[str, list[dict[str, object]]] = {}
    for row in rows:
        states.setdefault(str(row.get("attempt_id", "")), []).append(row)
    for attempt_id, events in states.items():
        if not attempt_id or events[0].get("status") != "RESERVED_BEFORE_MUTATION":
            raise RuntimeError("validation batch attempt transition is invalid")
        if len(events) > 2 or (
            len(events) == 2
            and events[1].get("status") not in {
                "SUCCEEDED", "FAILED_DEFINITE", "FAILED_UNCERTAIN",
            }
        ):
            raise RuntimeError("validation batch attempt transition is invalid")
    return states


def complete_validation_attempt(
    manifest_path: Path,
    *,
    attempt_id: str,
    status: str,
    archive_path: str | None = None,
    archive_sha256: str | None = None,
    order_refs: tuple[str, ...] = (),
    completed_at_ms: int | None = None,
) -> dict[str, object]:
    """Durably close one reservation after cleanup and archive finalization."""
    terminal = status.strip().upper()
    if terminal not in {"SUCCEEDED", "FAILED_DEFINITE", "FAILED_UNCERTAIN"}:
        raise RuntimeError("validation attempt terminal status is invalid")
    manifest = _load_manifest(manifest_path)
    ledger = manifest_path.with_suffix(manifest_path.suffix + ".attempts.ndjson")
    with ledger.open("a+", encoding="utf-8") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        rows = _read_ledger(handle, manifest)
        states = _attempt_states(rows)
        events = states.get(attempt_id)
        if events is None or len(events) != 1:
            raise RuntimeError("validation attempt is not open")
        digest = str(archive_sha256 or "").lower()
        if digest and not re.fullmatch(r"[0-9a-f]{64}", digest):
            raise RuntimeError("validation attempt archive hash is invalid")
        entry: dict[str, object] = {
            "schema_version": 3,
            "attempt_id": attempt_id,
            "batch_id": manifest["batch_id"],
            "manifest_sha256": manifest["manifest_sha256"],
            "status": terminal,
            "completed_at_ms": (
                int(time.time() * 1000)
                if completed_at_ms is None else int(completed_at_ms)
            ),
            "archive_path": str(archive_path or ""),
            "archive_sha256": digest,
            "order_refs": sorted({str(item) for item in order_refs if str(item)}),
            "previous_entry_sha256": (
                str(rows[-1]["entry_sha256"]) if rows else "0" * 64
            ),
        }
        entry["entry_sha256"] = _sha256(entry)
        handle.seek(0, os.SEEK_END)
        handle.write(_canonical(entry) + "\n")
        handle.flush()
        os.fsync(handle.fileno())
        return entry


def validation_batch_evidence(manifest_path: Path) -> dict[str, object]:
    """Return all terminal outcomes when the fixed cohort has enough coverage."""
    manifest = _load_manifest(manifest_path)
    ledger = manifest_path.with_suffix(manifest_path.suffix + ".attempts.ndjson")
    if not ledger.exists():
        raise RuntimeError("validation batch has no attempt evidence")
    with ledger.open("r", encoding="utf-8") as handle:
        rows = _read_ledger(handle, manifest)
    states = _attempt_states(rows)
    if len(states) != int(manifest["maximum_attempts"]):
        raise RuntimeError("validation batch is incomplete")
    minimum_successes = int(
        manifest.get("minimum_successful_attempts", manifest["maximum_attempts"])
    )
    terminals = [events[-1] for events in states.values()]
    if any(len(events) != 2 for events in states.values()) or any(
        row.get("status") == "FAILED_UNCERTAIN" for row in terminals
    ):
        raise RuntimeError("validation batch contains uncertain evidence")
    successful = [row for row in terminals if row.get("status") == "SUCCEEDED"]
    definite_failures = [
        row for row in terminals if row.get("status") == "FAILED_DEFINITE"
    ]
    if len(successful) < minimum_successes:
        raise RuntimeError("validation batch has insufficient covered attempts")
    drill_by_attempt = {
        attempt_id: str(events[0]["drill"])
        for attempt_id, events in states.items()
    }
    successful_by_drill = {
        drill: sum(
            row.get("status") == "SUCCEEDED"
            and drill_by_attempt[str(row["attempt_id"])] == drill
            for row in terminals
        )
        for drill in ALLOWED_DRILLS
    }
    minimum_by_drill = manifest.get("minimum_successful_attempts_by_drill")
    if not isinstance(minimum_by_drill, Mapping) or any(
        type(minimum_by_drill.get(drill)) is not int
        or int(minimum_by_drill[drill]) < 0
        or successful_by_drill[drill] < int(minimum_by_drill[drill])
        for drill in ALLOWED_DRILLS
    ):
        raise RuntimeError("validation batch drill coverage is insufficient")
    archive_hashes = tuple(
        str(row.get("archive_sha256", "")) for row in successful
    )
    order_refs = tuple(
        str(order_ref)
        for row in successful
        for order_ref in row.get("order_refs", [])
    )
    if (
        any(not re.fullmatch(r"[0-9a-f]{64}", item) for item in archive_hashes)
        or len(set(archive_hashes)) != len(archive_hashes)
        or not order_refs
        or len(set(order_refs)) != len(order_refs)
    ):
        raise RuntimeError("validation batch cohort identity is invalid")
    evidence: dict[str, object] = {
        "schema_version": 3,
        "status": "COHORT_COMPLETE_NOT_REPLAY_READY",
        "batch_id": manifest["batch_id"],
        "manifest_sha256": manifest["manifest_sha256"],
        "attempt_count": len(states),
        "successful_attempt_count": len(successful),
        "definite_failure_count": len(definite_failures),
        "minimum_successful_attempts": minimum_successes,
        "successful_attempts_by_drill": successful_by_drill,
        "minimum_successful_attempts_by_drill": dict(minimum_by_drill),
        "replay_readiness_proven": False,
        "replay_readiness_reason": (
            "actual filled order types require immutable replay import"
        ),
        "archive_sha256s": list(archive_hashes),
        "order_refs": list(order_refs),
        "terminal_outcomes": [
            {
                "attempt_id": str(row["attempt_id"]),
                "status": str(row["status"]),
                "entry_sha256": str(row["entry_sha256"]),
            }
            for row in terminals
        ],
        "ledger_terminal_sha256": rows[-1]["entry_sha256"],
    }
    evidence["cohort_sha256"] = _sha256(evidence)
    return evidence


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
    expected_turnover = _decimal(
        manifest.get("attempt_turnover_usdt"), field="manifest attempt turnover"
    )
    if turnover != expected_turnover:
        raise RuntimeError("validation attempt turnover differs from the manifest")
    ledger = manifest_path.with_suffix(manifest_path.suffix + ".attempts.ndjson")
    ledger.parent.mkdir(parents=True, exist_ok=True)
    with ledger.open("a+", encoding="utf-8") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        rows = _read_ledger(handle, manifest)
        states = _attempt_states(rows)
        reservations = [
            events[0] for events in states.values()
        ]
        if any(len(events) == 1 for events in states.values()):
            raise RuntimeError("validation batch has an unfinished attempt")
        if any(events[-1].get("status") == "FAILED_UNCERTAIN" for events in states.values()):
            raise RuntimeError("validation batch is permanently closed after uncertainty")
        previous_hash = str(rows[-1]["entry_sha256"]) if rows else "0" * 64
        consumed = sum((_decimal(row["turnover_usdt"], field="ledger turnover") for row in reservations), Decimal("0"))
        if len(reservations) >= int(manifest["maximum_attempts"]):
            raise RuntimeError("validation batch attempt limit reached")
        sequence = manifest.get("attempt_sequence")
        if (
            isinstance(sequence, list)
            and len(reservations) < len(sequence)
            and normalized_drill != sequence[len(reservations)]
        ):
            raise RuntimeError("validation drill differs from the fixed sequence")
        drill_rows = [row for row in reservations if row.get("drill") == normalized_drill]
        quota = int(manifest["maximum_attempts_by_drill"][normalized_drill])
        if len(drill_rows) >= quota:
            raise RuntimeError("validation batch drill quota reached")
        cooldown_ms = int(manifest.get("minimum_cooldown_sec", 0)) * 1_000
        if reservations and timestamp - int(reservations[-1].get("reserved_at_ms", 0)) < cooldown_ms:
            raise RuntimeError("validation batch cooldown is active")
        if consumed + turnover > _decimal(
            manifest["maximum_turnover_usdt"], field="turnover limit"
        ):
            raise RuntimeError("validation batch turnover limit reached")
        reservation = {
            "schema_version": 3,
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
    """Run the fixed sequence and stop only when an outcome remains uncertain."""
    if os.getenv("BOT_MAINNET_VALIDATION_BATCH_RUN_CONFIRMED", "") != "YES":
        raise RuntimeError("Mainnet validation batch run is not confirmed")
    manifest = _load_manifest(manifest_path)
    sequence = manifest.get("attempt_sequence")
    if not isinstance(sequence, list) or not sequence:
        raise RuntimeError("validation batch fixed sequence is unavailable")
    notional = _decimal(notional_usdt, field="attempt notional")
    if notional > HARD_MAX_ATTEMPT_NOTIONAL_USDT:
        raise RuntimeError("validation batch attempt exceeds 6 USDT")
    expected_notional = _decimal(
        manifest.get("attempt_notional_usdt"), field="manifest attempt notional"
    )
    if notional != expected_notional:
        raise RuntimeError("validation batch run notional differs from the manifest")
    ledger = manifest_path.with_suffix(manifest_path.suffix + ".attempts.ndjson")
    completed = 0
    definite_failures = 0
    if ledger.exists():
        with ledger.open("r", encoding="utf-8") as handle:
            rows = _read_ledger(handle, manifest)
        states = _attempt_states(rows)
        if any(len(events) == 1 for events in states.values()):
            raise RuntimeError("validation batch has an unfinished attempt")
        if any(events[-1].get("status") == "FAILED_UNCERTAIN" for events in states.values()):
            raise RuntimeError("validation batch is permanently closed after uncertainty")
        completed = len(states)
        definite_failures = sum(
            events[-1].get("status") == "FAILED_DEFINITE"
            for events in states.values()
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
    archive_directory: Path | None = None
    if pending:
        archive_directory = validation_batch_archive_directory(manifest_path)
        validation_archive_capacity(
            archive_directory,
            required_sessions=len(pending),
        )
    for index, drill in enumerate(pending):
        assert archive_directory is not None
        command = [
            sys.executable,
            "-m",
            modules[str(drill)],
            "--symbol",
            str(manifest["symbol"]),
            "--notional-usdt",
            format(notional, "f"),
            "--batch-manifest",
            str(manifest_path),
            "--archive-dir",
            str(archive_directory),
        ]
        result = subprocess.run(command, env=child_environment, check=False)
        if result.returncode == 3:
            with ledger.open("r", encoding="utf-8") as handle:
                refreshed_states = _attempt_states(
                    _read_ledger(handle, manifest)
                )
            if len(refreshed_states) != completed + index + 1:
                raise RuntimeError(
                    "definite validation failure lacks one closed reservation"
                )
            latest_events = list(refreshed_states.values())[-1]
            if (
                len(latest_events) != 2
                or latest_events[-1].get("status") != "FAILED_DEFINITE"
            ):
                raise RuntimeError(
                    "definite validation failure lacks durable absence evidence"
                )
            definite_failures += 1
        elif result.returncode not in {0, 2}:
            return int(result.returncode)
        else:
            with ledger.open("r", encoding="utf-8") as handle:
                refreshed_states = _attempt_states(
                    _read_ledger(handle, manifest)
                )
            if len(refreshed_states) != completed + index + 1:
                raise RuntimeError(
                    "successful validation child lacks one closed reservation"
                )
            latest_events = list(refreshed_states.values())[-1]
            if (
                len(latest_events) != 2
                or latest_events[-1].get("status") != "SUCCEEDED"
            ):
                raise RuntimeError(
                    "successful validation child lacks durable evidence"
                )
        cooldown = int(manifest.get("minimum_cooldown_sec", 0))
        if cooldown > 0 and index + 1 < len(pending):
            time.sleep(cooldown)
    try:
        validation_batch_evidence(manifest_path)
    except RuntimeError:
        return 3
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Create a bounded Mainnet validation batch")
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument(
        "--archive-directory",
        type=Path,
        default=Path("logs/replay-validation-archives"),
    )
    parser.add_argument("--symbol", default="SOLUSDT")
    parser.add_argument("--maximum-attempts", type=int, required=True)
    parser.add_argument("--maximum-turnover-usdt", type=Decimal, required=True)
    parser.add_argument(
        "--attempt-notional-usdt",
        type=Decimal,
        default=HARD_MAX_ATTEMPT_NOTIONAL_USDT,
    )
    parser.add_argument("--duration-hours", type=int, required=True)
    parser.add_argument("--limit-maker-attempts", type=int)
    parser.add_argument("--stop-limit-attempts", type=int)
    parser.add_argument("--minimum-cooldown-sec", type=int, default=0)
    parser.add_argument("--minimum-successful-attempts", type=int)
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
        archive_directory=args.archive_directory,
        symbol=args.symbol,
        maximum_attempts=args.maximum_attempts,
        maximum_turnover_usdt=args.maximum_turnover_usdt,
        duration_hours=args.duration_hours,
        limit_maker_attempts=args.limit_maker_attempts,
        stop_limit_attempts=args.stop_limit_attempts,
        minimum_cooldown_sec=args.minimum_cooldown_sec,
        minimum_successful_attempts=args.minimum_successful_attempts,
        attempt_notional_usdt=args.attempt_notional_usdt,
    )
    print(json.dumps(payload, sort_keys=True))
    return 0


__all__ = [
    "PreMutationValidationFailure",
    "complete_validation_attempt",
    "create_batch_manifest",
    "reserve_validation_attempt",
    "run_validation_batch",
    "validation_batch_archive_directory",
    "validation_batch_evidence",
]
