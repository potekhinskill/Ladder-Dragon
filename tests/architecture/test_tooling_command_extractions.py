"""Tooling commands retain executable interfaces, provenance, and child paths."""

import ast
from decimal import Decimal
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from tests.architecture.ast_contracts import extraction_digest
from tests.architecture.test_five_audit_extractions import checkout
from ladder_dragon.verification.architecture.command_ownership import TOOLING_COMMANDS
from ladder_dragon.verification.models import HarnessContext, HarnessOptions, Status
from ladder_dragon.verification.profiles import checks_for_profile
from ladder_dragon.verification.runner import HarnessRunner

ROOT = Path(__file__).resolve().parents[2]
DIGESTS = {
    "record_bnb_public": "915002d69161f7ae87ce52892e640ceed02d8468a9e7820553ce334576175e12",
    "verify_bnb_fills": "fbbf4d9580e1eda33a0f26b83b887efb742b4f2cc135cdf61293fe186d862dae",
    "prediction_history_backfill": "285e3731df8ef40dbc5cd23dde2cebf682e130d3304b180c52bd92bb92fc36d6",
    "update_vwap_env": "2774bb4346d853aade0f3494212cc33f83aa3ba64db69cdc149abcb44bf33897",
    "generate_star_history": "a1709d55ce3d49b2d4005f92706336d8f51a5117fbf9716d19e3b7a060ac8fe2",
}


@pytest.mark.parametrize("name", TOOLING_COMMANDS)
def test_syntax_and_offline_parser(name, tmp_path):
    source = ROOT / (TOOLING_COMMANDS[name].replace(".", "/") + ".py")
    assert extraction_digest(ast.parse(source.read_text())) == DIGESTS[name]
    result = subprocess.run([sys.executable, "-m", f"bin.{name}", "--help"], cwd=tmp_path,
        env={"PATH": os.defpath, "PYTHONPATH": str(ROOT), "PYTHON_DOTENV_DISABLED": "1"},
        capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr
    assert not list(tmp_path.iterdir())


@pytest.mark.parametrize("name", TOOLING_COMMANDS)
@pytest.mark.parametrize("profile", ["local", "release"])
@pytest.mark.parametrize("damage", ["launcher", "forwarder", "reverse", "missing"])
def test_required_check_rejects_tooling_damage(checkout, name, profile, damage):
    source = checkout / (TOOLING_COMMANDS[name].replace(".", "/") + ".py")
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


@pytest.mark.parametrize("fails", [False, True])
def test_vwap_child_paths_append_and_no_write_on_failure(fails, tmp_path, monkeypatch):
    from ladder_dragon.strategy import vwap_update_command as module
    for key in list(os.environ):
        if key.startswith("VWAP_AUTOTUNE"):
            monkeypatch.delenv(key)
    output = tmp_path / "synthetic-output.txt"
    output.write_text("EXISTING=1\n")
    commands = []
    def run(command, **kwargs):
        commands.append(command)
        assert command[0] == sys.executable
        assert Path(command[1]).parent == ROOT / "bin" and Path(command[1]).is_file()
        if fails:
            raise subprocess.CalledProcessError(2, command)
        return " SYNTHETIC=1\n\n"
    monkeypatch.setattr(module.subprocess, "check_output", run)
    monkeypatch.setattr(sys, "argv", ["vwap", "--symbols", "SOLUSDT", "--out", str(output), "--with-autotune"])
    if fails:
        with pytest.raises(subprocess.CalledProcessError):
            module.main()
        assert output.read_text() == "EXISTING=1\n"
    else:
        assert module.main() is None
        assert [Path(c[1]).name for c in commands] == ["gen_vwap_env.py", "gen_vwap_autotune.py"]
        assert output.read_text() == "EXISTING=1\nSYNTHETIC=1\nSYNTHETIC=1\n"


def test_history_preserves_exact_bars_and_observation_times(tmp_path):
    from ladder_dragon.strategy.prediction import history_command as module
    path = tmp_path / "synthetic.jsonl"
    path.write_text(json.dumps({"symbol": "solusdt", "kline": [0, "1.01", "1.04", "1.00", "1.02", "2.3", 59999],
        "funding_rate": "0.000001", "funding_time_ms": 60001}) + "\n")
    bars, auxiliary = module._load(path)
    assert bars["SOLUSDT"][0].close == Decimal("1.02")
    assert auxiliary["SOLUSDT"].funding[0].timestamp_ms == 60001
    assert module._json_value({"price": Decimal("1.0200")}) == {"price": "1.0200"}
