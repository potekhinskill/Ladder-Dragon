"""Trade summary ownership, canonical calculations, and resource lifetime."""

import ast
import copy
from pathlib import Path
import shutil
import sqlite3
import sys
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from tests.support.module_loaders import load_dashboard
from tests.architecture.ast_contracts import extraction_digest
from ladder_dragon.verification.models import HarnessContext, HarnessOptions, Status
from ladder_dragon.verification.profiles import checks_for_profile
from ladder_dragon.verification.runner import HarnessRunner

ROOT = Path(__file__).resolve().parents[2]
RUNTIME = 'ladder_dragon/dashboard/runtime.py'
ROUTER = 'ladder_dragon/dashboard/routers/summary.py'
STATE = 'ladder_dragon/dashboard/summary_dependencies.py'
HEADERS = {'Authorization': 'Bearer test-secret-token'}


def test_original_syntax():
    node = copy.deepcopy(next(n for n in ast.walk(ast.parse((ROOT / ROUTER).read_text()))
                              if isinstance(n, ast.FunctionDef) and n.name == 'trades_summary'))
    class Restore(ast.NodeTransformer):
        def visit_Attribute(self, n):
            if isinstance(n.value, ast.Name) and n.value.id == 'state':
                return ast.Name(id=n.attr, ctx=n.ctx)
            return self.generic_visit(n)
        def visit_Name(self, n):
            return ast.Name(id='app', ctx=n.ctx) if n.id == 'router' else n
    expected = '62f212f2e363964903950b41e1f98058e57b634bb96d16ac37d9cdf25056c823'
    assert extraction_digest(ast.Module(body=[Restore().visit(node)], type_ignores=[])) == expected


@pytest.mark.parametrize('profile', ['local', 'release'])
@pytest.mark.parametrize('damage', [None, 'missing', 'reverse', 'forwarder', 'method', 'copy', 'scope', 'binding', 'duplicate'])
def test_required_contract(tmp_path, profile, damage):
    for p in (RUNTIME, ROUTER, STATE):
        target = tmp_path / p; target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / p, target)
    router, runtime, state = (tmp_path / p for p in (ROUTER, RUNTIME, STATE))
    if damage == 'missing':
        state.unlink()
    elif damage == 'reverse':
        router.write_text(router.read_text() + '\nfrom ladder_dragon.dashboard.runtime import app\n')
    elif damage == 'forwarder':
        tree = ast.parse(router.read_text())
        n = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == 'trades_summary')
        n.body = ast.parse('return legacy()').body; router.write_text(ast.unparse(tree))
    elif damage == 'method':
        router.write_text(router.read_text().replace('@router.get(', '@router.post('))
    elif damage == 'copy':
        runtime.write_text(runtime.read_text().replace('SummaryRouteState(vars())', 'SummaryRouteState(dict(vars()))'))
    elif damage == 'scope':
        state.write_text(state.read_text().replace("'_open_db'", "'DASHBOARD_AUTH_TOKEN'"))
    elif damage == 'binding':
        runtime.write_text(runtime.read_text().replace('from ladder_dragon.dashboard.routers.summary import', 'from unknown import'))
    elif damage == 'duplicate':
        runtime.write_text(runtime.read_text() + '\n@app.get("/api/trades/summary")\ndef decoy(): return {}\n')
    context = HarnessContext(root=tmp_path, python=sys.executable,
                             options=HarnessOptions(profile=profile, output=tmp_path / 'report.json'))
    spec, = [s for s in checks_for_profile(context) if s.name == 'architecture_summary_routes']
    assert spec.required
    expected = Status.PASS if damage is None else Status.BLOCKED if damage == 'missing' else Status.FAILED
    assert HarnessRunner(context)._run_spec(spec).status is expected


@pytest.mark.parametrize('failure', [None, 'open', 'load', 'fifo', 'cache'])
def test_live_dependencies_cleanup_and_authorization(monkeypatch, failure, capsys):
    runtime = load_dashboard(monkeypatch, 'summary_dependencies')
    events = []
    connection = SimpleNamespace(close=lambda: events.append('close'))
    def stage(name, value):
        events.append(name)
        if failure == name:
            raise sqlite3.OperationalError('synthetic-private-detail')
        return value
    monkeypatch.setattr(runtime, '_open_db', lambda: stage('open', (connection, 'synthetic.db')))
    client = TestClient(runtime.app)
    assert client.get('/api/trades/summary').status_code == 401
    assert events == []
    monkeypatch.setattr(runtime, '_load_trades', lambda con, syms: stage('load', []))
    monkeypatch.setattr(runtime, '_fee_pct_default', lambda: 0)
    stats = dict(total_trades=0, buy_volume_usdt=0, sell_volume_usdt=0, fees_usdt=0,
                 cashflow_pnl_usdt=0, realized_pnl_usdt=None, realized_pnl_status='incomplete_fifo_history',
                 realized_pnl_excluded_symbols=['AAAUSDT'])
    monkeypatch.setattr(runtime, '_fifo_realized_pnl', lambda *a, **kw: stage('fifo', stats))
    monkeypatch.setattr(runtime, '_EQUITY_SUMMARY_CACHE', SimpleNamespace(get=lambda *a: stage('cache', (None, 'refreshing', None))))
    response = client.get('/api/trades/summary', headers=HEADERS)
    assert response.status_code == (503 if failure else 200)
    assert events.count('close') == (0 if failure == 'open' else 1)
    assert 'synthetic-private-detail' not in response.text + capsys.readouterr().out
    if not failure:
        payload = response.json()
        assert payload['realized_pnl_method'] == 'unavailable-incomplete-fifo-history'
        assert payload['realized_pnl_excluded_symbols'] == ['AAAUSDT']
        assert payload['equity_pnl_usdt'] is None


def test_namespace_is_restricted():
    from ladder_dragon.dashboard.summary_dependencies import SummaryRouteState
    state = SummaryRouteState({'DASHBOARD_AUTH_TOKEN': 'synthetic-private'})
    with pytest.raises(AttributeError):
        _ = state.DASHBOARD_AUTH_TOKEN
    assert 'synthetic-private' not in repr(state)


@pytest.mark.parametrize('hours,clamped', [(-1, 1), (24, 24), (999, 168)])
def test_cutoff_symbols_cache_and_deferred_live_loader(monkeypatch, hours, clamped):
    runtime = load_dashboard(monkeypatch, 'summary_parameters')
    rows = [object()]
    closed, callbacks, calls = [], [], []
    monkeypatch.setattr(runtime, 'time', SimpleNamespace(time=lambda: 1000000, monotonic=runtime.time.monotonic))
    monkeypatch.setattr(runtime, '_open_db', lambda: (SimpleNamespace(close=lambda: closed.append(True)), 'synthetic.db'))
    monkeypatch.setattr(runtime, '_fee_pct_default', lambda: 0)
    def load(con, symbols):
        assert symbols == ['AAAUSDT', 'BBBUSDT']
        return rows
    def fifo(received, cutoff, fee, *, end_s):
        assert received is rows and cutoff == 1000000 - clamped * 3600
        assert end_s == 1000000 and fee == 0
        return dict(total_trades=0, buy_volume_usdt=0, sell_volume_usdt=0,
                    fees_usdt=0, cashflow_pnl_usdt=0, realized_pnl_usdt=0)
    def cached(key, loader):
        assert key == (clamped, ('AAAUSDT', 'BBBUSDT'))
        callbacks.append(loader)
        return dict(equity_then_usdt=100, equity_pnl_usdt=2, method='cached'), 'stale', 1.23456
    monkeypatch.setattr(runtime, '_load_trades', load)
    monkeypatch.setattr(runtime, '_fifo_realized_pnl', fifo)
    monkeypatch.setattr(runtime, '_EQUITY_SUMMARY_CACHE', SimpleNamespace(get=cached))
    monkeypatch.setattr(runtime, 'equity_pnl_usdt', lambda *args: pytest.fail('eager network valuation'))
    response = TestClient(runtime.app).get('/api/trades/summary', headers=HEADERS,
                                         params={'hours': hours, 'symbols': ' aaausdt, ,bbbusdt '})
    assert response.status_code == 200
    assert closed == [True]
    payload = response.json()
    assert payload['hours'] == clamped and payload['symbols'] == 'AAAUSDT,BBBUSDT'
    assert payload['equity_pct'] == 2 and payload['equity_cache_age_sec'] == 1.235
    monkeypatch.setattr(runtime, 'equity_pnl_usdt', lambda *args: calls.append(args))
    callbacks[0]()
    assert calls == [(1000000 - clamped * 3600, rows, 0, ['AAAUSDT', 'BBBUSDT'])]
    assert calls[0][1] is not rows
