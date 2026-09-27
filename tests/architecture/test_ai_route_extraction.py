"""AI-status producer/consumer parity and required component contracts."""

import ast
import copy
from datetime import datetime, timezone
from pathlib import Path
import shutil
import sqlite3
import sys
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from tests.architecture.ast_contracts import extraction_digest
from tests.support.module_loaders import load_dashboard
from ladder_dragon.verification.models import HarnessContext, HarnessOptions, Status
from ladder_dragon.verification.profiles import checks_for_profile
from ladder_dragon.verification.runner import HarnessRunner

ROOT = Path(__file__).resolve().parents[2]
PREFIX = 'ladder_dragon/dashboard/'
FILES = ['runtime.py', 'routers/ai.py', 'ai_dependencies.py',
         'ai_status_context.py', 'ai_status_reader.py', 'ai_status_policy.py']
HEADERS = {'Authorization': 'Bearer test-secret-token'}


def function(path, name):
    return copy.deepcopy(next(n for n in ast.walk(ast.parse((ROOT / PREFIX / path).read_text()))
                              if isinstance(n, ast.FunctionDef) and n.name == name))


def test_reassembled_original_function():
    route = function('routers/ai.py', 'ai_status')
    context = function('ai_status_context.py', 'runtime_context')
    reader = function('ai_status_reader.py', 'read_ai_decisions')
    policy = function('ai_status_policy.py', 'policy_summary')
    body = []
    for node in route.body:
        call = node.value if isinstance(node, ast.Assign) and isinstance(node.value, ast.Call) else None
        if call and isinstance(call.func, ast.Name) and call.func.id == 'runtime_context':
            body.extend(context.body[:-1])
        elif call and isinstance(call.func, ast.Name) and call.func.id == 'policy_summary':
            body.extend(policy.body[:-1])
        elif isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name) and node.targets[0].id == 'db_path':
            body.extend(reader.body[:2])
            body.append(node)
        elif isinstance(node, ast.Try):
            condition = reader.body[2]
            node.body = condition.body
            condition.body = [node]
            body.append(condition)
        else:
            body.append(node)
    route.body = body
    route.decorator_list = [ast.parse('app.get("/api/ai/status")').body[0].value]
    class Restore(ast.NodeTransformer):
        def visit_Attribute(self, node):
            if isinstance(node.value, ast.Name) and node.value.id == 'deps':
                return ast.Name(id=node.attr, ctx=node.ctx)
            return self.generic_visit(node)
    original_digest = '8737204fe51b62ff867924282f17c4fd1fa180b05c2280f5e4c1ebc728746fbb'
    assert extraction_digest(ast.Module(body=[Restore().visit(route)], type_ignores=[])) == original_digest


@pytest.mark.parametrize('profile', ['local', 'release'])
@pytest.mark.parametrize('damage', [None, 'missing', 'stub', 'reverse', 'scope', 'copy',
                                    'detached', 'input', 'unguarded', 'method', 'duplicate'])
def test_required_components(tmp_path, profile, damage):
    for path in FILES:
        target = tmp_path / PREFIX / path
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / PREFIX / path, target)
    runtime, route, deps, context, reader, policy = (tmp_path / PREFIX / p for p in FILES)
    if damage == 'missing':
        reader.unlink()
    elif damage == 'stub':
        policy.write_text('def policy_summary(*args): return legacy(*args)\n')
    elif damage == 'reverse':
        context.write_text(context.read_text() + '\nfrom ladder_dragon.dashboard.runtime import app\n')
    elif damage == 'scope':
        deps.write_text(deps.read_text().replace("'time'", "'os'"))
    elif damage == 'copy':
        runtime.write_text(runtime.read_text().replace('AiRouteState(vars())', 'AiRouteState(dict(vars()))'))
    elif damage == 'detached':
        route.write_text(route.read_text().replace('from ladder_dragon.dashboard.ai_status_reader import', 'from unknown import'))
    elif damage == 'input':
        route.write_text(route.read_text().replace('read_ai_decisions(deps, db_path, limit)', 'read_ai_decisions(deps, db_path, 999)'))
    elif damage == 'unguarded':
        tree = ast.parse(route.read_text())
        handler = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == 'ai_status')
        pos = next(i for i, n in enumerate(handler.body) if isinstance(n, ast.Try))
        statement = handler.body[pos].body[0]
        handler.body[pos].body = [ast.Pass()]
        handler.body.insert(pos, statement)
        route.write_text(ast.unparse(tree))
    elif damage == 'method':
        route.write_text(route.read_text().replace('@router.get(', '@router.post('))
    elif damage == 'duplicate':
        runtime.write_text(runtime.read_text() + '\n@app.get("/api/ai/status")\ndef duplicate(): return {}\n')
    ctx = HarnessContext(root=tmp_path, python=sys.executable,
                         options=HarnessOptions(profile=profile, output=tmp_path / 'report.json'))
    spec, = [s for s in checks_for_profile(ctx) if s.name == 'architecture_ai_routes']
    assert spec.required
    result = HarnessRunner(ctx)._run_spec(spec)
    expected = Status.PASS if damage is None else Status.BLOCKED if damage == 'missing' else Status.FAILED
    assert result.status is expected, result.metrics


def synthetic_runtime(monkeypatch, tmp_path):
    r = load_dashboard(monkeypatch, 'ai_components')
    r.AI_DECISIONS_DB = str(tmp_path / 'decisions.db')
    r.AI_USAGE_LOG = str(tmp_path / 'usage.ndjson')
    r.DASHBOARD_FOLLOW_BOT_PATHS = False
    r._load_ai_runtime_status = lambda: {}
    r._ai_usage_today = lambda path: dict(requests=0, tokens=0, cost_usd='0', recent_errors=0)
    r.time = SimpleNamespace(time=lambda: 2000, monotonic=r.time.monotonic)
    return r


@pytest.mark.parametrize('limit,count', [(-1, 1), (2, 2), (999, 3)])
def test_real_reader_limit_order_rag_and_live_bindings(monkeypatch, tmp_path, limit, count):
    r = synthetic_runtime(monkeypatch, tmp_path)
    with sqlite3.connect(r.AI_DECISIONS_DB) as con:
        con.execute('CREATE TABLE ai_decisions(decision_id TEXT,symbol TEXT,created_at INTEGER,deterministic_mode TEXT,recommended_mode TEXT,width_scale REAL,cap_scale REAL,confidence REAL,applied INTEGER,return_15m REAL,return_1h REAL,return_4h REAL)')
        for i in range(3):
            con.execute("INSERT INTO ai_decisions VALUES(?,'AAAUSDT',?,'FLAT','UP',1,1,.8,0,NULL,.02,NULL)", (str(i), i))
        con.execute('CREATE TABLE knowledge_retrievals(decision_id TEXT,document_id TEXT,rank INTEGER,score REAL)')
        con.execute("INSERT INTO knowledge_retrievals VALUES('2','synthetic-document',1,.7)")
    original = Path(r.AI_DECISIONS_DB).read_bytes()
    client = TestClient(r.app)
    assert client.get('/api/ai/status').status_code == 401
    response = client.get('/api/ai/status', headers=HEADERS, params={'limit': limit})
    assert response.status_code == 200
    payload = response.json()
    assert len(payload['recent']) == count
    assert payload['recent'][0]['decision_id'] == '2'
    assert payload['recent'][0]['evaluation'] == {}
    assert payload['recent'][0]['rag_documents'] == [{'document_id': 'synthetic-document', 'rank': 1, 'score': .7}]
    assert payload['knowledge_base']['retrievals'] == 1
    assert payload['ai_vs_baseline_1h'] == {'samples': count, 'edge': 1.0}
    assert Path(r.AI_DECISIONS_DB).read_bytes() == original
    r._ai_database_aggregates = lambda *a, **kw: {'documents': 42}
    assert client.get('/api/ai/status', headers=HEADERS).json()['knowledge_base']['documents'] == 42


def test_database_failure_is_sanitized_before_usage(monkeypatch, tmp_path, capsys):
    r = synthetic_runtime(monkeypatch, tmp_path)
    Path(r.AI_DECISIONS_DB).write_bytes(b'synthetic-invalid-database')
    r._ai_usage_today = lambda *a: pytest.fail('usage must not run after failed SQLite read')
    response = TestClient(r.app).get('/api/ai/status', headers=HEADERS)
    assert response.status_code == 503
    assert response.json() == {'ok': False, 'error': 'AI_DB_READ_FAILED'}
    assert 'synthetic-invalid' not in response.text + capsys.readouterr().out


@pytest.mark.parametrize('mode,usage,budgets,expected', [
    ('DISABLED', {'cost_usd': '1'}, {}, 'DISABLED'),
    ('SHADOW', {}, {}, 'SHADOW'),
    ('APPLY', {}, {}, 'ACTIVE'),
    ('APPLY', {'requests': 1}, {'max_requests_per_day': 1}, 'DEGRADED'),
    ('SHADOW', {'tokens': 1}, {'max_tokens_per_day': 1}, 'DEGRADED'),
    ('APPLY', {'cost_usd': '0.100000000000000001'}, {'max_cost_usd_per_day': '0.100000000000000001'}, 'DEGRADED'),
    ('APPLY', {'cost_usd': '0.1'}, {'max_cost_usd_per_day': '0.100000000000000001'}, 'ACTIVE'),
])
def test_runtime_budgets_and_decimal_boundary(monkeypatch, tmp_path, mode, usage, budgets, expected):
    r = synthetic_runtime(monkeypatch, tmp_path)
    runtime = {'state': 'RUNNING', 'updated_at': datetime.fromtimestamp(1990, timezone.utc).isoformat(),
               'ai': {'mode': mode, 'enabled': True, 'budgets': budgets, 'api_key': 'synthetic-private'}}
    r._load_ai_runtime_status = lambda: runtime
    r._ai_usage_today = lambda *a: dict(requests=0, tokens=0, cost_usd='0', recent_errors=0) | usage
    response = TestClient(r.app).get('/api/ai/status', headers=HEADERS)
    assert response.status_code == 200
    payload = response.json()
    assert payload['state'] == expected
    assert payload['runtime']['age_sec'] == 10
    assert not payload['runtime']['stale']
    assert 'synthetic-private' not in response.text
    if budgets.get('max_cost_usd_per_day'):
        assert payload['runtime']['budgets']['max_cost_usd_per_day'] == budgets['max_cost_usd_per_day']


@pytest.mark.parametrize('updated,stale', [(None, True), ('invalid', True), ('1970-01-01T00:00:00+00:00', True)])
def test_stale_context_never_looks_current(monkeypatch, tmp_path, updated, stale):
    r = synthetic_runtime(monkeypatch, tmp_path)
    r._load_ai_runtime_status = lambda: {'state': 'RUNNING', 'updated_at': updated, 'ai': {'mode': 'APPLY', 'enabled': True}}
    payload = TestClient(r.app).get('/api/ai/status', headers=HEADERS).json()
    assert payload['runtime']['stale'] is stale
    assert not Path(r.AI_DECISIONS_DB).exists()


@pytest.mark.parametrize('fail', [False, True])
def test_reader_readonly_and_transaction_exit(monkeypatch, tmp_path, fail):
    from ladder_dragon.dashboard.ai_status_reader import read_ai_decisions
    path = tmp_path / 'read-only.db'
    with sqlite3.connect(path) as con:
        con.execute('CREATE TABLE ai_decisions(symbol TEXT,created_at INTEGER,deterministic_mode TEXT,recommended_mode TEXT,width_scale REAL,cap_scale REAL,confidence REAL,applied INTEGER,return_15m REAL,return_1h REAL,return_4h REAL)')
    original = sqlite3.connect
    events = []
    class Connection(sqlite3.Connection):
        def __enter__(self):
            events.append('enter')
            return super().__enter__()
        def __exit__(self, kind, value, traceback):
            events.append(('exit', kind))
            return super().__exit__(kind, value, traceback)
    def connect(database, **kwargs):
        assert database == f'file:{path}?mode=ro'
        assert kwargs == {'uri': True, 'timeout': 1}
        connection = original(database, **kwargs, factory=Connection)
        with pytest.raises(sqlite3.OperationalError):
            connection.execute('CREATE TABLE forbidden(value INTEGER)')
        return connection
    monkeypatch.setattr(sqlite3, 'connect', connect)
    def aggregates(*args, **kwargs):
        if fail:
            raise sqlite3.OperationalError('synthetic-read-failure')
        return {}
    deps = SimpleNamespace(_ai_database_aggregates=aggregates)
    if fail:
        with pytest.raises(sqlite3.OperationalError):
            read_ai_decisions(deps, path, 10)
    else:
        assert read_ai_decisions(deps, path, 10)[0] == []
    assert events == ['enter', ('exit', sqlite3.OperationalError if fail else None)]
