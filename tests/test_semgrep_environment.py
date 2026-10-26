"""Provenance and dependency drift must fail before scanner execution."""

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from ladder_dragon.verification import semgrep_environment as verifier
from ladder_dragon.verification import semgrep_install_command as installer


@pytest.fixture
def contract(tmp_path, monkeypatch):
    (tmp_path / "requirements").mkdir()
    (tmp_path / "semgrep").mkdir()
    (tmp_path / "semgrep/engine").write_bytes(b"verified engine")
    origin = {"archive_info": {"hashes": {"sha256": "a" * 64}}}
    distribution = SimpleNamespace(
        files=[Path("semgrep/engine")],
        locate_file=lambda name: tmp_path / name,
        read_text=lambda name: json.dumps(origin),
    )
    target = {"wheel_sha256": "a" * 64, "payload_sha256": verifier.payload_digest(distribution)}
    manifest = {"version": "1.168.0+ld.1", "platforms": {"test": target}}
    (tmp_path / "requirements/semgrep-build.json").write_text(json.dumps(manifest))
    (tmp_path / "requirements/semgrep.lock").write_text("mcp==1.30.0 \\\n    --hash=sha256:abc\n")
    versions = {"semgrep": "1.168.0+ld.1", "mcp": "1.30.0"}
    monkeypatch.setattr(verifier, "host_key", lambda: "test")
    monkeypatch.setattr(verifier.metadata, "version", versions.__getitem__)
    monkeypatch.setattr(verifier.metadata, "distribution", lambda name: distribution)
    monkeypatch.setattr(verifier, "verify_launchers", lambda distribution: None)
    monkeypatch.setattr(verifier.metadata, "distributions", lambda: [
        SimpleNamespace(metadata={"Name": name}) for name in versions
    ])
    return tmp_path, distribution, origin, versions


def test_exact_payload_and_versions_pass(contract):
    verifier.verify(contract[0])


@pytest.mark.parametrize("name", ["semgrep", "mcp"])
def test_drift_fails(contract, name):
    contract[3][name] = "0.0.0"
    with pytest.raises(ValueError, match="version"):
        verifier.verify(contract[0])


def test_fake_origin_fails(contract):
    contract[2]["archive_info"]["hashes"]["sha256"] = "b" * 64
    with pytest.raises(ValueError, match="provenance"):
        verifier.verify(contract[0])


def test_missing_origin_fails(contract):
    contract[2].clear()
    with pytest.raises(ValueError, match="provenance"):
        verifier.verify(contract[0])


def test_legacy_pip_provenance_requires_exact_hash(contract):
    contract[2]["archive_info"] = {"hash": "sha256=" + "a" * 64}
    verifier.verify(contract[0])
    contract[2]["archive_info"]["hash"] = "sha256=" + "b" * 64
    with pytest.raises(ValueError, match="provenance"):
        verifier.verify(contract[0])


def test_conflicting_provenance_formats_fail(contract):
    contract[2]["archive_info"]["hash"] = "sha256=" + "b" * 64
    with pytest.raises(ValueError, match="provenance"):
        verifier.verify(contract[0])


def test_modified_code_fails(contract):
    (contract[0] / "semgrep/engine").write_bytes(b"unreviewed engine")
    with pytest.raises(ValueError, match="payload"):
        verifier.verify(contract[0])


def test_missing_record_entries_fail(contract):
    contract[1].files = []
    with pytest.raises(ValueError, match="payload"):
        verifier.verify(contract[0])


def test_empty_dependency_contract_fails(contract):
    (contract[0] / "requirements/semgrep.lock").write_text("")
    with pytest.raises(ValueError, match="empty"):
        verifier.verify(contract[0])


def test_unlocked_extra_dependency_fails(contract):
    contract[3]["unlocked-package"] = "1.0"
    with pytest.raises(ValueError, match="dependency set"):
        verifier.verify(contract[0])


def test_unknown_platform_fails(contract, monkeypatch):
    monkeypatch.setattr(verifier, "host_key", lambda: "unknown")
    with pytest.raises(KeyError):
        verifier.verify(contract[0])


def test_changed_launcher_fails(tmp_path, monkeypatch):
    (tmp_path / "bin").mkdir()
    (tmp_path / "bin/semgrep").write_bytes(b"changed launcher")
    record = SimpleNamespace(hash=SimpleNamespace(mode="sha256", value="unmatched"))
    distribution = SimpleNamespace(files=[record], locate_file=lambda _: tmp_path / "bin/semgrep")
    monkeypatch.setattr(verifier.sys, "prefix", str(tmp_path))
    with pytest.raises(ValueError, match="integrity"):
        verifier.verify_launchers(distribution)


def test_existing_build_contract_cannot_be_overwritten(tmp_path):
    path = tmp_path / "wheel.lock"
    installer._write_contract(path, "first")
    installer._write_contract(path, "first")
    with pytest.raises(ValueError, match="differs"):
        installer._write_contract(path, "second")
    assert path.read_text() == "first"


def test_install_keeps_normal_resolver_and_minimal_environment(tmp_path, monkeypatch):
    (tmp_path / "requirements").mkdir()
    target = {"filename": "semgrep-1.168.0-py3-none-any.whl", "url": "https://example.invalid/pinned.whl",
              "source_sha256": hashlib.sha256(b"source").hexdigest(),
              "wheel_sha256": hashlib.sha256(b"rebuilt").hexdigest()}
    (tmp_path / "requirements/semgrep-build.json").write_text(json.dumps(
        {"version": "1.168.0+ld.1", "platforms": {"test": target}}))
    work = tmp_path / ".runtime/semgrep-build/1.168.0+ld.1/test"
    calls = []

    def run(argv, **kwargs):
        calls.append((argv, kwargs))
        assert "BINANCE_API_KEY" not in kwargs["env"]
        if "download" in argv:
            (work / target["filename"]).write_bytes(b"source")

    def build(source, destination):
        assert source.read_bytes() == b"source"
        (destination / "semgrep-1.168.0+ld.1-py3-none-any.whl").write_bytes(b"rebuilt")

    monkeypatch.setenv("BINANCE_API_KEY", "synthetic-do-not-inherit")
    monkeypatch.setattr(installer, "host_key", lambda: "test")
    monkeypatch.setattr(installer.subprocess, "run", run)
    monkeypatch.setattr(installer, "rebuild", build)
    installer.install(tmp_path)
    install = next(argv for argv, _ in calls if "install" in argv and str(work / "wheel.lock") in argv)
    assert "--require-hashes" in install
    assert "--no-deps" not in install
    assert str(tmp_path / "requirements/semgrep.lock") in install
    assert str(work / "wheel.lock") in install
    assert calls[-2][0][-2:] == ["pip", "check"]
    assert "-I" in calls[-1][0]
    bootstrap = next(argv for argv, _ in calls if str(tmp_path / "requirements/semgrep-bootstrap.lock") in argv)
    assert calls.index(next(call for call in calls if call[0] == bootstrap)) < calls.index(next(call for call in calls if call[0] == install))
