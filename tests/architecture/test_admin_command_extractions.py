"""Administrative entry points retain guards, paths, and caller ownership."""

import ast
import json
import os
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

import pytest

from tests.architecture.ast_contracts import extraction_digest
from tests.architecture.test_five_audit_extractions import checkout
from ladder_dragon.verification.architecture.command_ownership import ADMIN_COMMANDS
from ladder_dragon.verification.models import HarnessContext, HarnessOptions, Status
from ladder_dragon.verification.profiles import checks_for_profile
from ladder_dragon.verification.runner import HarnessRunner

ROOT = Path(__file__).resolve().parents[2]
DIGESTS = {
    "risk_ctl": "c97ad72092548fef85ef52f9752afdc93267b2976fcce79e6cca58281dc81678",
    "review_unattributed_fills": "7cd184ba48c34475e9b03576e4a11c45799afe80938f66d06b55d0b505f8f94c",
    "database_retention": "594d06c59fc2de09fef04e60a00e37ec3fbaa67f283a16820b5b25107879b15c",
    "check_technical_english": "85ba13cd577da3d9152e15a9eb2a88dbc48280f646d57969a40077ebc10247ee",
    "semgrep_scan": "ff74ce9d98c8ab29f79d8340653ea9af331ad013f5524790499179da315f913d",
}


@pytest.mark.parametrize("name", ADMIN_COMMANDS)
def test_original_syntax_and_offline_command(name, tmp_path):
    source = ROOT / (ADMIN_COMMANDS[name].replace(".", "/") + ".py")
    assert extraction_digest(ast.parse(source.read_text())) == DIGESTS[name]
    # English has no parser; execute its real read-only check against the checkout.
    args = [] if name == "check_technical_english" else ["--help"]
    result = subprocess.run([sys.executable, "-m", f"bin.{name}", *args], cwd=tmp_path,
        env={"PATH": os.defpath, "PYTHONPATH": str(ROOT), "PYTHON_DOTENV_DISABLED": "1"},
        capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr + result.stdout
    assert not list(tmp_path.iterdir())


@pytest.mark.parametrize("name", ADMIN_COMMANDS)
@pytest.mark.parametrize("profile", ["local", "release"])
@pytest.mark.parametrize("damage", ["launcher", "forwarder", "reverse", "missing"])
def test_required_check_rejects_admin_regression(checkout, name, profile, damage):
    source = checkout / (ADMIN_COMMANDS[name].replace(".", "/") + ".py")
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


@pytest.mark.parametrize("command", ["status", "reset"])
@pytest.mark.parametrize("testnet", [False, True])
def test_risk_command_keeps_mode_before_limits_and_reset_scope(command, testnet, tmp_path, monkeypatch, capsys):
    from ladder_dragon.risk import control_command as module
    calls = []
    limits = SimpleNamespace(halt_file=tmp_path / "halt.json", state_file=tmp_path / "state.json")
    limits.halt_file.write_text(json.dumps({"reason": "synthetic"}))
    before = limits.halt_file.read_bytes()
    monkeypatch.setattr(module, "load_dotenv", lambda: calls.append("dotenv"))
    monkeypatch.setattr(module, "apply_testnet_paths", lambda: calls.append("testnet"))
    def from_env():
        assert calls == (["dotenv", "testnet"] if testnet else ["dotenv"])
        calls.append("limits")
        return limits
    monkeypatch.setattr(module, "RiskLimits", SimpleNamespace(from_env=from_env))
    class Manager:
        def __init__(self, actual):
            assert actual is limits
            calls.append("manager")
        def reset(self, *, force):
            assert command == "reset" and force is True
            calls.append("reset")
    monkeypatch.setattr(module, "RiskManager", Manager)
    monkeypatch.setattr(sys, "argv", ["risk", command, "--force", *(["--testnet"] if testnet else [])])
    assert module.main() == 0
    output = capsys.readouterr().out
    assert ("reset" in calls) is (command == "reset")
    if command == "status":
        assert json.loads(output)["halted"] is True
    assert limits.halt_file.read_bytes() == before
    assert not limits.state_file.exists()


@pytest.mark.parametrize("failed", [False, True])
def test_english_resolves_checkout_and_preserves_failure(failed, monkeypatch, capsys):
    from ladder_dragon.verification import english_command as module
    def check(root):
        assert root == ROOT
        return [SimpleNamespace(format=lambda: "synthetic issue")] if failed else []
    monkeypatch.setattr(module, "check_documents", check)
    assert module.main() == (1 if failed else 0)
    assert ("FAILED" if failed else "PASS") in capsys.readouterr().out


def test_semgrep_paths_still_select_checkout_toolchain():
    from ladder_dragon.verification import semgrep_command as module
    assert module.PROJECT_ROOT == ROOT
    assert module.SEMGREP_BIN == ROOT / ".semgrep-venv/bin/semgrep"
    assert module.RULE_CONFIG == ROOT / ".semgrep/ladder-dragon.yml"
