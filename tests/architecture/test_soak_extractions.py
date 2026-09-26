"""Testnet monitor extraction preserves scopes, signals, and read-only behavior."""

import ast
import copy
from decimal import Decimal
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys

import pytest

from tests.architecture.ast_contracts import extraction_digest
from tests.architecture.test_five_audit_extractions import checkout
from tests.architecture.test_digest_extractions import _check
from tests.test_testnet_soak_monitor import _exchange_info
from ladder_dragon.verification.architecture.command_ownership import SOAK_OWNERS, SOAK_LINKS
from ladder_dragon.verification.models import Status

ROOT = Path(__file__).resolve().parents[2]
DIGESTS = {
    "RUN": "aa2340298b82b3d8c253da8a5dfa624c991eb2afb797148d7c13feb015af8d1a",
    "SOAK_SOURCE_ERRORS": "c439775a16e46366b37823de6e5e09fa54d14c67fddbdaa1fd16c3215b54b1e1",
    "SoakSample": "95a9a0d8574e5c38b6ba7fc7081d9230dfea819bbdd6b0733cfa5157e7230ae1",
    "evaluate_sample": "5f54d0425784d09e639a18bf5010d72a8fc6ef34341b9252118f65f678acb926",
    "oco_protection_coverage": "f4c6c7b0e498e55ea6cf081b5bedb3468dffca5867251333bbc23004dcaf6e4d",
    "_inventory_qty": "291a5f865bc6bcaea2c48bb4ea4f7832e0b4f7648a723e775de887298bce13b1",
    "_atomic_report": "bc466fa1a31705f13970e2f8b201b2f8022acfac376e3c3ece6e1cc331862357",
    "_json_sample": "75701a069febc5917530110a291fa4086bd015f285db5782bad90b61fffca670",
    "_stop": "0e1dc04154962e4ba050e3d03eb93aca388adecc26072b5e7cb9316db4217ad2",
    "main": "a5694fab2d68c28999f9ee3dca11fb131e46bb03202d205bd56eae09215de41b"
}
HELPERS = {"_parse_monitor_args": "soak_parser", "_read_sources": "soak_sources",
           "_advance_grace": "soak_policy", "_finish_report": "soak_reports"}


def tree(owner, root=ROOT):
    return ast.parse((root / f"ladder_dragon/verification/live/{owner}.py").read_text())


class Recompose(ast.NodeTransformer):
    def expand(self, node, call, returns):
        function = next(n for n in tree(HELPERS[call.func.id]).body
                        if isinstance(n, ast.FunctionDef) and n.name == call.func.id)
        assert not call.keywords
        assert [ast.unparse(a) for a in call.args] == [a.arg for a in function.args.args]
        if returns:
            return copy.deepcopy(function.body)
        assert isinstance(function.body[-1], ast.Return)
        assert ast.unparse(node.targets[0]) == ast.unparse(function.body[-1].value)
        return copy.deepcopy(function.body[:-1])

    def visit_Assign(self, node):
        if isinstance(node.value, ast.Call) and isinstance(node.value.func, ast.Name) and node.value.func.id in HELPERS:
            return self.expand(node, node.value, False)
        return self.generic_visit(node)

    def visit_Return(self, node):
        if isinstance(node.value, ast.Call) and isinstance(node.value.func, ast.Name) and node.value.func.id in HELPERS:
            return self.expand(node, node.value, True)
        return self.generic_visit(node)


@pytest.mark.parametrize("name", DIGESTS)
def test_original_syntax_after_explicit_helper_recomposition(name):
    nodes = [n for owner in SOAK_OWNERS for n in tree(owner).body
             if getattr(n, "name", None) == name or isinstance(n, ast.Assign)
             and any(isinstance(t, ast.Name) and t.id == name for t in n.targets)]
    assert len(nodes) == 1
    node = copy.deepcopy(nodes[0])
    if name == "main":
        node = Recompose().visit(node)
    assert extraction_digest(ast.Module(body=[node], type_ignores=[])) == DIGESTS[name]


@pytest.mark.parametrize("profile", ["local", "release"])
@pytest.mark.parametrize("owner", SOAK_OWNERS)
@pytest.mark.parametrize("damage", ["forwarder", "reverse", "missing"])
def test_harness_rejects_owner_damage(checkout, profile, owner, damage):
    path = checkout / f"ladder_dragon/verification/live/{owner}.py"
    if damage == "forwarder":
        source = tree(owner, checkout)
        node = next(n for n in source.body if getattr(n, "name", None) == SOAK_OWNERS[owner][0])
        node.body = [ast.Pass()]
        path.write_text(ast.unparse(source))
    elif damage == "reverse":
        path.write_text(path.read_text() + "\nfrom bin.testnet_soak_monitor import main as legacy\n")
    else:
        path.unlink()
    assert _check(checkout, profile) is (Status.BLOCKED if damage == "missing" else Status.FAILED)


@pytest.mark.parametrize("profile", ["local", "release"])
@pytest.mark.parametrize("owner,dependency", [(o,d) for o,ds in SOAK_LINKS.items() for d in ds])
def test_harness_rejects_detached_import(checkout, profile, owner, dependency):
    path = checkout / f"ladder_dragon/verification/live/{owner}.py"
    path.write_text(path.read_text().replace(f"live.{dependency} import", "live.wrong import"))
    assert _check(checkout, profile) is Status.FAILED


@pytest.mark.parametrize("profile", ["local", "release"])
@pytest.mark.parametrize("damage", ["launcher", "stop"])
def test_harness_rejects_launcher_and_stop_regressions(checkout, profile, damage):
    if damage == "launcher":
        path = checkout / "bin/testnet_soak_monitor.py"
        path.write_text(path.read_text() + "\ndef misplaced(): return 1\n")
    else:
        path = checkout / "ladder_dragon/verification/live/soak_command.py"
        path.write_text(path.read_text().replace("global RUN", "global OTHER"))
    assert _check(checkout, profile) is Status.FAILED


@pytest.fixture
def monitor(tmp_path, monkeypatch):
    from ladder_dragon.verification.live import soak_command as command
    db = tmp_path / "synthetic.sqlite"
    with sqlite3.connect(db) as c:
        c.execute("CREATE TABLE inventory_exact(symbol TEXT, qty_text TEXT)")
        c.execute("INSERT INTO inventory_exact VALUES('SOLUSDT','0')")
    monkeypatch.setenv("BOT_STATS_DB", str(db))
    monkeypatch.setenv("BOT_RUN_DIR", str(tmp_path))
    monkeypatch.setenv("BINANCE_TESTNET_API_KEY", "synthetic")
    monkeypatch.setenv("BINANCE_TESTNET_API_SECRET", "synthetic")
    monkeypatch.setattr(command, "load_dotenv", lambda: None)
    monkeypatch.setattr(command, "apply_testnet_paths", lambda: None)
    monkeypatch.setattr(command, "RUN", True)
    handlers = {}
    monkeypatch.setattr(command.signal, "signal", lambda sig, handler: handlers.setdefault(sig, handler))
    monkeypatch.setattr(sys, "argv", ["soak", "--duration-sec", "0", "--report", str(tmp_path / "report.json")])
    return command, db, handlers


@pytest.mark.parametrize("interrupt", [False, True])
def test_real_loop_preserves_read_order_and_live_signal_state(monitor, tmp_path, monkeypatch, interrupt):
    command, db, handlers = monitor
    before = db.read_bytes()
    calls = []
    class Client:
        def __init__(self, *args): pass
        def public_get(self, path, params=None):
            calls.append(path)
            if path.endswith("exchangeInfo"):
                return _exchange_info()
            if interrupt:
                handlers[command.signal.SIGTERM](command.signal.SIGTERM, None)
            return {"price": "77"}
        def signed(self, method, path, params=None):
            assert method == "GET"
            calls.append(path)
            return {"balances": []} if path.endswith("account") else []
    monkeypatch.setattr(command, "SpotTestnetClient", Client)
    assert command.main() == 0
    report = json.loads((tmp_path / "report.json").read_text())
    assert report["status"] == ("interrupted" if interrupt else "pass")
    assert report["samples"] == 1
    assert report["last_sample"]["total_exposure"] == "0"
    assert calls == ["/api/v3/exchangeInfo", "/api/v3/account", "/api/v3/openOrders", "/api/v3/ticker/price"]
    assert db.read_bytes() == before
    assert command.RUN is (not interrupt)


@pytest.mark.parametrize("args", [["--symbol", "?"], ["--interval-sec", "0"],
                                  ["--max-consecutive-read-failures", "0"]])
def test_parser_rejects_before_client_construction(monitor, monkeypatch, args):
    command, _, _ = monitor
    monkeypatch.setattr(command, "SpotTestnetClient", lambda *args: pytest.fail("client reached"))
    monkeypatch.setattr(sys, "argv", ["soak", *args])
    with pytest.raises(SystemExit) as caught:
        command.main()
    assert caught.value.code == 2


def test_grace_boundary_and_reset():
    from types import SimpleNamespace
    from ladder_dragon.verification.live.soak_policy import _advance_grace
    args = SimpleNamespace(grace_sec=10)
    assert _advance_grace(True, True, None, None, 100, [], args) == (100, 100, [])
    assert _advance_grace(True, True, 100, 100, 110, [], args) == (100, 100, [])
    unprotected, mismatch, reasons = _advance_grace(True, True, 100, 100, 111, [], args)
    assert (unprotected, mismatch) == (100, 100) and len(reasons) == 2
    assert _advance_grace(False, False, 100, 100, 112, [], args) == (None, None, [])


def test_atomic_report_preserves_previous_file_on_replace_error(tmp_path, monkeypatch):
    from ladder_dragon.verification.live import soak_reports
    path = tmp_path / "report.json"
    path.write_text("previous")
    def fail(*args): raise OSError("synthetic failure")
    monkeypatch.setattr(soak_reports.os, "replace", fail)
    with pytest.raises(OSError):
        soak_reports._atomic_report(path, {"status": "pass"})
    assert path.read_text() == "previous"
    assert list(tmp_path.iterdir()) == [path]


def test_help_is_offline_with_isolated_paths(tmp_path):
    env = {"PATH": os.defpath, "PYTHONPATH": str(ROOT), "PYTHON_DOTENV_DISABLED": "1",
           "BOT_TESTNET_RUN_DIR": str(tmp_path / "run"),
           "BOT_TESTNET_STATS_DB": str(tmp_path / "stats.sqlite"),
           "BOT_TESTNET_ORDER_JOURNAL": str(tmp_path / "journal.sqlite")}
    result = subprocess.run([sys.executable, "-m", "bin.testnet_soak_monitor", "--help"],
        cwd=tmp_path, env=env, capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr
    assert not list(tmp_path.iterdir())
