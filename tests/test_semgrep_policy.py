"""Contracts for the isolated deterministic Semgrep policy."""

from pathlib import Path
import re
import subprocess
import json
import pytest

from ladder_dragon.verification import semgrep_command as semgrep_scan


ROOT = Path(__file__).resolve().parents[1]


def test_each_semgrep_rule_has_one_positive_fixture():
    config = (ROOT / ".semgrep" / "ladder-dragon.yml").read_text()
    fixture = (ROOT / "tests" / "semgrep" / "unsafe_patterns.py").read_text()
    rules = set(re.findall(r"^  - id: (ladder-dragon\.[a-z0-9-]+)$", config, re.MULTILINE))
    markers = re.findall(r"# ruleid: (ladder-dragon\.[a-z0-9-]+)", fixture)

    assert len(rules) == 11
    assert set(markers) == rules
    assert len(markers) == len(set(markers))


def test_semgrep_is_pinned_in_an_isolated_hash_lock():
    source = (ROOT / "requirements" / "semgrep.in").read_text()
    lock = (ROOT / "requirements" / "semgrep.lock").read_text()
    audit = (ROOT / "requirements" / "audit.in").read_text()

    assert "semgrep==1.168.0" in source
    manifest = json.loads((ROOT / "requirements/semgrep-build.json").read_text())
    assert manifest["version"] == semgrep_scan.EXPECTED_VERSION == "1.168.0+ld.1"
    assert "mcp==1.30.0" in lock
    assert "opentelemetry-api==1.45.1" in lock
    assert "pyjwt[crypto]==2.15.0" in lock
    assert "semgrep==1.168.0" in (ROOT / "requirements/semgrep-upstream-audit.in").read_text()
    assert "--hash=sha256:" in lock
    assert "semgrep" not in audit


def test_ci_installs_and_audits_downstream_without_optional_checks():
    workflow = (ROOT / ".github/workflows/security.yml").read_text()
    assert "python -m bin.install_semgrep" in workflow
    for filename in ("semgrep.lock", "semgrep-upstream-audit.in", "raspberry.lock"):
        assert "python -m pip_audit --disable-pip --no-deps -r requirements/" + filename in workflow
    assert "continue-on-error" not in workflow
    assert "--ignore-vuln" not in workflow


def test_bootstrap_pins_and_hashes_are_covered_by_audited_lock():
    bootstrap = (ROOT / "requirements/semgrep-bootstrap.lock").read_text()
    lock = (ROOT / "requirements/semgrep.lock").read_text()
    for line in bootstrap.splitlines():
        if line.strip() and not line.startswith("#"):
            assert line in lock


@pytest.mark.parametrize("args", [[], ["--rules-test"], ["--compatibility-test"]])
def test_semgrep_wrapper_fails_closed_without_exact_toolchain(monkeypatch, args):
    monkeypatch.setattr(semgrep_scan, "_verify_toolchain", lambda: False)
    monkeypatch.setattr(
        semgrep_scan,
        "_production_scan",
        lambda: (_ for _ in ()).throw(AssertionError("scan must not start")),
    )

    assert semgrep_scan.main(args) == 2


def test_wrapper_runs_isolated_provenance_verifier(monkeypatch):
    calls = []
    monkeypatch.setattr(Path, "is_file", lambda _: True)
    def run(argv, **kwargs):
        calls.append((argv, kwargs))
        return subprocess.CompletedProcess(argv, 2, "", "")
    monkeypatch.setattr(semgrep_scan.subprocess, "run", run)
    assert semgrep_scan._verify_toolchain() is False
    assert "-I" in calls[0][0]
    assert any(str(arg).endswith("semgrep_environment.py") for arg in calls[0][0])


def test_compatibility_failure_propagates(monkeypatch):
    monkeypatch.setattr(semgrep_scan, "_verify_toolchain", lambda: True)
    monkeypatch.setattr(semgrep_scan.subprocess, "run", lambda *a, **k: subprocess.CompletedProcess(a[0], 1))
    assert semgrep_scan.main(["--compatibility-test"]) == 1


def test_semgrep_wrapper_uses_offline_bounded_settings():
    command = semgrep_scan._base_command()
    environment = semgrep_scan._scanner_environment()

    assert "--metrics=off" in command
    assert "--strict" in command
    assert "--timeout=30" in command
    assert "--timeout-threshold=1" in command
    assert "--no-git-ignore" in command
    assert environment["SEMGREP_SEND_METRICS"] == "off"
    assert environment["SEMGREP_ENABLE_VERSION_CHECK"] == "0"
    assert "tests" not in semgrep_scan.PRODUCTION_TARGETS


def test_semgrep_environment_does_not_inherit_application_secrets(monkeypatch):
    monkeypatch.setenv("BINANCE_API_KEY", "must-not-reach-scanner")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "must-not-reach-scanner")

    environment = semgrep_scan._scanner_environment()

    assert "BINANCE_API_KEY" not in environment
    assert "TELEGRAM_BOT_TOKEN" not in environment
    assert set(environment) <= {
        "HOME",
        "LANG",
        "PATH",
        "SEMGREP_ENABLE_VERSION_CHECK",
        "SEMGREP_LOG_FILE",
        "SEMGREP_SEND_METRICS",
        "SSL_CERT_FILE",
        "TMPDIR",
        "XDG_CACHE_HOME",
    }


def test_production_scan_receives_the_minimal_environment(monkeypatch):
    captured = {}

    def fake_run(*args, **kwargs):
        captured["environment"] = kwargs["env"]
        return subprocess.CompletedProcess(args[0], 0)

    monkeypatch.setenv("BINANCE_API_KEY", "must-not-reach-scanner")
    monkeypatch.setattr(semgrep_scan.subprocess, "run", fake_run)

    assert semgrep_scan._production_scan() == 0
    assert "BINANCE_API_KEY" not in captured["environment"]


def test_unsafe_fixture_name_is_not_classified_as_the_safe_fixture():
    unsafe = Path("tests/semgrep/unsafe_patterns.py")
    safe = Path("tests/semgrep/safe_patterns.py")

    assert unsafe.name.endswith(safe.name)
    assert semgrep_scan._is_fixture_path(str(unsafe), safe) is False
    assert semgrep_scan._is_fixture_path(str(safe), safe) is True
