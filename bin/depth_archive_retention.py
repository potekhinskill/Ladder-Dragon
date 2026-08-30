#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: encrypt completed L2 evidence externally before local rotation.
"""Archive public L2 segments without plaintext staging or evidence loss."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import sqlite3
import subprocess
import time

from ladder_dragon.strategy.depth_segments import atomic_json, bounded_json
from ladder_dragon.strategy.market_replay import archive_sha256


SEGMENT_RE = re.compile(r"^[A-Z0-9]{5,20}-[a-f0-9]{32}-[0-9]{6}\.jsonl$")
MAXIMUM_SEGMENTS_PER_RUN = 48
MAXIMUM_BACKUP_AGE_SEC = 48 * 60 * 60
MINIMUM_LOCAL_SEGMENTS = 24
MAXIMUM_REPLAY_REQUESTS = 128


def _backup_time(path: Path, *, now: float) -> float:
    payload = bounded_json(path)
    if (
        payload.get("schema_version") != 2
        or payload.get("status") != "success"
        or payload.get("archive_verified") is not True
    ):
        raise ValueError("a verified encrypted backup is required")
    raw = str(payload.get("updated_at") or "")
    try:
        stamp = datetime.strptime(raw, "%Y-%m-%dT%H:%M:%S UTC").replace(
            tzinfo=timezone.utc
        ).timestamp()
    except ValueError as exc:
        raise ValueError("backup timestamp is invalid") from exc
    if not 0 <= now - stamp <= MAXIMUM_BACKUP_AGE_SEC:
        raise ValueError("verified encrypted backup is stale")
    return stamp


def _protected_hashes(database: Path) -> set[str]:
    """Keep every segment referenced by live or immutable selection evidence."""
    if not database.exists():
        raise ValueError("prediction evidence database is unavailable")
    connection = sqlite3.connect(database.resolve().as_uri() + "?mode=ro", uri=True)
    try:
        connection.execute("PRAGMA query_only=ON")
        tables = {
            str(row[0]) for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
        hashes: set[str] = set()
        if "prediction_entry_l2_features" in tables:
            hashes.update(
                str(row[0]) for row in connection.execute(
                    "SELECT archive_sha256 FROM prediction_entry_l2_features"
                )
            )
        if "prediction_entry_veto_selection_artifacts" in tables:
            for (raw,) in connection.execute(
                "SELECT artifact_json FROM prediction_entry_veto_selection_artifacts"
            ):
                payload = json.loads(str(raw))
                values = payload.get("source_archive_sha256s", [])
                if isinstance(values, list):
                    hashes.update(str(value) for value in values)
        return {
            value for value in hashes
            if re.fullmatch(r"[a-f0-9]{64}", value)
        }
    finally:
        connection.close()


def _pending_replay_hashes(directory: Path) -> set[str]:
    """Protect every source pinned by a review draft or accepted request."""
    root = directory / ".historical-replay"
    requests = [
        path
        for name in ("drafts", "requests")
        for path in sorted((root / name).glob("*.json"))
        if path.name != "status.json"
    ]
    if len(requests) > MAXIMUM_REPLAY_REQUESTS * 2:
        raise ValueError("historical replay request capacity reached")
    protected: set[str] = set()
    for path in requests:
        payload = bounded_json(path)
        path_rows = (
            payload.get("paths")
            if payload.get("request_schema_version") == 2
            else [payload]
        )
        if not isinstance(path_rows, list) or not 1 <= len(path_rows) <= 12:
            raise ValueError("historical replay path sources are invalid")
        for path_row in path_rows:
            if not isinstance(path_row, dict):
                raise ValueError("historical replay path source is invalid")
            archives = path_row.get("archives")
            if not isinstance(archives, list) or not 1 <= len(archives) <= 10_000:
                raise ValueError("historical replay request sources are invalid")
            for source in archives:
                if not isinstance(source, dict) or set(source) != {"path", "sha256"}:
                    raise ValueError("historical replay source identity is invalid")
                digest = str(source["sha256"])
                if re.fullmatch(r"[a-f0-9]{64}", digest) is None:
                    raise ValueError("historical replay source hash is invalid")
                protected.add(digest)
    return protected


def eligible_segments(
    directory: Path,
    *,
    database: Path,
    backup_status: Path,
    retention_days: int,
    now: float,
) -> list[tuple[Path, dict[str, object]]]:
    """Return verified, calibrated, unreferenced segments safe to archive."""
    if not 1 <= retention_days <= 3650:
        raise ValueError("depth retention days are invalid")
    backup_stamp = _backup_time(backup_status, now=now)
    protected = _protected_hashes(database) | _pending_replay_hashes(directory)
    completed: list[tuple[Path, dict[str, object]]] = []
    for metadata_path in sorted(directory.glob("*.jsonl.metadata.json")):
        raw = metadata_path.name.removesuffix(".metadata.json")
        if not SEGMENT_RE.fullmatch(raw):
            continue
        archive = directory / raw
        calibration = archive.with_suffix(".calibration.json")
        if not archive.is_file() or not calibration.is_file():
            continue
        metadata = bounded_json(metadata_path)
        if (
            metadata.get("schema_version") != 2
            or metadata.get("contains_secrets") is not False
            or not isinstance(metadata.get("finished_at_ms"), int)
        ):
            raise ValueError("depth segment metadata is invalid")
        completed.append((archive, metadata))
    completed.sort(key=lambda item: int(item[1]["finished_at_ms"]))
    cutoff_ms = int((now - retention_days * 86_400) * 1000)
    eligible = []
    for archive, metadata in completed[:-MINIMUM_LOCAL_SEGMENTS]:
        digest = str(metadata.get("archive_sha256") or "")
        finished = int(metadata["finished_at_ms"])
        if finished >= cutoff_ms or digest in protected:
            continue
        if finished / 1000 > backup_stamp:
            raise ValueError("depth segment is newer than verified backup")
        if archive_sha256(archive) != digest:
            raise ValueError("depth segment hash differs before archival")
        eligible.append((archive, metadata))
        if len(eligible) >= MAXIMUM_SEGMENTS_PER_RUN:
            break
    return eligible


def _atomic_bytes(path: Path, payload: bytes) -> None:
    temporary = path.with_name(f".{path.name}.{os.getpid()}.{secrets.token_hex(6)}.tmp")
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def archive_segments(
    directory: Path,
    external_directory: Path,
    segments: list[tuple[Path, dict[str, object]]],
    *,
    age_recipient: str,
) -> dict[str, object]:
    """Encrypt one exact batch, verify publication, then remove local copies."""
    if not segments:
        return {"archived_segments": 0, "archived_bytes": 0}
    if not re.fullmatch(r"age1[0-9a-z]{20,}", age_recipient):
        raise ValueError("age recipient is invalid")
    external_directory.mkdir(parents=True, exist_ok=True)
    source_hashes = [str(metadata["archive_sha256"]) for _, metadata in segments]
    identity = hashlib.sha256("".join(source_hashes).encode()).hexdigest()
    oldest = int(segments[0][1]["finished_at_ms"])
    newest = int(segments[-1][1]["finished_at_ms"])
    name = f"depth-evidence-{oldest}-{newest}-{identity[:16]}.tar.age"
    target = external_directory / name
    checksum = target.with_name(f"{name}.sha256")
    if target.exists() or checksum.exists():
        raise ValueError("depth evidence bundle already exists")
    temporary = target.with_name(f".{name}.{os.getpid()}.{secrets.token_hex(6)}.tmp")
    members = []
    for archive, _metadata in segments:
        members.extend([
            archive.name,
            archive.with_suffix(".jsonl.metadata.json").name,
            archive.with_suffix(".calibration.json").name,
        ])
    tar = subprocess.Popen(
        ["tar", "-C", str(directory), "-cf", "-", "--", *members],
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
    )
    try:
        age = subprocess.run(
            ["age", "-r", age_recipient, "-o", str(temporary)],
            stdin=tar.stdout,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=3600,
            check=False,
        )
        if tar.stdout is not None:
            tar.stdout.close()
        tar_status = tar.wait(timeout=30)
        if age.returncode or tar_status or not temporary.is_file() or temporary.stat().st_size <= 0:
            raise RuntimeError("encrypted depth archival failed")
        digest = _file_sha256(temporary)
        os.replace(temporary, target)
        _atomic_bytes(checksum, f"{digest}  {name}\n".encode())
        if _file_sha256(target) != digest:
            raise RuntimeError("encrypted depth archive verification failed")
        archived_bytes = sum(archive.stat().st_size for archive, _ in segments)
        for archive, _metadata in segments:
            archive.unlink()
            archive.with_suffix(".jsonl.metadata.json").unlink()
            archive.with_suffix(".calibration.json").unlink()
        return {
            "archived_segments": len(segments),
            "archived_bytes": archived_bytes,
            "bundle_sha256": digest,
        }
    finally:
        if tar.poll() is None:
            tar.kill()
            tar.wait()
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--directory", type=Path, required=True)
    parser.add_argument("--external-directory", type=Path, required=True)
    parser.add_argument("--prediction-db", type=Path, required=True)
    parser.add_argument("--backup-status", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--retention-days", type=int, default=14)
    args = parser.parse_args(argv)
    try:
        rows = eligible_segments(
            args.directory,
            database=args.prediction_db,
            backup_status=args.backup_status,
            retention_days=args.retention_days,
            now=time.time(),
        )
        result = archive_segments(
            args.directory,
            args.external_directory,
            rows,
            age_recipient=os.getenv("BACKUP_AGE_RECIPIENT", ""),
        )
        payload = {
            "schema_version": 1,
            "status": "PASS",
            "retention_days": args.retention_days,
            "minimum_local_segments": MINIMUM_LOCAL_SEGMENTS,
            **result,
            "updated_at_ms": int(time.time() * 1000),
        }
        atomic_json(args.report, payload, replace=True)
    except (OSError, RuntimeError, ValueError, sqlite3.Error, subprocess.SubprocessError) as exc:
        print(f"[DEPTH-RETENTION] status=BLOCKED error={type(exc).__name__}")
        return 2
    print(
        f"[DEPTH-RETENTION] status=PASS archived={payload['archived_segments']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
