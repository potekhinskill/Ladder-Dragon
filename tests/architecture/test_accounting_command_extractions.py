"""Accounting command relocation preserves authority and concrete ownership."""

import ast
import os
from pathlib import Path
import sqlite3
import subprocess
import sys

import pytest

from tests.architecture.ast_contracts import extraction_digest
from tests.architecture.test_five_audit_extractions import checkout
from ladder_dragon.verification.architecture.command_ownership import ACCOUNTING_COMMANDS
from ladder_dragon.verification.models import HarnessContext, HarnessOptions, Status
from ladder_dragon.verification.profiles import checks_for_profile
from ladder_dragon.verification.runner import HarnessRunner

ROOT = Path(__file__).resolve().parents[2]
# Original HEAD syntax, with only entry guards and canonical imports adjusted.
DIGESTS = {
    "import_legacy_cost_basis": "fe9a8eefd3fb88805700758bc7ee07e6edaf773130be69ab521b7179e3ed94bd",
    "retire_legacy_accounting": "ed653f8f914ce0f4062a832fcca215a332cbb4220c2df1d601460677dc20b6cb",
    "revalue_legacy_commissions": "7dfe53e055a1a5478c91abfd33f93060a1bcae8ce9fefdfc7734e36b99c46921",
    "migrate_indexes": "7032ff0e64c0fa7f4a7897da32b61a567acb60d186def80cd5418322b9e4c3aa",
    "backtest": "691e507196fada5c9f4a842e725aad5d062d8bce0f4bdc9687c52014d40f9272",
}


@pytest.mark.parametrize("name", ACCOUNTING_COMMANDS)
def test_unchanged_syntax_and_isolated_entry(name, tmp_path):
    source = ROOT / (ACCOUNTING_COMMANDS[name].replace(".", "/") + ".py")
    assert extraction_digest(ast.parse(source.read_text())) == DIGESTS[name]
    env = {"PATH": os.defpath, "PYTHONPATH": str(ROOT), "PYTHON_DOTENV_DISABLED": "1"}
    args = ["--help"]
    if name == "migrate_indexes":
        # This executable has no help parser; never allow its production default.
        env["BOT_STATS_DB"] = str(tmp_path / "synthetic.sqlite")
        args = []
    result = subprocess.run([sys.executable, "-m", f"bin.{name}", *args],
        cwd=tmp_path, env=env, capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr
    if name == "migrate_indexes":
        assert "[SKIP]" in result.stdout
    else:
        assert not list(tmp_path.iterdir())


@pytest.mark.parametrize("name", ACCOUNTING_COMMANDS)
@pytest.mark.parametrize("profile", ["local", "release"])
@pytest.mark.parametrize("damage", ["launcher", "forwarder", "reverse", "missing"])
def test_required_harness_rejects_accounting_damage(checkout, name, profile, damage):
    source = checkout / (ACCOUNTING_COMMANDS[name].replace(".", "/") + ".py")
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


@pytest.mark.parametrize("schema", ["legacy", "exact"])
def test_index_entry_preserves_rows_and_is_idempotent(schema, tmp_path, monkeypatch):
    from ladder_dragon.persistence import index_command as module
    path = tmp_path / "synthetic.sqlite"
    columns = module.LEGACY_MONTHLY_COLUMNS if schema == "legacy" else module.EXACT_MONTHLY_COLUMNS
    with sqlite3.connect(path) as connection:
        connection.execute("CREATE TABLE trades (" + ", ".join(columns) + ", trade_id)")
        connection.execute("INSERT INTO trades VALUES (?, ?, ?, ?, ?, ?, ?)",
                           ("SOLUSDT", 1, "BUY", "1.00000001", "0.1", "0.001", 7))
        before = connection.execute("SELECT * FROM trades").fetchall()
    monkeypatch.setattr(module, "DB", str(path))
    assert module.main() == module.main() == 0
    with sqlite3.connect(path) as connection:
        assert connection.execute("SELECT * FROM trades").fetchall() == before
        indexes = {row[1] for row in connection.execute("PRAGMA index_list(trades)")}
        assert {"trades_monthly_cover", "trades_sym_tradeid_uq"} <= indexes


def test_relocated_accounting_commands_share_stopped_guard():
    from ladder_dragon.execution import cost_basis_command, commission_command, retirement_command
    assert commission_command._require_stopped_runtime is cost_basis_command._require_stopped_runtime
    assert retirement_command._require_stopped_runtime is cost_basis_command._require_stopped_runtime
    assert commission_command.fetch_all_trades is cost_basis_command.fetch_all_trades


def test_revaluation_confirmation_failure_never_creates_backup(tmp_path, monkeypatch):
    from ladder_dragon.execution import commission_command as module
    database = tmp_path / "synthetic.sqlite"
    database.touch()
    backup = tmp_path / "must-not-exist.sqlite"
    monkeypatch.setattr(module.market, "BASE_URL", module.MAINNET)
    monkeypatch.setattr(module, "legacy_rows", lambda connection: [])
    monkeypatch.setattr(sys, "argv", ["revalue", "--stats-db", str(database),
                                     "--backup", str(backup), "--apply"])
    with pytest.raises(SystemExit, match="--apply requires --confirm"):
        module.main()
    assert not backup.exists()
