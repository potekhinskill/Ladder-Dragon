"""Daily digest ownership preserves accounting, output, and delivery boundaries."""

import ast
import copy
import os
from pathlib import Path
import subprocess
import sys

import pytest

from tests.architecture.ast_contracts import extraction_digest
from tests.architecture.test_five_audit_extractions import checkout
from ladder_dragon.verification.architecture.command_ownership import DIGEST_OWNERS, DIGEST_LINKS
from ladder_dragon.verification.models import HarnessContext, HarnessOptions, Status
from ladder_dragon.verification.profiles import checks_for_profile
from ladder_dragon.verification.runner import HarnessRunner

ROOT = Path(__file__).resolve().parents[2]
# Captured before relocation. Recompose only the extracted final aggregation.
DIGESTS = {
    "PeriodSummary": "7cfa334a86eabe97d2302cab7342f12b63b4b951e85878345b3d41c563ec60a1",
    "_money": "c4096dc7bd02e87eee28196edadf965cfb6cbc1695b3e2a222cfeae31df098c1",
    "_timezone": "f989767bc7672c21a0900badfbf9d2e6031e84a39100339ad2c3e2029ac63df1",
    "_periods": "fe318d4f5fad9321909d991b3fd4ea8aef0aad219a87c2b42360cfabfbc8d1ea",
    "_as_decimal": "0d30f92d6801a8aea6ac351c1c7d1cadf9ccd6658436843fcaffaa7bb6632478",
    "_summaries": "7cf9565c1c54524a9cc9798c7d1280258185a0d38c8cc508516dad74fc6bf048",
    "build_digest": "f2d778f847f127a9420c99b2b353d0cb98bd790c41a260cb208915f76556a4e8",
    "_last_sent": "45d51bc5903decbe4c0ce1291b7e2d7e6c28441ae3b4cea41dfde0bfc0dcfda3",
    "_last_alert": "800d691f36712b52f2bbcb6f9b5a28538a3be8096914f822c165f99f7cb03318",
    "_mark_state": "cc0cb76bd58682e3b56c5a9922f44b089e6493ffea0b9f2e358fbaca8e78c263",
    "main": "a1acc0e564d758af0097044f28e9dfcdaf78f79afc7d8fb2f01d62db3102a004"
}


def tree(owner, root=ROOT):
    return ast.parse((root / f"ladder_dragon/execution/{owner}.py").read_text())


@pytest.mark.parametrize("name", DIGESTS)
def test_original_definition_syntax_is_preserved(name):
    nodes = [node for owner in DIGEST_OWNERS for node in tree(owner).body
             if isinstance(node, (ast.FunctionDef, ast.ClassDef)) and node.name == name]
    assert len(nodes) == 1
    node = copy.deepcopy(nodes[0])
    if name == "_summaries":
        assert ast.dump(node.body[-1]) == ast.dump(
            ast.parse("return _aggregate(periods, values, excluded)").body[0])
        aggregate = next(n for n in tree("digest_totals").body
                         if isinstance(n, ast.FunctionDef) and n.name == "_aggregate")
        node.body[-1:] = copy.deepcopy(aggregate.body)
    assert extraction_digest(ast.Module(body=[node], type_ignores=[])) == DIGESTS[name]


@pytest.mark.parametrize("profile", ["local", "release"])
@pytest.mark.parametrize("owner", DIGEST_OWNERS)
@pytest.mark.parametrize("damage", ["forwarder", "reverse", "missing"])
def test_harness_rejects_digest_owner_damage(checkout, profile, owner, damage):
    path = checkout / f"ladder_dragon/execution/{owner}.py"
    if damage == "forwarder":
        source = tree(owner, checkout)
        target = next(n for n in source.body if isinstance(n, ast.FunctionDef)
                      and n.name == DIGEST_OWNERS[owner][0])
        target.body = ast.parse("return legacy()").body
        path.write_text(ast.unparse(source))
    elif damage == "reverse":
        path.write_text(path.read_text() + "\nfrom bin.daily_trading_digest import main as legacy\n")
    else:
        path.unlink()
    assert _check(checkout, profile) is (Status.BLOCKED if damage == "missing" else Status.FAILED)


def _check(root, profile):
    context = HarnessContext(root=root, python=sys.executable, options=HarnessOptions(
        profile=profile, output=root / "report.json"))
    check, = [c for c in checks_for_profile(context) if c.name == "architecture_command_ownership"]
    assert check.required
    return HarnessRunner(context)._run_spec(check).status


@pytest.mark.parametrize("profile", ["local", "release"])
def test_complete_checkout_passes_before_mutation(checkout, profile):
    assert _check(checkout, profile) is Status.PASS


@pytest.mark.parametrize("profile", ["local", "release"])
@pytest.mark.parametrize("owner", DIGEST_LINKS)
def test_harness_rejects_detached_consumer(checkout, profile, owner):
    path = checkout / f"ladder_dragon/execution/{owner}.py"
    source = path.read_text()
    dependency = next(iter(DIGEST_LINKS[owner]))
    path.write_text(source.replace(f"execution.{dependency} import", "execution.wrong_owner import"))
    assert _check(checkout, profile) is Status.FAILED


@pytest.mark.parametrize("profile", ["local", "release"])
def test_harness_rejects_logic_returned_to_launcher(checkout, profile):
    path = checkout / "bin/daily_trading_digest.py"
    path.write_text(path.read_text() + "\ndef misplaced(): return 1\n")
    assert _check(checkout, profile) is Status.FAILED


def test_help_has_no_runtime_effects(tmp_path):
    result = subprocess.run([sys.executable, "-m", "bin.daily_trading_digest", "--help"],
        cwd=tmp_path, env={"PATH": os.defpath, "PYTHONPATH": str(ROOT), "PYTHON_DOTENV_DISABLED": "1"},
        capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr
    assert not list(tmp_path.iterdir())


def test_cli_dry_run_preserves_ledger_and_delivery_state(tmp_path, monkeypatch, capsys):
    from ladder_dragon.execution import digest_command as command, tools_stats
    db = tmp_path / "synthetic.sqlite"
    connection = tools_stats.init_db(str(db))
    connection.close()
    before = db.read_bytes()
    state = tmp_path / "delivery.json"
    monkeypatch.setattr(command, "send_message", lambda *args: pytest.fail("dry run delivered"))
    monkeypatch.setattr(sys, "argv", ["digest", "--db", str(db), "--state", str(state), "--dry-run"])
    assert command.main() == 0
    assert "Fills: 0 (BUY 0 / SELL 0)" in capsys.readouterr().out
    assert db.read_bytes() == before
    assert not state.exists()


def test_failed_delivery_does_not_advance_state_and_retries(tmp_path, monkeypatch):
    from ladder_dragon.execution import digest_command as command
    db = tmp_path / "synthetic.sqlite"
    db.touch()
    state = tmp_path / "delivery.json"
    calls = []
    monkeypatch.setattr(command, "build_digest", lambda *args, **kwargs: ("synthetic report", "2026-09-25"))
    monkeypatch.setattr(command, "send_message", lambda message: calls.append(message) or len(calls) > 1)
    monkeypatch.setattr(sys, "argv", ["digest", "--db", str(db), "--state", str(state)])
    assert command.main() == 1
    assert not state.exists()
    assert command.main() == 0
    assert command.main() == 0
    assert calls == ["synthetic report", "synthetic report"]
    assert state.stat().st_mode & 0o777 == 0o600
