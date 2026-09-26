"""Advisory-control parity, application gates, and live writer bindings."""

import ast
import copy
from pathlib import Path
import shutil
import sys

import pytest
from fastapi.testclient import TestClient
from ladder_dragon.verification.models import HarnessContext, HarnessOptions, Status
from ladder_dragon.verification.profiles import checks_for_profile
from ladder_dragon.verification.runner import HarnessRunner
from tests.architecture.ast_contracts import extraction_digest
from tests.support.module_loaders import load_dashboard

ROOT = Path(__file__).resolve().parents[2]
RUNTIME = "ladder_dragon/dashboard/runtime.py"
ROUTER = "ladder_dragon/dashboard/routers/control.py"
STATE = "ladder_dragon/dashboard/control_dependencies.py"
SNAPSHOT = "ladder_dragon/dashboard/control_snapshot.py"
DIGESTS = {
    "_ai_control_snapshot": "45d68ceb1371eb4e2a513d7f538c41d65de8cdf8e4e8a518c5686c40cf4cf74f",
    "ai_control": "b61bb444b75e39649b8c7b950ea0440d72f7536aec9f55793f9237341e001836",
    "set_ai_control": "35549848872763525b244606a26b1914c81ee591964f386b0e0d605c38394ba5",
}


@pytest.mark.parametrize("name", DIGESTS)
def test_original_syntax(name):
    tree = ast.parse((ROOT / (SNAPSHOT if name.startswith("_") else ROUTER)).read_text())
    actual = "control_snapshot" if name.startswith("_") else name
    node = copy.deepcopy(next(n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == actual))
    class Restore(ast.NodeTransformer):
        def visit_Attribute(self, n):
            if isinstance(n.value, ast.Name) and n.value.id == "state":
                return ast.Name(id=n.attr, ctx=n.ctx)
            return self.generic_visit(n)
        def visit_Call(self, n):
            if isinstance(n.func, ast.Name) and n.func.id == "control_snapshot":
                n.func.id = "_ai_control_snapshot"
                n.args = []
            return self.generic_visit(n)
        def visit_Name(self, n):
            return ast.Name(id="app", ctx=n.ctx) if n.id == "router" else n
    if name.startswith("_"):
        node.name = name
        node.args.args = []
    assert extraction_digest(ast.Module(body=[Restore().visit(node)], type_ignores=[])) == DIGESTS[name]


@pytest.fixture
def checkout(tmp_path):
    for p in (RUNTIME, ROUTER, STATE, SNAPSHOT):
        target = tmp_path / p
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / p, target)
    return tmp_path


@pytest.mark.parametrize("profile", ["local", "release"])
@pytest.mark.parametrize("damage", [None, "missing", "method", "async", "copy", "snapshot", "binding", "reverse"])
def test_required_contract(checkout, profile, damage):
    router, runtime, snapshot = (checkout / p for p in (ROUTER, RUNTIME, SNAPSHOT))
    if damage == "missing":
        snapshot.unlink()
    elif damage == "method":
        router.write_text(router.read_text().replace('@router.post(', '@router.get('))
    elif damage == "async":
        tree = ast.parse(router.read_text())
        factory = next(n for n in tree.body if isinstance(n, ast.FunctionDef))
        for i, n in enumerate(factory.body):
            if isinstance(n, ast.AsyncFunctionDef):
                factory.body[i] = ast.FunctionDef(name=n.name, args=n.args, body=[ast.Return(value=ast.Constant(None))], decorator_list=n.decorator_list)
        router.write_text(ast.unparse(ast.fix_missing_locations(tree)))
    elif damage == "copy":
        runtime.write_text(runtime.read_text().replace("ControlRouteState(vars())", "ControlRouteState(dict(vars()))"))
    elif damage == "snapshot":
        snapshot.write_text("def control_snapshot(state): return {}\n")
    elif damage == "binding":
        router.write_text(router.read_text().replace("from ladder_dragon.dashboard.control_snapshot import", "from unreviewed import"))
    elif damage == "reverse":
        snapshot.write_text(snapshot.read_text() + "\nfrom ladder_dragon.dashboard.runtime import app\n")
    context = HarnessContext(root=checkout, python=sys.executable,
                             options=HarnessOptions(profile=profile, output=checkout / "report.json"))
    spec, = [c for c in checks_for_profile(context) if c.name == "architecture_control_routes"]
    assert spec.required
    assert HarnessRunner(context)._run_spec(spec).status is (
        Status.PASS if damage is None else Status.BLOCKED if damage == "missing" else Status.FAILED)


@pytest.fixture
def control(monkeypatch, tmp_path):
    module = load_dashboard(monkeypatch, "control_route_runtime")
    events = []
    monkeypatch.setattr(module, "AI_CONTROL_FILE", tmp_path / "synthetic-control.json")
    monkeypatch.setattr(module, "_load_ai_runtime_status", lambda: {"ai": {"enabled": True, "configured_mode": "SHADOW"}})
    def read(path):
        events.append(("read", path))
        return None
    def write(path, **kw):
        events.append(("write", path, kw))
        return {**kw, "updated_at": "synthetic-time"}
    monkeypatch.setattr(module, "read_ai_control", read)
    monkeypatch.setattr(module, "write_ai_control", write)
    client = TestClient(module.app)
    headers = {"Authorization": "Bearer test-secret-token", "Origin": "http://testserver",
               "X-CSRF-Token": module.DASHBOARD_CSRF_TOKEN}
    return module, client, headers, events


@pytest.mark.parametrize("gate,expected", [("auth", 401), ("csrf", 403), ("origin", 403), ("fetch", 403), ("content", 415)])
def test_gates_precede_read_and_write(control, gate, expected):
    _, client, headers, events = control
    if gate == "auth":
        headers.pop("Authorization")
    elif gate == "csrf":
        headers.pop("X-CSRF-Token")
    elif gate == "origin":
        headers["Origin"] = "https://synthetic.invalid"
    elif gate == "fetch":
        headers["Sec-Fetch-Site"] = "cross-site"
    else:
        headers["Content-Type"] = "text/plain"
    response = client.post("/api/ai/control", headers=headers, json={"enabled": True})
    assert response.status_code == expected and not events


@pytest.mark.parametrize("payload", [None, [], {}, {"enabled": "false"}, {"enabled": 1}])
def test_boolean_validation_precedes_writer(control, payload):
    _, client, headers, events = control
    response = client.post("/api/ai/control", headers={**headers, "Content-Type": "application/json"}, json=payload)
    assert response.status_code == 400
    assert not any(e[0] == "write" for e in events)


@pytest.mark.parametrize("configured,mode", [(False, "SHADOW"), (True, "DISABLED")])
def test_not_configured_precedes_body_and_writer(control, monkeypatch, configured, mode):
    module, client, headers, events = control
    monkeypatch.setattr(module, "_load_ai_runtime_status", lambda: {"ai": {"enabled": configured, "configured_mode": mode}})
    response = client.post("/api/ai/control", headers={**headers, "Content-Type": "application/json"}, content="not-json")
    assert response.status_code == 409
    assert not any(e[0] == "write" for e in events)


def test_live_path_mode_and_writer(control, monkeypatch, tmp_path):
    module, client, headers, events = control
    path = tmp_path / "replacement.json"
    monkeypatch.setattr(module, "AI_CONTROL_FILE", path)
    monkeypatch.setattr(module, "_load_ai_runtime_status", lambda: {"ai": {"enabled": True, "configured_mode": "SHADOW"}})
    response = client.post("/api/ai/control", headers=headers, json={"enabled": False, "mode": "APPLY"})
    assert response.status_code == 200
    assert response.json() == {"ok": True, "configured": True, "enabled": False, "mode": "SHADOW", "updated_at": "synthetic-time"}
    assert events == [("read", path), ("write", path, {"enabled": False, "mode": "SHADOW"})]


@pytest.mark.parametrize("operation", ["read", "write"])
def test_safe_failure(control, monkeypatch, operation, capsys):
    module, client, headers, _ = control
    def fail(*a, **kw):
        raise OSError("synthetic-private-detail")
    monkeypatch.setattr(module, operation + "_ai_control", fail)
    response = (client.get("/api/ai/control", headers=headers) if operation == "read" else
                client.post("/api/ai/control", headers=headers, json={"enabled": True}))
    assert response.status_code == 503
    assert "synthetic-private-detail" not in response.text + capsys.readouterr().out


def test_snapshot_replacement_and_rate_limit(control, monkeypatch):
    module, client, headers, events = control
    monkeypatch.setattr(module, "read_ai_control", lambda path: {"enabled": False, "updated_at": "synthetic-time"})
    response = client.get("/api/ai/control", headers=headers)
    assert response.json()["enabled"] is False and response.json()["mode"] == "DISABLED"
    monkeypatch.setattr(module, "DASHBOARD_RATE_LIMIT_PER_MIN", 1)
    assert client.post("/api/ai/control", headers=headers, json={"enabled": True}).status_code == 429
    assert not any(e[0] == "write" for e in events)
