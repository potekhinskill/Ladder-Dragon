#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: archive rejected Mainnet validation sources after verified backup.
"""Encrypt terminal rejected validation evidence before local source removal."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import subprocess
import time

from ladder_dragon.strategy.depth_segments import bounded_json
from ladder_dragon.strategy.market_replay import archive_sha256
from ladder_dragon.verification.live.validation_batch import (
    _attempt_states,
    _load_manifest,
    _read_ledger,
)


MAXIMUM_BACKUP_AGE_SEC = 48 * 60 * 60
MAXIMUM_BATCH_ARCHIVES = 12
ARCHIVE_NAME = re.compile(
    r"^[A-Z0-9]{5,20}-(?:maker|stop)-[0-9]+\.[0-9]+\.[0-9]+-"
    r"[0-9]{8}T[0-9]{6}Z-[0-9]+\.jsonl$"
)


def _backup_time(path: Path, *, now: float) -> float:
    if path.is_symlink() or not path.is_file():
        raise ValueError("verified encrypted backup status is unavailable")
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


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _canonical(payload: dict[str, object]) -> bytes:
    return (
        json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n"
    ).encode()


def _atomic_bytes(path: Path, payload: bytes) -> None:
    temporary = path.with_name(
        f".{path.name}.{os.getpid()}.{secrets.token_hex(6)}.tmp"
    )
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


def rejected_batch_archives(
    manifest_path: Path,
    *,
    directory: Path,
    backup_status: Path,
    now: float,
) -> tuple[dict[str, object], list[tuple[Path, Path]]]:
    """Audit one terminal rejected batch and return its verified source pairs."""
    backup_stamp = _backup_time(backup_status, now=now)
    if manifest_path.is_symlink() or not manifest_path.is_file():
        raise ValueError("validation batch manifest path is invalid")
    manifest = _load_manifest(manifest_path)
    root = directory.resolve()
    bound_root = manifest.get("archive_directory")
    if bound_root is not None and Path(str(bound_root)).resolve() != root:
        raise ValueError("validation batch archive directory differs")
    ledger = manifest_path.with_suffix(manifest_path.suffix + ".attempts.ndjson")
    if ledger.is_symlink() or not ledger.is_file():
        raise ValueError("validation batch ledger path is invalid")
    with ledger.open("r", encoding="utf-8") as handle:
        rows = _read_ledger(handle, manifest)
    states = _attempt_states(rows)
    if len(states) != int(manifest["maximum_attempts"]) or any(
        len(events) != 2 for events in states.values()
    ):
        raise ValueError("validation batch is not terminal")
    terminals = [events[-1] for events in states.values()]
    if any(row.get("status") == "FAILED_UNCERTAIN" for row in terminals):
        raise ValueError("uncertain validation evidence must remain local")
    successful = sum(row.get("status") == "SUCCEEDED" for row in terminals)
    if successful >= int(manifest["minimum_successful_attempts"]):
        raise ValueError("promotion-eligible validation evidence must remain local")
    pairs: list[tuple[Path, Path]] = []
    digests: set[str] = set()
    for terminal in terminals:
        raw_path = str(terminal.get("archive_path") or "")
        digest = str(terminal.get("archive_sha256") or "")
        if not raw_path and not digest:
            continue
        if not raw_path or re.fullmatch(r"[a-f0-9]{64}", digest) is None:
            raise ValueError("validation archive identity is incomplete")
        raw_archive = Path(raw_path)
        if raw_archive.is_symlink():
            raise ValueError("validation archive path is invalid")
        archive = raw_archive.resolve()
        if (
            archive.parent != root
            or ARCHIVE_NAME.fullmatch(archive.name) is None
            or not archive.is_file()
        ):
            raise ValueError("validation archive path is invalid")
        raw_metadata = raw_archive.with_suffix(".jsonl.metadata.json")
        if raw_metadata.is_symlink():
            raise ValueError("validation archive metadata is unavailable")
        metadata_path = raw_metadata.resolve()
        if metadata_path.parent != root or not metadata_path.is_file():
            raise ValueError("validation archive metadata is unavailable")
        metadata = bounded_json(metadata_path)
        if (
            metadata.get("schema_version") != 1
            or metadata.get("contains_secrets") is not False
            or metadata.get("archive_sha256") != digest
            or not isinstance(metadata.get("finished_at_ms"), int)
        ):
            raise ValueError("validation archive metadata is invalid")
        if int(metadata["finished_at_ms"]) / 1000 > backup_stamp:
            raise ValueError("validation archive is newer than verified backup")
        if archive_sha256(archive) != digest or digest in digests:
            raise ValueError("validation archive hash differs before archival")
        digests.add(digest)
        pairs.append((archive, metadata_path))
    if not 1 <= len(pairs) <= MAXIMUM_BATCH_ARCHIVES:
        raise ValueError("validation archive batch size is invalid")
    audit = {
        "batch_id": manifest["batch_id"],
        "manifest_sha256": manifest["manifest_sha256"],
        "attempt_count": len(states),
        "successful_attempt_count": successful,
        "minimum_successful_attempts": manifest["minimum_successful_attempts"],
        "archive_count": len(pairs),
        "archive_sha256s": sorted(digests),
        "promotion_audit": "REJECTED_INSUFFICIENT_COVERAGE",
        "ledger_terminal_sha256": rows[-1]["entry_sha256"],
    }
    return audit, pairs


def archive_rejected_batch(
    manifest_path: Path,
    external_directory: Path,
    audit: dict[str, object],
    pairs: list[tuple[Path, Path]],
    *,
    age_recipient: str,
) -> dict[str, object]:
    """Encrypt and verify one rejected batch before exact local source removal."""
    if re.fullmatch(r"age1[0-9a-z]{20,}", age_recipient) is None:
        raise ValueError("age recipient is invalid")
    if external_directory.is_symlink() or not external_directory.is_dir():
        raise ValueError("external validation archive directory is unavailable")
    ledger = manifest_path.with_suffix(manifest_path.suffix + ".attempts.ndjson")
    source_root = manifest_path.parent.resolve()
    batch_id = str(audit["batch_id"])
    terminal = str(audit["ledger_terminal_sha256"])
    name = f"validation-evidence-{batch_id}-{terminal[:16]}.tar.age"
    target = external_directory / name
    checksum = external_directory / f"{name}.sha256"
    if target.exists() or checksum.exists():
        raise ValueError("validation evidence bundle already exists")
    audit_path = manifest_path.with_suffix(
        manifest_path.suffix + ".archive-audit.json"
    )
    audit_record = {
        "schema_version": 1,
        "status": "REJECTED_INSUFFICIENT_COVERAGE",
        "bundle": name,
        **audit,
    }
    audit_record["audit_sha256"] = hashlib.sha256(
        _canonical(audit_record)
    ).hexdigest()
    encoded_audit = _canonical(audit_record)
    if audit_path.exists():
        if audit_path.read_bytes() != encoded_audit:
            raise ValueError("validation archival audit differs")
    else:
        _atomic_bytes(audit_path, encoded_audit)
    members = [manifest_path.resolve(), ledger.resolve(), audit_path.resolve()]
    members.extend(path for pair in pairs for path in pair)
    if any(source_root not in path.parents and path != source_root for path in members):
        raise ValueError("validation archive source root differs")
    relative_members = [str(path.relative_to(source_root)) for path in members]
    temporary = external_directory / (
        f".{name}.{os.getpid()}.{secrets.token_hex(6)}.tmp"
    )
    tar = subprocess.Popen(
        ["tar", "-C", str(source_root), "-cf", "-", "--", *relative_members],
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
        if (
            age.returncode
            or tar_status
            or not temporary.is_file()
            or temporary.stat().st_size <= 0
        ):
            raise RuntimeError("encrypted validation archival failed")
        digest = _file_sha256(temporary)
        os.replace(temporary, target)
        _atomic_bytes(checksum, f"{digest}  {name}\n".encode())
        if _file_sha256(target) != digest:
            raise RuntimeError("encrypted validation archive verification failed")
        archived_bytes = sum(archive.stat().st_size for archive, _ in pairs)
        for archive, metadata in pairs:
            archive.unlink()
            metadata.unlink()
        return {
            **audit,
            "status": "ARCHIVED",
            "archived_bytes": archived_bytes,
            "bundle": name,
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
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--directory", type=Path, required=True)
    parser.add_argument("--external-directory", type=Path, required=True)
    parser.add_argument("--backup-status", type=Path, required=True)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--confirm", default="")
    args = parser.parse_args(argv)
    try:
        audit, pairs = rejected_batch_archives(
            args.manifest,
            directory=args.directory,
            backup_status=args.backup_status,
            now=time.time(),
        )
        if args.apply:
            if args.confirm != "ARCHIVE_REJECTED_VALIDATION_BATCH":
                raise ValueError("validation archival confirmation is required")
            payload = archive_rejected_batch(
                args.manifest,
                args.external_directory,
                audit,
                pairs,
                age_recipient=os.getenv("BACKUP_AGE_RECIPIENT", ""),
            )
        else:
            payload = {**audit, "status": "PREVIEW"}
    except (OSError, RuntimeError, ValueError, subprocess.SubprocessError) as exc:
        print(
            json.dumps(
                {"status": "BLOCKED", "cause_type": type(exc).__name__},
                sort_keys=True,
            )
        )
        return 2
    print(json.dumps(payload, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
