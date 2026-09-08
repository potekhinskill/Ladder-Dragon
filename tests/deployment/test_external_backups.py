"""External-only archive publication and legacy migration contracts."""

import hashlib
import os
import shlex
import subprocess
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = (ROOT / "deploy/backup_raspberry_pi.sh").read_text()
NAME = "ladder-dragon-2026-09-08-120000.tgz.age"


def _function(name):
    return name + "() {" + SCRIPT.split(name + "() {", 1)[1].split("\n}\n", 1)[0] + "\n}\n"


def _run(body, tmp_path):
    # Only platform commands differ on macOS. Execute the production shell logic.
    python = shlex.quote(sys.executable)
    wrappers = f"""
sha256sum() {{ {python} -c 'import hashlib,sys; p=sys.argv[1]; print(hashlib.sha256(open(p,"rb").read()).hexdigest()+"  "+p)' "$1"; }}
stat() {{ {python} -c 'import os,sys; print(os.stat(sys.argv[-1]).st_size)' "$@"; }}
mv() {{ {python} -c 'import os,sys; os.replace(sys.argv[-2],sys.argv[-1])' "$@"; }}
"""
    return subprocess.run(
        ["bash", "-c", "set -euo pipefail\n" + wrappers + body],
        cwd=tmp_path, env={"PATH": os.environ["PATH"]},
        capture_output=True, text=True, timeout=20,
    )


def _cipher(directory, name=NAME, data=b"synthetic-ciphertext"):
    directory.mkdir(exist_ok=True)
    (directory / name).write_bytes(data)
    digest = hashlib.sha256(data).hexdigest()
    (directory / (name + ".sha256")).write_text(f"{digest}  {name}\n")


def test_publication_creates_links_not_copies(tmp_path):
    external = tmp_path / "external"
    public = tmp_path / "public"
    public.mkdir()
    _cipher(external)
    _cipher(public, data=b"obsolete-local-copy")
    body = (
        f"PUBLIC_BACKUP_DIR={shlex.quote(str(public))}\n"
        f"BACKUP_EXTERNAL_DIR={shlex.quote(str(external))}\nACTIVE_TEMP_FILES=()\n"
        + _function("publish_public_archive") + f'publish_public_archive "{NAME}"\n'
    )
    result = _run(body, tmp_path)
    assert result.returncode == 0, result.stderr
    for suffix in ("", ".sha256"):
        pointer = public / (NAME + suffix)
        assert pointer.is_symlink()
        assert pointer.readlink() == external / (NAME + suffix)
    # Removing the external source cannot expose a retained local archive.
    (external / NAME).unlink()
    assert not (public / NAME).exists()


@pytest.mark.parametrize("case", ["match", "missing", "different", "bad_checksum", "checksum_link"])
def test_migration_preserves_unproved_copies(tmp_path, case):
    private, public, external = (tmp_path / name for name in ("private", "public", "external"))
    for directory in (private, public, external):
        directory.mkdir()
    _cipher(private)
    _cipher(public)
    if case != "missing":
        _cipher(external, data=b"different" if case == "different" else b"synthetic-ciphertext")
    if case == "bad_checksum":
        (external / (NAME + ".sha256")).write_text("wrong")
    if case == "checksum_link":
        checksum = external / (NAME + ".sha256")
        checksum.unlink()
        checksum.symlink_to(private / (NAME + ".sha256"))
    body = (
        f"BACKUP_DIR={shlex.quote(str(private))}\n"
        f"PUBLIC_BACKUP_DIR={shlex.quote(str(public))}\n"
        f"EXTERNAL_STORE={shlex.quote(str(external))}\n"
        + _function("retire_local_duplicates") + "retire_local_duplicates\n"
    )
    result = _run(body, tmp_path)
    assert result.returncode == 0, result.stderr
    for directory in (private, public):
        assert (directory / NAME).exists() is (case != "match")
    if case != "missing":
        assert (external / NAME).exists()


def test_missing_external_configuration_fails_before_staging(tmp_path):
    start = SCRIPT.index('if [[ -z "${BACKUP_EXTERNAL_MOUNT}"')
    stop = SCRIPT.index('install -d -m 0700 "${BACKUP_DIR}"', start)
    body = 'BACKUP_EXTERNAL_MOUNT=""\nBACKUP_EXTERNAL_DIR=""\n' + SCRIPT[start:stop]
    result = _run(body, tmp_path)
    assert result.returncode != 0
    assert "external backup storage is required" in result.stderr
    assert list(tmp_path.iterdir()) == []


def test_archive_destination_and_lock_contract():
    assert SCRIPT.index("flock -n 17") < SCRIPT.index("prune_stale_local_staging\n")
    assert 'exec 19<"${BACKUP_EXTERNAL_MOUNT}"' in SCRIPT
    assert 'EXTERNAL_STORE="/proc/$$/fd/20"' in SCRIPT
    assert 'mktemp "${BACKUP_DIR}/.${archive_name}' not in SCRIPT
    assert 'chmod 0600 "${EXTERNAL_STORE}' not in SCRIPT
    assert SCRIPT.index('sha256sum -c "${archive_name}.sha256"') < SCRIPT.index('publish_public_archive "${archive_name}"')
    assert 'tar -C "${BACKUP_DIR}" -czf - "${STAMP}"' in SCRIPT
    assert '| age -r "${BACKUP_AGE_RECIPIENT}"' in SCRIPT
    assert 'rm -rf -- "${DEST}"' in SCRIPT
    assert 'if [[ "${STAGING_CREATED}" == 1 ]]' in _function("cleanup_staging")


def test_unowned_staging_survives_cleanup(tmp_path):
    staging = tmp_path / "active-staging"
    staging.mkdir()
    source = staging / "pending-snapshot"
    source.write_text("synthetic-pending-data")
    body = (
        f"DEST={shlex.quote(str(staging))}\nSTAGING_CREATED=0\nACTIVE_TEMP_FILES=()\n"
        + _function("cleanup_staging") + "cleanup_staging\n"
    )
    result = _run(body, tmp_path)
    assert result.returncode == 0, result.stderr
    assert source.read_text() == "synthetic-pending-data"


def test_installer_emergency_archive_is_external():
    source = (ROOT / "deploy/install_raspberry_pi.sh").read_text()
    assert 'emergency="/proc/$$/fd/20/preinstall-${stamp}.tgz.age"' in source
    assert '/var/lib/ladder-dragon/backups/preinstall-' not in source
    assert '"${emergency_tmp}" "${emergency}"' in source


@pytest.mark.skipif(sys.platform != "linux", reason="Linux descriptor-backed mount path")
def test_pinned_directory_never_falls_back_to_replacement(tmp_path):
    external = tmp_path / "external"
    external.mkdir()
    body = f"""
exec 20<{shlex.quote(str(external))}
EXTERNAL_STORE="/proc/$$/fd/20"
command mv external detached
mkdir external
printf 'synthetic-ciphertext' >"${{EXTERNAL_STORE}}/{NAME}"
"""
    result = _run(body, tmp_path)
    assert result.returncode == 0, result.stderr
    assert not (external / NAME).exists()
    assert (tmp_path / "detached" / NAME).is_file()
