"""VWAP extraction parity and mandatory component ownership."""

import ast
import copy
from decimal import Decimal
import os
from pathlib import Path
import sqlite3
import subprocess
import sys

import pytest

from tests.architecture.ast_contracts import extraction_digest
from tests.architecture.test_five_audit_extractions import checkout
from tests.architecture.test_digest_extractions import _check
from ladder_dragon.verification.architecture.command_ownership import AUTOTUNE_OWNERS, AUTOTUNE_LINKS
from ladder_dragon.verification.models import Status

ROOT = Path(__file__).resolve().parents[2]
DIGESTS = {
    "clamp": "2f35cefd05e5e3cf1f17bf98791700647548811548fdb085d85cd577ebba97e3",
    "fmt_map": "d17a5e46c1905b1d415ff7151d1bd7328cbf172221dcdad69cdd03e12315524e",
    "ema": "b90f7709c82269eecf4e89cda132301337899064de9f8afdd00e19ab8b69d8d1",
    "load_prev_values": "d808590bf7fac8e71622385788968a4603dbe10cfdc29557f628162b674718a9",
    "save_values": "65f70a1c0f0f4e6a171fddefe2363a9bfad1add7d42cb3b21bc4a1d7c5606a33",
    "adaptive_discount": "ef5df14959a3d89ca9b8c419b9c40dd0e1ab98b32d276f8a98707eeacc4dc6c7",
    "decimal_ema": "375eeb0f31eec654e2762ddb9b48e5e09f48bfce9cc5d63e1e45c0329ac9ffa6",
    "get_stats": "75dee4062aeb030aad0e437fa9dba17737413dc5b97eee9fd74496e5276956f3",
    "main": "d975c02279ed2b1d06ad97a14c650e1b9148d500a9b88c4d3b550132df75bc80"
}


def tree(owner, root=ROOT):
    return ast.parse((root / f"ladder_dragon/strategy/{owner}.py").read_text())


@pytest.mark.parametrize("name", DIGESTS)
def test_original_definitions_unchanged(name):
    nodes = [n for owner in AUTOTUNE_OWNERS for n in tree(owner).body
             if isinstance(n, ast.FunctionDef) and n.name == name]
    assert len(nodes) == 1
    node = copy.deepcopy(nodes[0])
    if name == "main":
        assert ast.dump(node.body[0]) == ast.dump(ast.parse("parser = build_parser()").body[0])
        parser = next(n for n in tree("autotune_parser").body if isinstance(n, ast.FunctionDef))
        assert ast.dump(parser.body[-1]) == ast.dump(ast.parse("return parser").body[0])
        node.body[:1] = copy.deepcopy(parser.body[:-1])
    assert extraction_digest(ast.Module(body=[node], type_ignores=[])) == DIGESTS[name]


@pytest.mark.parametrize("profile", ["local", "release"])
@pytest.mark.parametrize("owner", AUTOTUNE_OWNERS)
@pytest.mark.parametrize("damage", ["forwarder", "reverse", "missing"])
def test_required_check_rejects_owner_damage(checkout, profile, owner, damage):
    path = checkout / f"ladder_dragon/strategy/{owner}.py"
    if damage == "forwarder":
        source = tree(owner, checkout)
        node = next(n for n in source.body if isinstance(n, ast.FunctionDef)
                    and n.name == AUTOTUNE_OWNERS[owner][0])
        node.body = ast.parse("return legacy()").body
        path.write_text(ast.unparse(source))
    elif damage == "reverse":
        path.write_text(path.read_text() + "\nfrom bin.gen_vwap_autotune import main as legacy\n")
    else:
        path.unlink()
    assert _check(checkout, profile) is (Status.BLOCKED if damage == "missing" else Status.FAILED)


@pytest.mark.parametrize("profile", ["local", "release"])
@pytest.mark.parametrize("dependency", AUTOTUNE_LINKS)
def test_required_check_rejects_detached_dependency(checkout, profile, dependency):
    path = checkout / "ladder_dragon/strategy/autotune_command.py"
    path.write_text(path.read_text().replace(f"strategy.{dependency} import", "strategy.wrong import"))
    assert _check(checkout, profile) is Status.FAILED


@pytest.mark.parametrize("profile", ["local", "release"])
def test_required_check_rejects_launcher_logic(checkout, profile):
    path = checkout / "bin/gen_vwap_autotune.py"
    path.write_text(path.read_text() + "\ndef misplaced(): return 1\n")
    assert _check(checkout, profile) is Status.FAILED


def test_help_is_offline(tmp_path):
    result = subprocess.run([sys.executable, "-m", "bin.gen_vwap_autotune", "--help"],
        cwd=tmp_path, env={"PATH": os.defpath, "PYTHONPATH": str(ROOT), "PYTHON_DOTENV_DISABLED": "1"},
        capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr
    assert not list(tmp_path.iterdir())


def test_history_includes_old_basis_excludes_future(tmp_path, monkeypatch):
    from ladder_dragon.strategy import autotune_history as history
    from ladder_dragon.execution import tools_stats
    c = tools_stats.init_db(str(tmp_path / "synthetic.sqlite"))
    now = 2_000_000
    for tid, ts, side, price in [(1, now - 200000, "BUY", "100"),
                                 (2, now - 100, "SELL", "90"),
                                 (3, now + 100, "SELL", "900")]:
        tools_stats.apply_trade(c, "SOLUSDT", side, price, "1", ts=ts * 1000,
                                trade_id=tid, commission_value_status="exact",
                                commission_amount="0", commission_quote="0")
    monkeypatch.setattr(history.time, "time", lambda: now)
    assert history.get_stats("SOLUSDT", c, 24) == (Decimal("-10"), 1)
    c.close()


@pytest.mark.parametrize("args,code", [
    (["--symbols", ""], 1),
    (["--symbols", "SOLUSDT"], 1),
    (["--symbols", "SOLUSDT", "--discount-max", "NaN"], 2),
])
def test_invalid_configuration_stops_before_database(args, code, monkeypatch):
    from ladder_dragon.strategy import autotune_command as command
    monkeypatch.delenv("BOT_STATS_DB", raising=False)
    monkeypatch.setattr(command, "migrate", lambda *a: pytest.fail("database reached"))
    monkeypatch.setattr(sys, "argv", ["autotune", *args])
    with pytest.raises(SystemExit) as exc:
        command.main()
    assert exc.value.code == code


def test_existing_decimal_state_failure_is_not_silently_fixed(tmp_path):
    from ladder_dragon.strategy.autotune_state import save_values, load_prev_values
    state = tmp_path / "synthetic.json"
    state.write_text('{"SOLUSDT":{"discount":"0.006"}}')
    before = state.read_bytes()
    save_values(str(state), {"SOLUSDT": {"pnl": Decimal("1")}})
    assert state.read_bytes() == before
    assert not state.with_suffix(".json.tmp").exists()
    assert load_prev_values(str(state)) == {"SOLUSDT": {"discount": "0.006"}}


def test_command_emits_same_maps_without_state_file(tmp_path, monkeypatch, capsys):
    from ladder_dragon.strategy import autotune_command as command
    db = tmp_path / "synthetic.sqlite"
    monkeypatch.setattr(sys, "argv", ["autotune", "--symbols", "SOLUSDT", "--stats-db", str(db)])
    assert command.main() is None
    assert capsys.readouterr().out == (
        "BUY_VWAP_PREMIUM_MAP=SOLUSDT:0.003000\n"
        "BUY_VWAP_DISCOUNT_MAP=SOLUSDT:0.006000\n"
        "BUY_VWAP_DISCOUNT_SCALE_MAP=SOLUSDT:1.300000\n")
