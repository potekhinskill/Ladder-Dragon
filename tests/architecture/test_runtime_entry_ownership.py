"""Runtime entry ownership without starting either trading service."""

import ast
import os
from pathlib import Path
import runpy
import subprocess
import sys
from types import ModuleType

import pytest

from ladder_dragon.verification.architecture.runtime_entry_ownership import RUNTIME_COMMANDS, INERT_PACKAGES
from ladder_dragon.verification.models import Status
from tests.architecture.ast_contracts import extraction_digest
from tests.architecture.test_digest_extractions import _check
from tests.architecture.test_five_audit_extractions import checkout

ROOT = Path(__file__).resolve().parents[2]
DIGESTS = {
    "ai_supervisor": "d59da1a3788c1622501028ca61ed26bd9a34be34252695d5d3e3a1e138d285db",
    "autosize_universal": "2b9ba62ead76cbcb4ececc451c5fb54e0326edd4680d3c71aa10aff63c859313",
}


@pytest.mark.parametrize("name", RUNTIME_COMMANDS)
def test_runtime_implementation_syntax_is_unchanged(name):
    owner = RUNTIME_COMMANDS[name][0]
    tree = ast.parse((ROOT / (owner.replace(".", "/") + ".py")).read_text())
    assert extraction_digest(tree) == DIGESTS[name]


@pytest.mark.parametrize("profile", ["local", "release"])
def test_complete_runtime_fixture_passes(checkout, profile):
    assert _check(checkout, profile) is Status.PASS


@pytest.mark.parametrize("profile", ["local", "release"])
@pytest.mark.parametrize("name", RUNTIME_COMMANDS)
@pytest.mark.parametrize("damage", ["missing", "wrong_owner", "unguarded", "stub", "rebound", "conditional_shadow"])
def test_runtime_entry_damage_is_rejected(checkout, profile, name, damage):
    owner, definition, _doc = RUNTIME_COMMANDS[name]
    source = checkout / (owner.replace(".", "/") + ".py")
    launcher = checkout / f"bin/{name}.py"
    if damage == "missing":
        source.unlink()
    elif damage == "wrong_owner":
        launcher.write_text(launcher.read_text().replace(owner, "ladder_dragon.unreviewed"))
    elif damage == "unguarded":
        launcher.write_text(launcher.read_text() + "\nmain()\n")
    elif damage == "stub":
        tree = ast.parse(source.read_text())
        node = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == definition)
        node.body = ast.parse("return legacy()").body
        source.write_text(ast.unparse(tree))
    elif damage == "rebound":
        source.write_text(source.read_text() + "\nmain = lambda: None\n")
    else:
        source.write_text(source.read_text() + f"\nif debug_enabled:\n    {definition} = lambda: None\n")
    assert _check(checkout, profile) is (Status.BLOCKED if damage == "missing" else Status.FAILED)


@pytest.mark.parametrize("profile", ["local", "release"])
@pytest.mark.parametrize("damage", ["copied_state", "wrong_lifecycle", "eager_runtime", "discarded_return"])
def test_worker_lifetime_boundary_damage_is_rejected(checkout, profile, damage):
    path = checkout / "ladder_dragon/execution/worker/bootstrap.py"
    text = path.read_text()
    if damage == "copied_state":
        text = text.replace("vars(runtime)", "dict(vars(runtime))")
    elif damage == "wrong_lifecycle":
        text = text.replace("worker.lifecycle", "worker.unreviewed")
    elif damage == "eager_runtime":
        text += "\nfrom ladder_dragon.execution.worker import runtime\n"
    else:
        text = text.replace("return run_worker", "run_worker")
    path.write_text(text)
    assert _check(checkout, profile) is Status.FAILED


@pytest.mark.parametrize("profile", ["local", "release"])
@pytest.mark.parametrize("relative", INERT_PACKAGES)
def test_required_runtime_initializers_remain_inert(checkout, profile, relative):
    path = checkout / relative
    path.write_text(path.read_text() + "\nimport requests\n")
    assert _check(checkout, profile) is Status.FAILED


@pytest.mark.parametrize("name", RUNTIME_COMMANDS)
@pytest.mark.parametrize("executable", [False, True])
def test_runtime_launchers_preserve_dispatch_without_starting_runtime(monkeypatch, name, executable):
    owner = RUNTIME_COMMANDS[name][0]
    fake = ModuleType(owner)
    calls = []

    def main():
        calls.append(tuple(sys.argv[1:]))
        return 37

    fake.main = main
    monkeypatch.setitem(sys.modules, owner, fake)
    monkeypatch.setattr(sys, "argv", [name, "--synthetic"])
    path = ROOT / f"bin/{name}.py"
    if executable:
        with pytest.raises(SystemExit) as caught:
            runpy.run_path(str(path), run_name="__main__")
        assert caught.value.code == 37
        assert calls == [("--synthetic",)]
    else:
        runpy.run_path(str(path), run_name="import_probe")
        assert calls == []


LAZY_IMPORT_PROBE = '''
import importlib.abc, sys
class DenyRuntime(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname in {'ladder_dragon.execution.worker.runtime',
                        'ladder_dragon.execution.worker.lifecycle', 'requests', 'dotenv'}:
            raise AssertionError('eager runtime dependency')
sys.meta_path.insert(0, DenyRuntime())
import bin.autosize_universal
assert callable(bin.autosize_universal.main)
print('lazy-import-pass')
'''


def test_worker_import_is_lazy_in_fresh_dependency_free_python(tmp_path):
    result = subprocess.run([sys.executable, "-S", "-c", LAZY_IMPORT_PROBE], cwd=tmp_path,
                            env={"PATH": os.defpath, "PYTHONPATH": str(ROOT)},
                            capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "lazy-import-pass"


def test_real_bootstrap_passes_live_state_and_reloads_current_namespace(monkeypatch):
    from ladder_dragon.execution import worker
    from ladder_dragon.execution.worker import bootstrap, lifecycle
    states = []

    def run(state):
        states.append(state)
        return 17

    monkeypatch.setattr(lifecycle, "run_worker", run)
    for index in range(2):
        runtime = ModuleType("ladder_dragon.execution.worker.runtime")
        runtime.running = True
        runtime.transport = object()
        monkeypatch.setitem(sys.modules, runtime.__name__, runtime)
        monkeypatch.setattr(worker, "runtime", runtime, raising=False)
        assert bootstrap.main() == 17
        state = states[index]
        assert state.namespace() is vars(runtime)
        runtime.running = False
        assert state.running is False
        replacement = object()
        state.transport = replacement
        assert runtime.transport is replacement
    assert states[0].namespace() is not states[1].namespace()


def test_worker_bootstrap_does_not_hide_lifecycle_failure(monkeypatch):
    from ladder_dragon.execution import worker
    from ladder_dragon.execution.worker import bootstrap, lifecycle
    runtime = ModuleType("ladder_dragon.execution.worker.runtime")
    monkeypatch.setitem(sys.modules, runtime.__name__, runtime)
    monkeypatch.setattr(worker, "runtime", runtime, raising=False)

    def fail(state):
        raise RuntimeError("synthetic lifecycle failure")

    monkeypatch.setattr(lifecycle, "run_worker", fail)
    with pytest.raises(RuntimeError, match="synthetic lifecycle"):
        bootstrap.main()
