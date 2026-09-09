"""Monthly command ownership, offline CLI, and notification-state parity."""

import ast
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from tests.architecture.ast_contracts import extraction_digest

from ladder_dragon.strategy.prediction import monthly_report_command as command

ROOT = Path(__file__).resolve().parents[2]
OWNER = ROOT / "ladder_dragon/strategy/prediction/monthly_report_command.py"


def test_implementation_keeps_exact_pre_extraction_ast():
    tree = ast.parse(OWNER.read_text())
    assert extraction_digest(tree) == (
        "c0d4176f87713b86e2e9b1ae7daa3b1dc90854d10782fe256a1ac562bc784737")
    assert {node.name for node in tree.body if isinstance(node, ast.FunctionDef)} == {"_features", "_load", "main"}
    launcher = ast.parse((ROOT / "bin/monthly_prediction_report.py").read_text())
    expected = ast.parse('from ladder_dragon.strategy.prediction.monthly_report_command import main\n'
                         'if __name__ == "__main__":\n    raise SystemExit(main())')
    assert ast.dump(launcher, include_attributes=False) == ast.dump(expected, include_attributes=False)


def cli(tmp_path, *args):
    return subprocess.run([sys.executable, "-m", "bin.monthly_prediction_report", *map(str, args)],
                          cwd=tmp_path, env={"PATH": os.defpath, "PYTHONPATH": str(ROOT),
                                             "PYTHON_DOTENV_DISABLED": "1"},
                          capture_output=True, text=True, timeout=30)


def test_help_and_missing_arguments_do_not_create_artifacts(tmp_path):
    assert cli(tmp_path, "--help").returncode == 0
    assert cli(tmp_path).returncode == 2
    assert list(tmp_path.iterdir()) == []


def test_empty_evidence_writes_exact_hash_bound_shadow_report(tmp_path):
    evidence, output, state = (tmp_path / name for name in ("evidence.jsonl", "report.json", "state.json"))
    evidence.write_text("")
    result = cli(tmp_path, "--evidence-jsonl", evidence, "--output", output,
                 "--cutoff-ts-ms", 1000, "--status-state", state)
    report = json.loads(output.read_text())
    assert result.returncode == 2 and report["status"] != "PASS"
    assert report["mode"] == "SHADOW" and report["risk_expansion"] is False
    assert report["cutoff_ts_ms"] == 1000
    assert json.loads(result.stdout) == {"status": report["status"], "report_sha256": report["report_sha256"], "output": str(output)}
    assert json.loads(state.read_text()) == command.compact_report_state(report)
    assert not state.with_suffix(".tmp").exists()
    assert evidence.read_text() == ""


@pytest.mark.parametrize("damage", ["missing", "invalid_json", "unsupported_kind", "notify_without_state"])
def test_invalid_input_never_overwrites_existing_report(tmp_path, damage):
    evidence, output = tmp_path / "evidence.jsonl", tmp_path / "report.json"
    output.write_text("preserve existing report")
    if damage != "missing":
        evidence.write_text("{" if damage == "invalid_json" else '{"kind":"unsupported"}')
    args = ["--evidence-jsonl", evidence, "--output", output, "--cutoff-ts-ms", 1000]
    if damage == "notify_without_state":
        args.append("--notify-on-change")
    assert cli(tmp_path, *args).returncode != 0
    assert output.read_text() == "preserve existing report"


def test_notify_on_change_uses_current_state_without_real_messages(tmp_path, monkeypatch):
    evidence, output, state = (tmp_path / name for name in ("evidence.jsonl", "report.json", "state.json"))
    evidence.write_text("")
    messages = []
    monkeypatch.setattr(command, "send_message", messages.append)
    monkeypatch.setattr(sys, "argv", ["monthly_prediction_report", "--evidence-jsonl", str(evidence),
                        "--output", str(output), "--cutoff-ts-ms", "1000", "--status-state", str(state), "--notify-on-change"])
    assert command.main() == 2
    assert command.main() == 2
    assert len(messages) == 1 and "risk expansion: disabled" in messages[0]
