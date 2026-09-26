"""Close ownership gaps without executing exchange qualification drills."""

import ast
import os
from pathlib import Path
import runpy
import subprocess
import sys
from types import ModuleType

import pytest

from ladder_dragon.verification.architecture.command_ownership import LIVE_COMMANDS
from ladder_dragon.verification.models import Status
from tests.architecture.ast_contracts import extraction_digest
from tests.architecture.test_digest_extractions import _check
from tests.architecture.test_five_audit_extractions import checkout

ROOT = Path(__file__).resolve().parents[2]
# Existing implementation syntax captured before adding these ownership gates.
DIGESTS = {
    "binance_testnet_smoke": "e85a5d66ca095e87c8a60a85900bbad97f4e8e373977cc7135153ee736c62bbc",
    "binance_mainnet_canary": "bf470dcf9d49498cd72f192b81f5b63c72b14d28d8f6566483b2cc8f519682ec",
    "mainnet_limit_maker_validation": "f81c27ae41bf2a1bc568e712ec73ac7f313130b449a8d8d1d6d446647bc0dbb6",
    "mainnet_stop_limit_validation": "41305ad8ed41151ba7853b23441c326571d0df96c05218971f3dc6def3570b7a",
    "mainnet_user_stream_drill": "4b2148407e424d9921819b275acf6cd3526201d491820f823651112db3eee432",
}


@pytest.mark.parametrize("name", LIVE_COMMANDS)
def test_live_implementations_are_unchanged(name):
    owner = LIVE_COMMANDS[name][0]
    source = ROOT / f"ladder_dragon/verification/live/{owner}.py"
    assert extraction_digest(ast.parse(source.read_text())) == DIGESTS[name]


@pytest.mark.parametrize("profile", ["local", "release"])
def test_complete_live_ownership_fixture_passes(checkout, profile):
    assert _check(checkout, profile) is Status.PASS


@pytest.mark.parametrize("profile", ["local", "release"])
@pytest.mark.parametrize("name", LIVE_COMMANDS)
@pytest.mark.parametrize("damage", [
    "wrong_owner", "unguarded_call", "main_forwarder", "workflow_forwarder",
    "reverse_import", "missing_owner", "invalid_source", "docstring_decoy",
])
def test_required_harness_rejects_live_ownership_damage(checkout, profile, name, damage):
    owner, workflow, _doc = LIVE_COMMANDS[name]
    source = checkout / f"ladder_dragon/verification/live/{owner}.py"
    launcher = checkout / f"bin/{name}.py"
    if damage == "wrong_owner":
        launcher.write_text(launcher.read_text().replace(f"live.{owner}", "live.unreviewed"))
    elif damage == "unguarded_call":
        launcher.write_text(launcher.read_text() + "\nmain()\n")
    elif damage == "docstring_decoy":
        launcher.write_text(launcher.read_text().replace(repr(_doc), "ignored()")
                            if repr(_doc) in launcher.read_text()
                            else launcher.read_text().replace(f'"""{_doc}"""', "ignored()"))
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


@pytest.mark.parametrize("name", LIVE_COMMANDS)
@pytest.mark.parametrize("executable", [False, True])
def test_launcher_dispatch_is_inert_on_import_and_preserves_exit(monkeypatch, name, executable):
    module_name = f"ladder_dragon.verification.live.{LIVE_COMMANDS[name][0]}"
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


@pytest.mark.parametrize("name", LIVE_COMMANDS)
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
