"""History route syntax, SQL behavior, lifecycle, and required ownership."""

import ast
import copy
from datetime import timezone
from pathlib import Path
import shutil
import sqlite3
import sys
import time
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from ladder_dragon.verification.models import HarnessContext, HarnessOptions, Status
from ladder_dragon.verification.profiles import checks_for_profile
from ladder_dragon.verification.runner import HarnessRunner
from tests.architecture.ast_contracts import extraction_digest
from tests.support.module_loaders import load_dashboard

ROOT = Path(__file__).resolve().parents[2]
RUNTIME = "ladder_dragon/dashboard/runtime.py"
ROUTER = "ladder_dragon/dashboard/routers/history.py"
STATE = "ladder_dragon/dashboard/history_dependencies.py"
READER = "ladder_dragon/dashboard/history_reader.py"
HEADERS = {"Authorization": "Bearer test-secret-token"}
PATHS = ["/api/trades/symbols", "/api/trades/recent", "/api/trades/filled", "/api/orders/filled", "/api/fills"]
DIGESTS = {
    "trades_symbols": "3dfed17fba6766da13ee4b27cbf7080fa68afc0ca8f73d8d705ff0eb6e74c7f9",
    "trades_recent": "86445bd101ab8dcae3c2719b215943785678b7ed50308546841ed13152120a49",
    "_select_filled_orders": "9d4a71ba46c06e6ae343a829643595cf23f152d48cc0c532d89e868a552a7e0d",
    "api_trades_filled": "ee72b91d6f00a3981467fe1206de19931f4a31943d51e09990615841cc81ed64",
    "api_orders_filled": "ab740de6712e99e144b6226f123cb12f8413b7f7bc1c2b4bee66a9916a49b65f",
    "api_fills": "2d42ce49a948fd9b61de7f95088ef53746a007061b976cbd7992e46f95dd78ed",
}


@pytest.mark.parametrize("name", DIGESTS)
def test_original_syntax(name):
    tree = ast.parse((ROOT / (READER if name.startswith("_") else ROUTER)).read_text())
    actual = "select_filled_orders" if name.startswith("_") else name
    function = copy.deepcopy(next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == actual))
    class Restore(ast.NodeTransformer):
        def visit_Attribute(self, node):
            if isinstance(node.value, ast.Name) and node.value.id == "state":
                return ast.Name(id=node.attr, ctx=node.ctx)
            return self.generic_visit(node)
        def visit_Call(self, node):
            if isinstance(node.func, ast.Name) and node.func.id == "select_filled_orders":
                node.func.id = "_select_filled_orders"
                node.args = node.args[1:]
            return self.generic_visit(node)
        def visit_Name(self, node):
            return ast.Name(id="app", ctx=node.ctx) if node.id == "router" else node
    if name.startswith("_"):
        function.name = name
        function.args.args = function.args.args[1:]
    assert extraction_digest(ast.Module(body=[Restore().visit(function)], type_ignores=[])) == DIGESTS[name]


@pytest.fixture
def checkout(tmp_path):
    for relative in (RUNTIME, ROUTER, STATE, READER):
        target = tmp_path / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / relative, target)
    return tmp_path


@pytest.mark.parametrize("profile", ["local", "release"])
@pytest.mark.parametrize("damage", [None, "missing", "method", "copy", "reader", "binding", "reverse", "forwarder"])
def test_required_contract(checkout, profile, damage):
    router, runtime, reader = (checkout / p for p in (ROUTER, RUNTIME, READER))
    if damage == "missing":
        reader.unlink()
    elif damage == "method":
        router.write_text(router.read_text().replace('@router.get("/api/fills")', '@router.post("/api/fills")'))
    elif damage == "copy":
        runtime.write_text(runtime.read_text().replace("HistoryRouteState(vars())", "HistoryRouteState(dict(vars()))"))
    elif damage == "reader":
        reader.write_text("def select_filled_orders(*args): return []\n")
    elif damage == "binding":
        router.write_text(router.read_text().replace("from ladder_dragon.dashboard.history_reader import", "from unreviewed import"))
    elif damage == "reverse":
        reader.write_text(reader.read_text() + "\nfrom ladder_dragon.dashboard.runtime import app\n")
    elif damage == "forwarder":
        router.write_text(router.read_text().replace("select_filled_orders(state, hours, syms, limit, offset)", "legacy(hours, syms, limit, offset)"))
    context = HarnessContext(root=checkout, python=sys.executable,
                             options=HarnessOptions(profile=profile, output=checkout / "report.json"))
    spec, = [c for c in checks_for_profile(context) if c.name == "architecture_history_routes"]
    assert spec.required
    status = HarnessRunner(context)._run_spec(spec).status
    assert status is (Status.PASS if damage is None else Status.BLOCKED if damage == "missing" else Status.FAILED)


@pytest.fixture
def history(monkeypatch):
    module = load_dashboard(monkeypatch, "history_route_runtime")
    monkeypatch.setattr(module, "time", SimpleNamespace(time=lambda: 2_000_000_000, monotonic=time.monotonic))
    monkeypatch.setattr(module, "APP_TZ", timezone.utc)
    monkeypatch.setattr(module, "_fee_pct_default", lambda: 0.001)
    connections = []
    class Connection:
        def __init__(self):
            self.closed = False
            self.calls = []
            self.db = sqlite3.connect(":memory:", check_same_thread=False)
            self.db.row_factory = sqlite3.Row
            self.db.execute("CREATE TABLE trades_exact(symbol,side,price_text,gross_qty_text,commission_quote_text,ts)")
            self.db.executemany("INSERT INTO trades_exact VALUES(?,?,?,?,?,?)", [
                ("SOLUSDT", "BUY", "100", "0.1", "0.01", 1_999_999_999_000),
                ("ETHUSDT", "SELL", "200", "0.2", "0", 1_999_996_400),
                ("OLDUSDT", "BUY", "1", "1", "0", 1_999_000_000),
            ])
            self.db.execute("CREATE VIEW trades AS SELECT * FROM trades_exact")
        def execute(self, sql, args=()):
            assert sql.lstrip().startswith("SELECT")
            self.calls.append((sql, args))
            return self.db.execute(sql, args)
        def close(self):
            self.closed = True
            self.db.close()
    def open_db():
        connection = Connection()
        connections.append(connection)
        return connection, "synthetic"
    monkeypatch.setattr(module, "_open_db", open_db)
    return module, TestClient(module.app), connections


@pytest.mark.parametrize("path", PATHS)
def test_auth_before_database(history, path):
    _, client, connections = history
    assert client.get(path).status_code == 401
    assert not connections


@pytest.mark.parametrize("path", PATHS[2:])
def test_aliases_preserve_sql_filter_cutoff_and_pagination(history, path):
    _, client, connections = history
    response = client.get(path, params={"hours": 1, "symbols": " ethusdt ", "limit": 1}, headers=HEADERS)
    assert response.status_code == 200
    assert response.json() == [{"time": 1_999_996_400_000, "symbol": "ETHUSDT", "side": "SELL",
        "price": 200.0, "qty": 0.2, "quoteQty": 40.0, "commission": 0.04, "commissionAsset": "USDT"}]
    assert connections[-1].calls[-1][1] == ["ETHUSDT", 1_999_996_400, 1, 0]
    assert connections[-1].closed
    assert client.get(path, params={"hours": 1, "offset": 2}, headers=HEADERS).json() == []
    assert connections[-1].closed


def test_symbols_and_recent_preserve_mixed_timestamps(history):
    _, client, connections = history
    assert client.get(PATHS[0], params={"hours": 1}, headers=HEADERS).json()["symbols"] == ["ETHUSDT", "SOLUSDT"]
    assert "OLDUSDT" in client.get(PATHS[0], params={"hours": 0}, headers=HEADERS).json()["symbols"]
    row, = client.get(PATHS[1], params={"symbols": "solusdt", "limit": 1}, headers=HEADERS).json()["rows"]
    assert row["ts_s"] == 1_999_999_999 and row["price"] == 100 and row["fee_quote"] == 0.01
    assert all(c.closed for c in connections)


@pytest.mark.parametrize("path", PATHS)
def test_query_error_closes_connection(history, monkeypatch, path):
    module, client, connections = history
    original = module._open_db
    def broken():
        con, p = original()
        def fail(*args):
            raise sqlite3.OperationalError("synthetic-private-detail")
        con.execute = fail
        return con, p
    monkeypatch.setattr(module, "_open_db", broken)
    response = client.get(path, headers=HEADERS)
    assert response.status_code == 503
    assert "synthetic-private-detail" not in response.text
    assert connections[-1].closed


def test_live_binding_and_parameterization(history, monkeypatch):
    module, client, connections = history
    monkeypatch.setattr(module, "_fee_pct_default", lambda: 0.002)
    assert client.get(PATHS[2], params={"symbols": "ETHUSDT"}, headers=HEADERS).json()[0]["commission"] == 0.08
    assert client.get(PATHS[1], params={"symbols": "' OR 1=1 --"}, headers=HEADERS).json()["rows"] == []
    sql, args = connections[-1].calls[-1]
    assert "OR 1=1" not in sql and args[0] == "' OR 1=1 --"


@pytest.mark.parametrize("path", PATHS[:2])
def test_open_failure_is_sanitized(history, monkeypatch, path, capsys):
    module, client, _ = history
    def fail():
        raise ValueError("synthetic-private-detail")
    monkeypatch.setattr(module, "_open_db", fail)
    response = client.get(path, headers=HEADERS)
    assert response.status_code == 503
    assert "synthetic-private-detail" not in response.text + capsys.readouterr().out
