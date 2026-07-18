"""Regression coverage for watchdog Telegram alert format and deduplication."""

import json
import os
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _fake_bin(tmp_path: Path) -> Path:
    bindir = tmp_path / "bin"
    bindir.mkdir()
    (bindir / "systemctl").write_text(
        "#!/bin/sh\n"
        "case \"$1\" in\n"
        "  is-active) exit 1 ;;\n"
        "  restart) exit 0 ;;\n"
        "  *) exit 0 ;;\n"
        "esac\n",
        encoding="utf-8",
    )
    (bindir / "ping").write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    (bindir / "ip").write_text(
        "#!/bin/sh\n"
        "if [ \"$1\" = r ]; then echo 'default via 192.168.8.1 dev eth0'; exit 0; fi\n"
        "echo '2: eth0    inet 192.168.8.79/24 scope global eth0'\n",
        encoding="utf-8",
    )
    (bindir / "uptime").write_text("#!/bin/sh\necho ' up 1 hour'\n", encoding="utf-8")
    (bindir / "curl").write_text(
        "#!/usr/bin/env python3\n"
        "import json, os, sys\n"
        "with open(os.environ['CURL_LOG'], 'a', encoding='utf-8') as stream:\n"
        "    json.dump(sys.argv[1:], stream)\n"
        "    stream.write('\\n')\n"
        "if os.environ.get('CURL_FAIL') == '1':\n"
        "    raise SystemExit(7)\n",
        encoding="utf-8",
    )
    for command in bindir.iterdir():
        command.chmod(0o755)
    return bindir


def _run_watchdog(tmp_path: Path, bindir: Path, curl_log: Path, *, curl_fail: bool = False) -> None:
    uptime_source = tmp_path / "uptime"
    uptime_source.write_text("3600.0 0.0\n", encoding="utf-8")
    env = os.environ.copy()
    env.update(
        {
            "PATH": f"{bindir}:{env['PATH']}",
            "TG_BOT_TOKEN": "test-token",
            "TG_CHAT_ID": "123",
            "STRIKES": "1",
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
            "CURL_LOG": str(curl_log),
            "CURL_FAIL": "1" if curl_fail else "0",
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
        args = json.loads(line)
        texts.extend(value.removeprefix("text=") for value in args if value.startswith("text="))
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


def test_watchdog_queues_alerts_offline_and_reports_network_recovery(tmp_path):
    bindir = _fake_bin(tmp_path)
    curl_log = tmp_path / "curl.jsonl"
    _run_watchdog(tmp_path, bindir, curl_log, curl_fail=True)
    outbox = tmp_path / "state-dir" / "telegram-outbox"
    assert list(outbox.glob("*.msg"))

    _run_watchdog(tmp_path, bindir, curl_log, curl_fail=False)
    texts = _telegram_texts(curl_log)
    assert any("Telegram connection restored" in text for text in texts)
    assert any("Queued notification" in text for text in texts)
    assert any("network recovered" in text for text in texts)
    assert not list(outbox.glob("*.msg"))
