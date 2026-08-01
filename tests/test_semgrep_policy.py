"""Contracts for the isolated deterministic Semgrep policy."""

from pathlib import Path
import re

from bin import semgrep_scan


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
    assert "semgrep==1.168.0" in lock
    assert "--hash=sha256:" in lock
    assert "semgrep" not in audit


def test_semgrep_wrapper_fails_closed_without_exact_toolchain(monkeypatch):
    monkeypatch.setattr(semgrep_scan, "_verify_toolchain", lambda: False)
    monkeypatch.setattr(
        semgrep_scan,
        "_production_scan",
        lambda: (_ for _ in ()).throw(AssertionError("scan must not start")),
    )

    assert semgrep_scan.main([]) == 2


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


def test_unsafe_fixture_name_is_not_classified_as_the_safe_fixture():
    unsafe = Path("tests/semgrep/unsafe_patterns.py")
    safe = Path("tests/semgrep/safe_patterns.py")

    assert unsafe.name.endswith(safe.name)
    assert semgrep_scan._is_fixture_path(str(unsafe), safe) is False
    assert semgrep_scan._is_fixture_path(str(safe), safe) is True
