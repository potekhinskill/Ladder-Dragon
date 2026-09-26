"""Exercise updater failures without production paths, services, or Git access."""

from pathlib import Path
import subprocess

import pytest


SOURCE = (Path(__file__).resolve().parents[1] / "deploy/update_raspberry_pi.sh").read_text()
DIAGNOSTICS = SOURCE.split('PROJECT_DIR=', 1)[0]
FAIL = SOURCE.split('fail() {', 1)[1].split('\nset_env_value()', 1)[0]
BOOTSTRAP = SOURCE.split('bootstrap_verified_target_runner() {', 1)[1].split(
    '\nrun_preupdate_backup()', 1
)[0]


@pytest.mark.parametrize('operation,stage', [
    ('fetch', 'bootstrap_fetch'),
    ('cat-file', 'bootstrap_commit'),
    ('rev-parse', 'bootstrap_commit'),
    ('merge-base', 'bootstrap_ancestry'),
    ('trust', 'bootstrap_signature'),
    ('signature', 'bootstrap_signature'),
    ('mktemp', 'bootstrap_runner'),
    ('show', 'bootstrap_runner'),
    ('chmod', 'bootstrap_runner'),
])
def test_bootstrap_stops_at_failed_operation(tmp_path, operation, stage):
    script = DIAGNOSTICS + '\nfail() {' + FAIL
    script += '\nbootstrap_verified_target_runner() {' + BOOTSTRAP
    script += r'''
BOT_USER=synthetic
PROJECT_DIR=synthetic
WEB_ROOT=synthetic
BOT_HOSTNAME=synthetic
BREAK_GLASS_MARKER=missing-marker
runuser() {
  local operation="$5"
  printf '%s\n' "$operation" >> calls
  [[ "$operation" != "$FAIL_OPERATION" ]] || return 71
  case "$operation" in
    rev-parse) printf 'origin/main\n' ;;
    show) printf '# synthetic runner\n' ;;
  esac
}
load_trusted_signer() { [[ "$FAIL_OPERATION" != trust ]]; }
verify_trusted_commit() { [[ "$FAIL_OPERATION" != signature ]]; }
mktemp() { [[ "$FAIL_OPERATION" != mktemp ]] || return 72; printf 'runner\n'; }
chmod() { [[ "$FAIL_OPERATION" != chmod ]]; }
bootstrap_verified_target_runner 1111111111111111111111111111111111111111
printf 'UNSAFE_CONTINUATION\n'
'''
    result = subprocess.run(
        ['bash', '-c', script], cwd=tmp_path,
        env={'PATH': '/usr/bin:/bin', 'FAIL_OPERATION': operation},
        capture_output=True, text=True, timeout=5,
    )
    assert result.returncode != 0
    assert 'UNSAFE_CONTINUATION' not in result.stdout
    events = [line for line in result.stderr.splitlines() if line.startswith('[UPDATE-FAILURE]')]
    assert events == [f'[UPDATE-FAILURE] stage={stage} exit={result.returncode}']
    calls = (tmp_path / 'calls').read_text().splitlines()
    if operation in {'fetch', 'cat-file', 'rev-parse', 'merge-base'}:
        assert calls[-1] == operation
        assert 'show' not in calls


@pytest.mark.parametrize('command,status', [('false', 1), ('exit 23', 23), ('true', 0)])
def test_exit_event_excludes_private_runtime_values(command, status):
    result = subprocess.run(
        ['bash', '-c', DIAGNOSTICS + '\nPRIVATE_VALUE=synthetic-private-marker\n' + command],
        capture_output=True, text=True, timeout=5,
    )
    assert result.returncode == status
    assert 'synthetic-private-marker' not in result.stdout + result.stderr
    assert result.stderr == (
        f'[UPDATE-FAILURE] stage=initialization exit={status}\n' if status else ''
    )


def test_bootstrap_invocation_does_not_disable_errexit():
    assert 'if bootstrap_verified_target_runner' not in SOURCE
    assert '\n    bootstrap_verified_target_runner "${UPDATE_COMMIT}"\n' in SOURCE
    assert SOURCE.index('trap report_update_exit EXIT') < SOURCE.index('PROJECT_DIR=')
