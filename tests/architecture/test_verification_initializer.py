"""Keep result imports independent of harness orchestration."""

import ast
import os
from pathlib import Path
import subprocess
import sys

from ladder_dragon.verification.architecture.cycle_growth import compare_cycle_growth
from ladder_dragon.verification.architecture.dependency_graph import dependency_graph


def test_fresh_process_import_preserves_result_identity_without_runner():
    root = Path(__file__).resolve().parents[2]
    result = subprocess.run(
        [sys.executable, "-c", """
import sys
import ladder_dragon.verification as package
from ladder_dragon.verification.models import CheckResult, HarnessReport, Status
assert package.CheckResult is CheckResult
assert package.HarnessReport is HarnessReport
assert package.Status is Status
assert package.__all__ == ['CheckResult', 'HarnessReport', 'Status']
assert 'ladder_dragon.verification.runner' not in sys.modules
assert 'ladder_dragon.verification.profiles' not in sys.modules
from ladder_dragon.verification.runner import HarnessRunner
assert HarnessRunner.__module__ == 'ladder_dragon.verification.runner'
"""], cwd=root, env={**os.environ, "PYTHON_DOTENV_DISABLED": "1"},
        capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0, result.stderr


def test_restored_runner_export_is_rejected_by_cycle_comparator():
    root = Path(__file__).resolve().parents[2]
    package = root / "ladder_dragon/verification"
    trees = {path.relative_to(root).as_posix(): ast.parse(path.read_text())
             for path in package.rglob("*.py")}
    before = dependency_graph(trees)
    assert before["cycles"] == []
    initializer = "ladder_dragon/verification/__init__.py"
    trees[initializer] = ast.parse((root / initializer).read_text() + "\nfrom .runner import HarnessRunner\n")
    result = compare_cycle_growth(before, dependency_graph(trees))
    assert result["status"] == "FAILED"
    assert result["new_combined_cyclic_edges"]
