"""Access extraction parity, fail-closed requests, and mandatory wiring."""

import ast
import copy
from collections import defaultdict, deque
from pathlib import Path
import shutil
import sys
from types import SimpleNamespace
import threading

import pytest
from fastapi.testclient import TestClient
from tests.architecture.ast_contracts import extraction_digest
from tests.support.module_loaders import load_dashboard
from ladder_dragon.verification.models import HarnessContext, HarnessOptions, Status
from ladder_dragon.verification.profiles import checks_for_profile
from ladder_dragon.verification.runner import HarnessRunner

ROOT = Path(__file__).resolve().parents[2]
RUNTIME = 'ladder_dragon/dashboard/runtime.py'
ACCESS = 'ladder_dragon/dashboard/access_policy.py'
ROUTER = 'ladder_dragon/dashboard/routers/security.py'
DEPS = 'ladder_dragon/dashboard/security_dependencies.py'
DIGESTS = dict(zip(
    ["_is_loopback_peer","_rate_limit_client","_prune_rate_buckets","authenticate_and_rate_limit","csrf_token"],
    ["01e4cde03d2598833f788d3ddeaca1ebcd94f4c110f6eb0bcfa5417248b2a2b0","3cce9e430e599ed4bff206b0b89fb1abb9d18b8e1e96b9e272d8f45e479aa3d7","9df2b860062e01552c76d53d626e7502d662e2d50b460c61b1e3b37185a6a0db","fe069e34ba4f8c34b756ad4bf2309e9a0e416409a9a8a85474359cdc168a0ef2","3e3d4e9fc69566b68537b6b3556669802ff736a7c4a4f3deaa87d0b097e7e27b"],
))
HEADERS = {'Authorization': 'Bearer test-secret-token'}


@pytest.mark.parametrize('name', list(DIGESTS))
def test_original_access_syntax(name):
    tree = ast.parse((ROOT / (ROUTER if name == 'csrf_token' else ACCESS)).read_text())
    node = copy.deepcopy(next(n for n in ast.walk(tree)
                            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == name))
    class Restore(ast.NodeTransformer):
        def visit_Attribute(self, n):
            if isinstance(n.value, ast.Name) and n.value.id == 'state':
                return ast.Name(id=n.attr, ctx=n.ctx)
            return self.generic_visit(n)
        def visit_Call(self, n):
            if isinstance(n.func, ast.Name) and n.func.id == '_prune_rate_buckets':
                n.args.pop(0)
            return self.generic_visit(n)
        def visit_Name(self, n):
            return ast.Name(id='app', ctx=n.ctx) if n.id == 'router' else n
    node = Restore().visit(node)
    if name == '_prune_rate_buckets':
        node.args.args.pop(0)
    if name == 'authenticate_and_rate_limit':
        node.decorator_list = [ast.parse('app.middleware("http")').body[0].value]
    assert extraction_digest(ast.Module(body=[node], type_ignores=[])) == DIGESTS[name]


@pytest.mark.parametrize('profile', ['local', 'release'])
@pytest.mark.parametrize('damage', [
    None, 'missing', 'copy', 'scope', 'reverse', 'method', 'duplicate',
    'detached', 'middleware_copy', 'middleware_stub', 'helper_stub', 'adapter_copy',
])
def test_required_access_contract(tmp_path, profile, damage):
    for path in (RUNTIME, ACCESS, ROUTER, DEPS):
        target = tmp_path / path
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / path, target)
    runtime, access, router, deps = (tmp_path / p for p in (RUNTIME, ACCESS, ROUTER, DEPS))
    if damage == 'missing':
        access.unlink()
    elif damage == 'copy':
        runtime.write_text(runtime.read_text().replace('SecurityRouteState(vars())', 'SecurityRouteState(dict(vars()))'))
    elif damage == 'scope':
        deps.write_text(deps.read_text().replace("'time'", "'os'"))
    elif damage == 'reverse':
        access.write_text(access.read_text() + '\nfrom ladder_dragon.dashboard.runtime import app\n')
    elif damage == 'method':
        router.write_text(router.read_text().replace('@router.get(', '@router.post('))
    elif damage == 'duplicate':
        runtime.write_text(runtime.read_text() + '\n@app.get("/api/security/csrf")\ndef duplicate(): return {}\n')
    elif damage == 'detached':
        runtime.write_text(runtime.read_text().replace('app.middleware("http")(build_access_middleware(AccessState(vars())))', ''))
    elif damage == 'middleware_copy':
        runtime.write_text(runtime.read_text().replace('AccessState(vars())', 'AccessState(dict(vars()))'))
    elif damage in ('middleware_stub', 'helper_stub'):
        tree = ast.parse(access.read_text())
        name = 'authenticate_and_rate_limit' if damage == 'middleware_stub' else '_rate_limit_client'
        n = next(n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == name)
        n.body = ast.parse('return unsafe()').body
        access.write_text(ast.unparse(tree))
    elif damage == 'adapter_copy':
        deps.write_text(deps.read_text().replace('return self._namespace[name]', 'return None'))
    context = HarnessContext(root=tmp_path, python=sys.executable,
                             options=HarnessOptions(profile=profile, output=tmp_path / 'report.json'))
    spec, = [s for s in checks_for_profile(context) if s.name == 'architecture_security_routes']
    assert spec.required
    result = HarnessRunner(context)._run_spec(spec)
    expected = Status.PASS if damage is None else Status.BLOCKED if damage == 'missing' else Status.FAILED
    assert result.status is expected, result.metrics


def test_current_tokens_and_rate_resources(monkeypatch):
    r = load_dashboard(monkeypatch, 'access_live')
    client = TestClient(r.app)
    assert client.get('/api/security/csrf').status_code == 401
    r.DASHBOARD_AUTH_TOKEN = 'synthetic-replacement'
    r.DASHBOARD_CSRF_TOKEN = 'synthetic-csrf'
    r.DASHBOARD_RATE_LIMIT_PER_MIN = 1
    r._RATE_BUCKETS = defaultdict(deque)
    r._RATE_PRUNE_STATE = {'last': 0}
    r._RATE_LOCK = threading.Lock()
    assert client.get('/api/security/csrf', headers=HEADERS).status_code == 401
    headers = {'X-Dashboard-Token': 'synthetic-replacement'}
    response = client.get('/api/security/csrf', headers=headers)
    assert response.json() == {'ok': True, 'csrf_token': 'synthetic-csrf'}
    limited = client.get('/api/security/csrf', headers=headers)
    assert limited.status_code == 429 and int(limited.headers['Retry-After']) >= 1
    r._RATE_BUCKETS = defaultdict(deque)
    assert client.get('/api/security/csrf', headers=headers).status_code == 200
    r.DASHBOARD_AUTH_TOKEN = ''
    r.DASHBOARD_TRUST_PROXY_AUTH = False
    assert client.get('/api/security/csrf', headers=headers).status_code == 503
    assert client.get('/non-api-path').status_code == 404


@pytest.mark.parametrize('peer,secret,expected', [
    ('127.0.0.1', 'synthetic-proxy', 200), ('::1', 'synthetic-proxy', 200),
    ('192.0.2.1', 'synthetic-proxy', 401), ('127.0.0.1', 'wrong', 401),
])
def test_proxy_boundary(monkeypatch, peer, secret, expected):
    r = load_dashboard(monkeypatch, 'access_proxy')
    r.DASHBOARD_AUTH_TOKEN = ''
    r.DASHBOARD_TRUST_PROXY_AUTH = True
    r.DASHBOARD_PROXY_AUTH_SECRET = 'synthetic-proxy'
    response = TestClient(r.app, client=(peer, 321)).get('/api/security/csrf', headers={
        'X-Authenticated-User': 'synthetic-user', 'X-Dashboard-Proxy-Secret': secret,
        'X-Real-IP': '198.51.100.5',
    })
    assert response.status_code == expected
    assert 'synthetic-proxy' not in response.text
    if expected == 200:
        assert list(r._RATE_BUCKETS) == ['198.51.100.5']


@pytest.mark.parametrize('change,expected', [
    ({}, 200), ({'Content-Type': 'text/plain'}, 415),
    ({'Origin': 'https://other.invalid'}, 403),
    ({'Origin': ''}, 403), ({'Sec-Fetch-Site': 'cross-site'}, 403),
    ({'X-CSRF-Token': ''}, 403), ({'X-CSRF-Token': 'wrong'}, 403),
])
def test_request_forgery_rejected_before_consumer(monkeypatch, change, expected):
    r = load_dashboard(monkeypatch, 'access_post')
    calls = []
    @r.app.post('/api/synthetic')
    def consumer():
        calls.append(True)
        return {'ok': True}
    client = TestClient(r.app)
    csrf = client.get('/api/security/csrf', headers=HEADERS).json()['csrf_token']
    headers = {**HEADERS, 'Content-Type': 'application/json', 'Origin': 'http://testserver',
               'Sec-Fetch-Site': 'same-origin', 'X-CSRF-Token': csrf, **change}
    response = client.post('/api/synthetic', headers=headers, json={})
    assert response.status_code == expected
    assert calls == ([True] if expected == 200 else [])
    if expected != 200:
        assert csrf not in response.text


def test_access_adapter_hides_values_and_restricts_scope():
    from ladder_dragon.dashboard.security_dependencies import AccessState
    state = AccessState({'DASHBOARD_AUTH_TOKEN': 'synthetic-private'})
    assert 'synthetic-private' not in repr(state)
    with pytest.raises(AttributeError):
        _ = state.os
