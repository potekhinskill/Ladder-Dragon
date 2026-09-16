# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: exercise competing backup ownership without private data or services.
"""Run the production lock boundary with real kernel file locks."""

import fcntl
import os
from pathlib import Path
import select
import shlex
import subprocess
import sys

import pytest


ROOT = Path(__file__).resolve().parents[2]
SOURCE = (ROOT / "deploy/backup_raspberry_pi.sh").read_text()


def _waiter(tmp_path, mode="wait", outcome=0):
    # macOS lacks util-linux flock. Preserve its inherited-descriptor semantics
    # with fcntl, verify production arguments, and shorten only the test deadline.
    adapter = tmp_path / "flock_adapter.py"
    adapter.write_text('''import fcntl, os, sys, time
assert sys.argv[1:] == ["-w", "600", "17"]
print("WAITING", flush=True)
if os.environ["LOCK_MODE"] == "error":
    sys.exit(2)
deadline = time.monotonic() + 0.5
while True:
    try:
        fcntl.flock(17, fcntl.LOCK_EX | fcntl.LOCK_NB)
        break
    except BlockingIOError:
        if time.monotonic() >= deadline:
            sys.exit(1)
        time.sleep(0.01)
''')
    start = SOURCE.index("exec 17>>")
    end = SOURCE.index('if [[ -r /var/lib/pi-watchdog', start)
    boundary = SOURCE[start:end].replace(
        "/var/lib/ladder-dragon/backup.lock", str(tmp_path / "backup.lock")
    )
    body = f'''set -euo pipefail
BACKUP_DIR={shlex.quote(str(tmp_path))}
flock() {{ {shlex.quote(sys.executable)} {shlex.quote(str(adapter))} "$@"; }}
date() {{ printf 'after-lock\\n'; }}
on_exit() {{ local result=$?; printf '%s' "$result" >status; }}
{boundary}
printf '%s' "$STAMP" >acquired
exit {outcome}
'''
    return subprocess.Popen(
        ["bash", "-c", body], cwd=tmp_path,
        env={"PATH": os.environ["PATH"], "LOCK_MODE": mode},
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
    )


@pytest.mark.parametrize("outcome", [0, 7])
def test_queued_backup_runs_after_owner_releases_lock(tmp_path, outcome):
    with (tmp_path / "backup.lock").open("w") as owner:
        fcntl.flock(owner, fcntl.LOCK_EX)
        proc = _waiter(tmp_path, outcome=outcome)
        try:
            assert select.select([proc.stdout], [], [], 5)[0]
            assert proc.stdout.readline().strip() == "WAITING"
            assert proc.poll() is None
            assert not (tmp_path / "acquired").exists()
            assert not (tmp_path / "status").exists()
            fcntl.flock(owner, fcntl.LOCK_UN)
            _, stderr = proc.communicate(timeout=5)
            assert proc.returncode == outcome, stderr
            assert (tmp_path / "acquired").read_text() == "after-lock"
            assert (tmp_path / "status").read_text() == str(outcome)
        finally:
            if proc.poll() is None:
                proc.kill()
                proc.communicate()


@pytest.mark.parametrize("mode", ["wait", "error"])
def test_timeout_or_lock_error_preserves_other_backup_status(tmp_path, mode):
    (tmp_path / "status").write_text("previous-owner-success")
    with (tmp_path / "backup.lock").open("w") as owner:
        fcntl.flock(owner, fcntl.LOCK_EX)
        proc = _waiter(tmp_path, mode=mode)
        _, stderr = proc.communicate(timeout=5)
    assert proc.returncode != 0
    assert "backup lock wait failed or timed out" in stderr
    assert not (tmp_path / "acquired").exists()
    assert (tmp_path / "status").read_text() == "previous-owner-success"


def test_backup_ownership_precedes_status_staging_and_timestamp():
    lock = SOURCE.index("flock -w 600 17")
    assert SOURCE.index("flock -s -w 45 18") < lock
    assert SOURCE.index("trap on_exit EXIT") > lock
    assert SOURCE.index('STAMP="$(date') > lock
    assert SOURCE.index('DEST="${BACKUP_DIR}/${STAMP}"') > lock
    assert SOURCE.index("prune_stale_local_staging\n") > lock
    assert SOURCE.index('install -d -m 0700 "${DEST}"') > lock


def test_update_requires_post_backup_before_starting_daily_timer():
    source = (ROOT / "deploy/update_raspberry_pi.sh").read_text()
    backup = "systemctl start ladder-dragon-update-backup.service"
    timer = "systemctl start ladder-dragon-backup.timer"
    assert source.count(backup) == source.count(timer) == 1
    assert source.index(backup) < source.index(timer)
    assert "set -euo pipefail" in source
    # Run these exact adjacent commands with a synthetic service manager.
    segment = source[source.index(backup):source.index(timer) + len(timer)]
    for result in (0, 1):
        body = f'''set -euo pipefail
systemctl() {{ echo "$2"; if [[ "$2" == ladder-dragon-update-backup.service ]]; then return {result}; fi; }}
{segment}
'''
        run = subprocess.run(["bash", "-c", body], capture_output=True, text=True, timeout=5)
        assert run.returncode == result
        assert ("ladder-dragon-backup.timer" in run.stdout) is (result == 0)
