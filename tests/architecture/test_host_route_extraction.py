"""Concrete host handlers, live dependencies, and authenticated route parity."""

import ast
from collections import Counter
import copy
from dataclasses import FrozenInstanceError
import json
from pathlib import Path
import shutil
import sys
from types import SimpleNamespace
import threading

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from ladder_dragon.dashboard.host_dependencies import HostRouteState
from ladder_dragon.dashboard.routers.host import build_host_router
from ladder_dragon.verification.architecture.host_routes import RUNTIME, ROUTER, STATE, HOST_PATHS
from ladder_dragon.verification.models import HarnessContext, HarnessOptions, Status
from ladder_dragon.verification.profiles import checks_for_profile
from ladder_dragon.verification.runner import HarnessRunner
from tests.architecture.ast_contracts import extraction_digest
from tests.support.module_loaders import load_dashboard, dashboard_route_contexts

ROOT = Path(__file__).resolve().parents[2]
DIGESTS = {
    "update_check": "cb059e7a6d9f4740a0e42ecf2a2035c9e2c02245dd90e54fb534435de69ae071",
    "health": "db270e2a870c34a4780ebbf608f0ba613ce884e720b17d6e337f6fc7478c0bab",
    "history": "ce5d18afac793ea8a3cfb1977c1c5f28bc11abbacfcef5fa44b6fd0182fefd62"
}
ROUTES = [["get","/api/security/csrf"],["get","/api/trading/overview"],["get","/api/update/check"],["get","/api/health"],["get","/api/account/balances"],["get","/api/account/open-orders"],["get","/api/history"],["get","/api/ai/status"],["get","/api/market/scenarios"],["get","/api/ai/control"],["post","/api/ai/control"],["get","/api/trades/symbols"],["get","/api/trades/summary"],["get","/api/trades/recent"],["get","/api/trades/filled"],["get","/api/orders/filled"],["get","/api/fills"]]


@pytest.mark.parametrize("name", DIGESTS)
def test_original_route_syntax(name):
    tree = ast.parse((ROOT / ROUTER).read_text())
    function = copy.deepcopy(next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == name))
    class Restore(ast.NodeTransformer):
        def visit_Attribute(self, node):
            if isinstance(node.value, ast.Name) and node.value.id == "state":
                return ast.Name(id=node.attr, ctx=node.ctx)
            return self.generic_visit(node)
        def visit_Name(self, node):
            return ast.Name(id="app", ctx=node.ctx) if node.id == "router" else node
    function = Restore().visit(function)
    assert extraction_digest(ast.Module(body=[function], type_ignores=[])) == DIGESTS[name]


def _check(root, profile):
    context = HarnessContext(root=root, python=sys.executable, options=HarnessOptions(
        profile=profile, output=root / "report.json"))
    spec, = [s for s in checks_for_profile(context) if s.name == "architecture_host_routes"]
    assert spec.required
    return HarnessRunner(context)._run_spec(spec).status


@pytest.fixture
def checkout(tmp_path):
    for relative in (RUNTIME, ROUTER, STATE):
        target = tmp_path / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / relative, target)
    return tmp_path


@pytest.mark.parametrize("profile", ["local", "release"])
def test_complete_fixture(checkout, profile):
    assert _check(checkout, profile) is Status.PASS


@pytest.mark.parametrize("profile", ["local", "release"])
@pytest.mark.parametrize("damage", ["missing", "reverse", "forwarder", "method", "copy", "scope", "binding", "resolution", "duplicate"])
def test_required_rejection(checkout, profile, damage):
    route = checkout / ROUTER
    runtime = checkout / RUNTIME
    state = checkout / STATE
    if damage == "missing":
        route.unlink()
    elif damage == "reverse":
        route.write_text(route.read_text() + "\nfrom ladder_dragon.dashboard.runtime import app\n")
    elif damage == "forwarder":
        tree = ast.parse(route.read_text())
        node = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "health")
        node.body = ast.parse("return legacy()").body
        route.write_text(ast.unparse(tree))
    elif damage == "method":
        route.write_text(route.read_text().replace('@router.get("/api/history")', '@router.post("/api/history")'))
    elif damage == "copy":
        runtime.write_text(runtime.read_text().replace("HostRouteState(vars())", "HostRouteState(dict(vars()))"))
    elif damage == "scope":
        state.write_text(state.read_text().replace('"HIST_FILE",', '"DASHBOARD_AUTH_TOKEN",'))
    elif damage == "binding":
        runtime.write_text(runtime.read_text().replace("from ladder_dragon.dashboard.routers.host import", "from unreviewed import"))
    elif damage == "resolution":
        state.write_text(state.read_text().replace("return self._namespace[name]", "return None"))
    else:
        runtime.write_text(runtime.read_text() + '\n@app.get("/api/health")\ndef decoy(): return {}\n')
    assert _check(checkout, profile) is (Status.BLOCKED if damage == "missing" else Status.FAILED)


def test_state_resolves_replacements_without_exposing_unlisted_values():
    namespace = {"HIST_FILE": "old", "_OPS_CACHE": {}, "DASHBOARD_AUTH_TOKEN": "synthetic-private"}
    state = HostRouteState(namespace)
    replacement = {}
    namespace.update(HIST_FILE="new", _OPS_CACHE=replacement)
    assert state.HIST_FILE == "new" and state._OPS_CACHE is replacement
    with pytest.raises(AttributeError):
        _ = state.DASHBOARD_AUTH_TOKEN
    with pytest.raises(FrozenInstanceError):
        state.HIST_FILE = "bad"
    assert "synthetic-private" not in repr(state)


def test_runtime_keeps_complete_route_inventory(monkeypatch):
    runtime = load_dashboard(monkeypatch, "host_inventory")
    observed = Counter((method.lower(), r.path) for r in dashboard_route_contexts(runtime.app) for method in r.methods)
    assert observed == Counter(tuple(r) for r in ROUTES)


@pytest.mark.parametrize("path", HOST_PATHS.values())
def test_global_auth_blocks_before_host_reads(monkeypatch, path):
    runtime = load_dashboard(monkeypatch, "host_auth")
    monkeypatch.setattr(runtime, "DASHBOARD_TRUST_PROXY_AUTH", False)
    def forbidden(*a, **kw):
        raise AssertionError("Unauthorized host read")
    for name in ("_github_update_snapshot", "read_temp_c", "load_history_payload"):
        monkeypatch.setattr(runtime, name, forbidden)
    response = TestClient(runtime.app).get(path)
    assert response.status_code == 401
    assert "test-secret-token" not in response.text


def test_rate_limit_still_wraps_extracted_route(monkeypatch):
    runtime = load_dashboard(monkeypatch, "host_rate")
    monkeypatch.setattr(runtime, "DASHBOARD_RATE_LIMIT_PER_MIN", 1)
    monkeypatch.setattr(runtime, "_github_update_snapshot", lambda: {"status": "synthetic"})
    client = TestClient(runtime.app)
    headers = {"Authorization": "Bearer test-secret-token"}
    assert client.get("/api/update/check", headers=headers).status_code == 200
    assert client.get("/api/update/check", headers=headers).status_code == 429


@pytest.mark.parametrize("fail", [False, True])
def test_history_current_path_cleanup_and_failure(fail):
    closed = []
    seen = []
    connection = SimpleNamespace(close=lambda: closed.append(True))
    def history(path, **kw):
        seen.append((path, kw))
        return {"_epochs": [123], "labels": ["synthetic"]}
    def volume(con, epochs):
        assert con is connection and epochs == [123]
        if fail:
            raise ValueError("synthetic-private-failure")
        return ["12.50"]
    namespace = {"HIST_FILE": "old", "APP_TZ": None, "load_history_payload": history,
                 "_open_db": lambda: (connection, "synthetic"),
                 "rolling_trade_volume_24h_usdt": volume}
    app = FastAPI()
    app.include_router(build_host_router(HostRouteState(namespace)))
    namespace["HIST_FILE"] = "replacement"
    response = TestClient(app).get("/api/history?hours=999&points=17")
    assert response.status_code == 200 and closed == [True]
    payload = response.json()
    assert payload["trading_volume_24h_status"] == ("unavailable" if fail else "exact")
    assert payload["trading_volume_24h_usdt"] == ([None] if fail else ["12.50"])
    assert seen[0][0] == "replacement" and seen[0][1]["points"] == 17
    assert "synthetic-private-failure" not in response.text and "_epochs" not in payload


def test_updated_reader_binding_is_observed():
    namespace = {"_github_update_snapshot": lambda: {"revision": 1}}
    app = FastAPI()
    app.include_router(build_host_router(HostRouteState(namespace)))
    client = TestClient(app)
    assert client.get("/api/update/check").json() == {"revision": 1}
    namespace["_github_update_snapshot"] = lambda: {"revision": 2}
    assert client.get("/api/update/check").json() == {"revision": 2}


def test_health_replacement_cache_and_lock(monkeypatch):
    from ladder_dragon.dashboard.routers import host
    metric = SimpleNamespace(total=1024, used=512, percent=50)
    monkeypatch.setattr(host.psutil, "virtual_memory", lambda: metric)
    monkeypatch.setattr(host.psutil, "swap_memory", lambda: metric)
    monkeypatch.setattr(host.psutil, "boot_time", lambda: 0)
    monkeypatch.setattr(host.shutil, "disk_usage", lambda p: metric)
    calls = []
    class Lock:
        def __enter__(self):
            calls.append("lock")
        def __exit__(self, *exc):
            calls.append("unlock")
    namespace = {"_OPS_CACHE": {"payload": {"marker": 1}, "ts": host.time.monotonic()},
                 "_OPS_CACHE_LOCK": threading.Lock(), "_OPS_CACHE_TTL_SEC": 999,
                 "read_temp_c": lambda: 42, "network_ok": lambda: False, "PRODUCT_NAME": "synthetic",
                 "__version__": "test", "now_str": lambda: "synthetic", "_host_snapshot": lambda: {},
                 "parse_throttled": lambda: {}, "GiB": 1024, "mounts_info": lambda: [],
                 "service_active": lambda n: "active", "fail2ban_bans": lambda n: 0,
                 "read_deployment_status": lambda: {}}
    app = FastAPI()
    app.include_router(build_host_router(HostRouteState(namespace)))
    replacement = {"payload": {"marker": 2, "binance": {"ok": True}}, "ts": host.time.monotonic()}
    namespace.update(_OPS_CACHE=replacement, _OPS_CACHE_LOCK=Lock())
    response = TestClient(app).get("/api/health")
    assert response.json()["operations"]["marker"] == 2
    assert response.json()["network_ok"] is True and response.json()["network_probe_ok"] is False
    assert calls == ["lock", "unlock"]
