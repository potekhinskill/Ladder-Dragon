# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: verify that privileged deployment configuration is parsed as data.

from pathlib import Path
import importlib.util
import os
import subprocess


ROOT = Path(__file__).resolve().parents[1]


def run_parser(name: str, *args: str) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(
        ["python3", str(ROOT / "deploy" / name), *args],
        capture_output=True,
        check=False,
    )


def test_service_args_parser_accepts_only_documented_options():
    result = run_parser(
        "parse_service_args.py",
        "--cap-floor-usdt 10 --target-buy-per-symbol 1 --smart-rolling",
    )
    assert result.returncode == 0
    assert result.stdout.split(b"\0")[:-1] == [
        b"--cap-floor-usdt", b"10", b"--target-buy-per-symbol", b"1", b"--smart-rolling",
    ]


def test_service_args_parser_rejects_command_and_safety_overrides():
    for value in (
        "--base-script /tmp/evil.py",
        "--live",
        "--cap-floor-usdt 10; touch /tmp/owned",
        "--cap-floor-usdt $(id)",
    ):
        result = run_parser("parse_service_args.py", value)
        assert result.returncode != 0, value


def test_backup_env_parser_rejects_shell_syntax_and_unsafe_permissions(tmp_path):
    config = tmp_path / "backup.env"
    config.write_text(
        "BACKUP_AGE_RECIPIENT=age1qqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqq\n"
        "BACKUP_EXTERNAL_MOUNT=/mnt/usb1\n"
        "BACKUP_EXTERNAL_DIR=/mnt/usb1/ladder-dragon-backups\n"
        "BACKUP_EXTERNAL_RETENTION_DAYS=90\n"
    )
    os.chmod(config, 0o600)
    spec = importlib.util.spec_from_file_location(
        "read_backup_env", ROOT / "deploy" / "read_backup_env.py"
    )
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    values = module.read_backup_env(
        config, expected_uid=os.getuid(), expected_gid=os.getgid()
    )
    assert values[1:] == ["/mnt/usb1", "/mnt/usb1/ladder-dragon-backups", "90"]

    config.write_text(config.read_text() + "EVIL=$(id)\n")
    try:
        module.read_backup_env(config, expected_uid=os.getuid(), expected_gid=os.getgid())
    except ValueError:
        pass
    else:
        raise AssertionError("forbidden backup.env key was accepted")

    config.write_text(config.read_text().split("EVIL=", 1)[0])
    os.chmod(config, 0o640)
    try:
        module.read_backup_env(config, expected_uid=os.getuid(), expected_gid=os.getgid())
    except ValueError:
        pass
    else:
        raise AssertionError("group-readable backup.env was accepted")
