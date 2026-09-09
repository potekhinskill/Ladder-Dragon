"""Executable and structural contracts for the first read-only CLI extraction."""

import ast
import os
from pathlib import Path
import sqlite3
import subprocess
import sys

import pytest

from tests.architecture.ast_contracts import extraction_digest

ROOT = Path(__file__).resolve().parents[2]
OWNER = "ladder_dragon/execution/stats_view.py"
# Original module syntax, excluding only its executable __main__ guard.
BASELINE_AST = "b139174a50cdf04229e8683e9e3e46fdc490b50cc6722e7ae903461d593449e1"


def run_cli(tmp_path, *args):
    return subprocess.run([sys.executable, "-m", "bin.stats_view", *args], cwd=ROOT,
        env={"PATH": os.defpath, "PYTHONPATH": str(ROOT), "PYTHON_DOTENV_DISABLED": "1",
             "BOT_STATS_DB": str(tmp_path / "missing.sqlite"), "TZ": "UTC"},
        text=True, capture_output=True, timeout=20)


def test_implementation_is_identical_and_launcher_has_no_reverse_delegation():
    tree = ast.parse((ROOT / OWNER).read_text())
    assert extraction_digest(tree) == BASELINE_AST
    assert {node.name for node in tree.body if isinstance(node, ast.FunctionDef)} == {
        "env_default_db", "detect_symbols", "ts_expr", "print_inventory", "print_last_trades",
        "print_daily_monthly", "print_global_last", "main"}
    launcher = ast.parse((ROOT / "bin/stats_view.py").read_text())
    expected = ast.parse('from ladder_dragon.execution.stats_view import main\nif __name__ == "__main__":\n    main()\n')
    assert ast.dump(launcher, include_attributes=False) == ast.dump(expected, include_attributes=False)


@pytest.mark.parametrize("args,code,text", [
    (("--help",), 0, "--global-limit"),
    (("--limit", "invalid"), 2, "invalid int value"),
    (("--unknown",), 2, "unrecognized arguments"),
    ((), 2, "Database not found:"),
])
def test_cli_help_errors_and_exit_codes_do_not_create_a_database(tmp_path, args, code, text):
    result = run_cli(tmp_path, *args)
    assert result.returncode == code
    assert text in result.stdout + result.stderr
    assert not (tmp_path / "missing.sqlite").exists()


def test_empty_database_returns_existing_exit_code_without_writes(tmp_path):
    path = tmp_path / "empty.sqlite"
    with sqlite3.connect(path) as con:
        con.execute("CREATE TABLE trades(symbol TEXT)")
    before = path.read_bytes()
    result = run_cli(tmp_path, "--db", str(path))
    assert result.returncode == 3
    assert "No symbols found" in result.stderr
    assert path.read_bytes() == before


def test_exact_rows_and_unpriced_commission_remain_read_only(tmp_path):
    path = tmp_path / "sample.sqlite"
    with sqlite3.connect(path) as con:
        con.executescript("""
CREATE TABLE trades(id INTEGER, symbol TEXT, side TEXT, ts INTEGER,
 price_text TEXT, gross_qty_text TEXT, net_qty_text TEXT, commission_asset TEXT,
 commission_amount_text TEXT, commission_quote_text TEXT, commission_value_status TEXT);
CREATE VIEW trades_exact AS SELECT * FROM trades;
CREATE TABLE inventory_exact(symbol TEXT, qty_text TEXT, avg_cost_text TEXT, realized_pnl_text TEXT);
INSERT INTO inventory_exact VALUES('SOLUSDT','0.1','100','-0.02');
INSERT INTO trades VALUES(1,'SOLUSDT','BUY',1000,'100','0.1','0.1','BNB','0.001',NULL,'unpriced');
""")
    before = path.read_bytes()
    result = run_cli(tmp_path, "--db", str(path), "--utc", "--limit", "1", "--global-limit", "1")
    assert result.returncode == 0, result.stderr
    assert "qty=0.1000000000  avg=100.00000000  realized_pnl=-0.02" in result.stdout
    assert result.stdout.count("fee_q=unpriced") == 2
    assert "Symbols: SOLUSDT" in result.stdout
    assert path.read_bytes() == before
    assert sorted(p.name for p in tmp_path.iterdir()) == ["sample.sqlite"]


def test_missing_explicit_database_is_not_created(tmp_path):
    path = tmp_path / "explicit.sqlite"
    result = run_cli(tmp_path, "--db", str(path), "--symbols", "SOLUSDT")
    assert result.returncode == 2
    assert not path.exists()
