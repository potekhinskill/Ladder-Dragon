"""Read-model route parity, stale responses, and required ownership."""

import ast
import copy
from pathlib import Path
import shutil
import sys

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from ladder_dragon.dashboard.routers.trading import build_trading_router
from ladder_dragon.dashboard.trading_dependencies import TradingRouteState
from ladder_dragon.verification.architecture.trading_routes import TRADING_PATHS
from ladder_dragon.verification.models import HarnessContext, HarnessOptions, Status
from ladder_dragon.verification.profiles import checks_for_profile
from ladder_dragon.verification.runner import HarnessRunner
from tests.architecture.ast_contracts import extraction_digest
from tests.support.module_loaders import load_dashboard

ROOT = Path(__file__).resolve().parents[2]
RUNTIME = "ladder_dragon/dashboard/runtime.py"
ROUTER = "ladder_dragon/dashboard/routers/trading.py"
STATE = "ladder_dragon/dashboard/trading_dependencies.py"
DIGESTS = {
    "trading_overview": "df1dba9e840bd840f0416327b4af462fe08e0c772f8358f153d605da0fe49eba",
    "account_balances": "4d0604ca35322185cf5d45ceab22994cfea7b90254adbeecabc7dcc7efb7d3ae",
    "account_open_orders": "e5497bbbbed12ac3cc3b35acfda021613d77d53b3f97ab5051f1a18b49372c2c",
    "market_scenarios": "829d82671b9f62a7f2fd650520f688c4f44a462212d5030befa2bca40f20801b"
}


@pytest.mark.parametrize("name", DIGESTS)
def test_original_handler_syntax(name):
    tree = ast.parse((ROOT / ROUTER).read_text())
    function = copy.deepcopy(next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == name))
    class Restore(ast.NodeTransformer):
        def visit_Attribute(self, node):
            if isinstance(node.value, ast.Name) and node.value.id == "state":
                return ast.Name(id=node.attr, ctx=node.ctx)
            return self.generic_visit(node)
        def visit_Name(self, node):
            return ast.Name(id="app", ctx=node.ctx) if node.id == "router" else node
    assert extraction_digest(ast.Module(body=[Restore().visit(function)], type_ignores=[])) == DIGESTS[name]


@pytest.fixture
def checkout(tmp_path):
    for relative in (RUNTIME, ROUTER, STATE):
        target = tmp_path / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / relative, target)
    return tmp_path


def _check(root, profile):
    context = HarnessContext(root=root, python=sys.executable,
                             options=HarnessOptions(profile=profile, output=root / "report.json"))
    spec, = [c for c in checks_for_profile(context) if c.name == "architecture_trading_routes"]
    assert spec.required
    return HarnessRunner(context)._run_spec(spec).status


@pytest.mark.parametrize("profile", ["local", "release"])
def test_valid_fixture(checkout, profile):
    assert _check(checkout, profile) is Status.PASS


@pytest.mark.parametrize("profile", ["local", "release"])
@pytest.mark.parametrize("damage", ["missing", "reverse", "forwarder", "method", "copy", "scope", "binding", "resolution", "duplicate"])
def test_required_rejection(checkout, profile, damage):
    route, runtime, state = (checkout / p for p in (ROUTER, RUNTIME, STATE))
    if damage == "missing":
        state.unlink()
    elif damage == "reverse":
        route.write_text(route.read_text() + "\nfrom ladder_dragon.dashboard.runtime import app\n")
    elif damage == "forwarder":
        tree = ast.parse(route.read_text())
        n = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "account_balances")
        n.body = ast.parse("return legacy()").body
        route.write_text(ast.unparse(tree))
    elif damage == "method":
        route.write_text(route.read_text().replace('@router.get("/api/account/balances")', '@router.post("/api/account/balances")'))
    elif damage == "copy":
        runtime.write_text(runtime.read_text().replace("TradingRouteState(vars())", "TradingRouteState(dict(vars()))"))
    elif damage == "scope":
        state.write_text(state.read_text().replace("'_BALANCE_CACHE',", "'DASHBOARD_AUTH_TOKEN',"))
    elif damage == "binding":
        runtime.write_text(runtime.read_text().replace("from ladder_dragon.dashboard.routers.trading import", "from unreviewed import"))
    elif damage == "resolution":
        state.write_text(state.read_text().replace("return self._namespace[name]", "return None"))
    else:
        runtime.write_text(runtime.read_text() + '\n@app.get("/api/account/balances")\ndef decoy(): return {}\n')
    assert _check(checkout, profile) is (Status.BLOCKED if damage == "missing" else Status.FAILED)


def client(namespace):
    app = FastAPI()
    app.include_router(build_trading_router(TradingRouteState(namespace)))
    return TestClient(app)


@pytest.mark.parametrize("path,reader", [
    ("/api/trading/overview", "trading_overview_snapshot"),
    ("/api/account/balances", "account_balances_snapshot"),
    ("/api/account/open-orders", "account_open_orders_snapshot"),
    ("/api/market/scenarios", "market_analysis_snapshot"),
])
def test_live_reader_and_authentication(path, reader, monkeypatch):
    runtime = load_dashboard(monkeypatch, "trading_route_auth")
    def forbidden():
        raise AssertionError("Unauthorized read")
    monkeypatch.setattr(runtime, reader, forbidden)
    c = TestClient(runtime.app)
    assert c.get(path).status_code == 401
    monkeypatch.setattr(runtime, reader, lambda: {"revision": 2, "can_change_orders": False})
    response = c.get(path, headers={"Authorization": "Bearer test-secret-token"})
    assert response.status_code == 200
    assert response.json() == {"revision": 2, "can_change_orders": False}


@pytest.mark.parametrize("kind", ["balances", "open-orders"])
@pytest.mark.parametrize("stale", [False, True])
def test_stale_policy_current_cache_lock_and_safe_failure(kind, stale, capsys):
    balance = kind == "balances"
    reader = "account_balances_snapshot" if balance else "account_open_orders_snapshot"
    cache_name = "_BALANCE_CACHE" if balance else "_OPEN_ORDERS_CACHE"
    error = "ACCOUNT_BALANCE_FAILED" if balance else "OPEN_ORDERS_FAILED"
    reason = "ACCOUNT_BALANCE_STALE" if balance else "OPEN_ORDERS_STALE"
    def failure():
        raise ValueError("synthetic-private-provider-body")
    calls = []
    namespace = {reader: failure, "_DATA_SOURCE_ERRORS": (ValueError,),
                 cache_name: {"old": True}, cache_name + "_LOCK": object()}
    c = client(namespace)
    replacement, lock = {}, object()
    namespace.update({cache_name: replacement, cache_name + "_LOCK": lock})
    def fallback(cache, actual_lock, actual_reason):
        assert cache is replacement and actual_lock is lock and actual_reason == reason
        calls.append(True)
        return {"ok": True, "stale": True} if stale else None
    namespace["_stale_binance_snapshot"] = fallback
    response = c.get("/api/account/" + kind)
    assert calls == [True]
    assert response.status_code == (200 if stale else 503)
    if stale:
        assert response.json() == {"ok": True, "stale": True}
        label = "balance" if balance else "open-orders"
        assert response.headers["Warning"] == '110 - "stale Binance ' + label + ' snapshot"'
    else:
        assert response.json() == {"ok": False, "error": error}
        assert "Warning" not in response.headers
    output = capsys.readouterr().out
    assert "type=ValueError" in output
    assert "synthetic-private-provider-body" not in response.text + output


def test_overview_failure_is_sanitized(capsys):
    def fail():
        raise ValueError("synthetic-private-detail")
    response = client({"trading_overview_snapshot": fail, "_DATA_SOURCE_ERRORS": (ValueError,)}).get("/api/trading/overview")
    assert response.status_code == 503
    assert response.json() == {"ok": False, "error": "TRADING_OVERVIEW_FAILED"}
    assert "synthetic-private-detail" not in capsys.readouterr().out + response.text


@pytest.mark.parametrize("reader,path", [
    ("trading_overview_snapshot", "/api/trading/overview"),
    ("account_balances_snapshot", "/api/account/balances"),
    ("account_open_orders_snapshot", "/api/account/open-orders"),
])
def test_programming_error_is_not_hidden(reader, path):
    def fail():
        raise AttributeError("synthetic programming error")
    with pytest.raises(AttributeError):
        client({reader: fail, "_DATA_SOURCE_ERRORS": (ValueError,)}).get(path)


def test_dependency_scope_is_not_the_runtime_namespace():
    state = TradingRouteState({"DASHBOARD_AUTH_TOKEN": "synthetic-private"})
    with pytest.raises(AttributeError):
        _ = state.DASHBOARD_AUTH_TOKEN
    assert "synthetic-private" not in repr(state)


def test_existing_middleware_limits_trading_routes(monkeypatch):
    runtime = load_dashboard(monkeypatch, "trading_rate")
    monkeypatch.setattr(runtime, "DASHBOARD_RATE_LIMIT_PER_MIN", 1)
    monkeypatch.setattr(runtime, "market_analysis_snapshot", lambda: {"mode": "SHADOW"})
    c = TestClient(runtime.app)
    headers = {"Authorization": "Bearer test-secret-token"}
    assert c.get("/api/market/scenarios", headers=headers).status_code == 200
    assert c.get("/api/market/scenarios", headers=headers).status_code == 429
