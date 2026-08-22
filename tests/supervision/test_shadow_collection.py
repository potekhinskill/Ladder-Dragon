import ast
import inspect
import textwrap
from types import SimpleNamespace

import pytest

from ladder_dragon.supervision import runtime as supervisor


def test_confirmed_regime_is_routed_to_shadow_evidence_collector():
    tree = ast.parse(textwrap.dedent(inspect.getsource(supervisor.run_for_symbol)))
    calls = {
        node.func.id: node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
        and node.func.id in {
            "_build_ai_market_context", "_record_prediction_shadow"
        }
    }
    ai_keywords = {item.arg for item in calls["_build_ai_market_context"].keywords}
    shadow_keywords = {
        item.arg: item.value
        for item in calls["_record_prediction_shadow"].keywords
    }

    assert "execution_regime" not in ai_keywords
    assert isinstance(shadow_keywords["execution_regime"], ast.Name)
    assert shadow_keywords["execution_regime"].id == "confirmed_regime"


def test_prediction_symbols_do_not_widen_execution_scope():
    execution = ["SOLUSDT"]

    configured, shadow_only = supervisor.resolve_prediction_shadow_symbols(
        execution, "SOLUSDT,ETHUSDT,BTCUSDT"
    )

    assert execution == ["SOLUSDT"]
    assert configured == ["SOLUSDT", "ETHUSDT", "BTCUSDT"]
    assert shadow_only == ["ETHUSDT", "BTCUSDT"]


def test_execution_symbols_remain_in_prediction_evidence():
    configured, shadow_only = supervisor.resolve_prediction_shadow_symbols(
        ["SOLUSDT"], "ETHUSDT"
    )

    assert configured == ["SOLUSDT", "ETHUSDT"]
    assert shadow_only == ["ETHUSDT"]


def test_execution_controls_are_not_applicable_to_shadow_only_symbol():
    assert supervisor.execution_control_scope(
        "ETHUSDT", ["SOLUSDT"]
    ) == (False, "not_applicable_shadow_only")
    assert supervisor.execution_control_scope(
        "SOLUSDT", ["SOLUSDT"]
    ) == (True, "active")
    assert supervisor.execution_control_scope(
        "SOLUSDT", "SOLUSDT"
    ) == (True, "active")


def test_external_ai_budget_stays_inside_execution_scope():
    source = inspect.getsource(supervisor.run_for_symbol)

    assert "execution_control_scope(symbol, args.symbols)[0]" in source


@pytest.mark.parametrize("configured", ["SOLUSDT,SOLUSDT", "SOL/USDT"])
def test_prediction_symbols_reject_invalid_configuration(configured):
    with pytest.raises(ValueError):
        supervisor.resolve_prediction_shadow_symbols(
            ["SOLUSDT"], configured
        )


def test_prediction_store_keeps_collector_active_without_ai(monkeypatch):
    calls = []
    monkeypatch.setattr(supervisor, "_AI_ADVISOR", None)
    monkeypatch.setattr(supervisor, "_AI_POLICY", None)
    monkeypatch.setattr(supervisor, "_PREDICTION_SHADOW", object())
    monkeypatch.setattr(supervisor, "_BLOCKED_SHADOW_LAST_ATTEMPT", {})
    monkeypatch.setattr(
        supervisor,
        "run_for_symbol",
        lambda symbol, args, *, execution_allowed: calls.append(
            (symbol, execution_allowed)
        ),
    )

    supervisor._collect_blocked_shadow(
        ["ETHUSDT"], SimpleNamespace(), now_monotonic=100
    )

    assert calls == [("ETHUSDT", False)]
