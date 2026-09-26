"""Interpreter-first bootstrap and concrete verification component parity."""

import ast
import copy
import os
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

import pytest

from ladder_dragon import harness_bootstrap as bootstrap
from ladder_dragon.verification import harness_identity as identity
from ladder_dragon.verification.harness_options import prepare_options
from ladder_dragon.verification.harness_parser import build_parser
from ladder_dragon.verification.architecture.harness_ownership import HARNESS_OWNERS, HARNESS_LINKS
from ladder_dragon.verification.models import Status
from tests.architecture.ast_contracts import extraction_digest
from tests.architecture.test_digest_extractions import _check
from tests.architecture.test_five_audit_extractions import checkout

ROOT = Path(__file__).resolve().parents[2]
# Captured from the original launcher before relocation.
DIGESTS = {
    "_project_venv_python": "f6f0dc4735fd7467a87eed76790203c882a5064059bea84d4e8c15480ebeb24a",
    "_reexec_project_venv_if_needed": "9beb606a50f779cf29f765d0d28ef39c4c50b8da73d0ef96a7e28ff2c9334ec4",
    "_commit_sha": "f094e2edfc69a0e97b97aa0ae9e60a9190236f0c09397af74c2da05f76a03bad",
    "build_parser": "58860c9a3b688550904c3f78440d328748c84ce0e310e7b1c70163c687a12e08",
    "main": "9a8157244462b77fc11447ec9d30092a880c7f7cf57220b9ea2b916477f591b6",
}


def source(owner, root=ROOT):
    return root / (owner.replace(".", "/") + ".py")


@pytest.mark.parametrize("name", DIGESTS)
def test_pre_move_function_syntax_survives_recomposition(name):
    nodes = {n.name: n for owner in HARNESS_OWNERS
             for n in ast.parse(source(owner).read_text()).body if isinstance(n, ast.FunctionDef)}
    node = copy.deepcopy(nodes[name])
    if name == "_reexec_project_venv_if_needed":
        node.body[0].value.value = node.body[0].value.value.replace(
            "before verification imports.", "before project imports.")
    if name == "main":
        assert ast.dump(node.body[1]) == ast.dump(ast.parse("options = prepare_options(args)").body[0])
        node.body[1:2] = copy.deepcopy(nodes["prepare_options"].body[:-1])
        write = next(n for n in node.body if isinstance(n, ast.Expr) and isinstance(n.value, ast.Call)
                     and isinstance(n.value.func, ast.Name) and n.value.func.id == "write_report")
        assert ast.dump(write.value.args[0]) == ast.dump(ast.parse("options.output", mode="eval").body)
        write.value.args[0] = ast.Name(id="output", ctx=ast.Load())
    assert extraction_digest(ast.Module(body=[node], type_ignores=[])) == DIGESTS[name]


@pytest.mark.parametrize("profile", ["local", "release"])
def test_complete_harness_fixture_passes(checkout, profile):
    assert _check(checkout, profile) is Status.PASS


@pytest.mark.parametrize("profile", ["local", "release"])
@pytest.mark.parametrize("owner", HARNESS_OWNERS)
@pytest.mark.parametrize("damage", ["missing", "forwarder", "reverse_import"])
def test_required_harness_rejects_component_damage(checkout, profile, owner, damage):
    path = source(owner, checkout)
    if damage == "missing":
        path.unlink()
    elif damage == "reverse_import":
        path.write_text(path.read_text() + "\nfrom bin.verification_harness import main\n")
    else:
        tree = ast.parse(path.read_text())
        target = next(n for n in tree.body if isinstance(n, ast.FunctionDef)
                      and n.name == HARNESS_OWNERS[owner][0])
        target.body = ast.parse("return legacy()").body
        path.write_text(ast.unparse(tree))
    assert _check(checkout, profile) is (Status.BLOCKED if damage == "missing" else Status.FAILED)


@pytest.mark.parametrize("profile", ["local", "release"])
@pytest.mark.parametrize("owner,dependency", [(o, d) for o, links in HARNESS_LINKS.items() for d in links])
def test_required_harness_rejects_detached_import(checkout, profile, owner, dependency):
    path = source(owner, checkout)
    path.write_text(path.read_text().replace(f"from {dependency} import", "from unreviewed import"))
    assert _check(checkout, profile) is Status.FAILED


@pytest.mark.parametrize("profile", ["local", "release"])
@pytest.mark.parametrize("damage", ["early_dependency", "no_bootstrap", "bootstrap_dependency", "initializer", "root"])
def test_required_harness_rejects_bootstrap_boundary_damage(checkout, profile, damage):
    launcher = checkout / "bin/verification_harness.py"
    boot = checkout / "ladder_dragon/harness_bootstrap.py"
    if damage == "early_dependency":
        launcher.write_text("from ladder_dragon.verification.harness_command import main\n" + launcher.read_text())
    elif damage == "no_bootstrap":
        launcher.write_text(launcher.read_text().replace("    _reexec_project_venv_if_needed()", "    pass"))
    elif damage == "bootstrap_dependency":
        boot.write_text(boot.read_text() + "\nimport requests\n")
    elif damage == "initializer":
        path = checkout / "ladder_dragon/__init__.py"
        path.write_text(path.read_text() + "\nimport requests\n")
    else:
        boot.write_text(boot.read_text().replace("parents[1]", "parents[2]"))
    assert _check(checkout, profile) is Status.FAILED


def test_bootstrap_precedes_dependency_imports_in_fresh_python(tmp_path):
    candidate = tmp_path / ".venv/bin/python"
    candidate.parent.mkdir(parents=True)
    candidate.touch()
    probe = '''
import importlib.abc, pathlib, runpy, sys
class BlockVerification(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.startswith('ladder_dragon.verification'):
            raise AssertionError('verification imported before reexec')
sys.meta_path.insert(0, BlockVerification())
from ladder_dragon import harness_bootstrap as bootstrap
class Reexecuted(Exception): pass
def execute(path, argv, environment):
    assert argv[1:3] == ['-m', 'bin.verification_harness']
    assert environment[bootstrap._VENV_REEXEC_MARKER] == '1'
    raise Reexecuted()
root = pathlib.Path(sys.argv[1])
bootstrap._reexec_project_venv_if_needed.__kwdefaults__.update(
    project_root=root, prefix=root / 'host', environ={}, execve_fn=execute)
try:
    runpy.run_module('bin.verification_harness', run_name='__main__')
except Reexecuted:
    print('bootstrap-first')
else:
    raise AssertionError('reexec was not reached')
'''
    result = subprocess.run([sys.executable, "-S", "-c", probe, str(tmp_path)], cwd=tmp_path,
                            env={"PATH": os.defpath, "PYTHONPATH": str(ROOT)},
                            capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "bootstrap-first"


def test_bootstrap_exec_failure_is_closed(tmp_path):
    candidate = tmp_path / ".venv/bin/python"
    candidate.parent.mkdir(parents=True)
    candidate.touch()

    def denied(*args):
        raise OSError("synthetic")

    with pytest.raises(SystemExit, match="cannot execute"):
        bootstrap._reexec_project_venv_if_needed(project_root=tmp_path, prefix=tmp_path / "host",
                                                environ={}, execve_fn=denied)


@pytest.mark.parametrize("value,expected", [("A" * 40, "a" * 40), ("bad", "0" * 40), ("", "0" * 40)])
def test_identity_preserves_normalization_and_invalid_fallback(monkeypatch, value, expected):
    monkeypatch.setattr(identity.subprocess, "run", lambda *a, **k: SimpleNamespace(stdout=value))
    assert identity._commit_sha() == expected


def test_identity_unavailable_remains_zero(monkeypatch):
    def unavailable(*args, **kwargs):
        raise OSError("synthetic")
    monkeypatch.setattr(identity.subprocess, "run", unavailable)
    assert identity._commit_sha() == "0" * 40


def test_options_preserve_explicit_permissions_and_normalized_defaults():
    args = build_parser().parse_args(["--profile", " LOCAL ", "--symbol", " ethusdt ",
        "--confirm-mainnet-canary", "--confirm-testnet-mutation", "--confirm-authenticated-testnet",
        "--source", "first.json", "--source", "second.json"])
    options = prepare_options(args)
    assert options.profile == "local" and options.symbol == "ETHUSDT"
    assert options.output == Path(".runtime/verification-local.json")
    assert options.user_stream_status.name == "user_stream_ETHUSDT.json"
    assert options.source_paths == (Path("first.json"), Path("second.json"))
    assert options.confirm_mainnet_canary and options.confirm_testnet_mutation and options.confirm_authenticated_testnet


def test_invalid_profile_is_sanitized_before_default_path():
    options = prepare_options(build_parser().parse_args(["--profile", "../../unsafe"]))
    assert options.profile == "invalid"
    assert options.output == Path(".runtime/verification-invalid.json")
    assert not options.confirm_mainnet_canary and not options.confirm_testnet_mutation


def test_invalid_symbol_fails_before_execution():
    with pytest.raises(SystemExit, match="valid uppercase"):
        prepare_options(build_parser().parse_args(["--profile", "local", "--symbol", "bad!"]))
