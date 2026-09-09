"""Legacy size ratchets preserve physical history and reject growth."""

import ast
import json
from dataclasses import replace

import pytest

from ladder_dragon.verification.architecture.function_spans import function_spans
from ladder_dragon.verification.architecture.new_code_sizes import compare_legacy_sizes
from ladder_dragon.verification.models import Status
from ladder_dragon.verification.profiles import checks_for_profile
from ladder_dragon.verification.runner import HarnessRunner
from tests.verification.test_release_continuity import _release_repository


def compare(before, after):
    tree = ast.parse(before)
    tree.source_lines = len(before.splitlines())
    return compare_legacy_sizes({"x.py": tree}, [{"path": "x.py", "lines": len(after.splitlines()),
                                                "functions": function_spans(ast.parse(after))}])


def test_large_module_shrink_and_restoration_ratchet():
    before = "# comment\n" * 600
    smaller = "# comment\n" * 550
    assert compare(before, before)["status"] == "PASS"
    assert compare(before, smaller)["status"] == "PASS"
    assert compare(smaller, before)["status"] == "FAILED"
    assert compare("pass\n", "# comment\n" * 500)["status"] == "PASS"
    assert compare("pass\n", "# comment\n" * 501)["status"] == "FAILED"


def test_function_growth_and_decorator_are_counted():
    before = "def f():\n" + " pass\n" * 130
    assert compare(before, before)["status"] == "PASS"
    result = compare(before, "@decorator\n" + before)
    assert result["violations"][0]["limit"] == 131
    assert result["violations"][0]["lines"] == 132
    assert compare(before, "def f(): pass")["status"] == "PASS"
    assert compare("def f(): pass", before)["status"] == "FAILED"


def test_ambiguous_legacy_spans_block_changed_matching():
    before = "def f(): pass\ndef f(): pass"
    assert compare(before, before)["status"] == "PASS"
    assert compare(before, before + "\ndef f(): pass")["status"] == "BLOCKED"


def test_missing_physical_metadata_blocks_instead_of_estimating_from_ast():
    with pytest.raises(ValueError, match="historical physical size"):
        compare_legacy_sizes({"x.py": ast.parse("pass")}, [{"path": "x.py", "lines": 1, "functions": []}])


@pytest.mark.parametrize("profile", ["local", "release"])
@pytest.mark.parametrize("lines,expected", [(500, Status.PASS), (501, Status.FAILED)])
def test_real_profile_checks_existing_module_growth(tmp_path, profile, lines, expected):
    context, _ = _release_repository(tmp_path)
    root = context.root
    context = replace(context, options=replace(context.options, profile=profile))
    (root / "schemas").mkdir()
    (root / "schemas/architecture_contract.json").write_text(json.dumps({
        "schema_version": 1, "scope": "python_ownership_and_static_launcher_boundary",
        "directories": {"ladder_dragon/sample": "sample"}, "files": {"product_version.py": "product.identity"}}))
    path = root / "product_version.py"
    original = path.read_text()
    path.write_text(original + "# PRIVATE_MARKER\n" * (lines - len(original.splitlines())))
    spec = next(spec for spec in checks_for_profile(context) if spec.name == "architecture_legacy_sizes")
    result = HarnessRunner(context)._run_spec(spec)
    assert result.required and result.status is expected
    assert "PRIVATE_MARKER" not in json.dumps(result.metrics)


@pytest.mark.parametrize("profile", ["local", "release"])
def test_missing_lineage_blocks_legacy_profile(tmp_path, profile):
    context, _ = _release_repository(tmp_path)
    context = replace(context, options=replace(context.options, profile=profile))
    (context.root / ".release-lineage.json").unlink()
    spec = next(spec for spec in checks_for_profile(context) if spec.name == "architecture_legacy_sizes")
    assert HarnessRunner(context)._run_spec(spec).status is Status.BLOCKED
