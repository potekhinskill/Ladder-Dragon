from datetime import datetime, timezone
from decimal import Decimal
import io
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from bin import mainnet_validation_archive_retention as retention
from ladder_dragon.strategy.market_replay import archive_sha256
from ladder_dragon.verification.live import validation_batch


COMMIT = "a" * 40
NOW = 2_000_000_000.0


def _backup_status(path: Path, stamp: float) -> None:
    path.write_text(json.dumps({
        "schema_version": 2,
        "status": "success",
        "archive_verified": True,
        "updated_at": datetime.fromtimestamp(stamp, timezone.utc).strftime(
            "%Y-%m-%dT%H:%M:%S UTC"
        ),
    }))


def _terminal_batch(tmp_path: Path, monkeypatch, statuses):
    logs = tmp_path / "logs"
    directory = logs / "replay-validation-archives"
    directory.mkdir(parents=True)
    manifest_path = logs / "batch.json"
    validation_batch.create_batch_manifest(
        manifest_path,
        archive_directory=directory,
        symbol="SOLUSDT",
        maximum_attempts=len(statuses),
        minimum_successful_attempts=2,
        maximum_turnover_usdt=Decimal(12 * len(statuses)),
        duration_hours=24,
        created_at_ms=int((NOW - 100) * 1000),
        source_commit=COMMIT,
    )
    monkeypatch.setattr(validation_batch, "_current_commit", lambda: COMMIT)
    archives = []
    for index, status in enumerate(statuses, 1):
        drill = "LIMIT_MAKER" if index % 2 else "STOP_LOSS_LIMIT"
        reservation = validation_batch.reserve_validation_attempt(
            manifest_path,
            drill=drill,
            symbol="SOLUSDT",
            turnover_usdt=Decimal("12"),
            now_ms=int((NOW - 90 + index) * 1000),
        )
        archive_path = None
        digest = None
        if status != "FAILED_DEFINITE_PRE_MUTATION":
            label = "maker" if drill == "LIMIT_MAKER" else "stop"
            archive_path = directory / (
                f"SOLUSDT-{label}-2.20.300-20260903T12000{index}Z-{index}.jsonl"
            )
            archive_path.write_text(f"archive-{index}\n")
            digest = archive_sha256(archive_path)
            archive_path.with_suffix(".jsonl.metadata.json").write_text(
                json.dumps({
                    "schema_version": 1,
                    "contains_secrets": False,
                    "archive_sha256": digest,
                    "finished_at_ms": int((NOW - 20 + index) * 1000),
                })
            )
            archives.append(archive_path)
        terminal = (
            "FAILED_DEFINITE"
            if status == "FAILED_DEFINITE_PRE_MUTATION" else status
        )
        validation_batch.complete_validation_attempt(
            manifest_path,
            attempt_id=reservation["attempt_id"],
            status=terminal,
            archive_path=str(archive_path or ""),
            archive_sha256=digest,
            order_refs=((f"order-{index}",) if terminal == "SUCCEEDED" else ()),
            completed_at_ms=int((NOW - 10 + index) * 1000),
        )
    backup = tmp_path / "backup.json"
    _backup_status(backup, NOW - 5)
    return manifest_path, directory, backup, archives


def test_rejected_batch_preview_requires_backup_and_failed_promotion(
    tmp_path, monkeypatch
):
    manifest, directory, backup, archives = _terminal_batch(
        tmp_path,
        monkeypatch,
        ("SUCCEEDED", "FAILED_DEFINITE", "FAILED_DEFINITE_PRE_MUTATION"),
    )

    audit, pairs = retention.rejected_batch_archives(
        manifest,
        directory=directory,
        backup_status=backup,
        now=NOW,
    )

    assert audit["promotion_audit"] == "REJECTED_INSUFFICIENT_COVERAGE"
    assert audit["successful_attempt_count"] == 1
    assert [pair[0] for pair in pairs] == archives

    _backup_status(backup, NOW - retention.MAXIMUM_BACKUP_AGE_SEC - 1)
    with pytest.raises(ValueError, match="stale"):
        retention.rejected_batch_archives(
            manifest,
            directory=directory,
            backup_status=backup,
            now=NOW,
        )


def test_promotion_eligible_or_uncertain_batch_must_remain_local(
    tmp_path, monkeypatch
):
    manifest, directory, backup, _archives = _terminal_batch(
        tmp_path / "eligible",
        monkeypatch,
        ("SUCCEEDED", "SUCCEEDED"),
    )
    with pytest.raises(ValueError, match="promotion-eligible"):
        retention.rejected_batch_archives(
            manifest, directory=directory, backup_status=backup, now=NOW
        )

    manifest, directory, backup, _archives = _terminal_batch(
        tmp_path / "uncertain",
        monkeypatch,
        ("SUCCEEDED", "FAILED_UNCERTAIN"),
    )
    with pytest.raises(ValueError, match="uncertain"):
        retention.rejected_batch_archives(
            manifest, directory=directory, backup_status=backup, now=NOW
        )


def test_archive_and_metadata_symlinks_are_rejected(tmp_path, monkeypatch):
    manifest, directory, backup, archives = _terminal_batch(
        tmp_path,
        monkeypatch,
        ("SUCCEEDED", "FAILED_DEFINITE"),
    )
    archive = archives[0]
    real_archive = archive.with_name(f"real-{archive.name}")
    archive.rename(real_archive)
    archive.symlink_to(real_archive)

    with pytest.raises(ValueError, match="archive path is invalid"):
        retention.rejected_batch_archives(
            manifest, directory=directory, backup_status=backup, now=NOW
        )

    archive.unlink()
    real_archive.rename(archive)
    metadata = archive.with_suffix(".jsonl.metadata.json")
    real_metadata = metadata.with_name(f"real-{metadata.name}")
    metadata.rename(real_metadata)
    metadata.symlink_to(real_metadata)

    with pytest.raises(ValueError, match="metadata is unavailable"):
        retention.rejected_batch_archives(
            manifest, directory=directory, backup_status=backup, now=NOW
        )

def test_verified_encryption_precedes_exact_source_removal(
    tmp_path, monkeypatch
):
    manifest, directory, backup, archives = _terminal_batch(
        tmp_path,
        monkeypatch,
        ("SUCCEEDED", "FAILED_DEFINITE", "FAILED_DEFINITE_PRE_MUTATION"),
    )
    audit, pairs = retention.rejected_batch_archives(
        manifest, directory=directory, backup_status=backup, now=NOW
    )
    external = tmp_path / "external"
    external.mkdir()

    class Tar:
        def __init__(self):
            self.stdout = io.BytesIO(b"public-tar")

        def wait(self, timeout=None):
            return 0

        def poll(self):
            return 0

        def kill(self):
            raise AssertionError("completed tar was killed")

    def fake_run(arguments, **_kwargs):
        target = Path(arguments[arguments.index("-o") + 1])
        target.write_bytes(b"age-encrypted-validation-evidence")
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(retention.subprocess, "Popen", lambda *_a, **_k: Tar())
    monkeypatch.setattr(retention.subprocess, "run", fake_run)

    result = retention.archive_rejected_batch(
        manifest,
        external,
        audit,
        pairs,
        age_recipient="age1" + "q" * 30,
    )

    assert result["status"] == "ARCHIVED"
    assert manifest.is_file()
    assert manifest.with_suffix(".json.attempts.ndjson").is_file()
    assert manifest.with_suffix(".json.archive-audit.json").is_file()
    assert not any(path.exists() for path in archives)
    assert len(list(external.glob("*.tar.age"))) == 1
    assert len(list(external.glob("*.tar.age.sha256"))) == 1


def test_failed_encryption_preserves_every_local_source(tmp_path, monkeypatch):
    manifest, directory, backup, archives = _terminal_batch(
        tmp_path,
        monkeypatch,
        ("SUCCEEDED", "FAILED_DEFINITE", "FAILED_DEFINITE_PRE_MUTATION"),
    )
    audit, pairs = retention.rejected_batch_archives(
        manifest, directory=directory, backup_status=backup, now=NOW
    )
    external = tmp_path / "external"
    external.mkdir()

    class Tar:
        stdout = io.BytesIO(b"public-tar")

        def wait(self, timeout=None):
            return 0

        def poll(self):
            return 0

        def kill(self):
            pass

    monkeypatch.setattr(retention.subprocess, "Popen", lambda *_a, **_k: Tar())
    monkeypatch.setattr(
        retention.subprocess,
        "run",
        lambda *_a, **_k: SimpleNamespace(returncode=1),
    )

    with pytest.raises(RuntimeError, match="archival failed"):
        retention.archive_rejected_batch(
            manifest,
            external,
            audit,
            pairs,
            age_recipient="age1" + "q" * 30,
        )

    assert all(path.is_file() for path in archives)
    assert all(
        path.with_suffix(".jsonl.metadata.json").is_file()
        for path in archives
    )
    assert manifest.with_suffix(".json.archive-audit.json").is_file()


def test_preview_failure_does_not_expose_metadata_content(
    tmp_path, monkeypatch, capsys
):
    manifest, directory, backup, archives = _terminal_batch(
        tmp_path,
        monkeypatch,
        ("SUCCEEDED", "FAILED_DEFINITE", "FAILED_DEFINITE_PRE_MUTATION"),
    )
    metadata_path = archives[0].with_suffix(".jsonl.metadata.json")
    metadata = json.loads(metadata_path.read_text())
    metadata["contains_secrets"] = True
    metadata["private_detail"] = "private-source-text"
    metadata_path.write_text(json.dumps(metadata))

    result = retention.main([
        "--manifest", str(manifest),
        "--directory", str(directory),
        "--external-directory", str(tmp_path / "external"),
        "--backup-status", str(backup),
    ])

    output = capsys.readouterr().out
    assert result == 2
    assert json.loads(output)["status"] == "BLOCKED"
    assert "private-source-text" not in output


def test_deployment_installs_manual_hardened_retention_wrapper():
    wrapper = Path(
        "deploy/run_mainnet_validation_archive_retention.sh"
    ).read_text()
    assets = Path("deploy/install_runtime_assets.sh").read_text()

    assert "[[ \"${EUID}\" -eq 0 ]]" in wrapper
    assert "BACKUP_EXTERNAL_MOUNT" in wrapper
    assert "findmnt -T" in wrapper
    assert "ARCHIVE_REJECTED_VALIDATION_BATCH" in wrapper
    assert 'cd "${PROJECT_DIR}"' in wrapper
    assert "exec env PYTHONPATH=." in wrapper
    assert "ladder-dragon-validation-retention" in assets
