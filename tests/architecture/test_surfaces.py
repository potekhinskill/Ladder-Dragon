"""Source inventory contracts do not run launchers or deployment scripts."""

import json
from pathlib import Path
import subprocess

import pytest

from ladder_dragon.verification.architecture import surfaces
from ladder_dragon.verification.models import HarnessContext, HarnessOptions, Status
from ladder_dragon.verification.profiles import checks_for_profile
from ladder_dragon.verification.runner import HarnessRunner


@pytest.fixture
def checkout(tmp_path):
    def git(*args):
        subprocess.run(["git", "-c", "commit.gpgsign=false", "-c", "user.name=Test",
                        "-c", "user.email=test@example.invalid", *args], cwd=tmp_path,
                       check=True, capture_output=True)
    git("init", "-q")
    files = {"bin/sample.py": "python_command", "bin/control.sh": "shell_command",
             "deploy/sample.service": "service", "FRONT/index.html": "frontend_asset",
             "ladder_dragon/migrations/001_test.sql": "accounting_migration"}
    for name in files:
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("PRIVATE_MARKER\n")
    (tmp_path / "schemas").mkdir()
    (tmp_path / surfaces.CONTRACT).write_text(json.dumps(dict(schema_version=1,
        scope="source_surface_inventory_not_interface_parity", files=files)))
    (tmp_path / "docs").mkdir()
    (tmp_path / surfaces.COMMAND_GUIDE).write_text("| `sample` | purpose |\n| `control.sh` | purpose |\n")
    (tmp_path / ".gitignore").write_text(".env\n.runtime/\n")
    git("add", ".")
    git("commit", "-qm", "fixture")
    return tmp_path


def test_source_membership_never_executes_or_echoes_contents(checkout):
    (checkout / ".env").write_text("IGNORED_PRIVATE_MARKER")
    result = surfaces.audit_surfaces(checkout)
    assert result["status"] == "PASS"
    assert result["source_count"] == 5
    assert result["counts"]["python_command"] == 1
    assert "PRIVATE_MARKER" not in json.dumps(result)
    assert str(checkout) not in json.dumps(result)
    assert "CLI behavior" in result["limits"]
    assert all(len(row["source_sha256"]) == 64 for row in result["sources"])


@pytest.mark.parametrize("name", ["bin/new.py", "bin/nested/new.py", "bin/PRIVATE_MARKER",
    "deploy/new.timer", "deploy/other/new.sh", "FRONT/new.css", "FRONT/vendor/new.js",
    "FastAPI/pi-dashboard/other.py", "ladder_dragon/migrations/002_test.sql",
    "ladder_dragon/strategy/prediction/context_migrations/002_test.sql"])
def test_new_unregistered_surfaces_fail_before_content_read(checkout, name, monkeypatch):
    path = checkout / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("PRIVATE_MARKER")
    original = surfaces.read_source

    def guarded(root, relative, ceiling):
        assert relative != name
        return original(root, relative, ceiling)

    monkeypatch.setattr(surfaces, "read_source", guarded)
    result = surfaces.audit_surfaces(checkout)
    assert result["status"] == "FAILED"
    assert {"reason": "unregistered_surface"} in result["violations"]
    assert "PRIVATE_MARKER" not in json.dumps(result)


def test_registered_new_command_requires_documentation(checkout):
    manifest = checkout / surfaces.CONTRACT
    payload = json.loads(manifest.read_text())
    payload["files"]["bin/new.py"] = "python_command"
    manifest.write_text(json.dumps(payload))
    (checkout / "bin/new.py").write_text("raise RuntimeError('DO_NOT_EXECUTE')\n")
    result = surfaces.audit_surfaces(checkout)
    assert result["status"] == "FAILED"
    assert result["violations"] == [{"path": "bin/new.py", "reason": "command_missing_from_guide"}]
    guide = checkout / surfaces.COMMAND_GUIDE
    guide.write_text(guide.read_text() + "| `new` | purpose |\n")
    assert surfaces.audit_surfaces(checkout)["status"] == "PASS"


@pytest.mark.parametrize("staged", [False, True])
def test_removed_resources_fail_even_when_deletion_is_staged(checkout, staged):
    (checkout / "FRONT/index.html").unlink()
    if staged:
        subprocess.run(["git", "add", "-u"], cwd=checkout, check=True, capture_output=True)
    result = surfaces.audit_surfaces(checkout)
    assert result["status"] == "FAILED"
    assert result["violations"][0]["reason"] == (
        "registered_surface_outside_inventory" if staged else "registered_surface_missing")


@pytest.mark.parametrize("damage", ["missing", "duplicate", "role", "path", "version", "empty", "fields"])
def test_invalid_contract_blocks(checkout, damage):
    path = checkout / surfaces.CONTRACT
    payload = json.loads(path.read_text())
    if damage == "missing":
        path.unlink()
    elif damage == "duplicate":
        path.write_text('{"schema_version":1,"schema_version":1}')
    else:
        if damage == "role":
            payload["files"]["bin/sample.py"] = "frontend_asset"
        elif damage == "path":
            payload["files"]["deploy/../private.py"] = "deployment_python"
        elif damage == "version":
            payload["schema_version"] = True
        elif damage == "empty":
            payload["files"] = {}
        else:
            payload["permissions"] = ["trade"]
        path.write_text(json.dumps(payload))
    assert surfaces.audit_surfaces(checkout)["status"] == "BLOCKED"


@pytest.mark.parametrize("damage", ["symlink", "oversize", "directory", "guide"])
def test_unavailable_inputs_block_without_payloads(checkout, damage):
    source = checkout / "bin/sample.py"
    if damage == "symlink":
        source.unlink()
        private = checkout / ".env"
        private.write_text("PRIVATE_MARKER")
        source.symlink_to(private)
    elif damage == "oversize":
        source.write_text("x" * (1024 * 1024 + 1))
    elif damage == "directory":
        source.unlink()
        source.mkdir()
    else:
        (checkout / surfaces.COMMAND_GUIDE).unlink()
    result = surfaces.audit_surfaces(checkout)
    assert result["status"] == "BLOCKED"
    assert "PRIVATE_MARKER" not in json.dumps(result)


@pytest.mark.parametrize("profile", ["local", "release"])
def test_required_profile_calls_surface_check(checkout, profile):
    (checkout / "deploy/new.service").write_text("PRIVATE_MARKER")
    context = HarnessContext(root=checkout, python="python", options=HarnessOptions(
        profile=profile, output=checkout / "report.json"))
    specs = [spec for spec in checks_for_profile(context) if spec.name == "architecture_surfaces"]
    assert len(specs) == 1 and specs[0].required
    assert HarnessRunner(context)._run_spec(specs[0]).status is Status.FAILED


def test_hashes_observe_changes_without_claiming_migration_approval(checkout):
    first = surfaces.audit_surfaces(checkout)
    (checkout / "ladder_dragon/migrations/001_test.sql").write_text("SELECT 1;\n")
    second = surfaces.audit_surfaces(checkout)
    assert second["status"] == "PASS"
    assert first["sources"] != second["sources"]
    assert "migration compatibility remain separate checks" in second["limits"]


def test_repository_inventory_and_report_ceiling(checkout, monkeypatch):
    result = surfaces.audit_surfaces(Path(__file__).resolve().parents[2])
    assert result["status"] == "PASS"
    monkeypatch.setattr(surfaces, "MAX_REPORT", 20)
    assert surfaces.audit_surfaces(checkout)["status"] == "BLOCKED"
    assert surfaces.audit_surfaces(checkout / "absent")["status"] == "BLOCKED"


def test_command_aggregates_surface_failure(monkeypatch, capsys):
    from ladder_dragon.verification.architecture import cli

    monkeypatch.setattr(cli, "audit", lambda root: {"status": "PASS"})
    monkeypatch.setattr(cli, "audit_references", lambda root: {"status": "PASS"})
    monkeypatch.setattr(cli, "audit_surfaces", lambda root: {"status": "FAILED"})
    assert cli.main() == 1
    assert json.loads(capsys.readouterr().out)["status"] == "FAILED"
