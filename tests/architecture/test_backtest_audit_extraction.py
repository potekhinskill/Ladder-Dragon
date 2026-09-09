"""Preserve the saved-report command contract during implementation relocation."""

import ast
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from tests.architecture.ast_contracts import extraction_digest

ROOT = Path(__file__).resolve().parents[2]
OWNER = ROOT / "ladder_dragon/verification/backtest_reports.py"
BASELINE_AST = "43c340f91bdee96855e715286ebcb75f573236050b510b897db73a74c3cc6fd4"


def run_cli(*args):
    return subprocess.run([sys.executable, "-m", "bin.audit_backtest_reports", *map(str, args)],
        cwd=ROOT, env={"PATH": os.defpath, "PYTHONPATH": str(ROOT), "PYTHON_DOTENV_DISABLED": "1"},
        capture_output=True, text=True, timeout=15)


def test_concrete_owner_and_thin_launcher_preserve_baseline_syntax():
    tree = ast.parse(OWNER.read_text())
    assert extraction_digest(tree) == BASELINE_AST
    assert {node.name for node in tree.body if isinstance(node, ast.FunctionDef)} == {
        "_impact_bps", "classify_report", "_paths", "main"}
    expected = ast.parse('from ladder_dragon.verification.backtest_reports import main\nif __name__ == "__main__":\n    raise SystemExit(main())\n')
    actual = ast.parse((ROOT / "bin/audit_backtest_reports.py").read_text())
    assert ast.dump(actual, include_attributes=False) == ast.dump(expected, include_attributes=False)


@pytest.mark.parametrize("schema,impact,code,reason", [
    (2, "10", 0, "current execution model"),
    (1, "0", 0, "legacy report unaffected by market impact correction"),
    (1, "10", 2, "legacy report with non-zero market impact"),
])
def test_report_classification_and_exit_codes_preserve_inputs(tmp_path, schema, impact, code, reason):
    path = tmp_path / "report.json"
    path.write_text(json.dumps({"report_schema_version": schema, "final_equity": "PRIVATE_MARKER",
        "realized_pnl": "FUTURE_MARKER", "trades": [], "config": {"market_impact_bps": impact},
        "execution_model": {"market_impact_bps_divisor": "10000"}}))
    before = path.read_bytes()
    result = run_cli(path)
    assert result.returncode == code
    payload = json.loads(result.stdout)
    assert payload["reports"] == [{"path": str(path), "current": schema >= 2,
        "market_impact_bps": impact, "rerun_required": code == 2, "reason": reason}]
    assert payload["invalid"] == 0
    assert payload["rerun_required"] == int(code == 2)
    assert "PRIVATE_MARKER" not in result.stdout + result.stderr
    assert "FUTURE_MARKER" not in result.stdout + result.stderr
    assert path.read_bytes() == before


@pytest.mark.parametrize("content", ["PRIVATE_MARKER", "[]", '{"config":"PRIVATE_MARKER"}'])
def test_invalid_reports_fail_without_echoing_payload_or_modifying_input(tmp_path, content):
    path = tmp_path / "invalid.json"
    path.write_text(content)
    result = run_cli(path)
    assert result.returncode == 1
    assert json.loads(result.stdout)["invalid"] == 1
    assert "PRIVATE_MARKER" not in result.stdout + result.stderr
    assert path.read_text() == content


def test_missing_input_and_cli_errors_do_not_create_files(tmp_path):
    missing = tmp_path / "missing.json"
    assert run_cli(missing).returncode == 1
    assert not missing.exists()
    assert run_cli().returncode == 2
    assert run_cli("--unknown").returncode == 2
    assert run_cli("--help").returncode == 0


def test_directory_order_and_rerun_precedence_remain_stable(tmp_path):
    (tmp_path / "a.json").write_text("invalid")
    (tmp_path / "b.json").write_text(json.dumps({"final_equity": "0", "realized_pnl": "0",
        "trades": [], "config": {"market_impact_bps": "1"}}))
    before = {path.name: path.read_bytes() for path in tmp_path.iterdir()}
    result = run_cli(tmp_path)
    assert result.returncode == 2
    payload = json.loads(result.stdout)
    assert payload["invalid"] == payload["rerun_required"] == 1
    assert [Path(row["path"]).name for row in payload["reports"]] == ["a.json", "b.json"]
    assert {path.name: path.read_bytes() for path in tmp_path.iterdir()} == before
