"""Context observations retain uncertain imports without running source."""

import ast
import json

import pytest

from ladder_dragon.verification.architecture.import_contexts import import_contexts
from ladder_dragon.verification.models import HarnessContext, HarnessOptions, Status
from ladder_dragon.verification.profiles import checks_for_profile
from ladder_dragon.verification.runner import HarnessRunner
from tests.architecture.test_dependency_graph import graph
from tests.architecture.test_ownership import checkout, source


@pytest.mark.parametrize("text,flags", [
    ("import pkg.a", (False, False, False)),
    ("def f():\n import pkg.a", (True, False, False)),
    ("async def f():\n if flag:\n  import pkg.a", (True, True, False)),
    ("class A:\n import pkg.a", (False, False, True)),
    ("def f():\n class A:\n  import pkg.a", (True, False, True)),
    ("try:\n import pkg.a\nexcept ImportError:\n pass", (False, True, False)),
])
def test_syntactic_contexts(text, flags):
    sites = import_contexts(ast.parse(text))
    assert len(sites) == 1
    assert tuple(sites[0][1][key] for key in ("deferred", "conditional", "class_body")) == flags


@pytest.mark.parametrize("prefix,guard", [
    ("from typing import TYPE_CHECKING as check", "check"),
    ("import typing as t", "t.TYPE_CHECKING"),
])
def test_type_guard_body_and_else_are_distinct_without_binding_claim(prefix, guard):
    tree = ast.parse(prefix + f"\nif {guard}:\n import pkg.a\nelse:\n import pkg.b")
    sites = import_contexts(tree)[1:]
    assert [context["type_guard_syntax"] for _, context in sites] == [True, False]
    assert all(context["conditional"] for _, context in sites)


def test_guard_rebinding_does_not_remove_edges():
    result = graph({"pkg/a.py": "from typing import TYPE_CHECKING as check\ncheck=True\nif check:\n import pkg.b",
                    "pkg/b.py": "import pkg.a"})
    assert result["direct_cycles"] == [["pkg/a.py", "pkg/b.py"]]
    assert result["unguarded_direct_cycles"] == []
    assert "shadowed or rebound" in result["context_scope"]
    assert result["import_contexts"][0]["type_guard_syntax"] is True


def test_multiple_sites_keep_distinct_contexts_for_same_edge():
    result = graph({"a.py": "import b\ndef f():\n import b", "b.py": "import a"})
    assert result["edge_count"] == 2
    assert len(result["import_contexts"]) == 3
    assert result["unguarded_direct_cycles"] == result["direct_cycles"]


@pytest.mark.parametrize("profile", ["local", "release"])
def test_actual_profiles_keep_deferred_cycle_without_private_condition_text(checkout, profile):
    source(checkout, "ladder_dragon/sample/a.py", "def hidden():\n if PRIVATE_MARKER():\n  from . import b")
    source(checkout, "ladder_dragon/sample/b.py", "from . import a")
    context = HarnessContext(root=checkout, python="python", options=HarnessOptions(
        profile=profile, output=checkout / "report.json"))
    spec = next(spec for spec in checks_for_profile(context) if spec.name == "architecture_ownership")
    result = HarnessRunner(context)._run_spec(spec)
    assert result.required and result.status is Status.PASS
    data = result.metrics["dependency_graph"]
    assert data["direct_cycles"] and data["unguarded_direct_cycles"] == []
    assert data["import_contexts"][0]["deferred"] and data["import_contexts"][0]["conditional"]
    assert "PRIVATE_MARKER" not in json.dumps(result.metrics)
