from pathlib import Path
import stat
import subprocess


ROOT = Path(__file__).resolve().parents[2]
UPDATER = (ROOT / "deploy/update_raspberry_pi.sh").read_text(encoding="utf-8")


def _function(name: str, next_name: str) -> str:
    return UPDATER.split(f"{name}() {{", 1)[1].split(
        f"{next_name}() {{", 1
    )[0]


def test_env_rewrite_preserves_literal_operator_path(tmp_path):
    target = tmp_path / "operator.env"
    target.write_text(
        "KEEP=unchanged\nBINANCE_AUTH_STATE_FILE=old\n",
        encoding="utf-8",
    )
    target.chmod(0o640)
    value = r"/srv/a|b&c\release/db/auth_resilience.json"
    script = "\n".join(
        (
            "set -euo pipefail",
            "fail() { echo \"[FAIL] $*\" >&2; exit 1; }",
            "chown() { :; }",
            "chmod() { command chmod 640 \"$2\"; }",
            "set_env_value() {",
            _function("set_env_value", "prepare_persistent_control"),
            "set_env_value \"$1\" BINANCE_AUTH_STATE_FILE \"$2\"",
        )
    )

    completed = subprocess.run(
        ("bash", "-c", script, "bash", str(target), value),
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0, completed.stderr
    assert target.read_text(encoding="utf-8") == (
        f"KEEP=unchanged\nBINANCE_AUTH_STATE_FILE={value}\n"
    )
    assert stat.S_IMODE(target.stat().st_mode) == 0o640


def test_malformed_dashboard_token_fails_before_curl(tmp_path):
    dashboard_env = tmp_path / "dashboard.env"
    dashboard_env.write_text(
        "DASHBOARD_AUTH_TOKEN=not-a-valid-token\n",
        encoding="utf-8",
    )
    script = "\n".join(
        (
            "set -euo pipefail",
            "fail() { echo \"[FAIL] $*\" >&2; exit 1; }",
            "DASHBOARD_ENV=\"$1\"",
            "dashboard_database_status() {",
            _function("dashboard_database_status", "wait_for_dashboard_database"),
            "dashboard_database_status",
        )
    )

    completed = subprocess.run(
        ("bash", "-c", script, "bash", str(dashboard_env)),
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 1
    assert "malformed DASHBOARD_AUTH_TOKEN" in completed.stderr
    assert "000" not in completed.stdout


def test_failed_update_rolls_back_before_service_restart():
    rollback = _function("restore_previous_checkout", "start_recovery_dashboard")
    recovery = _function("recover_after_failure", "wait_for_service")
    update = UPDATER.split('if [[ "${ACTION}" == "update" ]]; then', 2)[-1]

    assert 'git reset --hard "${PREVIOUS_HEAD}"' in rollback
    assert rollback.index("git reset --hard") < rollback.index(
        "--require-hashes -r requirements/raspberry.lock"
    )
    assert "pip install" in rollback
    assert "pip check" in rollback
    assert 'EXTERNAL_DEPLOYMENT_MUTATED}" == "0"' in recovery
    assert recovery.index("restore_previous_checkout") < recovery.index(
        "start_previous_services"
    )
    assert "start_recovery_dashboard" in recovery
    assert "mybot remains stopped" in recovery
    assert update.index('PREVIOUS_HEAD="$(') < update.index(
        'git merge --ff-only "${UPDATE_COMMIT}"'
    )
    assert UPDATER.index("EXTERNAL_DEPLOYMENT_MUTATED=1") < UPDATER.index(
        'PROJECT_DIR="${PROJECT_DIR}" deploy/install_runtime_assets.sh'
    )


def test_update_readiness_rejects_intentionally_stopped_runtime():
    heartbeat = _function("wait_for_heartbeat", "dashboard_database_status")

    assert '"RECOVERY_BLOCKED"' in heartbeat
    assert '"RISK_PENDING"' in heartbeat
    assert '"INTENTIONALLY_STOPPED"' not in heartbeat


def test_supervisor_publishes_fail_closed_live_startup_before_preflight():
    runtime = (
        ROOT / "ladder_dragon" / "supervision" / "runtime.py"
    ).read_text(encoding="utf-8")
    startup_gate = runtime.index("**initial_runtime_risk_status")
    first_publish = runtime.index("_publish_ai_runtime_status()", startup_gate)
    preflight = runtime.index("_preflight_with_auth_backoff", first_publish)

    assert startup_gate < first_publish < preflight


def test_break_glass_attempt_consumption_is_documented():
    runbook = (ROOT / "docs/RASPBERRY_PI_INSTALL.md").read_text(
        encoding="utf-8"
    )
    normalized = " ".join(runbook.split())

    assert "consumed before the update attempt continues" in normalized
    assert "must create a new exact-SHA authorization" in normalized
