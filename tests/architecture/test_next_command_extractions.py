"""Second P2 slice: implementation identity, executable parity, and rejection."""

import ast
import importlib
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from tests.architecture.ast_contracts import extraction_digest
from tests.architecture.test_five_audit_extractions import checkout
from ladder_dragon.verification.architecture.command_ownership import NEXT_COMMANDS
from ladder_dragon.verification.models import HarnessContext, HarnessOptions, Status
from ladder_dragon.verification.profiles import checks_for_profile
from ladder_dragon.verification.runner import HarnessRunner

ROOT = Path(__file__).resolve().parents[2]
DIGESTS = {
    "audit_legacy_compatibility": "92a5a19f14a7d4d7916cc3ffbf8916cb4856b41efd4fb369311ff0f5fef387f5",
    "audit_user_stream_soak": "771ab521ce1dcdd554d40c6de2f4180d70d0b5fbc93dee5910c1d1cde1fab942",
    "calibrate_replay": "0032b29ffc5afcf41a9de092b522b3cbab3fbbe7e398492d4409e0a18afebfe4",
    "validate_replay_outcomes": "e3935df9e75e6e2f5c02be1964a61c268f7e5ebf5574062fcef698c2d586a1d2",
    "maintenance_state": "64aa60106c4aae52632c736a3bba624785928f45e40966b477e03fa3fe077c87",
}


def cli(name, tmp_path, *args):
    return subprocess.run(
        [sys.executable, "-m", f"bin.{name}", *map(str, args)], cwd=tmp_path,
        env={"PATH": os.defpath, "PYTHONPATH": str(ROOT), "PYTHON_DOTENV_DISABLED": "1"},
        capture_output=True, text=True, timeout=30,
    )


@pytest.mark.parametrize("name", NEXT_COMMANDS)
def test_implementation_and_offline_parser(name, tmp_path):
    source = ROOT / (NEXT_COMMANDS[name].replace(".", "/") + ".py")
    assert extraction_digest(ast.parse(source.read_text())) == DIGESTS[name]
    assert cli(name, tmp_path, "--help").returncode == 0
    assert cli(name, tmp_path).returncode == 2
    assert not list(tmp_path.iterdir())


@pytest.mark.parametrize("name", NEXT_COMMANDS)
@pytest.mark.parametrize("profile", ["local", "release"])
@pytest.mark.parametrize("damage", ["launcher", "forwarder", "reverse", "missing"])
def test_required_check_rejects_regressions(name, profile, damage, checkout):
    tmp_path = checkout
    source = tmp_path / (NEXT_COMMANDS[name].replace(".", "/") + ".py")
    if damage == "launcher":
        launcher = tmp_path / f"bin/{name}.py"
        launcher.write_text(launcher.read_text() + "\ndef hidden_logic(): return 1\n")
    elif damage == "forwarder":
        source.write_text("def main():\n    return legacy()\n")
    elif damage == "reverse":
        source.write_text(source.read_text() + f"\nfrom bin.{name} import main as legacy\n")
    else:
        source.unlink()
    context = HarnessContext(root=tmp_path, python=sys.executable, options=HarnessOptions(
        profile=profile, output=tmp_path / "report.json"))
    check, = [c for c in checks_for_profile(context) if c.name == "architecture_command_ownership"]
    assert check.required
    result = HarnessRunner(context)._run_spec(check)
    assert result.status is (Status.BLOCKED if damage == "missing" else Status.FAILED)


def test_maintenance_real_round_trip_and_readonly_status(tmp_path):
    marker = tmp_path / "synthetic-maintenance.json"
    assert cli("maintenance_state", tmp_path, "status", "--path", marker).returncode == 0
    assert not marker.exists()
    result = cli("maintenance_state", tmp_path, "set", "--path", marker, "--reason", "Synthetic test")
    assert result.returncode == 2 and json.loads(result.stdout)["active"] is True
    before = marker.read_bytes()
    assert cli("maintenance_state", tmp_path, "status", "--path", marker).returncode == 2
    assert marker.read_bytes() == before
    result = cli("maintenance_state", tmp_path, "clear", "--path", marker)
    assert result.returncode == 0 and json.loads(result.stdout)["active"] is False


def test_legacy_missing_database_fails_without_creating_state(tmp_path):
    result = cli("audit_legacy_compatibility", tmp_path, "--stats-db", tmp_path / "missing.sqlite",
                 "--legacy-path", tmp_path / "missing-legacy")
    assert result.returncode == 2
    assert json.loads(result.stdout)["ready_for_major_removal"] is False
    assert not list(tmp_path.iterdir())


def test_real_soak_rejects_missing_evidence(tmp_path):
    result = cli("audit_user_stream_soak", tmp_path, tmp_path / "missing.json")
    assert result.returncode == 2 and json.loads(result.stdout)["ready"] is False
    assert not list(tmp_path.iterdir())


def test_real_calibration_to_validation_rejects_insufficient_evidence(tmp_path):
    archive = tmp_path / "synthetic.jsonl"
    archive.write_text(json.dumps({"lastUpdateId": 1, "E": 1000,
                                  "bids": [["99", "1"]], "asks": [["101", "1"]]}) + "\n")
    executions = tmp_path / "empty-executions.jsonl"
    executions.write_text("")
    calibration = tmp_path / "calibration.json"
    result = cli("calibrate_replay", tmp_path, archive, "--output", calibration)
    assert result.returncode == 2 and json.loads(result.stdout)["eligible"] is False
    assert calibration.exists()
    arguments = [archive, "--execution-log", executions, "--calibration", calibration]
    for fee in ("maker-buy", "maker-sell", "taker-buy", "taker-sell"):
        arguments += [f"--{fee}-fee-pct", "0.001"]
    result = cli("validate_replay_outcomes", tmp_path, *arguments)
    assert result.returncode == 2 and json.loads(result.stdout)["ready"] is False


@pytest.mark.parametrize("name", ["audit_legacy_compatibility", "audit_user_stream_soak", "calibrate_replay", "validate_replay_outcomes"])
@pytest.mark.parametrize("ready", [False, True])
def test_output_exit_and_policy_forwarding(name, ready, monkeypatch, capsys):
    module = importlib.import_module(NEXT_COMMANDS[name])
    from types import SimpleNamespace
    report = SimpleNamespace(ready=ready, eligible=ready, ready_for_major_removal=ready,
                             as_dict=lambda: {"synthetic": True, "ready": ready})
    calls = []
    writes = []
    def audit(*args, **kwargs):
        calls.append((args, kwargs))
        return report
    if name == "audit_legacy_compatibility":
        monkeypatch.setattr(module, "audit_compatibility", audit)
        args = ["--stats-db", "synthetic.sqlite", "--legacy-path", "synthetic-legacy"]
    elif name == "audit_user_stream_soak":
        monkeypatch.setattr(module, "audit_user_stream_soak", audit)
        args = ["synthetic.json"]
    else:
        monkeypatch.setattr(module, "load_jsonl_archive", lambda _: ["synthetic-event"])
        args = ["synthetic.jsonl", "--output", "synthetic-output.json"]
        if name == "calibrate_replay":
            monkeypatch.setattr(module, "archive_sha256", lambda _: "a" * 64)
            monkeypatch.setattr(module, "calibrate_market_events", audit)
            monkeypatch.setattr(module, "write_calibration", lambda *a: writes.append(a))
        else:
            policy = module.PRODUCTION_REPLAY_ACCEPTANCE_POLICY
            calibration = SimpleNamespace(acceptance_policy=policy.as_dict(), acceptance_policy_sha256=policy.fingerprint)
            monkeypatch.setattr(module, "read_calibration", lambda _: calibration)
            monkeypatch.setattr(module, "load_execution_outcomes", lambda _: ["synthetic-outcome"])
            monkeypatch.setattr(module, "validate_replay_outcomes", audit)
            monkeypatch.setattr(module, "write_replay_validation", lambda *a: writes.append(a))
            args += ["--execution-log", "synthetic-log", "--calibration", "synthetic-calibration"]
            for fee in ("maker-buy", "maker-sell", "taker-buy", "taker-sell"):
                args += [f"--{fee}-fee-pct", "0.001"]
    monkeypatch.setattr(sys, "argv", [name, *args])
    assert module.main() == (0 if ready else 2)
    assert json.loads(capsys.readouterr().out) == report.as_dict()
    assert len(calls) == 1
    if name == "audit_user_stream_soak":
        assert calls[0][1]["require_reconnect"] is True
        assert calls[0][1]["require_order_event"] is True
        assert calls[0][1]["require_event_woken_rest"] is True
    if name in ("calibrate_replay", "validate_replay_outcomes"):
        assert writes == [("synthetic-output.json", report)]
