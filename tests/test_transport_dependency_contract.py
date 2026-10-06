"""Keep the patched HTTP dependency consistent across deployment profiles."""

import importlib.metadata
from pathlib import Path
import re

import pytest
from packaging.version import Version


def runtime_pin():
    source = Path("pyproject.toml").read_text()
    match = re.search(r'"urllib3==([0-9.]+)"', source)
    assert match is not None
    return match.group(1)


def test_installed_transport_matches_patched_runtime_pin():
    assert Version(runtime_pin()) >= Version("2.8.0")
    assert importlib.metadata.version("urllib3") == runtime_pin()


@pytest.mark.parametrize("profile", ["ci", "raspberry", "audit", "semgrep"])
def test_transport_lock_versions_and_hashes_agree(profile):
    def entry(name):
        source = Path(f"requirements/{name}.lock").read_text()
        match = re.search(r"^urllib3==[^\n]+\n(?:    --hash=[^\n]+\n)+", source, re.MULTILINE)
        assert match is not None
        return match.group(0)
    locked = entry(profile)
    assert locked.startswith(f"urllib3=={runtime_pin()} ")
    assert locked == entry("ci")
    assert len(re.findall(r"--hash=sha256:[a-f0-9]{64}", locked)) >= 2
