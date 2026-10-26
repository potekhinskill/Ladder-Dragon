"""Shared timing syntax, real consumers, and mandatory negative contracts."""

import ast
from pathlib import Path
import shutil
import sys

import pytest

from ladder_dragon.observability import startup_timing as timing
from ladder_dragon.verification.architecture.startup_timing import OWNER_PATH, CONSUMERS
from ladder_dragon.verification.models import HarnessContext, HarnessOptions, Status
from ladder_dragon.verification.profiles import checks_for_profile
from ladder_dragon.verification.runner import HarnessRunner
from tests.architecture.ast_contracts import extraction_digest

ROOT = Path(__file__).resolve().parents[2]


def test_unchanged_implementation_syntax():
    # Captured from 446b93673e6f1f39353c0ca4dc67da930e3b7a5b before relocation.
    tree = ast.parse((ROOT / OWNER_PATH).read_text())
    assert extraction_digest(tree) == "5017e8ba661807a43817436d2a284f2a8b2c0418d82d4970a463ef78d6d2c871"


def test_real_consumers_share_timing_objects_and_worker_logging():
    from ladder_dragon.execution.worker.lifecycle import WorkerResources
    from ladder_dragon.supervision import runtime

    assert runtime.StartupTimeline is timing.StartupTimeline
    assert runtime.StartupSubphases is timing.StartupSubphases
    assert runtime.first_subphase_callback is timing.first_subphase_callback
    assert runtime.record_failed_startup_attempt is timing.record_failed_startup_attempt
    assert WorkerResources.startup_timeline is timing.StartupTimeline
    assert WorkerResources.log_startup is timing.log_worker_startup
    clock = iter((10.0, 10.25))
    timeline = WorkerResources.startup_timeline(lambda: next(clock))
    messages = []
    WorkerResources.log_startup(timeline, messages.append, "SOLUSDT", "clock")
    WorkerResources.log_startup(timeline, messages.append, "SOLUSDT", "clock")
    assert messages == [
        "[STARTUP-TIMING] component=worker phase=clock symbol=SOLUSDT delta_ms=250 elapsed_ms=250"
    ]
    snapshot = timeline.snapshot()
    snapshot["phases"]["clock"]["delta_ms"] = -1
    assert timeline.snapshot()["phases"]["clock"]["delta_ms"] == 250


@pytest.mark.parametrize("profile", ("local", "release"))
@pytest.mark.parametrize("damage", (
    None, "missing", "syntax", "stub", "method_stub", "reverse", "relative",
    "initializer", "legacy", "worker_import", "supervisor_import", "binding", "shadow",
))
def test_required_contract_rejects_regressions(tmp_path, profile, damage):
    for path in (OWNER_PATH, "ladder_dragon/observability/__init__.py", *CONSUMERS):
        target = tmp_path / path
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / path, target)
    owner = tmp_path / OWNER_PATH
    worker, supervisor = (tmp_path / path for path in CONSUMERS)
    if damage == "missing":
        owner.unlink()
    elif damage == "syntax":
        owner.write_text("class")
    elif damage == "stub":
        owner.write_text("from legacy import *\n")
    elif damage == "method_stub":
        tree = ast.parse(owner.read_text())
        cls = next(n for n in tree.body if isinstance(n, ast.ClassDef))
        method = next(n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == "mark")
        method.body = [ast.Pass()]
        owner.write_text(ast.unparse(tree))
    elif damage in {"reverse", "relative"}:
        source = ("from ladder_dragon.supervision import runtime\n" if damage == "reverse"
                  else "from ..supervision import runtime\n")
        owner.write_text(owner.read_text() + source)
    elif damage == "initializer":
        (owner.parent / "__init__.py").write_text("import ladder_dragon.execution.worker.lifecycle\n")
    elif damage == "legacy":
        (supervisor.parent / "startup_timing.py").write_text("from ladder_dragon.observability.startup_timing import *\n")
    elif damage in {"worker_import", "supervisor_import"}:
        path = worker if damage == "worker_import" else supervisor
        path.write_text(path.read_text().replace("ladder_dragon.observability.startup_timing", "ladder_dragon.supervision.startup_timing"))
    elif damage == "binding":
        worker.write_text(worker.read_text().replace("staticmethod(log_worker_startup)", "staticmethod(StartupTimeline)"))
    elif damage == "shadow":
        worker.write_text(worker.read_text() + "\nStartupTimeline = lambda: None\n")
    context = HarnessContext(root=tmp_path, python=sys.executable,
                             options=HarnessOptions(profile=profile, output=tmp_path / "report.json"))
    spec, = [s for s in checks_for_profile(context) if s.name == "architecture_startup_timing"]
    assert spec.required
    result = HarnessRunner(context)._run_spec(spec)
    expected = (Status.PASS if damage is None else Status.BLOCKED
                if damage in {"missing", "syntax"} else Status.FAILED)
    assert result.status is expected, result.metrics
