"""Approved size thresholds use immutable history through actual profiles."""

import ast
import json
from dataclasses import replace

import pytest

from ladder_dragon.verification.architecture.function_spans import function_spans
from ladder_dragon.verification.architecture.new_code_sizes import compare_new_code_sizes
from ladder_dragon.verification.models import Status
from ladder_dragon.verification.profiles import checks_for_profile
from ladder_dragon.verification.runner import HarnessRunner
from tests.verification.test_release_continuity import _release_repository


@pytest.mark.parametrize("profile", ["local", "release"])
@pytest.mark.parametrize("kind,size,expected,warning", [
    ("module", 500, Status.PASS, False), ("module", 501, Status.FAILED, False),
    ("function", 80, Status.PASS, False), ("function", 81, Status.PASS, True),
    ("function", 120, Status.PASS, True), ("function", 121, Status.FAILED, False),
])
def test_profile_thresholds_and_new_functions_in_old_files(tmp_path, profile, kind, size, expected, warning):
    context, _ = _release_repository(tmp_path)
    root = context.root
    context = replace(context, options=replace(context.options, profile=profile))
    (root / "schemas").mkdir()
    (root / "schemas/architecture_contract.json").write_text(json.dumps({
        "schema_version": 1, "scope": "python_ownership_and_static_launcher_boundary",
        "directories": {"ladder_dragon/sample": "sample"}, "files": {"product_version.py": "product.identity"}}))
    if kind == "module":
        path = root / "ladder_dragon/sample/new.py"
        path.parent.mkdir(parents=True)
        path.write_text("# PRIVATE_MARKER\n" * size)
    else:
        path = root / "product_version.py"
        path.write_text(path.read_text() + "\ndef added():\n" + "    pass # PRIVATE_MARKER\n" * (size - 1))
    spec = next(spec for spec in checks_for_profile(context) if spec.name == "architecture_new_sizes")
    result = HarnessRunner(context)._run_spec(spec)
    assert result.required and result.status is expected
    assert bool(result.metrics["warnings"]) is warning
    assert "PRIVATE_MARKER" not in json.dumps(result.metrics)


@pytest.mark.parametrize("profile", ["local", "release"])
def test_missing_lineage_blocks_new_size_profile(tmp_path, profile):
    context, _ = _release_repository(tmp_path)
    context = replace(context, options=replace(context.options, profile=profile))
    (context.root / ".release-lineage.json").unlink()
    spec = next(spec for spec in checks_for_profile(context) if spec.name == "architecture_new_sizes")
    result = HarnessRunner(context)._run_spec(spec)
    assert result.required and result.status is Status.BLOCKED


def compare(before, after):
    return compare_new_code_sizes({"x.py": ast.parse(before)} if before is not None else {},
                                  [{"path": "x.py", "lines": len(after.splitlines()),
                                    "functions": function_spans(ast.parse(after))}])


def test_ambiguous_newness_never_grants_growth():
    duplicate = "def f(): pass\ndef f(): pass"
    assert compare(None, duplicate)["status"] == "BLOCKED"
    assert compare(duplicate, duplicate)["status"] == "PASS"
    assert compare(duplicate, duplicate + "\ndef f(): pass")["status"] == "BLOCKED"
    assert compare("def f(): pass", duplicate)["status"] == "BLOCKED"


def test_legacy_growth_is_not_misreported_as_new_and_rename_is_new():
    before = "def f():\n" + " pass\n" * 120
    result = compare(before, before + " pass\n")
    assert result["status"] == "PASS"
    assert "Existing size growth" in result["scope"]
    assert compare(before, before.replace("f()", "renamed()"))["status"] == "FAILED"


def test_nested_async_decorator_and_removed_function_restoration():
    source = "class C:\n @decorator\n async def f(self):\n" + "  pass\n" * 119
    assert compare("class C: pass", source)["status"] == "FAILED"
    assert compare("pass", source)["violations"][0]["qualified_name"] == "C.f"
