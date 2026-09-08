"""Status-bound external backup links fail closed without their mounted store."""

import hashlib
import json
import os
from datetime import timezone
from pathlib import Path

import pytest

from ladder_dragon.dashboard.services import backup_health as health
from ladder_dragon.persistence import backup_storage


NAME = "ladder-dragon-2026-09-08-120000.tgz.age"


@pytest.fixture
def external_backup(tmp_path, monkeypatch):
    mount = tmp_path / "usb"
    store = mount / "archives"
    store.mkdir(parents=True)
    public = tmp_path / "public"
    public.mkdir()
    content = b"synthetic-age-ciphertext"
    digest = hashlib.sha256(content).hexdigest()
    (store / NAME).write_bytes(content)
    (store / (NAME + ".sha256")).write_text(f"{digest}  {NAME}\n")
    for suffix in ("", ".sha256"):
        (public / (NAME + suffix)).symlink_to(store / (NAME + suffix))
    status = public / "backup_status.json"
    status.write_text(json.dumps({
        "schema_version": 2, "status": "success", "archive_verified": True,
        "archive_name": NAME, "archive_size_bytes": len(content), "archive_sha256": digest,
        "storage": "external", "external_mount": str(mount), "external_directory": str(store),
    }))
    original_stat = Path.stat

    def stat(path, *args, **kwargs):
        result = original_stat(path, *args, **kwargs)
        if path == mount or mount in path.parents:
            fields = list(result)
            fields[2] = 987654  # Synthetic separate filesystem, not a real mount.
            return os.stat_result(fields)
        return result

    monkeypatch.setattr(Path, "stat", stat)
    monkeypatch.setattr(backup_storage.os.path, "ismount", lambda path: path == mount)
    return public, store, status


def _snapshot(fixture):
    public, _store, status = fixture
    return health.backup_snapshot(public_dir=public, status_paths=(status,), timezone=timezone.utc, minimum_archive_bytes=1)


def test_external_link_health(external_backup):
    result = _snapshot(external_backup)
    assert result["status"] == "success"
    assert result["archive_count"] == 1


def test_unmounted_store_is_not_success(external_backup, monkeypatch):
    monkeypatch.setattr(backup_storage.os.path, "ismount", lambda path: False)
    result = _snapshot(external_backup)
    assert result["status"] == "unknown"
    assert result["reason"] == "external backup storage is unavailable"


@pytest.mark.parametrize("change", ["local_copy", "outside_link", "target_link", "oversize_checksum", "missing"])
def test_invalid_external_artifact(external_backup, tmp_path, change):
    public, store, _status = external_backup
    outside = tmp_path / "private-material"
    outside.write_text("must-not-be-exposed")
    if change == "local_copy":
        (public / NAME).unlink()
        (public / NAME).write_bytes(b"synthetic-age-ciphertext")
    elif change == "outside_link":
        (public / NAME).unlink()
        (public / NAME).symlink_to(outside)
    elif change == "target_link":
        (store / NAME).unlink()
        (store / NAME).symlink_to(outside)
    elif change == "oversize_checksum":
        (store / (NAME + ".sha256")).write_bytes(b"x" * 257)
    else:
        (store / NAME).unlink()
    result = _snapshot(external_backup)
    assert result["status"] != "success"
    assert "must-not-be-exposed" not in json.dumps(result)


def test_bad_storage_mode_cannot_use_legacy_fallback(external_backup):
    _public, _store, status = external_backup
    payload = json.loads(status.read_text())
    payload["storage"] = "unknown"
    status.write_text(json.dumps(payload))
    assert _snapshot(external_backup)["status"] == "unknown"
