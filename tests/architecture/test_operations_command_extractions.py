"""Operational commands preserve authority, error boundaries, and executable interfaces."""

import ast
from decimal import Decimal
import json
import os
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

import pytest

from tests.architecture.ast_contracts import extraction_digest
from tests.architecture.test_five_audit_extractions import checkout
from ladder_dragon.verification.architecture.command_ownership import OPERATIONS_COMMANDS
from ladder_dragon.verification.models import HarnessContext, HarnessOptions, Status
from ladder_dragon.verification.profiles import checks_for_profile
from ladder_dragon.verification.runner import HarnessRunner

ROOT = Path(__file__).resolve().parents[2]
DIGESTS = {
    "ai_advisor_smoke": "33b02f914c0ae116b28fcea4371083a8e57dca7df71e297a4c8780f641436c01",
    "gen_vwap_env": "a428cb0d55fdac01e0536e17ca32517cc8868bd39356fd58a5c287f38297b3b9",
    "depth_archive_retention": "e0fe8d53991e73d234a31c328fc1bb7b4b1eccbb4af9ce93e4db9b7f00cc3160",
    "mainnet_validation_archive_retention": "e2a686f98b3047384a9df676e9d72f99f5b82c595ad81a9d91071a57b1fe927b",
    "ip_guard": "2d455954c7c15d0a309e9227efc9f762f0bca0934aedc3d5a76662f6ddc81648",
}


@pytest.mark.parametrize("name", OPERATIONS_COMMANDS)
def test_syntax_and_offline_parser(name, tmp_path):
    source = ROOT / (OPERATIONS_COMMANDS[name].replace(".", "/") + ".py")
    assert extraction_digest(ast.parse(source.read_text())) == DIGESTS[name]
    result = subprocess.run([sys.executable, "-m", f"bin.{name}", "--help"], cwd=tmp_path,
        env={"PATH": os.defpath, "PYTHONPATH": str(ROOT), "PYTHON_DOTENV_DISABLED": "1"},
        capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr
    assert not list(tmp_path.iterdir())


@pytest.mark.parametrize("name", OPERATIONS_COMMANDS)
@pytest.mark.parametrize("profile", ["local", "release"])
@pytest.mark.parametrize("damage", ["launcher", "forwarder", "reverse", "missing"])
def test_required_check_rejects_operations_damage(checkout, name, profile, damage):
    source = checkout / (OPERATIONS_COMMANDS[name].replace(".", "/") + ".py")
    if damage == "launcher":
        path = checkout / f"bin/{name}.py"
        path.write_text(path.read_text() + "\ndef misplaced(): return 1\n")
    elif damage == "forwarder":
        source.write_text("def main():\n    return legacy()\n")
    elif damage == "reverse":
        source.write_text(source.read_text() + f"\nfrom bin.{name} import main as legacy\n")
    else:
        source.unlink()
    context = HarnessContext(root=checkout, python=sys.executable, options=HarnessOptions(
        profile=profile, output=checkout / "report.json"))
    check, = [c for c in checks_for_profile(context) if c.name == "architecture_command_ownership"]
    assert check.required
    assert HarnessRunner(context)._run_spec(check).status is (
        Status.BLOCKED if damage == "missing" else Status.FAILED)


@pytest.mark.parametrize("profile", ["local", "release"])
def test_ip_error_wrapper_cannot_disappear(checkout, profile):
    source = checkout / "ladder_dragon/execution/ip_guard_command.py"
    source.write_text(source.read_text().split("def cli()", 1)[0])
    context = HarnessContext(root=checkout, python=sys.executable, options=HarnessOptions(
        profile=profile, output=checkout / "report.json"))
    check, = [c for c in checks_for_profile(context) if c.name == "architecture_command_ownership"]
    assert HarnessRunner(context)._run_spec(check).status is Status.FAILED


@pytest.mark.parametrize("error", [OSError, RuntimeError, ValueError])
def test_ip_error_boundary_redacts_provider_message(error, monkeypatch, capsys):
    from ladder_dragon.execution import ip_guard_command as module
    def fail():
        raise error("synthetic-sensitive-provider-message")
    monkeypatch.setattr(module, "main", fail)
    with pytest.raises(SystemExit) as exc:
        module.cli()
    assert exc.value.code == 1
    result = capsys.readouterr()
    assert result.out == ""
    assert result.err == f"IP_GUARD error_type={error.__name__}\n"


def test_ip_cli_consensus_failure_does_not_write(tmp_path):
    target = tmp_path / "must-not-exist.json"
    result = subprocess.run([sys.executable, "-m", "bin.ip_guard", "accept-current"],
        cwd=tmp_path, env={"PATH": os.defpath, "PYTHONPATH": str(ROOT),
            "PYTHON_DOTENV_DISABLED": "1", "BINANCE_AUTH_STATE_FILE": str(target)},
        capture_output=True, text=True, timeout=30)
    assert result.returncode == 1
    assert result.stderr == "IP_GUARD error_type=RuntimeError\n"
    assert not target.exists()


@pytest.mark.parametrize("missing", [False, True])
def test_advisor_smoke_uses_only_synthetic_advisor(missing, monkeypatch, capsys):
    from ladder_dragon.ai import smoke_command as module
    class Advisor:
        def __init__(self, *args, **kwargs):
            pass
        def recommend(self, scenario):
            return None if missing else SimpleNamespace(
                cap_scale=1, confidence=1, mode="FLAT", ladder_width_scale=1)
    monkeypatch.setattr(module, "AIAdvisor", Advisor)
    monkeypatch.setattr(module.requests, "Session", lambda: object())
    monkeypatch.setattr(sys, "argv", ["smoke"])
    assert module.main() == int(missing)
    output = capsys.readouterr().out
    assert "binance_calls=0 orders=0" in output
    assert f"failed={4 if missing else 0}" in output


def test_retention_confirmation_blocks_before_archive(tmp_path, monkeypatch, capsys):
    from ladder_dragon.verification.live import archive_retention_command as module
    monkeypatch.setattr(module, "rejected_batch_archives", lambda *args, **kwargs: ({}, []))
    def unexpected(*args, **kwargs):
        pytest.fail("unconfirmed archival reached the writer")
    monkeypatch.setattr(module, "archive_rejected_batch", unexpected)
    args = ["--manifest", "synthetic", "--directory", str(tmp_path),
            "--external-directory", str(tmp_path), "--backup-status", "synthetic", "--apply"]
    assert module.main(args) == 2
    assert json.loads(capsys.readouterr().out) == {"status": "BLOCKED", "cause_type": "ValueError"}
    assert not list(tmp_path.iterdir())
