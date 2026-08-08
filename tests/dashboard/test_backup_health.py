"""Encrypted backup evidence regressions for the dashboard."""

import hashlib
import json
import os
from datetime import timezone
from pathlib import Path

from ladder_dragon.dashboard.services.backup_health import backup_snapshot


ARCHIVE = "ladder-dragon-2026-08-08-120000.tgz.age"


def _status(directory: Path, *, name: str = ARCHIVE, size: int, digest: str):
    path = directory / "backup_status.json"
    path.write_text(
        json.dumps({
            "schema_version": 2,
            "status": "success",
            "reason": "",
            "archive_name": name,
            "archive_size_bytes": size,
            "archive_sha256": digest,
            "archive_verified": True,
        }),
        encoding="utf-8",
    )
    return path


def _archive(directory: Path, *, name: str = ARCHIVE, content: bytes = b"age-data"):
    path = directory / name
    path.write_bytes(content)
    digest = hashlib.sha256(content).hexdigest()
    (directory / f"{name}.sha256").write_text(
        f"{digest}  {name}\n", encoding="ascii"
    )
    return path, digest


def _snapshot(directory: Path, status: Path, *, minimum=1):
    return backup_snapshot(
        public_dir=directory,
        status_paths=(status,),
        timezone=timezone.utc,
        minimum_archive_bytes=minimum,
        now=lambda: 100.0,
    )


def test_archive_without_verified_status_is_unknown(tmp_path):
    _archive(tmp_path)

    result = _snapshot(tmp_path, tmp_path / "missing.json")

    assert result["status"] == "unknown"
    assert result["reason"] == "verified backup status is unavailable"
    assert "last_success" not in result


def test_bad_status_is_unknown(tmp_path):
    _archive(tmp_path)
    status = tmp_path / "backup_status.json"
    status.write_text("not-json", encoding="utf-8")

    corrupt = _snapshot(tmp_path, status)
    status.write_text('{"status":"success"}', encoding="utf-8")
    legacy = _snapshot(tmp_path, status)

    assert corrupt["status"] == "unknown"
    assert legacy["status"] == "unknown"


def test_matching_identity_size_and_checksum_are_success(tmp_path):
    archive, digest = _archive(tmp_path)
    status = _status(
        tmp_path, size=archive.stat().st_size, digest=digest
    )

    result = _snapshot(tmp_path, status)

    assert result["status"] == "success"
    assert result["last_success"]["name"] == ARCHIVE
    assert result["last_success"]["sha256"] == digest


def test_suspiciously_small_archive_is_unknown(tmp_path):
    archive, digest = _archive(tmp_path, content=b"")
    status = _status(tmp_path, size=archive.stat().st_size, digest=digest)

    result = _snapshot(tmp_path, status, minimum=1024)

    assert result["status"] == "unknown"
    assert result["reason"] == "archive is suspiciously small"


def test_stale_success_cannot_confirm_a_newer_archive(tmp_path):
    archive, digest = _archive(tmp_path)
    status = _status(tmp_path, size=archive.stat().st_size, digest=digest)
    newer_name = "ladder-dragon-2026-08-08-130000.tgz.age"
    newer, _digest = _archive(tmp_path, name=newer_name)
    os.utime(archive, (10, 10))
    os.utime(newer, (20, 20))

    result = _snapshot(tmp_path, status)

    assert result["status"] == "unknown"
    assert result["reason"] == "a newer unverified archive exists"


def test_checksum_or_size_mismatch_is_unknown(tmp_path):
    archive, digest = _archive(tmp_path)
    status = _status(tmp_path, size=archive.stat().st_size + 1, digest=digest)

    size_result = _snapshot(tmp_path, status)
    status = _status(tmp_path, size=archive.stat().st_size, digest="0" * 64)
    digest_result = _snapshot(tmp_path, status)

    assert size_result["reason"] == "archive size differs from backup status"
    assert digest_result["reason"] == "archive checksum evidence differs"


def test_status_archive_name_cannot_escape_public_directory(tmp_path):
    outside = tmp_path.parent / "secret-backup-material"
    outside.write_text("must-not-be-read", encoding="utf-8")
    status = _status(
        tmp_path,
        name="../secret-backup-material",
        size=outside.stat().st_size,
        digest=hashlib.sha256(outside.read_bytes()).hexdigest(),
    )

    result = _snapshot(tmp_path, status)

    assert result["status"] == "unknown"
    assert result["reason"] == "verified backup identity is invalid"
    assert "must-not-be-read" not in json.dumps(result)


def test_failed_status_remains_failed_without_an_archive(tmp_path):
    status = tmp_path / "backup_status.json"
    status.write_text(
        json.dumps({
            "schema_version": 2,
            "status": "failed",
            "reason": "backup exited with code 1",
        }),
        encoding="utf-8",
    )

    result = _snapshot(tmp_path, status)

    assert result == {
        "status": "failed",
        "reason": "backup exited with code 1",
        "directory": str(tmp_path),
        "archive_count": 0,
    }


def test_newer_failed_status_wins_over_stale_success(tmp_path):
    archive, digest = _archive(tmp_path)
    stale = tmp_path / "runtime-status.json"
    current = tmp_path / "public-status.json"
    _status(tmp_path, size=archive.stat().st_size, digest=digest).replace(stale)
    current.write_text(
        json.dumps({
            "schema_version": 2,
            "status": "failed",
            "reason": "latest attempt failed",
        }),
        encoding="utf-8",
    )
    os.utime(stale, (10, 10))
    os.utime(current, (20, 20))

    result = backup_snapshot(
        public_dir=tmp_path,
        status_paths=(stale, current),
        timezone=timezone.utc,
        minimum_archive_bytes=1,
    )

    assert result["status"] == "failed"
    assert result["reason"] == "latest attempt failed"
