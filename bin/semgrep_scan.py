# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: run the pinned isolated Semgrep policy without network access.
"""Execute Ladder Dragon Semgrep rules with fail-closed local settings."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SEMGREP_ROOT = PROJECT_ROOT / ".semgrep-venv"
SEMGREP_BIN = SEMGREP_ROOT / "bin" / "semgrep"
SEMGREP_PYTHON = SEMGREP_ROOT / "bin" / "python"
RULE_CONFIG = PROJECT_ROOT / ".semgrep" / "ladder-dragon.yml"
EXPECTED_VERSION = "1.168.0"
PRODUCTION_TARGETS = ("ladder_dragon", "bin", "deploy", "FastAPI")
RULE_MARKER = re.compile(r"# ruleid: (?P<rule>ladder-dragon\.[a-z0-9-]+)")


def _scanner_environment() -> dict[str, str]:
    """Return a minimal environment without application credentials."""
    runtime_root = PROJECT_ROOT / ".runtime"
    home = runtime_root / "semgrep-home"
    temporary = runtime_root / "semgrep-tmp"
    cache = runtime_root / "semgrep-cache"
    for directory in (home, temporary, cache):
        directory.mkdir(parents=True, exist_ok=True)
    environment = {
        "HOME": str(home),
        "LANG": "C.UTF-8",
        "PATH": os.pathsep.join((str(SEMGREP_ROOT / "bin"), os.defpath)),
        "SEMGREP_SEND_METRICS": "off",
        "SEMGREP_ENABLE_VERSION_CHECK": "0",
        "SEMGREP_LOG_FILE": str(runtime_root / "semgrep.log"),
        "TMPDIR": str(temporary),
        "XDG_CACHE_HOME": str(cache),
    }
    certificates = tuple(
        SEMGREP_ROOT.glob("lib/python*/site-packages/certifi/cacert.pem")
    )
    if certificates:
        environment["SSL_CERT_FILE"] = str(certificates[0])
    return environment


def _verify_toolchain() -> bool:
    """Require the exact isolated package before a scan can start."""
    if not SEMGREP_BIN.is_file() or not SEMGREP_PYTHON.is_file():
        return False
    completed = subprocess.run(
        (
            str(SEMGREP_PYTHON),
            "-c",
            "import importlib.metadata; print(importlib.metadata.version('semgrep'))",
        ),
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
        env=_scanner_environment(),
    )
    return completed.returncode == 0 and completed.stdout.strip() == EXPECTED_VERSION


def _base_command() -> list[str]:
    return [
        str(SEMGREP_BIN),
        "scan",
        "--metrics=off",
        "--strict",
        "--timeout=30",
        "--timeout-threshold=1",
        "--jobs=2",
        "--no-git-ignore",
        "--config",
        str(RULE_CONFIG),
    ]


def _is_fixture_path(value: str, fixture: Path) -> bool:
    """Match one fixture by its complete filename, not an overlapping suffix."""
    return Path(value).name == fixture.name


def _rules_test() -> int:
    """Prove that each rule detects one unsafe fixture and no safe fixture."""
    unsafe = PROJECT_ROOT / "tests" / "semgrep" / "unsafe_patterns.py"
    safe = PROJECT_ROOT / "tests" / "semgrep" / "safe_patterns.py"
    expected = set(RULE_MARKER.findall(unsafe.read_text(encoding="utf-8")))
    completed = subprocess.run(
        _base_command() + ["--json", str(unsafe), str(safe)],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        timeout=180,
        check=False,
        env=_scanner_environment(),
    )
    try:
        payload = json.loads(completed.stdout)
        results = payload["results"]
        found = {str(item["check_id"]).removeprefix("semgrep.") for item in results}
        safe_findings = [
            item for item in results if _is_fixture_path(str(item["path"]), safe)
        ]
    except (KeyError, TypeError, ValueError, json.JSONDecodeError):
        return 1
    return 0 if completed.returncode == 0 and found == expected and not safe_findings else 1


def _production_scan() -> int:
    """Scan production paths and fail on findings, warnings, or timeouts."""
    completed = subprocess.run(
        _base_command() + ["--error", *PRODUCTION_TARGETS],
        cwd=PROJECT_ROOT,
        timeout=600,
        check=False,
        env=_scanner_environment(),
    )
    return 0 if completed.returncode == 0 else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rules-test", action="store_true")
    args = parser.parse_args(argv)
    (PROJECT_ROOT / ".runtime").mkdir(parents=True, exist_ok=True)
    if not _verify_toolchain():
        print(
            "Semgrep 1.168.0 is unavailable; install requirements/semgrep.lock",
            file=sys.stderr,
        )
        return 2
    return _rules_test() if args.rules_test else _production_scan()


if __name__ == "__main__":
    raise SystemExit(main())
