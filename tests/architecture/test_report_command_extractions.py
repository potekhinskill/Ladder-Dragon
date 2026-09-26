"""Report commands preserve syntax, executable boundaries, and evidence semantics."""

import ast
from decimal import Decimal
import json
import os
import sqlite3
from pathlib import Path
import subprocess
import sys

import pytest

from tests.architecture.ast_contracts import extraction_digest
from tests.architecture.test_five_audit_extractions import checkout
from ladder_dragon.verification.architecture.command_ownership import REPORT_COMMANDS
from ladder_dragon.verification.models import HarnessContext, HarnessOptions, Status
from ladder_dragon.verification.profiles import checks_for_profile
from ladder_dragon.verification.runner import HarnessRunner

ROOT = Path(__file__).resolve().parents[2]
DIGESTS = {
    "pnl_24h": "bc76a969122dd8b6f89a6a4929a85e11c75fd986f3c0f4a4e025cf48a1fe2228",
    "pnl_reporter": "2c7f28a1d8c791707d66454829059e42898e3d37d701000372052b75ffba874e",
    "regime_pnl_report": "0637b4dab202e07dd07a47537a7590cbec9be839d7344c1dc6c33c2657d49b7a",
    "production_soak_report": "ad290e48664cf759a665607294a8aa46565fd012d68625de0163685e0667c26e",
    "auto_ladder_map": "7105c8f99128b018bbf590569b2e29c9016532e86736937c6c44ab8d878093ae",
}


@pytest.mark.parametrize("name", REPORT_COMMANDS)
def test_syntax_and_offline_parser(name, tmp_path):
    source = ROOT / (REPORT_COMMANDS[name].replace(".", "/") + ".py")
    assert extraction_digest(ast.parse(source.read_text())) == DIGESTS[name]
    result = subprocess.run([sys.executable, "-m", f"bin.{name}", "--help"], cwd=tmp_path,
        env={"PATH": os.defpath, "PYTHONPATH": str(ROOT), "PYTHON_DOTENV_DISABLED": "1"},
        capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr
    assert not list(tmp_path.iterdir())


@pytest.mark.parametrize("name", REPORT_COMMANDS)
@pytest.mark.parametrize("profile", ["local", "release"])
@pytest.mark.parametrize("damage", ["launcher", "forwarder", "reverse", "missing"])
def test_required_check_rejects_report_damage(checkout, name, profile, damage):
    source = checkout / (REPORT_COMMANDS[name].replace(".", "/") + ".py")
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


def test_daily_and_regime_consumers_share_canonical_reader():
    from ladder_dragon.execution import digest_fifo as daily_trading_digest
    from ladder_dragon.strategy import regime_report_command
    from ladder_dragon.execution import pnl_window_command
    for consumer in (daily_trading_digest, regime_report_command):
        assert consumer._execution is pnl_window_command._execution
        assert consumer.iter_trades_until is pnl_window_command.iter_trades_until


@pytest.mark.parametrize("method", ["cash", "realized"])
def test_window_cli_preserves_values_and_database(method, tmp_path):
    database = tmp_path / "synthetic.sqlite"
    with sqlite3.connect(database) as connection:
        connection.execute("CREATE TABLE trades (id, symbol, side, price, qty, fee_quote, ts, trade_id)")
        connection.executemany("INSERT INTO trades VALUES (?, ?, ?, ?, ?, ?, ?, ?)", [
            (1, "SOLUSDT", "BUY", "10", "2", "0.1", 1700000001, 1),
            (2, "SOLUSDT", "SELL", "11", "2", "0.1", 1700000002, 2),
        ])
    before = database.read_bytes()
    result = subprocess.run([sys.executable, "-m", "bin.pnl_24h", "--db", str(database),
        "--from", "2023-11-14", "--to", "2023-11-15", "--utc", "--method", method, "--json"],
        cwd=tmp_path, env={"PATH": os.defpath, "PYTHONPATH": str(ROOT), "PYTHON_DOTENV_DISABLED": "1"},
        capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["total"] == "1.80"
    assert database.read_bytes() == before


@pytest.mark.parametrize("fails", [False, True])
def test_ladder_map_output_and_fallback(fails, monkeypatch, capsys):
    from ladder_dragon.strategy import ladder_map_command as module
    monkeypatch.setattr(sys, "argv", ["ladder", "--symbols", "SOLUSDT", "--format", "raw"])
    monkeypatch.setattr(module, "make_session", lambda: object())
    def fetch(*args, **kwargs):
        if fails:
            raise module.requests.Timeout("synthetic")
        return []
    monkeypatch.setattr(module, "fetch_klines", fetch)
    assert module.main() is None
    output = capsys.readouterr()
    assert json.loads(output.out)["ladder_pct_map"] == "SOLUSDT=-0.600,-3.500,2.800"
    assert ("fallback FLAT" in output.err) is fails


def test_regime_snapshots_keep_strict_cutoff_and_exact_price(tmp_path):
    from ladder_dragon.strategy import regime_report_command as module
    database = tmp_path / "synthetic.sqlite"
    with sqlite3.connect(database) as connection:
        connection.execute("CREATE TABLE prediction_decisions (symbol, snapshot_ts_ms, feature_json)")
        connection.executemany("INSERT INTO prediction_decisions VALUES (?, ?, ?)", [
            ("SOLUSDT", stamp, json.dumps({"regime": "RANGE", "price": price}))
            for stamp, price in [(100, "10.0000000000000001"), (200, "999")]
        ])
    before = database.read_bytes()
    snapshots = module._snapshots(database, 200)
    assert len(snapshots) == 1
    assert snapshots[0].price == Decimal("10.0000000000000001")
    assert snapshots[0].timestamp_ms == 100
    assert database.read_bytes() == before
