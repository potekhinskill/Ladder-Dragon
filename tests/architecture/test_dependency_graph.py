"""Exact source edges, conservative cycle observations, and profile rejection."""

import ast
import json

import pytest

from ladder_dragon.verification.architecture.dependency_graph import dependency_graph, cycle_groups
from ladder_dragon.verification.architecture import inventory
from ladder_dragon.verification.models import HarnessContext, HarnessOptions, Status
from ladder_dragon.verification.profiles import checks_for_profile
from ladder_dragon.verification.runner import HarnessRunner
from tests.architecture.test_ownership import checkout, source


def graph(sources):
    return dependency_graph({name: ast.parse(text) for name, text in sources.items()})


def test_relative_nested_imports_resolve_real_modules_not_functions():
    result = graph({
        "pkg/__init__.py": "from . import child",
        "pkg/child.py": "def hidden():\n from .helper import work as hidden\n",
        "pkg/helper.py": "def work(): pass",
        "other.py": "import pkg.child as alias\nfrom pkg.helper import work\nimport external",
    })
    assert result["edges"]["pkg/__init__.py"] == ["pkg/child.py"]
    assert result["edges"]["pkg/child.py"] == ["pkg/__init__.py", "pkg/helper.py"]
    assert result["edges"]["other.py"] == ["pkg/__init__.py", "pkg/child.py", "pkg/helper.py"]
    assert result["cycles"] == [["pkg/__init__.py", "pkg/child.py"]]


def test_root_modules_namespace_packages_and_parent_relatives():
    result = graph({"pkg/nested/a.py": "from .. import b\nimport product_version",
                    "pkg/b.py": "pass", "product_version.py": "pass"})
    assert result["edges"]["pkg/nested/a.py"] == ["pkg/b.py", "product_version.py"]
    assert result["edge_count"] == 2 and result["cycles"] == []


def test_initializer_only_cycle_is_distinguished_from_direct_import_cycle():
    sources = {"pkg/__init__.py": "from .a import work", "pkg/a.py": "import pkg.b\nwork = 1",
               "pkg/b.py": "pass"}
    before = graph(sources)
    assert before["cycles"] == [["pkg/__init__.py", "pkg/a.py"]]
    assert before["direct_cycles"] == []
    assert before["cycle_details"] == [{"members": ["pkg/__init__.py", "pkg/a.py"],
                                        "direct_edge_count": 1, "initializer_only_edge_count": 1,
                                        "direct_cycles": []}]
    sources["pkg/b.py"] = "import pkg.a"
    after = graph(sources)
    assert after["direct_cycles"] == [["pkg/a.py", "pkg/b.py"]]
    assert after["cycle_details"][0]["direct_cycles"] == after["direct_cycles"]


def test_edge_kinds_preserve_union_without_double_counting():
    result = graph({"pkg/__init__.py": "pass", "pkg/a.py": "pass",
                    "other.py": "import pkg\nimport pkg.a"})
    assert result["direct_edges"]["other.py"] == ["pkg/__init__.py", "pkg/a.py"]
    assert result["initializer_edges"]["other.py"] == ["pkg/__init__.py"]
    assert result["edge_count"] == 2
    for path, targets in result["edges"].items():
        assert set(targets) == set(result["direct_edges"][path]) | set(result["initializer_edges"][path])


def test_cycle_details_keep_distinct_direct_groups_inside_one_combined_group():
    result = graph({"pkg/__init__.py": "import pkg.a\nimport pkg.c",
                    "pkg/a.py": "import pkg.b", "pkg/b.py": "import pkg.a",
                    "pkg/c.py": "import pkg.d", "pkg/d.py": "import pkg.c"})
    assert len(result["cycles"]) == 1
    assert result["direct_cycles"] == [["pkg/a.py", "pkg/b.py"], ["pkg/c.py", "pkg/d.py"]]
    details = result["cycle_details"][0]
    assert details["direct_cycles"] == result["direct_cycles"]
    assert details["direct_edge_count"] == 6
    assert details["initializer_only_edge_count"] == 4


def test_star_import_uses_package_without_inventing_all_exports():
    result = graph({"pkg/__init__.py": "pass", "pkg/child.py": "pass", "a.py": "from pkg import *"})
    assert result["edges"]["a.py"] == ["pkg/__init__.py"]


@pytest.mark.parametrize("sources", [
    {"pkg.py": "pass", "pkg/__init__.py": "pass"},
    {"pkg/a.py": "from ... import private"},
])
def test_ambiguous_modules_and_escaping_relatives_block(sources):
    with pytest.raises(ValueError):
        graph(sources)


def test_cycle_algorithm_handles_deep_chains_self_loops_and_multiple_groups():
    edges = {str(i): {str(i + 1)} for i in range(2000)}
    edges["2000"] = set()
    assert cycle_groups(edges) == []
    edges["2000"] = {"1999"}
    edges["self"] = {"self"}
    edges["a"], edges["b"] = {"b"}, {"a"}
    assert cycle_groups(edges) == [["1999", "2000"], ["a", "b"], ["self"]]


def test_all_three_node_graphs_match_independent_reachability():
    nodes = ["a", "b", "c"]
    pairs = [(a, b) for a in nodes for b in nodes]
    for mask in range(1 << len(pairs)):
        edges = {node: set() for node in nodes}
        for bit, (a, b) in enumerate(pairs):
            if mask & (1 << bit):
                edges[a].add(b)
        reachable = {a: set(edges[a]) for a in nodes}
        for _ in nodes:
            for a in nodes:
                reachable[a].update(b for middle in list(reachable[a]) for b in reachable[middle])
        expected = {tuple(b for b in nodes if b in reachable[a] and a in reachable[b]) for a in nodes}
        assert cycle_groups(edges) == sorted(list(group) for group in expected if group)


@pytest.mark.parametrize("profile", ["local", "release"])
def test_real_profile_reports_cycle_without_executing_modules(checkout, profile):
    source(checkout, "ladder_dragon/sample/a.py", "from . import b\nraise RuntimeError('PRIVATE_MARKER')")
    source(checkout, "ladder_dragon/sample/b.py", "if False:\n from . import a")
    context = HarnessContext(root=checkout, python="python", options=HarnessOptions(
        profile=profile, output=checkout / "report.json"))
    spec = next(item for item in checks_for_profile(context) if item.name == "architecture_ownership")
    result = HarnessRunner(context)._run_spec(spec)
    assert result.required and result.status is Status.PASS
    assert result.metrics["dependency_graph"]["cycles"] == [[
        "ladder_dragon/sample/a.py", "ladder_dragon/sample/b.py"]]
    assert result.metrics["dependency_graph"]["direct_cycles"] == result.metrics["dependency_graph"]["cycles"]
    assert result.metrics["dependency_graph"]["cycle_details"][0]["initializer_only_edge_count"] == 0
    assert "not approved exceptions" in result.metrics["dependency_graph"]["scope"]
    assert "PRIVATE_MARKER" not in json.dumps(result.metrics)


@pytest.mark.parametrize("profile", ["local", "release"])
def test_real_profile_blocks_ambiguous_module_identity(checkout, profile):
    policy_path = checkout / inventory.CONTRACT
    policy = json.loads(policy_path.read_text())
    policy["files"]["ladder_dragon/sample.py"] = "sample"
    policy_path.write_text(json.dumps(policy))
    source(checkout, "ladder_dragon/sample.py", "PRIVATE_MARKER = 1")
    source(checkout, "ladder_dragon/sample/__init__.py", "pass")
    context = HarnessContext(root=checkout, python="python", options=HarnessOptions(
        profile=profile, output=checkout / "report.json"))
    spec = next(item for item in checks_for_profile(context) if item.name == "architecture_ownership")
    result = HarnessRunner(context)._run_spec(spec)
    assert result.required and result.status is Status.BLOCKED
    assert "PRIVATE_MARKER" not in json.dumps(result.metrics)
