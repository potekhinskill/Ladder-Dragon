"""Mutation and real-profile checks for the first architecture slice."""

import json
from pathlib import Path
import subprocess

import pytest

from ladder_dragon.verification.architecture import inventory
from ladder_dragon.verification.models import HarnessContext, HarnessOptions, Status
from ladder_dragon.verification.profiles import checks_for_profile
from ladder_dragon.verification.runner import HarnessRunner


@pytest.fixture
def checkout(tmp_path):
    def git(*args):
        subprocess.run(
            ["git", "-c", "commit.gpgsign=false", "-c", "user.name=Test",
             "-c", "user.email=test@example.invalid", *args], cwd=tmp_path,
            check=True, capture_output=True,
        )
    git("init", "-q")
    (tmp_path / "schemas").mkdir()
    policy = {"schema_version": 1, "scope": "python_ownership_and_static_launcher_boundary",
              "directories": {"ladder_dragon/sample": "sample"},
              "files": {"product_version.py": "product.identity"}}
    (tmp_path / inventory.CONTRACT).write_text(json.dumps(policy))
    (tmp_path / "product_version.py").write_text('VERSION = "test"\n')
    (tmp_path / ".gitignore").write_text(".env\n.runtime/\n")
    (tmp_path / "ladder_dragon/sample").mkdir(parents=True)
    git("add", ".")
    git("commit", "-qm", "fixture")
    return tmp_path


def source(root, name, text):
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    return path


def test_inventory_includes_untracked_source_without_importing_it(checkout):
    source(checkout, "ladder_dragon/sample/new.py", 'raise RuntimeError("DO_NOT_IMPORT")\n')
    source(checkout, ".env", "PRIVATE_MARKER")
    source(checkout, ".runtime/private.py", "PRIVATE_MARKER")
    result = inventory.audit(checkout)
    assert result["status"] == "PASS"
    assert result["source_count"] == 2
    assert "PRIVATE_MARKER" not in json.dumps(result)
    assert "DO_NOT_IMPORT" not in json.dumps(result)
    assert all(not row["path"].startswith(".runtime") for row in result["sources"])
    assert all(len(row["source_sha256"]) == 64 for row in result["sources"])


@pytest.mark.parametrize("name", ["new.py", "ladder_dragon/unknown/new.py", "ladder_dragon/sample/unregistered/new.py"])
def test_unknown_locations_fail_without_reading_their_contents(checkout, name):
    source(checkout, name, "PRIVATE_MARKER")
    result = inventory.audit(checkout)
    assert result["status"] == "FAILED"
    assert result["violations"] == [{"rule": "A01", "path": name, "reason": "unknown_owner"}]
    assert "PRIVATE_MARKER" not in json.dumps(result)


@pytest.mark.parametrize("text", [
    "import bin.ai_supervisor as hidden\n",
    "def hidden():\n    from bin import ai_supervisor\n",
    "if False:\n    import bin\n",
])
def test_static_launcher_imports_fail_in_all_scopes(checkout, text):
    source(checkout, "ladder_dragon/sample/new.py", text)
    result = inventory.audit(checkout)
    assert result["status"] == "FAILED"
    assert result["violations"][0]["rule"] == "A02"


def test_relative_imports_are_reported_and_dynamic_limits_are_explicit(checkout):
    source(checkout, "ladder_dragon/sample/new.py", "from . import sibling\nfrom ..risk import policy\n")
    result = inventory.audit(checkout)
    assert result["status"] == "PASS"
    row = next(row for row in result["sources"] if row["path"].endswith("new.py"))
    assert "ladder_dragon.sample.sibling" in row["imports"]
    assert "ladder_dragon.risk.policy" in row["imports"]
    assert "dynamic imports" in result["limits"]


@pytest.mark.parametrize("damage", ["missing", "duplicate", "overlap", "traversal", "version"])
def test_invalid_contract_blocks(checkout, damage):
    path = checkout / inventory.CONTRACT
    policy = json.loads(path.read_text())
    if damage == "missing":
        path.unlink()
    elif damage == "duplicate":
        path.write_text('{"schema_version":1,"schema_version":1}')
    else:
        if damage == "overlap":
            policy["files"]["ladder_dragon/sample/new.py"] = "duplicate"
        elif damage == "traversal":
            policy["directories"]["../private"] = "private"
        else:
            policy["schema_version"] = True
        path.write_text(json.dumps(policy))
    assert inventory.audit(checkout)["status"] == "BLOCKED"


@pytest.mark.parametrize("damage", ["syntax", "symlink", "oversize"])
def test_source_errors_block_without_secret_diagnostics(checkout, damage):
    path = checkout / "ladder_dragon/sample/new.py"
    if damage == "symlink":
        source(checkout, ".env", "PRIVATE_MARKER")
        path.symlink_to(checkout / ".env")
    else:
        path.write_text("PRIVATE_MARKER = (" if damage == "syntax" else "x" * (1024 * 1024 + 1))
    result = inventory.audit(checkout)
    assert result["status"] == "BLOCKED"
    assert "PRIVATE_MARKER" not in json.dumps(result)
    assert str(checkout) not in json.dumps(result)


@pytest.mark.parametrize("profile", ["local", "release"])
def test_profile_invokes_required_architecture_rule(checkout, profile):
    source(checkout, "unexpected.py", "raise RuntimeError('NO_RUNTIME')\n")
    context = HarnessContext(root=checkout, python="python", options=HarnessOptions(profile=profile, output=checkout / "report.json"))
    specs = [spec for spec in checks_for_profile(context) if spec.name == "architecture_ownership"]
    assert len(specs) == 1 and specs[0].required
    result = HarnessRunner(context)._run_spec(specs[0])
    assert result.status is Status.FAILED
    assert result.metrics["violations"][0]["rule"] == "A01"


def test_report_ceiling_and_missing_git_fail_closed(checkout, monkeypatch):
    monkeypatch.setattr(inventory, "MAX_REPORT", 300)
    assert inventory.audit(checkout)["status"] == "BLOCKED"
    assert inventory.audit(checkout / "not-a-checkout")["status"] == "BLOCKED"


@pytest.mark.parametrize("profile", ["local", "release"])
def test_profile_reports_cli_sites_without_running_defaults(checkout, profile):
    source(checkout, "ladder_dragon/sample/new.py",
           "import argparse as ap\np=ap.ArgumentParser()\np.add_argument('--x', default=PRIVATE_MARKER())\n")
    context = HarnessContext(root=checkout, python="python", options=HarnessOptions(
        profile=profile, output=checkout / "report.json"))
    spec = next(spec for spec in checks_for_profile(context) if spec.name == "architecture_ownership")
    result = HarnessRunner(context)._run_spec(spec)
    assert result.status is Status.PASS
    assert result.metrics["cli_site_count"] == 2
    assert "Syntactic observations only" in result.metrics["cli_inventory_scope"]
    assert "PRIVATE_MARKER" not in json.dumps(result.metrics)
