"""Keep numeric budgets and required safety invocation unchanged after relocation."""

import ast
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

from ladder_dragon.verification import numeric_boundaries as numeric
from ladder_dragon.verification.models import HarnessContext, HarnessOptions, Status
from ladder_dragon.verification.profiles import checks_for_profile
from ladder_dragon.verification.runner import HarnessRunner

ROOT = Path(__file__).resolve().parents[2]
OWNER = "ladder_dragon/verification/numeric_boundaries.py"
BASELINE_AST = "9a1ad689b8fc55fd9ce46281ae099a6ad00c3bae67cc2a4684864859e4f55ec4"


def test_policy_and_analyzer_keep_the_baseline_syntax():
    tree = ast.parse((ROOT / OWNER).read_text())
    tree.body = [node for node in tree.body if not isinstance(node, ast.FunctionDef) or node.name != "main"]
    assert hashlib.sha256(ast.dump(tree, include_attributes=False).encode()).hexdigest() == BASELINE_AST
    launcher = ast.parse((ROOT / "bin/audit_numeric_boundaries.py").read_text())
    expected = ast.parse('from ladder_dragon.verification.numeric_boundaries import main\nif __name__ == "__main__":\n    raise SystemExit(main())\n')
    assert ast.dump(launcher, include_attributes=False) == ast.dump(expected, include_attributes=False)


def test_command_resolves_checkout_independently_of_working_directory(tmp_path):
    result = subprocess.run([sys.executable, "-m", "bin.audit_numeric_boundaries"], cwd=tmp_path,
        env={"PATH": os.defpath, "PYTHONPATH": str(ROOT), "PYTHON_DOTENV_DISABLED": "1"},
        capture_output=True, text=True, timeout=20)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == numeric.audit_numeric_boundaries(ROOT)


@pytest.fixture
def checkout(tmp_path):
    for path in numeric.LIMITS:
        target = tmp_path / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("")
    for name in (OWNER, "bin/audit_numeric_boundaries.py"):
        target = tmp_path / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / name, target)
    for name in ("bin/__init__.py", "ladder_dragon/__init__.py", "ladder_dragon/verification/__init__.py"):
        (tmp_path / name).write_text("")
    return tmp_path


@pytest.mark.parametrize("profile", ["local", "release"])
def test_real_harness_command_still_rejects_a_new_float(checkout, profile):
    target = checkout / "ladder_dragon/execution/orders/new_path.py"
    target.write_text("value = float('PRIVATE_MARKER')\n")
    context = HarnessContext(root=checkout, python=sys.executable, options=HarnessOptions(
        profile=profile, output=checkout / "report.json"))
    specs = [spec for spec in checks_for_profile(context) if spec.name == "numeric_boundary_audit"]
    assert len(specs) == 1 and specs[0].required
    assert specs[0].argv == (sys.executable, "-m", "bin.audit_numeric_boundaries")
    result = HarnessRunner(context)._run_spec(specs[0])
    assert result.status is not Status.PASS
    assert result.exit_code == 2
    assert "PRIVATE_MARKER" not in str(result)


def test_main_failure_report_preserves_the_zero_budget(checkout, monkeypatch, capsys):
    target = checkout / "ladder_dragon/execution/orders/new_path.py"
    target.write_text("value = float('PRIVATE_MARKER')\n")
    monkeypatch.setattr(numeric, "__file__", str(checkout / OWNER))
    assert numeric.main() == 2
    output = capsys.readouterr().out
    report = json.loads(output)
    assert report["regressions"] == {
        "ladder_dragon/execution/orders/new_path.py": {"actual": 1, "maximum": 0}}
    assert "PRIVATE_MARKER" not in output


def test_reference_map_points_to_the_concrete_policy_owner():
    records = json.loads((ROOT / "schemas/architecture_reference_map.json").read_text())["records"]
    record = next(item for item in records if item["id"] == "numeric_budgets")
    assert record["path"] == OWNER
    assert record["anchors"] == ["LIMITS", "EXACT_PACKAGE_ROOTS"]
