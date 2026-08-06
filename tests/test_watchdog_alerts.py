"""Regression coverage for watchdog Telegram alert format and deduplication."""

import json
import os
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _fake_bin(tmp_path: Path) -> Path:
    bindir = tmp_path / "bin"
    bindir.mkdir()
    (bindir / "systemctl").write_text(
        "#!/bin/sh\n"
        "case \"$1\" in\n"
        "  is-active) [ \"${MYBOT_ACTIVE:-0}\" = 1 ] ;;\n"
        "  is-enabled)\n"
        "    if [ \"${MYBOT_ENABLED:-1}\" = 1 ]; then echo enabled; exit 0; fi\n"
        "    echo disabled; exit 1 ;;\n"
        "  restart) echo restart >>\"${SYSTEMCTL_LOG}\"; exit 0 ;;\n"
        "  *) exit 0 ;;\n"
        "esac\n",
        encoding="utf-8",
    )
    (bindir / "ping").write_text(
        "#!/bin/sh\n"
        "printf '%s\\n' \"$*\" >>\"${PING_LOG}\"\n"
        "exit 0\n",
        encoding="utf-8",
    )
    (bindir / "ip").write_text(
        "#!/bin/sh\n"
        "if [ \"$1\" = r ]; then\n"
        "  [ \"${NO_DEFAULT_ROUTE:-0}\" = 1 ] || echo 'default via 192.168.8.1 dev eth0'\n"
        "  exit 0\n"
        "fi\n"
        "echo '2: eth0    inet 192.168.8.79/24 scope global eth0'\n",
        encoding="utf-8",
    )
    (bindir / "uptime").write_text("#!/bin/sh\necho ' up 1 hour'\n", encoding="utf-8")
    (bindir / "curl").write_text(
        "#!/usr/bin/env python3\n"
        "import json, os, sys\n"
        "args = sys.argv[1:]\n"
        "config = ''\n"
        "if '--config' in args:\n"
        "    config_path = args[args.index('--config') + 1]\n"
        "    with open(config_path, encoding='utf-8') as source:\n"
        "        config = source.read()\n"
        "is_telegram = 'api.telegram.org' in config\n"
        "message = sys.stdin.read() if is_telegram else ''\n"
        "with open(os.environ['CURL_LOG'], 'a', encoding='utf-8') as stream:\n"
        "    json.dump({'args': args, 'message': message, 'telegram': is_telegram}, stream)\n"
        "    stream.write('\\n')\n"
        "is_api = any('api.binance.com' in arg for arg in args)\n"
        "if ((is_api and os.environ.get('API_CURL_FAIL') == '1') or\n"
        "        (is_telegram and os.environ.get('TELEGRAM_CURL_FAIL') == '1')):\n"
        "    raise SystemExit(7)\n",
        encoding="utf-8",
    )
    for command in bindir.iterdir():
        command.chmod(0o755)
    return bindir


def _run_watchdog(
    tmp_path: Path,
    bindir: Path,
    curl_log: Path,
    *,
    api_fail: bool = False,
    telegram_fail: bool = False,
    mybot_active: bool = False,
    mybot_enabled: bool = True,
    no_default_route: bool = False,
    strikes: int = 1,
    outbox_max_files: int = 288,
    outbox_max_age_sec: int = 86400,
    heartbeat_state: str = "RUNNING",
) -> None:
    uptime_source = tmp_path / "uptime"
    uptime_source.write_text("3600.0 0.0\n", encoding="utf-8")
    heartbeat = tmp_path / "ai_status.json"
    heartbeat.write_text(
        json.dumps(
            {
                "state": heartbeat_state,
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }
        ),
        encoding="utf-8",
    )
    env = os.environ.copy()
    env.update(
        {
            "PATH": f"{bindir}:{env['PATH']}",
            "TG_BOT_TOKEN": "123456:test-token",
            "TG_CHAT_ID": "123",
            "STRIKES": str(strikes),
            "WATCHDOG_RECOVERY_SUCCESSES": "2",
            "MIN_UPTIME": "0",
            "WATCHDOG_LOG": str(tmp_path / "watchdog.log"),
            "WATCHDOG_STATE": str(tmp_path / "state"),
            "WATCHDOG_STATE_DIR": str(tmp_path / "state-dir"),
            "WATCHDOG_ALERT_COOLDOWN_SEC": "3600",
            "WATCHDOG_ALERT_LOAD_THRESHOLD": "999",
            "WATCHDOG_ALERT_TEMP_THRESHOLD_C": "999",
            "WATCHDOG_ALERT_LOAD_DELTA": "999",
            "WATCHDOG_ALERT_TEMP_DELTA_C": "999",
            "WATCHDOG_UPTIME_SOURCE": str(uptime_source),
            "AI_RUNTIME_STATUS_FILE": str(heartbeat),
            "BOT_MAINTENANCE_FILE": str(
                tmp_path / "test-maintenance-does-not-exist.json"
            ),
            "CURL_LOG": str(curl_log),
            "API_CURL_FAIL": "1" if api_fail else "0",
            "TELEGRAM_CURL_FAIL": "1" if telegram_fail else "0",
            "MYBOT_ACTIVE": "1" if mybot_active else "0",
            "MYBOT_ENABLED": "1" if mybot_enabled else "0",
            "NO_DEFAULT_ROUTE": "1" if no_default_route else "0",
            "SYSTEMCTL_LOG": str(tmp_path / "systemctl.log"),
            "PING_LOG": str(tmp_path / "ping.log"),
            "WATCHDOG_TELEGRAM_OUTBOX_MAX_FILES": str(outbox_max_files),
            "WATCHDOG_TELEGRAM_OUTBOX_MAX_AGE_SEC": str(outbox_max_age_sec),
        }
    )
    subprocess.run(
        ["bash", str(ROOT / "deploy/pi-watchdog_v3.sh")],
        cwd=ROOT,
        env=env,
        check=True,
        capture_output=True,
        text=True,
    )


def _telegram_texts(curl_log: Path) -> list[str]:
    texts = []
    for line in curl_log.read_text(encoding="utf-8").splitlines():
        call = json.loads(line)
        if call["telegram"]:
            texts.append(call["message"])
    return texts


def test_watchdog_sends_one_full_snapshot_and_suppresses_identical_repeat(tmp_path):
    bindir = _fake_bin(tmp_path)
    curl_log = tmp_path / "curl.jsonl"
    _run_watchdog(tmp_path, bindir, curl_log)
    _run_watchdog(tmp_path, bindir, curl_log)

    texts = _telegram_texts(curl_log)
    assert len(texts) == 1
    assert "mybot unhealthy" in texts[0]
    assert "load:" in texts[0]
    assert "temp:" in texts[0]
    assert "binance_bot: ⚠️ binance_bot:" not in texts[0]
    assert "172.17." not in texts[0]


def test_watchdog_repeats_unresolved_health_alert_after_cooldown(tmp_path):
    bindir = _fake_bin(tmp_path)
    curl_log = tmp_path / "curl.jsonl"
    _run_watchdog(tmp_path, bindir, curl_log)
    _run_watchdog(tmp_path, bindir, curl_log)

    alert_files = list((tmp_path / "state-dir").glob("telegram-alert.state.*"))
    assert len(alert_files) == 1
    fields = alert_files[0].read_text(encoding="utf-8").split()
    fields[1] = str(int(time.time()) - 3601)
    alert_files[0].write_text(" ".join(fields) + "\n", encoding="utf-8")

    _run_watchdog(tmp_path, bindir, curl_log)

    texts = _telegram_texts(curl_log)
    assert sum("mybot unhealthy" in text for text in texts) == 2


def test_watchdog_queues_alerts_offline_and_reports_network_recovery(tmp_path):
    bindir = _fake_bin(tmp_path)
    curl_log = tmp_path / "curl.jsonl"
    _run_watchdog(
        tmp_path,
        bindir,
        curl_log,
        api_fail=True,
        telegram_fail=True,
    )
    outbox = tmp_path / "state-dir" / "telegram-outbox"
    assert list(outbox.glob("*.msg"))

    _run_watchdog(tmp_path, bindir, curl_log)
    assert not any(
        "network recovered" in text for text in _telegram_texts(curl_log)
    )
    _run_watchdog(tmp_path, bindir, curl_log)
    texts = _telegram_texts(curl_log)
    assert any("Telegram connection restored" in text for text in texts)
    assert any("Queued notification" in text for text in texts)
    assert any("network recovered" in text for text in texts)
    assert not list(outbox.glob("*.msg"))


def test_transient_probe_failures_do_not_emit_recovery_noise(tmp_path):
    bindir = _fake_bin(tmp_path)
    curl_log = tmp_path / "curl.jsonl"

    _run_watchdog(
        tmp_path,
        bindir,
        curl_log,
        api_fail=True,
        mybot_active=True,
        strikes=3,
    )
    _run_watchdog(tmp_path, bindir, curl_log, mybot_active=True, strikes=3)
    _run_watchdog(tmp_path, bindir, curl_log, mybot_active=True, strikes=3)

    assert _telegram_texts(curl_log) == []


def test_confirmed_incident_needs_two_successes_before_recovery(tmp_path):
    bindir = _fake_bin(tmp_path)
    curl_log = tmp_path / "curl.jsonl"

    for _ in range(3):
        _run_watchdog(
            tmp_path,
            bindir,
            curl_log,
            api_fail=True,
            mybot_active=True,
            strikes=3,
        )
    assert sum(
        "network failure" in text for text in _telegram_texts(curl_log)
    ) == 1

    _run_watchdog(tmp_path, bindir, curl_log, mybot_active=True, strikes=3)
    assert not any(
        "network recovered" in text for text in _telegram_texts(curl_log)
    )
    _run_watchdog(tmp_path, bindir, curl_log, mybot_active=True, strikes=3)

    texts = _telegram_texts(curl_log)
    assert sum("network failure" in text for text in texts) == 1
    assert sum("network recovered" in text for text in texts) == 1


def test_disabled_inactive_bot_is_not_restarted_or_reported_unhealthy(tmp_path):
    bindir = _fake_bin(tmp_path)
    curl_log = tmp_path / "curl.jsonl"

    _run_watchdog(
        tmp_path,
        bindir,
        curl_log,
        mybot_active=False,
        mybot_enabled=False,
    )

    assert not (tmp_path / "systemctl.log").exists()
    assert _telegram_texts(curl_log) == []
    assert "intentionally stopped" in (tmp_path / "watchdog.log").read_text(
        encoding="utf-8"
    )


def test_fresh_risk_pending_bot_is_not_restarted(tmp_path):
    bindir = _fake_bin(tmp_path)
    curl_log = tmp_path / "curl.jsonl"

    _run_watchdog(
        tmp_path,
        bindir,
        curl_log,
        mybot_active=True,
        heartbeat_state="RISK_PENDING",
    )

    assert not (tmp_path / "systemctl.log").exists()
    assert not any("mybot unhealthy" in row for row in _telegram_texts(curl_log))


def test_telegram_credentials_and_message_never_enter_curl_argv(tmp_path):
    bindir = _fake_bin(tmp_path)
    curl_log = tmp_path / "curl.jsonl"

    _run_watchdog(tmp_path, bindir, curl_log)

    calls = [
        json.loads(line)
        for line in curl_log.read_text(encoding="utf-8").splitlines()
    ]
    telegram_call = next(call for call in calls if call["telegram"])
    argv = "\n".join(telegram_call["args"])
    assert "123456:test-token" not in argv
    assert "chat_id=123" not in argv
    assert "mybot unhealthy" not in argv
    assert telegram_call["message"].startswith("binance_bot ⚠️ mybot unhealthy")


def test_outbox_prunes_expired_messages_and_caps_backlog(tmp_path):
    bindir = _fake_bin(tmp_path)
    curl_log = tmp_path / "curl.jsonl"
    outbox = tmp_path / "state-dir" / "telegram-outbox"
    outbox.mkdir(parents=True)
    now = int(time.time())
    (outbox / f"{now - 120}-1-old.msg").write_text("expired", encoding="utf-8")
    for index in range(4):
        (outbox / f"{now - 4 + index}-1-{index}.msg").write_text(
            f"recent-{index}", encoding="utf-8"
        )

    _run_watchdog(
        tmp_path,
        bindir,
        curl_log,
        telegram_fail=True,
        outbox_max_files=3,
        outbox_max_age_sec=60,
    )

    queued = sorted(outbox.glob("*.msg"))
    assert len(queued) == 3
    assert all("old" not in path.name for path in queued)


def test_missing_default_route_is_reported_without_guessing_gateway(tmp_path):
    bindir = _fake_bin(tmp_path)
    curl_log = tmp_path / "curl.jsonl"

    _run_watchdog(
        tmp_path,
        bindir,
        curl_log,
        mybot_active=True,
        no_default_route=True,
    )

    ping_log = (tmp_path / "ping.log").read_text(encoding="utf-8")
    assert "192.168.8.1" not in ping_log
    assert "missing-default-route" in (tmp_path / "state-dir" / "reason.txt").read_text(
        encoding="utf-8"
    )
