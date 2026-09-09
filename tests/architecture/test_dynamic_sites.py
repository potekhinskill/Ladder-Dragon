"""Source-only dynamic observations preserve uncertainty and bounded disclosure."""

import ast
import json

import pytest

from ladder_dragon.verification.architecture.dynamic_sites import dynamic_sites
from ladder_dragon.verification.models import HarnessContext, HarnessOptions, Status
from ladder_dragon.verification.profiles import checks_for_profile
from ladder_dragon.verification.runner import HarnessRunner
from tests.architecture.test_ownership import checkout, source


@pytest.mark.parametrize("text", [
    "import importlib\nimportlib.import_module('ladder_dragon.sample.target')",
    "import importlib as loader\ndef nested():\n loader.import_module(name='ladder_dragon.sample.target')",
    "from importlib import import_module as load\nif False:\n load('.target', package='ladder_dragon.sample')",
    "__import__('ladder_dragon.sample.target')",
    "from builtins import __import__ as load\nload('ladder_dragon.sample.target', level=0)",
])
def test_literal_local_targets_across_import_aliases_and_scopes(text):
    rows = dynamic_sites(ast.parse(text), {"ladder_dragon.sample.target"})
    assert len(rows) == 1
    assert rows[0]["resolution"] == "local_literal"
    assert rows[0]["target"] == "ladder_dragon.sample.target"
    assert len(rows[0]["ast_sha256"]) == 64


@pytest.mark.parametrize("call", [
    "load(PRIVATE_MARKER())", "load('PRIVATE_MARKER')", "load('.target', PRIVATE_MARKER)",
    "load('ladder_dragon.sample.target', **PRIVATE_MARKER)",
    "load(*PRIVATE_MARKER)", "load('ladder_dragon.sample.target', name='PRIVATE_MARKER')",
    "load('..target', 'sample')", "load('ladder_dragon.sample.target', invalid='PRIVATE_MARKER')",
    "__import__('ladder_dragon.sample.target', level=PRIVATE_MARKER)",
    "__import__('ladder_dragon.sample.target', level=1)",
    "__import__('ladder_dragon.sample.target', {}, {}, [], 0, level=0)",
])
def test_unknown_ambiguous_and_expanded_arguments_do_not_disclose_or_resolve(call):
    rows = dynamic_sites(ast.parse("from importlib import import_module as load\n" + call),
                         {"ladder_dragon.sample.target"})
    assert len(rows) == 1 and rows[0]["target"] is None
    assert rows[0]["resolution"] != "local_literal"
    assert "PRIVATE_MARKER" not in json.dumps(rows)


def test_observations_are_deterministic_and_do_not_claim_binding_provenance():
    tree = ast.parse("from importlib import import_module as load\n"
                     "load = lambda *args: None\nload('local.target')")
    assert dynamic_sites(tree, {"local.target"}) == dynamic_sites(tree, {"local.target"})
    assert dynamic_sites(tree, {"local.target"})[0]["resolution"] == "local_literal"


@pytest.mark.parametrize("profile", ["local", "release"])
def test_actual_profile_reports_observations_without_importing_targets(checkout, profile):
    source(checkout, "ladder_dragon/sample/target.py", "raise RuntimeError('PRIVATE_MARKER')\n")
    source(checkout, "ladder_dragon/sample/load.py",
           "from importlib import import_module as load\n"
           "load('.target', 'ladder_dragon.sample')\nload(PRIVATE_MARKER())\n")
    context = HarnessContext(root=checkout, python="python", options=HarnessOptions(
        profile=profile, output=checkout / "report.json"))
    spec = next(spec for spec in checks_for_profile(context) if spec.name == "architecture_ownership")
    result = HarnessRunner(context)._run_spec(spec)
    assert result.required and result.status is Status.PASS
    assert result.metrics["dynamic_import_site_count"] == 2
    assert "shadowed or rebound" in result.metrics["dynamic_inventory_scope"]
    row = next(row for row in result.metrics["sources"] if row["path"].endswith("load.py"))
    assert row["dynamic_import_sites"][0]["target"] == "ladder_dragon.sample.target"
    assert row["dynamic_import_sites"][1]["target"] is None
    assert "PRIVATE_MARKER" not in json.dumps(result.metrics)
