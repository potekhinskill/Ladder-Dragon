from datetime import datetime, timezone
import io
import json
from pathlib import Path
import sqlite3
from types import SimpleNamespace

import pytest

from bin import depth_archive_retention as module
from ladder_dragon.strategy.market_replay import archive_sha256


def setup_prediction_db(path):
    with sqlite3.connect(path) as connection:
        connection.execute(
            "CREATE TABLE prediction_entry_l2_features (archive_sha256 TEXT)"
        )
        connection.execute(
            "CREATE TABLE prediction_entry_veto_selection_artifacts (artifact_json TEXT)"
        )


def backup_status(path, stamp):
    path.write_text(json.dumps({
        "schema_version": 2,
        "status": "success",
        "archive_verified": True,
        "updated_at": datetime.fromtimestamp(stamp, timezone.utc).strftime(
            "%Y-%m-%dT%H:%M:%S UTC"
        ),
    }), encoding="utf-8")


def segment(directory, index, finished_ms):
    name = f"SOLUSDT-{'a' * 32}-{index:06d}.jsonl"
    archive = directory / name
    archive.write_bytes(f"segment-{index}\n".encode())
    metadata = {
        "schema_version": 2,
        "contains_secrets": False,
        "finished_at_ms": finished_ms,
        "archive_sha256": archive_sha256(archive),
    }
    archive.with_suffix(".jsonl.metadata.json").write_text(
        json.dumps(metadata), encoding="utf-8"
    )
    archive.with_suffix(".calibration.json").write_text(
        json.dumps({"eligible": True}), encoding="utf-8"
    )
    return archive, metadata


def test_retention_requires_backup_and_preserves_recent_and_referenced(tmp_path):
    now = 2_000_000_000.0
    directory = tmp_path / "depth"
    directory.mkdir()
    database = tmp_path / "prediction.sqlite3"
    setup_prediction_db(database)
    rows = [
        segment(directory, index, int((now - 20 * 86_400 + index) * 1000))
        for index in range(26)
    ]
    with sqlite3.connect(database) as connection:
        connection.execute(
            "INSERT INTO prediction_entry_l2_features VALUES(?)",
            (rows[0][1]["archive_sha256"],),
        )
    status = tmp_path / "backup.json"
    backup_status(status, now - 60)
    eligible = module.eligible_segments(
        directory, database=database, backup_status=status,
        retention_days=14, now=now,
    )
    assert [path for path, _ in eligible] == [rows[1][0]]
    backup_status(status, now - module.MAXIMUM_BACKUP_AGE_SEC - 1)
    with pytest.raises(ValueError, match="stale"):
        module.eligible_segments(
            directory, database=database, backup_status=status,
            retention_days=14, now=now,
        )


@pytest.mark.parametrize(
    "queue_name",
    ["drafts", "requests", "confirmation-drafts", "confirmation-requests"],
)
@pytest.mark.parametrize("nested_paths", [False, True])
def test_retention_preserves_sources_pinned_by_pending_replay(
    tmp_path, queue_name, nested_paths
):
    now = 2_000_000_000.0
    directory = tmp_path / "depth"
    directory.mkdir()
    database = tmp_path / "prediction.sqlite3"
    setup_prediction_db(database)
    rows = [
        segment(directory, index, int((now - 20 * 86_400 + index) * 1000))
        for index in range(26)
    ]
    requests = directory / ".historical-replay" / queue_name
    requests.mkdir(parents=True)
    source = {
        "archives": [{
                "path": str(rows[0][0]),
                "sha256": rows[0][1]["archive_sha256"],
            }],
    }
    requests.joinpath("selection.json").write_text(
        json.dumps(
            {"request_schema_version": 2, "paths": [source]}
            if nested_paths else source
        ),
        encoding="utf-8",
    )
    status = tmp_path / "backup.json"
    backup_status(status, now - 60)

    eligible = module.eligible_segments(
        directory,
        database=database,
        backup_status=status,
        retention_days=14,
        now=now,
    )

    assert [path for path, _ in eligible] == [rows[1][0]]


def test_archive_is_verified_before_exact_local_triplet_removal(tmp_path, monkeypatch):
    directory = tmp_path / "depth"
    external = tmp_path / "external"
    directory.mkdir()
    external.mkdir()
    archive, metadata = segment(directory, 0, 1_000)

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
        target.write_bytes(b"age-encrypted-evidence")
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(module.subprocess, "Popen", lambda *_args, **_kwargs: Tar())
    monkeypatch.setattr(module.subprocess, "run", fake_run)
    result = module.archive_segments(
        directory, external, [(archive, metadata)],
        age_recipient="age1" + "q" * 30,
    )
    assert result["archived_segments"] == 1
    assert not archive.exists()
    assert not archive.with_suffix(".jsonl.metadata.json").exists()
    assert not archive.with_suffix(".calibration.json").exists()
    bundles = list(external.glob("*.tar.age"))
    assert len(bundles) == 1
    assert bundles[0].with_name(f"{bundles[0].name}.sha256").is_file()


def test_failed_encryption_never_removes_local_evidence(tmp_path, monkeypatch):
    directory = tmp_path / "depth"
    external = tmp_path / "external"
    directory.mkdir()
    external.mkdir()
    archive, metadata = segment(directory, 0, 1_000)

    class Tar:
        stdout = io.BytesIO(b"public-tar")
        def wait(self, timeout=None):
            return 0
        def poll(self):
            return 0
        def kill(self):
            pass

    monkeypatch.setattr(module.subprocess, "Popen", lambda *_args, **_kwargs: Tar())
    monkeypatch.setattr(
        module.subprocess, "run", lambda *_args, **_kwargs: SimpleNamespace(returncode=1)
    )
    with pytest.raises(RuntimeError, match="archival failed"):
        module.archive_segments(
            directory, external, [(archive, metadata)],
            age_recipient="age1" + "q" * 30,
        )
    assert archive.is_file()
    assert archive.with_suffix(".jsonl.metadata.json").is_file()
    assert archive.with_suffix(".calibration.json").is_file()


def test_deployment_installs_and_mount_binds_retention():
    installer = Path("deploy/install_raspberry_pi.sh").read_text(encoding="utf-8")
    updater = Path("deploy/update_raspberry_pi.sh").read_text(encoding="utf-8")
    assets = Path("deploy/install_runtime_assets.sh").read_text(encoding="utf-8")
    runner = Path("deploy/run_depth_archive_retention.sh").read_text(encoding="utf-8")
    service = Path("deploy/ladder-dragon-depth-retention.service").read_text(encoding="utf-8")
    for source in (installer, updater):
        assert "ladder-dragon-depth-retention.timer" in source
        assert "depth_retention_dropin" in source
        assert "RequiresMountsFor=%s" in source
    assert "/usr/local/bin/ladder-dragon-depth-retention" in assets
    assert "ConditionPathExists=/etc/ladder-dragon/backup.env" in service
    assert "EnvironmentFile=/etc/ladder-dragon/backup.env" in service
    assert "backup.conf" not in service
    assert "ReadWritePaths=/var/lib/ladder-dragon/depth-archives" in service
    assert "CapabilityBoundingSet=CAP_DAC_OVERRIDE CAP_FOWNER" in service
    assert 'mkdir -p "${BACKUP_EXTERNAL_DIR}/depth-evidence"' in runner
    assert 'install -d -m 0700 "${BACKUP_EXTERNAL_DIR}/depth-evidence"' not in runner
