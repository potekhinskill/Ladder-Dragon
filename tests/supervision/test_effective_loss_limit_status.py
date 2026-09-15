"""Verify the actual startup publication without starting trading or reading env files."""
import ast
import inspect
from dataclasses import replace
from decimal import Decimal

from ladder_dragon.supervision import runtime


def test_published_loss_limits_use_effective_object_not_environment(monkeypatch):
    limits = runtime.RiskLimits.from_mapping({})
    limits = replace(limits, max_daily_loss_usdt=Decimal('7.123456789123456789'),
        max_start_drawdown_pct=Decimal('0.0123'), max_peak_drawdown_pct=Decimal('0.0045'),
        max_consecutive_losses=2, cooldown_sec=789)
    monkeypatch.setenv('CB_MAX_DAILY_LOSS_USDT', '999999')
    tree = ast.parse(inspect.getsource(runtime.main))
    expressions = [kw.value for node in ast.walk(tree) if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name) and node.func.id == '_publish_ai_runtime_status'
        for kw in node.keywords if kw.arg == 'risk_limits']
    assert len(expressions) == 1
    report = eval(compile(ast.Expression(expressions[0]), '<actual-status-expression>', 'eval'),
                  {'limits': limits, 'str': str})
    assert report['max_daily_loss_usdt'] == '7.123456789123456789'
    assert report['max_start_drawdown_pct'] == '0.0123'
    assert report['max_peak_drawdown_pct'] == '0.0045'
    assert report['max_consecutive_losses'] == 2
    assert report['cooldown_sec'] == 789
    assert set(report) == {'reserve_usdt', 'portfolio_cap_usdt', 'daily_buy_cap_usdt',
        'open_order_count_cap', 'max_daily_loss_usdt', 'max_start_drawdown_pct',
        'max_peak_drawdown_pct', 'max_consecutive_losses', 'cooldown_sec'}
