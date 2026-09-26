"""Entry commands retain startup boundaries and replay checkpoint ownership."""

import ast
from decimal import Decimal
import json
import os
from pathlib import Path
import subprocess
import sys
import hashlib
import runpy
from types import SimpleNamespace

import pytest

from tests.architecture.ast_contracts import extraction_digest
from tests.architecture.test_five_audit_extractions import checkout
from ladder_dragon.verification.architecture.command_ownership import ENTRY_COMMANDS
from ladder_dragon.verification.models import HarnessContext, HarnessOptions, Status
from ladder_dragon.verification.profiles import checks_for_profile
from ladder_dragon.verification.runner import HarnessRunner

ROOT = Path(__file__).resolve().parents[2]
DIGESTS = {
    "run_dashboard": "4435707317a9145e7b12c3f78714c26ee1a08f01a74df00d1ab7a63baefca6b4",
    "db_migrate": "f5bf7ed9a3863611d543359af1a6d1495613322d1f5a8f0177ad6195361e0108",
    "run_mainnet_validation_batch": "c2ae01b0597a5900771a020afec592c147e92e675f1d9f5fa014f9cd6c768c83",
    "replay_historical_entries": "291bf088f0139c501087ada037bd588ac343dd156cc16c8e4017ed5219a96fa6",
    "historical_replay_runner": "85b1a53fbf150d974a55a9be0088b1a0bfb0a262c9ca5c6e51356b984e6e2ede",
}


@pytest.mark.parametrize("name", ENTRY_COMMANDS)
def test_syntax_and_offline_parser(name, tmp_path):
    source = ROOT / (ENTRY_COMMANDS[name].replace(".", "/") + ".py")
    assert extraction_digest(ast.parse(source.read_text())) == DIGESTS[name]
    if name in {"run_dashboard", "db_migrate"}:
        return  # No help parser: these launchers require isolated adapters.
    result = subprocess.run([sys.executable, "-m", f"bin.{name}", "--help"], cwd=tmp_path,
        env={"PATH": os.defpath, "PYTHONPATH": str(ROOT), "PYTHON_DOTENV_DISABLED": "1"},
        capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr
    assert not list(tmp_path.iterdir())


@pytest.mark.parametrize("name", ENTRY_COMMANDS)
@pytest.mark.parametrize("profile", ["local", "release"])
@pytest.mark.parametrize("damage", ["launcher", "forwarder", "reverse", "missing"])
def test_required_check_rejects_entry_damage(checkout, name, profile, damage):
    source = checkout / (ENTRY_COMMANDS[name].replace(".", "/") + ".py")
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


def test_dashboard_loopback_and_absolute_source_path(monkeypatch):
    from ladder_dragon.dashboard import server_command as module
    application = object()
    calls = []
    monkeypatch.setitem(sys.modules, "app", SimpleNamespace(app=application))
    monkeypatch.setattr(sys, "path", list(sys.path))
    monkeypatch.setenv("DASHBOARD_PORT", "8087")
    monkeypatch.setattr(module.uvicorn, "run", lambda *args, **kwargs: calls.append((args, kwargs)))
    with pytest.raises(SystemExit) as exc:
        runpy.run_module("bin.run_dashboard", run_name="__main__")
    assert exc.value.code is None
    assert sys.path[0] == str(ROOT / "FastAPI/pi-dashboard")
    assert calls == [((application,), {"host": "127.0.0.1", "port": 8087, "proxy_headers": False})]


@pytest.mark.parametrize("fails", [False, True])
def test_migration_timing_does_not_hide_failure(fails, monkeypatch, capsys):
    from ladder_dragon.persistence import migration_command as module
    def migrate():
        if fails:
            raise RuntimeError("synthetic failure")
        return 7
    monkeypatch.setattr(module, "migrate_main", migrate)
    if fails:
        with pytest.raises(RuntimeError):
            module.main()
        assert capsys.readouterr().out == ""
    else:
        with pytest.raises(SystemExit) as exc:
            runpy.run_module("bin.db_migrate", run_name="__main__")
        assert exc.value.code == 7
        assert "[STARTUP-TIMING] phase=migration elapsed_ms=" in capsys.readouterr().out


def test_batch_cli_rejects_unconfirmed_execution(monkeypatch):
    from ladder_dragon.verification.live import batch_run_command as module
    def forbidden(*args, **kwargs):
        pytest.fail("unconfirmed batch reached execution")
    monkeypatch.setattr(module, "run_validation_batch", forbidden)
    monkeypatch.setattr(sys, "argv", ["batch", "--manifest", "synthetic", "--confirm", "NO"])
    with pytest.raises(SystemExit, match="--confirm must equal"):
        module.main()


@pytest.mark.parametrize("code,status", [(0, "COHORT_COMPLETE_NOT_REPLAY_READY"), (3, "INCOMPLETE"), (2, "FAILED")])
def test_batch_status_mapping_uses_only_fake_runner(code, status, monkeypatch, capsys):
    from ladder_dragon.verification.live import batch_run_command as module
    monkeypatch.setattr(module, "run_validation_batch", lambda *args, **kwargs: code)
    monkeypatch.setattr(sys, "argv", ["batch", "--manifest", "synthetic", "--confirm", "RUN_VALIDATION_BATCH"])
    assert module.main() == code
    assert json.loads(capsys.readouterr().out) == {"status": status}


def test_checkpoint_hashes_concrete_owner_and_preserves_old_state(tmp_path, monkeypatch):
    from ladder_dragon.strategy.prediction import replay_progress as module
    from tests.strategy.test_replay_progress import binding, report
    identities = module.implementation_identity()
    owner = ROOT / "ladder_dragon/strategy/prediction/replay_command.py"
    assert identities["replay_command.py"] == hashlib.sha256(owner.read_bytes()).hexdigest()
    with monkeypatch.context() as old:
        old.setattr(module, "implementation_identity", lambda: {"replay_historical_entries.py": "old"})
        checkpoint = module.PathCheckpoint(tmp_path, binding())
        checkpoint.write([report()])
        preserved = checkpoint.path.read_bytes()
    current = module.PathCheckpoint(tmp_path, binding())
    assert current.path != checkpoint.path
    assert current.read() is None
    assert checkpoint.path.read_bytes() == preserved


def test_replay_runner_imports_concrete_request_owner():
    from ladder_dragon.strategy.prediction import replay_command, replay_runner_command
    assert replay_runner_command.run_replay_request_batch is replay_command.run_replay_request_batch
