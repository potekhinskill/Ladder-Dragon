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


def _restore_service_trace(
    tmp_path: Path,
    *,
    mybot_active: int,
    watchdog_enabled: int,
) -> list[str]:
    trace = tmp_path / "systemctl.trace"
    trace.parent.mkdir(parents=True, exist_ok=True)
    script = "\n".join(
        (
            "set -euo pipefail",
            'TRACE="$1"',
            "systemctl() { printf '%s\\n' \"$*\" >>\"${TRACE}\"; }",
            f"MYBOT_WAS_ACTIVE={mybot_active}",
            "DASHBOARD_WAS_ACTIVE=0",
            "MYBOT_WAS_ENABLED=1",
            "DASHBOARD_WAS_ENABLED=0",
            f"WATCHDOG_WAS_ENABLED={watchdog_enabled}",
            "restore_autostart() {",
            _function("restore_autostart", "start_previous_services"),
            "start_previous_services() {",
            _function("start_previous_services", "verify_previous_service_state"),
            "start_previous_services",
        )
    )
    completed = subprocess.run(
        ("bash", "-c", script, "bash", str(trace)),
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stderr
    return trace.read_text(encoding="utf-8").splitlines()


def test_enabled_watchdog_recovers_from_inactive_state_after_update(tmp_path):
    commands = _restore_service_trace(
        tmp_path,
        mybot_active=1,
        watchdog_enabled=1,
    )

    assert "start mybot" in commands
    assert "start pi-watchdog-v3.timer" in commands


def test_watchdog_stays_stopped_without_active_bot_or_enablement(tmp_path):
    inactive_bot = _restore_service_trace(
        tmp_path / "inactive",
        mybot_active=0,
        watchdog_enabled=1,
    )
    disabled_watchdog = _restore_service_trace(
        tmp_path / "disabled",
        mybot_active=1,
        watchdog_enabled=0,
    )

    assert "start pi-watchdog-v3.timer" not in inactive_bot
    assert "start pi-watchdog-v3.timer" not in disabled_watchdog


def _verify_service_state(*, watchdog_active: int) -> subprocess.CompletedProcess[str]:
    script = "\n".join(
        (
            "set -euo pipefail",
            "fail() { echo \"[FAIL] $*\" >&2; exit 70; }",
            f"WATCHDOG_ACTIVE={watchdog_active}",
            "MYBOT_WAS_ACTIVE=1",
            "DASHBOARD_WAS_ACTIVE=0",
            "MYBOT_WAS_ENABLED=1",
            "DASHBOARD_WAS_ENABLED=0",
            "WATCHDOG_WAS_ENABLED=1",
            "systemctl() {",
            "  [[ \"$1\" == \"is-active\" ]] || return 1",
            "  [[ \"${@: -1}\" == \"pi-watchdog-v3.timer\" ]] || return 1",
            "  [[ \"${WATCHDOG_ACTIVE}\" == \"1\" ]]",
            "}",
            "service_flag() {",
            "  case \"$2\" in",
            "    mybot|pi-watchdog-v3.timer) echo 1 ;;",
            "    pi-healthd) echo 0 ;;",
            "  esac",
            "}",
            "wait_for_service() {",
            "  if [[ \"$1\" == \"pi-watchdog-v3.timer\" ]]; then",
            "    [[ \"${WATCHDOG_ACTIVE}\" == \"1\" ]] || fail \"$1 did not become active in $2s\"",
            "  fi",
            "}",
            "verify_previous_service_state() {",
            _function("verify_previous_service_state", "restore_previous_checkout"),
            "verify_previous_service_state",
        )
    )
    return subprocess.run(
        ("bash", "-c", script),
        check=False,
        capture_output=True,
        text=True,
    )


def test_update_verification_requires_enabled_watchdog_to_be_active():
    completed = _verify_service_state(watchdog_active=0)

    assert completed.returncode == 70
    assert "pi-watchdog-v3.timer did not become active in 15s" in completed.stderr


def test_update_verification_accepts_recovered_enabled_watchdog():
    completed = _verify_service_state(watchdog_active=1)

    assert completed.returncode == 0, completed.stderr


def test_update_readiness_rejects_intentionally_stopped_runtime():
    heartbeat = _function("wait_for_heartbeat", "dashboard_database_status")

    assert '"RECOVERY_BLOCKED"' in heartbeat
    assert '"RISK_PENDING"' in heartbeat
    assert '"INTENTIONALLY_STOPPED"' not in heartbeat


def test_verified_deployment_notice_follows_dashboard_readiness():
    publish = UPDATER.split("publish_verified_deployment_status() {", 1)[1].split(
        '\n}\n\nif [[ "${EUID}"', 1
    )[0]
    success_path = UPDATER.rsplit(
        'if [[ "${MYBOT_WAS_ACTIVE}" == "1" && "${DASHBOARD_WAS_ACTIVE}" == "1" ]]; then',
        1,
    )[1]

    assert "ladder_dragon.deployment.status" in publish
    assert "--runtime-state" in publish
    assert success_path.index("check_link") < success_path.index(
        "publish_verified_deployment_status"
    )


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
