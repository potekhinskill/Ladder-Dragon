"""Function metrics retain lexical ambiguity and never execute decorators."""

import ast
import json

import pytest

from ladder_dragon.verification.architecture.function_spans import function_spans
from ladder_dragon.verification.models import HarnessContext, HarnessOptions, Status
from ladder_dragon.verification.profiles import checks_for_profile
from ladder_dragon.verification.runner import HarnessRunner
from tests.architecture.test_ownership import checkout, source


def test_decorators_async_nested_classes_and_lambdas():
    rows = function_spans(ast.parse("""@decorate(
 'PRIVATE_MARKER')
async def outer():
    # Included physical line.
    class Inner:
        def method(self):
            return lambda: 1
    return Inner
"""))
    assert rows == [
        {"qualified_name": "outer", "definition_line": 3, "start_line": 1, "end_line": 8,
         "lines": 8, "async": True, "ambiguous_identity": False},
        {"qualified_name": "outer.Inner.method", "definition_line": 6, "start_line": 6,
         "end_line": 7, "lines": 2, "async": False, "ambiguous_identity": False}]
    assert "PRIVATE_MARKER" not in json.dumps(rows)


@pytest.mark.parametrize("body", [
    "def same(): pass\ndef same(): pass",
    "if condition:\n def same(): pass\nelse:\n def same(): pass",
    "@overload\ndef same(): ...\ndef same(): pass",
    "class C:\n def same(self): pass\nclass C:\n def same(self): pass",
])
def test_duplicate_lexical_names_are_not_merged(body):
    rows = function_spans(ast.parse(body))
    assert len(rows) == 2
    assert all(row["ambiguous_identity"] for row in rows)
    assert rows[0]["definition_line"] < rows[1]["definition_line"]


def test_separate_class_names_and_empty_module():
    rows = function_spans(ast.parse("class A:\n def f(self): pass\nclass B:\n def f(self): pass"))
    assert [row["qualified_name"] for row in rows] == ["A.f", "B.f"]
    assert not any(row["ambiguous_identity"] for row in rows)
    assert function_spans(ast.parse("pass")) == []


@pytest.mark.parametrize("profile", ["local", "release"])
def test_actual_profiles_publish_spans_without_execution(checkout, profile):
    source(checkout, "ladder_dragon/sample/new.py", "@PRIVATE_MARKER()\ndef f():\n pass\ndef f(): pass")
    context = HarnessContext(root=checkout, python="python", options=HarnessOptions(
        profile=profile, output=checkout / "report.json"))
    spec = next(spec for spec in checks_for_profile(context) if spec.name == "architecture_ownership")
    result = HarnessRunner(context)._run_spec(spec)
    assert result.status is Status.PASS and result.required
    assert result.metrics["function_count"] == 2
    row = next(row for row in result.metrics["sources"] if row["path"].endswith("new.py"))
    assert row["maximum_function_lines"] == 3
    assert len(row["functions"]) == 2
    assert all(item["ambiguous_identity"] for item in row["functions"])
    assert "PRIVATE_MARKER" not in json.dumps(result.metrics)
