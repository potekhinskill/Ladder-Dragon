"""Host recovery tests never disconnect a device or request a real reboot."""

import fcntl
import json
from pathlib import Path
import subprocess

import pytest

from deploy import network_recovery as recovery


def tick(state, second, *, healthy=False, blocked="", boot="boot-a", day=100000):
    return recovery.advance(state, boot=boot, now=day + second,
                            uptime=second, reachable=healthy, blocked=blocked)


def outage(state, end=1000, **kwargs):
    return [tick(state, second, **kwargs) for second in range(100, end + 1, 60)]


def test_fifteen_minutes_with_two_bounded_recovery_steps():
    state = recovery.fresh_state("boot-a")
    results = outage(state)
    assert [(100 + n * 60, action) for n, (action, _) in enumerate(results)
            if action != "none"] == [(280, "reconnect"), (580, "restart-network"),
                                      (1000, "reboot")]
    assert state["latched"] is True
    assert sum("network-lost" in events for _, events in results) == 1
    assert tick(state, 1060)[0] == "none"


def test_reachable_lan_cancels_timer_even_without_exchange_access():
    state = recovery.fresh_state("boot-a")
    outage(state, 940)
    assert tick(state, 1000, healthy=True) == ("none", ["network-restored"])
    assert tick(state, 1060)[0] == "none"
    assert state["failed_since"] == 1060


def test_process_pause_is_not_continuous_network_failure():
    state = recovery.fresh_state("boot-a")
    tick(state, 100)
    assert tick(state, 1100)[0] == "none"
    assert state["failed_since"] == 1100


def test_persistent_latch_survives_boot_and_requires_stable_recovery():
    state = recovery.fresh_state("boot-a")
    outage(state)
    result = tick(state, 100, boot="boot-b")
    assert "boot-observed" in result[1]
    assert all(action != "reboot" for action, _ in outage(state, boot="boot-b"))
    for second in range(1060, 3001, 60):
        tick(state, second, healthy=True, boot="boot-b")
    assert state["latched"]  # Less than 24 hours since the reboot request.
    for second in range(3060, 5001, 60):
        tick(state, second, healthy=True, boot="boot-b", day=200000)
    assert not state["latched"]


def test_successful_reboot_reports_both_boot_and_restored_network():
    state = recovery.fresh_state("boot-a")
    outage(state)
    action, events = tick(state, 100, boot="boot-b", healthy=True)
    assert action == "none"
    assert events == ["boot-observed", "network-restored"]
    assert state["latched"] is True


@pytest.mark.parametrize("reason", ["backup-active", "maintenance-invalid",
                                    "backup-or-update-locked"])
def test_protected_work_suppresses_mutations_without_notification_storm(reason):
    state = recovery.fresh_state("boot-a")
    results = outage(state, blocked=reason)
    assert all(action == "none" for action, _ in results)
    assert sum(bool(events) for _, events in results) == 1
    assert tick(state, 1060)[0] == "none"
    assert state["failed_since"] == 1060


def test_state_corruption_cannot_reset_reboot_authority(tmp_path):
    path = tmp_path / "network.json"
    path.write_text('{"latched":"false"}')
    with pytest.raises(ValueError):
        recovery.read_state(path, "boot-a")
    state = recovery.fresh_state("boot-a")
    state["latched"] = True
    recovery.atomic_write(path, json.dumps(state))
    assert recovery.read_state(path, "boot-b")["latched"] is True
    assert path.stat().st_mode & 0o777 == 0o600


def test_route_or_fallback_success_prevents_false_reboot(monkeypatch):
    calls = []

    def run(args, timeout=5):
        calls.append(args)
        if args[0] == "ip":
            return subprocess.CompletedProcess(args, 0, '[{"gateway":"192.0.2.1"}]')
        return subprocess.CompletedProcess(args, 1, "")

    monkeypatch.setattr(recovery, "run", run)
    monkeypatch.setattr(recovery, "tcp_probe", lambda host, port: host == "1.1.1.1")
    assert recovery.network_reachable()
    assert all("binance" not in str(call) for call in calls)


def test_maintenance_and_legacy_sd_timer_fail_closed(tmp_path, monkeypatch):
    maintenance = tmp_path / "maintenance.json"
    monkeypatch.setattr(recovery, "MAINTENANCE", maintenance)
    maintenance.write_text('{"schema_version":1,"active":"false"}')
    assert recovery.safety_blocker() == "maintenance-invalid"
    maintenance.write_text('{"schema_version":1,"active":false}')
    monkeypatch.setattr(recovery, "run", lambda args: subprocess.CompletedProcess(
        args, 0, "inactive\ninactive\nactive\n"))
    assert recovery.safety_blocker() == "backup-active"


def test_outbox_is_bounded_persistent_and_contains_no_credentials(tmp_path, monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "private-test-value")
    for index in range(300):
        recovery.notify(tmp_path, "network-lost", index, 100000 + index)
    assert len(list(tmp_path.glob("*.msg"))) == 288
    assert all("private-test-value" not in path.read_text() for path in tmp_path.glob("*.msg"))
    assert not list(tmp_path.glob("*.tmp"))


@pytest.fixture
def fake_host(tmp_path, monkeypatch):
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    monkeypatch.setattr(recovery, "LOCK", tmp_path / "guard")
    monkeypatch.setattr(recovery, "PENDING", tmp_path / "pending")
    monkeypatch.setattr(recovery, "network_reachable", lambda: False)
    monkeypatch.setattr(recovery, "safety_blocker", lambda: "")
    boot_path = Path("/proc/sys/kernel/random/boot_id")
    original = Path.read_text
    monkeypatch.setattr(Path, "read_text", lambda path, *a, **kw:
                        "boot-a" if path == boot_path else original(path, *a, **kw))
    monkeypatch.setattr(recovery.time, "monotonic", lambda: 1000)
    monkeypatch.setattr(recovery.time, "time", lambda: 101000)
    state = recovery.fresh_state("boot-a")
    outage(state, 940)
    recovery.atomic_write(state_dir / "network-recovery.json", json.dumps(state))
    return state_dir, tmp_path / "outbox"


def test_reboot_is_durable_notified_and_inhibitor_aware(fake_host, monkeypatch):
    state_dir, outbox = fake_host
    commands = []

    def run(args, timeout=5):
        assert recovery.PENDING.read_text() == "boot-a\n"
        assert recovery.read_state(state_dir / "network-recovery.json", "boot-a")["latched"]
        assert any("controlled reboot" in path.read_text() for path in outbox.glob("*.msg"))
        commands.append(args)
        return subprocess.CompletedProcess(args, 0, "")

    monkeypatch.setattr(recovery, "run", run)
    recovery.cycle(state_dir, outbox)
    assert commands == [["systemctl", "--check-inhibitors=yes", "--no-ask-password", "reboot"]]


def test_backup_lock_prevents_reboot_at_boundary(fake_host, monkeypatch):
    commands = []
    monkeypatch.setattr(recovery, "run", lambda args, **kwargs: commands.append(args))
    with recovery.LOCK.open("a+") as backup:
        fcntl.flock(backup, fcntl.LOCK_SH | fcntl.LOCK_NB)
        recovery.cycle(*fake_host)
    assert commands == []
    assert not recovery.PENDING.exists()


def test_recheck_cancels_mutation_and_failed_reboot_never_loops(fake_host, monkeypatch):
    checks = iter([False, True])
    monkeypatch.setattr(recovery, "network_reachable", lambda: next(checks))
    monkeypatch.setattr(recovery, "run", lambda *a, **kw: pytest.fail("unsafe mutation"))
    recovery.cycle(*fake_host)
    assert not recovery.PENDING.exists()


def test_failed_reboot_keeps_latch_but_releases_pending_marker(fake_host, monkeypatch):
    monkeypatch.setattr(recovery, "run", lambda args, **kw: subprocess.CompletedProcess(args, 1, "private-error"))
    recovery.cycle(*fake_host)
    assert not recovery.PENDING.exists()
    state_dir, outbox = fake_host
    assert recovery.read_state(state_dir / "network-recovery.json", "boot-a")["latched"]
    assert all("private-error" not in path.read_text() for path in outbox.glob("*.msg"))


def test_deployment_installs_helper_and_guards_both_backup_intervals():
    root = Path(__file__).resolve().parents[2]
    updater = (root / "deploy/update_raspberry_pi.sh").read_text()
    backup = (root / "deploy/backup_raspberry_pi.sh").read_text()
    assets = (root / "deploy/install_runtime_assets.sh").read_text()
    watchdog = (root / "deploy/pi-watchdog_v3.sh").read_text()
    assert '--maintenance-file "${MAINTENANCE_FILE}"' in watchdog
    assert updater.index("flock -s -w 45 19") < updater.index(
        'run_preupdate_backup "${UPDATE_COMMIT}"'
    )
    assert backup.index("flock -s -w 45 18") < backup.index('command -v age')
    for source in (updater, backup):
        assert "network-reboot.boot /proc/sys/kernel/random/boot_id" in source
    assert "/usr/local/libexec/ladder-dragon/network_recovery.py" in assets


def test_cli_preserves_custom_maintenance_authority(tmp_path, monkeypatch):
    import sys

    marker = tmp_path / "operator-maintenance.json"
    marker.write_text('{"schema_version":1,"active":true}')
    monkeypatch.setattr(recovery, "MAINTENANCE", recovery.MAINTENANCE)
    monkeypatch.setattr(sys, "argv", ["network_recovery", "--state-dir", str(tmp_path),
                        "--outbox", str(tmp_path), "--maintenance-file", str(marker)])

    def check(*args):
        assert recovery.safety_blocker() == "maintenance-active"

    monkeypatch.setattr(recovery, "cycle", check)
    assert recovery.main() == 0
