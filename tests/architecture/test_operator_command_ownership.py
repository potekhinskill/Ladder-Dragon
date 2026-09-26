"""Enforce existing operator owners without starting workers or mutating exchange state."""

import ast
import os
from pathlib import Path
import runpy
import subprocess
import sys
from types import ModuleType

import pytest

from ladder_dragon.verification.architecture.command_ownership import OPERATOR_COMMANDS
from ladder_dragon.verification.models import Status
from tests.architecture.ast_contracts import extraction_digest
from tests.architecture.test_digest_extractions import _check
from tests.architecture.test_five_audit_extractions import checkout

ROOT = Path(__file__).resolve().parents[2]
# Existing implementation syntax captured before adding these ownership gates.
DIGESTS = {'ai_plan_runner': 'f95832248a44c429a158e66a7c11335e5d888671fca78f2f6d7811fe44bfc6d4',
 'tools_cancel_open': '43d34fc49100cfa76d9832520a466758798698c8749d69d48745bbfb1d4772f8',
 'monthly_prediction_report': 'c0d4176f87713b86e2e9b1ae7daa3b1dc90854d10782fe256a1ac562bc784737',
 'validate_replay_sessions': 'b3aa97cd6aef86c3134e36d6a1d8747f5eb1253d824db93a9b3bc6c8e6274e4f',
 'mainnet_validation_batch': 'd12eb8e1f6363b09274bd4c424265e1758989e4dc71c7173332685fc6bccd361'}


@pytest.mark.parametrize("name", OPERATOR_COMMANDS)
def test_operator_implementations_are_unchanged(name):
    owner = OPERATOR_COMMANDS[name][0]
    source = ROOT / (owner.replace(".", "/") + ".py")
    assert extraction_digest(ast.parse(source.read_text())) == DIGESTS[name]


@pytest.mark.parametrize("profile", ["local", "release"])
def test_complete_operator_ownership_fixture_passes(checkout, profile):
    assert _check(checkout, profile) is Status.PASS


@pytest.mark.parametrize("profile", ["local", "release"])
@pytest.mark.parametrize("name", OPERATOR_COMMANDS)
@pytest.mark.parametrize("damage", [
    "wrong_owner", "unguarded_call", "main_forwarder", "workflow_forwarder",
    "reverse_import", "missing_owner", "invalid_source", "docstring_decoy",
])
def test_required_harness_rejects_operator_ownership_damage(checkout, profile, name, damage):
    owner, workflow, _doc = OPERATOR_COMMANDS[name]
    source = checkout / (owner.replace(".", "/") + ".py")
    launcher = checkout / f"bin/{name}.py"
    if damage == "wrong_owner":
        launcher.write_text(launcher.read_text().replace(owner, "ladder_dragon.unreviewed"))
    elif damage == "unguarded_call":
        launcher.write_text(launcher.read_text() + "\nmain()\n")
    elif damage == "docstring_decoy":
        tree = ast.parse(launcher.read_text())
        tree.body.insert(0, ast.parse("ignored()").body[0])
        launcher.write_text(ast.unparse(tree))
    elif damage in {"main_forwarder", "workflow_forwarder"}:
        tree = ast.parse(source.read_text())
        target = "main" if damage == "main_forwarder" else workflow
        function = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == target)
        function.body = ast.parse("return legacy()").body
        source.write_text(ast.unparse(tree))
    elif damage == "reverse_import":
        source.write_text(source.read_text() + f"\nfrom bin.{name} import main as legacy\n")
    elif damage == "invalid_source":
        source.write_text("def main(:\n")
    else:
        source.unlink()
    expected = Status.BLOCKED if damage in {"missing_owner", "invalid_source"} else Status.FAILED
    assert _check(checkout, profile) is expected


@pytest.mark.parametrize("name", OPERATOR_COMMANDS)
@pytest.mark.parametrize("executable", [False, True])
def test_launcher_dispatch_is_inert_on_import_and_preserves_exit(monkeypatch, name, executable):
    module_name = OPERATOR_COMMANDS[name][0]
    fake = ModuleType(module_name)
    calls = []

    def main():
        calls.append(tuple(sys.argv))
        return 37

    fake.main = main
    monkeypatch.setitem(sys.modules, module_name, fake)
    monkeypatch.setattr(sys, "argv", [name, "--synthetic-argument"])
    path = ROOT / f"bin/{name}.py"
    if executable:
        with pytest.raises(SystemExit) as error:
            runpy.run_path(str(path), run_name="__main__")
        assert error.value.code == 37
        assert len(calls) == 1
        assert calls[0][1:] == ("--synthetic-argument",)
    else:
        runpy.run_path(str(path), run_name="import_probe")
        assert calls == []


# Also used for installed-wheel checks; never permits a network connection.
OFFLINE_CLI = """
import runpy, socket, sys
def denied(*args, **kwargs):
    raise AssertionError('network use in offline CLI check')
socket.socket.connect = denied
socket.socket.connect_ex = denied
socket.create_connection = denied
socket.getaddrinfo = denied
module = sys.argv.pop(1)
runpy.run_module(module, run_name='__main__')
"""


@pytest.mark.parametrize("name", OPERATOR_COMMANDS)
@pytest.mark.parametrize("arguments,exit_code", [(('--help',), 0), (('--symbol', 'bad!'), 2)])
def test_real_cli_help_and_invalid_input_remain_offline(tmp_path, name, arguments, exit_code):
    result = subprocess.run(
        [sys.executable, "-c", OFFLINE_CLI, f"bin.{name}", *arguments],
        cwd=tmp_path,
        env={"PATH": os.defpath, "PYTHONPATH": str(ROOT),
             "PYTHON_DOTENV_DISABLED": "1", "PYTHONDONTWRITEBYTECODE": "1"},
        capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == exit_code, result.stderr
    assert list(tmp_path.iterdir()) == []
