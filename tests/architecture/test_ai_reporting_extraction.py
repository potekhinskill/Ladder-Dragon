"""AI reporting relocation parity, live resources, and required ownership."""

import ast
from datetime import datetime, timezone
import json
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
FILES = ['runtime.py', 'ai_reporting_dependencies.py', 'services/ai_report_cache.py',
         'services/ai_usage.py', 'services/ai_aggregates.py', 'services/ai_calibration.py']
ORIGINALS = [
    ('ai_report_cache', 'cache_get', '_ai_cache_get'),
    ('ai_report_cache', 'cache_put', '_ai_cache_put'),
    ('ai_usage', 'usage_today', '_ai_usage_today'),
    ('ai_aggregates', 'database_aggregates', '_ai_database_aggregates'),
    ('ai_calibration', 'calibration', '_ai_calibration'),
]
DIGESTS = [
    'f04b30213ee66ec6be2fe0bed2850b93056ec20ce2d5ebbe12eea3cf7c0b7c84',
    '04c86ebd15bf399442f93d82b5f5fefc43d0f16f97677d7162836ee25c2fe37b',
    '074a9815ae00fc7f46bc5d25a1c14af3913061d19c4ba53e35bba028023a9c6b',
    '76abcb30e339cf0395a9d53d9ffc57c9ce8a6fef97d149e2e53640e17cb133b3',
    'be36fca2f64c4b191f9a44680fe2d66cca6a45b43a30d7b1142dd3499e3eb7ce',
]


@pytest.mark.parametrize('spec,digest', zip(ORIGINALS, DIGESTS))
def test_original_implementation_syntax(spec, digest):
    module, name, original = spec
    tree = ast.parse((ROOT / PREFIX / 'services' / (module + '.py')).read_text())
    node = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == name)
    node.name = original
    if name != 'calibration':
        node.args.args.pop(0)
    class Restore(ast.NodeTransformer):
        def visit_Attribute(self, value):
            if isinstance(value.value, ast.Name) and value.value.id == 'deps':
                return ast.Name(id=value.attr, ctx=value.ctx)
            return self.generic_visit(value)
    assert extraction_digest(ast.Module(body=[Restore().visit(node)], type_ignores=[])) == digest


@pytest.mark.parametrize('profile', ['local', 'release'])
@pytest.mark.parametrize('damage', [None, 'missing', 'stub', 'reverse', 'import', 'copy',
                                    'duplicate', 'wrong_function', 'owner', 'scope', 'resolver'])
def test_required_reporting_contract(tmp_path, profile, damage):
    for path in FILES:
        target = tmp_path / PREFIX / path
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / PREFIX / path, target)
    runtime, state, cache, usage, aggregates, calibration = (tmp_path / PREFIX / p for p in FILES)
    if damage == 'missing':
        usage.unlink()
    elif damage == 'stub':
        cache.write_text('def cache_get(*args): return legacy(*args)\ndef cache_put(*args): return legacy(*args)\n')
    elif damage == 'reverse':
        aggregates.write_text(aggregates.read_text() + '\nfrom ladder_dragon.dashboard.runtime import app\n')
    elif damage == 'import':
        runtime.write_text(runtime.read_text().replace('from ladder_dragon.dashboard.services.ai_usage import', 'from unknown import'))
    elif damage == 'copy':
        runtime.write_text(runtime.read_text().replace('AiReportingState(vars())', 'AiReportingState(dict(vars()))'))
    elif damage == 'duplicate':
        runtime.write_text(runtime.read_text() + '\n_ai_cache_get = lambda key: None\n')
    elif damage == 'wrong_function':
        runtime.write_text(runtime.read_text().replace('partial(usage_today,', 'partial(cache_get,'))
    elif damage == 'owner':
        runtime.write_text(runtime.read_text() + '\ndef _ai_calibration(recent): return []\n')
    elif damage == 'scope':
        state.write_text(state.read_text().replace("'time'", "'os'"))
    elif damage == 'resolver':
        state.write_text(state.read_text().replace('return self._namespace[name]', 'return None'))
    ctx = HarnessContext(root=tmp_path, python=sys.executable,
                         options=HarnessOptions(profile=profile, output=tmp_path / 'report.json'))
    spec, = [s for s in checks_for_profile(ctx) if s.name == 'architecture_ai_reporting']
    assert spec.required
    result = HarnessRunner(ctx)._run_spec(spec)
    expected = Status.PASS if damage is None else Status.BLOCKED if damage == 'missing' else Status.FAILED
    assert result.status is expected, result.metrics


def test_cache_live_replacements_lock_ttl_copy_and_eviction(monkeypatch):
    r = load_dashboard(monkeypatch, 'report_cache')
    original = r._AI_SUMMARY_CACHE
    r._AI_SUMMARY_CACHE = {}
    tick = [0]
    held = [False]
    class Lock:
        def __enter__(self):
            assert not held[0]
            held[0] = True
        def __exit__(self, *args):
            held[0] = False
    class Cache(dict):
        def get(self, *args):
            assert held[0]
            return super().get(*args)
        def __setitem__(self, key, value):
            assert held[0]
            super().__setitem__(key, value)
    r._AI_SUMMARY_CACHE = Cache()
    r._AI_SUMMARY_CACHE_LOCK = Lock()
    r.time = SimpleNamespace(monotonic=lambda: tick[0])
    r.DASHBOARD_AI_AGGREGATE_CACHE_SEC = 30
    payload = {'count': 1}
    assert r._ai_cache_put('one', payload) is payload
    payload['count'] = 2
    tick[0] = 30
    assert r._ai_cache_get('one') == {'count': 1}
    copy = r._ai_cache_get('one')
    copy['count'] = 3
    assert r._ai_cache_get('one') == {'count': 1}
    r.DASHBOARD_AI_AGGREGATE_CACHE_SEC = 29
    assert r._ai_cache_get('one') is None
    for index in range(17):
        tick[0] = index
        r._ai_cache_put(str(index), {'count': index})
    assert len(r._AI_SUMMARY_CACHE) == 16 and '0' not in r._AI_SUMMARY_CACHE
    assert not original and not held[0]
    assert '_AI_SUMMARY_CACHE' not in repr(r._ai_reporting_state)
    with pytest.raises(AttributeError):
        getattr(r._ai_reporting_state, 'app')


def test_usage_utc_decimal_missing_file_and_live_callbacks(monkeypatch, tmp_path):
    r = load_dashboard(monkeypatch, 'report_usage')
    now = datetime(2026, 9, 27, 1, tzinfo=timezone.utc)
    path = tmp_path / 'usage.ndjson'
    assert r._ai_usage_today(path, now=now)['requests'] == 0
    r._AI_SUMMARY_CACHE = {}
    rows = [{'timestamp': stamp, 'outcome': 'ok', 'total_tokens': 2, 'estimated_cost_usd': '0.1'}
            for stamp in ['2026-09-27T04:59:00+05:00', '2026-09-27T05:00:00+05:00', '2026-09-27T05:30:00+05:00']]
    path.write_text('\n'.join(json.dumps(row) for row in rows) + '\ninvalid\n{}\n')
    result = r._ai_usage_today(path, now=now)
    assert (result['requests'], result['tokens'], result['cost_usd']) == (2, 4, '0.2')
    r._ai_cache_get = lambda key: {'replaced': key}
    assert 'replaced' in r._ai_usage_today(path, now=now)
    r._ai_cache_get = lambda key: None
    r._ai_cache_put = lambda key, value: {'stored': value}
    assert r._ai_usage_today(path, now=now)['stored']['requests'] == 2


def test_characterizes_preexisting_recent_error_undercount(monkeypatch, tmp_path):
    # Known defect, not approved behavior: fix separately from mechanical relocation.
    r = load_dashboard(monkeypatch, 'report_legacy_errors')
    now = datetime(2026, 9, 27, 1, tzinfo=timezone.utc)
    path = tmp_path / 'usage.ndjson'
    path.write_text('\n'.join(json.dumps({'timestamp': now.isoformat(), 'outcome': 'error'}) for _ in range(3)))
    result = r._ai_usage_today(path, now=now)
    assert result['errors'] == 3
    assert result['recent_errors'] == 1


def test_future_error_is_not_recent(monkeypatch, tmp_path):
    r = load_dashboard(monkeypatch, 'report_future')
    path = tmp_path / 'usage.ndjson'
    path.write_text(json.dumps({'timestamp': '2026-09-27T02:00:00+00:00', 'outcome': 'error'}))
    result = r._ai_usage_today(path, now=datetime(2026, 9, 27, 1, tzinfo=timezone.utc))
    assert result['recent_errors'] == 0


def test_real_reporting_through_authenticated_endpoint(monkeypatch, tmp_path):
    r = load_dashboard(monkeypatch, 'report_http')
    r.AI_DECISIONS_DB = str(tmp_path / 'decisions.db')
    r.AI_USAGE_LOG = str(tmp_path / 'usage.ndjson')
    r.DASHBOARD_FOLLOW_BOT_PATHS = False
    r._load_ai_runtime_status = lambda: {}
    Path(r.AI_USAGE_LOG).write_text(json.dumps({'timestamp': datetime.now(timezone.utc).isoformat(), 'total_tokens': 7, 'estimated_cost_usd': '0.2'}))
    with sqlite3.connect(r.AI_DECISIONS_DB) as con:
        con.execute('CREATE TABLE ai_decisions(decision_id TEXT,symbol TEXT,created_at INTEGER,deterministic_mode TEXT,recommended_mode TEXT,width_scale REAL,cap_scale REAL,confidence REAL,applied INTEGER,return_15m REAL,return_1h REAL,return_4h REAL,evaluation_json TEXT)')
        for index, complete in enumerate([True, False]):
            evaluation = json.dumps({'realized_execution': {'closed': True, 'financial_evidence_complete': complete, 'net_pnl_quote_text': '1.25'}})
            con.execute("INSERT INTO ai_decisions VALUES(?,'AAAUSDT',?,'FLAT','UP',1,1,.8,0,NULL,.02,NULL,?)", (str(index), index, evaluation))
        con.execute('CREATE TABLE knowledge_documents(status TEXT)')
        con.executemany('INSERT INTO knowledge_documents VALUES(?)', [('validated',), ('virtual_validated',), ('unverified',)])
    before = Path(r.AI_DECISIONS_DB).read_bytes()
    client = TestClient(r.app)
    assert client.get('/api/ai/status').status_code == 401
    response = client.get('/api/ai/status', headers={'Authorization': 'Bearer test-secret-token'})
    assert response.status_code == 200, response.text
    result = response.json()
    assert result['usage_today']['tokens'] == 7
    stats = result['knowledge_base']
    assert (stats['closed_decisions'], stats['incomplete_closed_decisions']) == (1, 1)
    assert stats['realized_net_pnl_quote'] == 1.25
    assert stats['documents'] == stats['archived_virtual_documents'] == 1
    assert stats['virtual_documents'] == 0
    assert sum(row['samples'] for row in result['calibration_1h']) == 2
    assert Path(r.AI_DECISIONS_DB).read_bytes() == before
