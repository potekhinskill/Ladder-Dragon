"""Execute the shipped retention helper against isolated synthetic ciphertext."""

from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest


ROOT = Path(__file__).resolve().parents[2]
SOURCE = (ROOT / "deploy/backup_raspberry_pi.sh").read_text()


def helper(function):
    body = SOURCE.split(function + "() {", 1)[1]
    return body.split("<<'PY'\n", 1)[1].split("\nPY\n", 1)[0]


def archive(root, days, hour=12):
    stamp = (datetime.now(timezone.utc) - timedelta(days=days)).replace(hour=hour, minute=0, second=0)
    name = "ladder-dragon-" + stamp.strftime("%Y-%m-%d-%H%M%S") + ".tgz.age"
    path = root / name
    data = ("synthetic ciphertext " + name).encode()
    path.write_bytes(data)
    path.with_name(name + ".sha256").write_text(hashlib.sha256(data).hexdigest() + "  " + name + "\n")
    return path


def run(root, retention="30", prefix=""):
    return subprocess.run([sys.executable, "-c", prefix + helper("prune_expired_external_backups"),
                           str(root), retention], capture_output=True, text=True, timeout=15)


def protected(root):
    return [archive(root, days) for days in (1, 2, 3)]


def test_daily_thinning_expiry_recent_and_unrelated_data(tmp_path):
    recent = protected(tmp_path) + [archive(tmp_path, 2, 13)]
    early, late = archive(tmp_path, 10, 10), archive(tmp_path, 10, 14)
    expired = archive(tmp_path, 40)
    evidence = tmp_path / 'depth-evidence'
    evidence.mkdir()
    (evidence / expired.name).write_bytes(b'never-delete')
    install = tmp_path / 'preinstall-2020-01-01-120000.tgz.age'
    install.write_bytes(b'never-delete')
    result = run(tmp_path)
    assert result.returncode == 0, result.stderr
    assert not early.exists() and not expired.exists()
    assert late.exists() and all(p.exists() for p in recent)
    assert install.exists() and (evidence / expired.name).exists()
    events = [json.loads(line) for line in (tmp_path / 'backup-retention.jsonl').read_text().splitlines()]
    assert [e['event'] for e in events] == ['delete_planned', 'deleted'] * 2
    assert json.loads(result.stdout)['removed'] == 2
    assert run(tmp_path).returncode == 0


def test_last_three_survive_even_after_horizon(tmp_path):
    paths = [archive(tmp_path, days) for days in (80, 70, 60, 50)]
    assert run(tmp_path).returncode == 0
    assert not paths[0].exists()
    assert all(p.exists() for p in paths[1:])


@pytest.mark.parametrize('count', [0, 1, 2, 3])
def test_bootstrap_never_deletes_only_recovery_copies(tmp_path, count):
    paths = [archive(tmp_path, 80+i) for i in range(count)]
    assert run(tmp_path).returncode == 0
    assert all(p.exists() for p in paths)


@pytest.mark.parametrize('damage', ['corrupt', 'missing_checksum', 'symlink', 'hardlink', 'oversize', 'wrong_name'])
def test_bad_protected_copy_blocks_all_deletions(tmp_path, damage):
    paths = protected(tmp_path)
    old = archive(tmp_path, 40)
    target = paths[0]
    side = target.with_name(target.name + '.sha256')
    if damage == 'corrupt': target.write_bytes(b'changed')
    if damage == 'missing_checksum': side.unlink()
    if damage == 'symlink':
        side.unlink(); side.symlink_to(paths[1].with_name(paths[1].name + '.sha256'))
    if damage == 'hardlink': os.link(target, tmp_path / 'unexpected-hardlink')
    if damage == 'oversize': side.write_text('x' * 257)
    if damage == 'wrong_name': side.write_text('a' * 64 + '  wrong.age\n')
    result = run(tmp_path)
    assert result.returncode != 0
    assert old.exists()
    assert not (tmp_path / 'backup-retention.jsonl').exists()


def test_daily_replacement_must_be_verified(tmp_path):
    protected(tmp_path)
    early, late = archive(tmp_path, 10, 10), archive(tmp_path, 10, 14)
    late.write_bytes(b'corrupt')
    assert run(tmp_path).returncode != 0
    assert early.exists()


def test_audit_failure_prevents_deletion(tmp_path):
    protected(tmp_path)
    old = archive(tmp_path, 40)
    (tmp_path / 'backup-retention.jsonl').mkdir()
    assert run(tmp_path).returncode != 0
    assert old.exists()


def test_future_names_and_invalid_policy_fail_closed(tmp_path):
    protected(tmp_path)
    old = archive(tmp_path, 40)
    assert run(tmp_path, '0').returncode != 0
    archive(tmp_path, -2)
    assert run(tmp_path).returncode != 0
    assert old.exists()


def test_audit_is_bounded(tmp_path):
    protected(tmp_path)
    archive(tmp_path, 40)
    (tmp_path / 'backup-retention.jsonl').write_text('x' * 1024**2)
    assert run(tmp_path).returncode == 0
    assert (tmp_path / 'backup-retention.jsonl.1').stat().st_size == 1024**2
    assert (tmp_path / 'backup-retention.jsonl').stat().st_size < 1024


@pytest.mark.parametrize('available,staged,success', [(9, 0, True), (7, 0, False), (9, 1024**3, False)])
def test_capacity_reserves_external_space(tmp_path, available, staged, success):
    prefix = ('import os,types\n' +
              f'os.statvfs=lambda p: types.SimpleNamespace(f_bavail={available}*1024**3,f_frsize=1)\n')
    result = subprocess.run([sys.executable, '-c', prefix + helper('check_external_capacity'),
                             str(tmp_path), str(staged)], capture_output=True, text=True, timeout=5)
    assert (result.returncode == 0) is success


def test_live_order_and_defaults():
    assert SOURCE.index('flock -w 600 17') < SOURCE.index('prune_expired_external_backups\n')
    assert SOURCE.index('check_external_capacity\n') < SOURCE.index('install -d -m 0700 "${DEST}"')
    assert SOURCE.index('check_external_capacity "${staged_archive_bound}"') < SOURCE.index('tar -C "${BACKUP_DIR}"')
    assert "* 8192" in SOURCE
    assert '${BACKUP_EXTERNAL_RETENTION_DAYS:-30}' in SOURCE
