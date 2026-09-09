"""Cycle regression gates use real release history and fail closed."""

import json
from dataclasses import replace

import pytest

from ladder_dragon.verification.architecture.cycle_growth import historical_graph, compare_cycle_growth
from ladder_dragon.verification.models import HarnessOptions, Status
from ladder_dragon.verification.profiles import checks_for_profile
from ladder_dragon.verification.runner import HarnessRunner
from tests.architecture.test_dependency_graph import graph
from tests.verification.test_release_continuity import _release_repository, _git


def test_new_cycle_edges_fail_and_removal_passes():
    before = graph({"a.py": "import b", "b.py": "import a", "c.py": "pass"})
    assert compare_cycle_growth(before, before)["status"] == "PASS"
    removed = graph({"a.py": "import b", "b.py": "pass", "c.py": "pass"})
    assert compare_cycle_growth(before, removed)["status"] == "PASS"
    assert compare_cycle_growth(removed, before)["status"] == "FAILED"
    expanded = graph({"a.py": "import b", "b.py": "import a\nimport c", "c.py": "import a"})
    assert compare_cycle_growth(before, expanded)["new_cyclic_edges"] == [
        {"source": "b.py", "target": "c.py"}, {"source": "c.py", "target": "a.py"}]


def test_adding_edge_inside_existing_group_is_not_hidden_by_same_membership():
    before = graph({"a.py": "import b", "b.py": "import c", "c.py": "import a"})
    after = graph({"a.py": "import b\nimport c", "b.py": "import c", "c.py": "import a"})
    assert before["direct_cycles"] == after["direct_cycles"]
    assert compare_cycle_growth(before, after)["new_cyclic_edges"] == [{"source": "a.py", "target": "c.py"}]


def test_merging_groups_is_growth_even_without_new_files():
    before = graph({"a.py": "import b", "b.py": "import a\nimport c",
                    "c.py": "import d", "d.py": "import c"})
    after = graph({"a.py": "import b", "b.py": "import a\nimport c",
                   "c.py": "import d", "d.py": "import c\nimport a"})
    assert compare_cycle_growth(before, after)["new_cyclic_edges"] == [
        {"source": "b.py", "target": "c.py"}, {"source": "d.py", "target": "a.py"}]


def test_historical_symlink_is_rejected_without_following_it(tmp_path):
    context, _ = _release_repository(tmp_path)
    (context.root / "unsafe.py").symlink_to("PRIVATE_MARKER")
    _git(context.root, "add", "unsafe.py")
    _git(context.root, "commit", "-m", "synthetic symlink")
    with pytest.raises(ValueError, match="source type"):
        historical_graph(context.root, _git(context.root, "rev-parse", "HEAD"))


@pytest.mark.parametrize("profile", ["local", "release"])
@pytest.mark.parametrize("cycle", [False, True, "initializer"])
def test_actual_profiles_use_release_baseline_not_candidate_graph(tmp_path, profile, cycle):
    context, _ = _release_repository(tmp_path)
    root = context.root
    context = replace(context, options=replace(context.options, profile=profile))
    (root / "schemas").mkdir()
    (root / "schemas/architecture_contract.json").write_text(json.dumps({
        "schema_version": 1, "scope": "python_ownership_and_static_launcher_boundary",
        "directories": {"ladder_dragon/sample": "sample"}, "files": {"product_version.py": "product.identity"}}))
    package = root / "ladder_dragon/sample"
    package.mkdir(parents=True)
    (package / "a.py").write_text("from . import b\nraise RuntimeError('PRIVATE_MARKER')")
    (package / "b.py").write_text("def hidden():\n from . import a" if cycle else "pass")
    if cycle == "initializer":
        (package / "__init__.py").write_text("from . import a")
        (package / "a.py").write_text("import ladder_dragon.sample.b\nraise RuntimeError('PRIVATE_MARKER')")
        (package / "b.py").write_text("pass")
    specs = [spec for spec in checks_for_profile(context) if spec.name == "architecture_cycles"]
    assert len(specs) == 1 and specs[0].required
    result = HarnessRunner(context)._run_spec(specs[0])
    assert result.status is (Status.FAILED if cycle else Status.PASS)
    assert result.metrics["baseline_sha"] == _git(root, "rev-list", "-n", "1", "v1.0.0")
    assert "PRIVATE_MARKER" not in json.dumps(result.metrics)
    if cycle == "initializer":
        assert result.metrics["new_cyclic_edges"] == []
        assert result.metrics["new_combined_cyclic_edges"]


def test_initializer_cycle_growth_removal_and_restoration():
    before = graph({"p/__init__.py": "from . import a", "p/a.py": "pass", "p/b.py": "pass"})
    after = graph({"p/__init__.py": "from . import a", "p/a.py": "import p.b", "p/b.py": "pass"})
    assert after["direct_cycles"] == []
    result = compare_cycle_growth(before, after)
    assert result["status"] == "FAILED" and result["new_cyclic_edges"] == []
    assert result["new_combined_cyclic_edges"] == [
        {"source": "p/__init__.py", "target": "p/a.py"},
        {"source": "p/a.py", "target": "p/__init__.py"}]
    assert compare_cycle_growth(after, after)["status"] == "PASS"
    assert compare_cycle_growth(after, before)["status"] == "PASS"


def test_combined_allowance_does_not_approve_new_direct_cycle():
    before = graph({"p/__init__.py": "from . import a", "p/a.py": "import p.b", "p/b.py": "pass"})
    after = graph({"p/__init__.py": "from . import a", "p/a.py": "import p.b\nimport p", "p/b.py": "pass"})
    assert before["edges"] == after["edges"]
    result = compare_cycle_growth(before, after)
    assert result["status"] == "FAILED"
    assert result["new_cyclic_edges"]
    assert result["new_combined_cyclic_edges"] == []


@pytest.mark.parametrize("profile", ["local", "release"])
def test_unverified_lineage_blocks_actual_profile(tmp_path, profile):
    context, _ = _release_repository(tmp_path)
    (context.root / ".release-lineage.json").unlink()
    context = replace(context, options=replace(context.options, profile=profile))
    spec = next(spec for spec in checks_for_profile(context) if spec.name == "architecture_cycles")
    result = HarnessRunner(context)._run_spec(spec)
    assert result.required and result.status is Status.BLOCKED


@pytest.mark.parametrize("identity", ["HEAD", "--help", "0" * 40])
def test_invalid_or_missing_baseline_fails_closed(tmp_path, identity):
    import subprocess
    context, _ = _release_repository(tmp_path)
    with pytest.raises((ValueError, subprocess.SubprocessError)):
        historical_graph(context.root, identity)


def test_history_reads_committed_source_not_working_copy(tmp_path):
    context, candidate = _release_repository(tmp_path)
    (context.root / "product_version.py").write_text("PRIVATE_MARKER = (")
    result = historical_graph(context.root, candidate)
    assert result["direct_cycles"] == []
    assert "PRIVATE_MARKER" not in json.dumps(result)
