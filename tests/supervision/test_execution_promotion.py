from __future__ import annotations

import inspect
import json

import pytest

from ladder_dragon.supervision import execution_promotion
from ladder_dragon.supervision import runtime as supervisor


def _environment(symbol: str) -> dict[str, str]:
    return {
        f"RISK_SYMBOL_CAP_{symbol}": "10",
        f"RISK_MANAGED_INVENTORY_HARD_CAP_{symbol}": "30",
        f"BOT_EXECUTION_PROMOTION_APPROVED_{symbol}": "YES",
    }


def test_candidate_list_is_staged_without_widening_execution_scope():
    execution = ["SOLUSDT"]

    candidates = execution_promotion.resolve_execution_candidate_symbols(
        "BTCUSDT,ETHUSDT"
    )

    assert execution == ["SOLUSDT"]
    assert candidates == ["BTCUSDT", "ETHUSDT"]


@pytest.mark.parametrize("configured", ["BTCUSDT,BTCUSDT", "BTC/USDT"])
def test_candidate_list_rejects_ambiguous_configuration(configured: str):
    with pytest.raises(ValueError):
        execution_promotion.resolve_execution_candidate_symbols(configured)


def test_candidate_remains_blocked_without_confirmation_caps_and_approval(
    monkeypatch,
):
    monkeypatch.setattr(
        execution_promotion,
        "_current_generation_status",
        lambda _store, _symbol: ("v12", "SELECTION"),
    )

    report = execution_promotion.build_execution_promotion_report(
        execution_symbols=["SOLUSDT"],
        prediction_symbols=["SOLUSDT", "BTCUSDT"],
        candidate_symbols=["BTCUSDT"],
        store=object(),
        environment={},
    )

    candidate = report["candidates"]["BTCUSDT"]
    assert candidate["promotion_eligible"] is False
    assert candidate["execution_enabled"] is False
    assert candidate["lifecycle_status"] == "SELECTION"
    assert report["can_change_execution_scope"] is False
    assert len(candidate["blocking_reasons"]) == 4


def test_confirmed_candidate_needs_caps_consistent_with_total_limit(monkeypatch):
    monkeypatch.setattr(
        execution_promotion,
        "_current_generation_status",
        lambda _store, _symbol: ("v12", "CONFIRMED"),
    )
    environment = _environment("BTCUSDT")
    environment["RISK_SYMBOL_CAP_BTCUSDT"] = "31"

    report = execution_promotion.build_execution_promotion_report(
        execution_symbols=["SOLUSDT"],
        prediction_symbols=["SOLUSDT", "BTCUSDT"],
        candidate_symbols=["BTCUSDT"],
        store=object(),
        environment=environment,
    )

    candidate = report["candidates"]["BTCUSDT"]
    assert candidate["promotion_eligible"] is False
    assert candidate["blocking_reasons"] == [
        "per-order CAP exceeds managed-inventory hard CAP"
    ]


def test_all_promotion_gates_can_pass_without_enabling_execution(monkeypatch):
    monkeypatch.setattr(
        execution_promotion,
        "_current_generation_status",
        lambda _store, _symbol: ("v12", "CONFIRMED"),
    )

    report = execution_promotion.build_execution_promotion_report(
        execution_symbols=["SOLUSDT"],
        prediction_symbols=["SOLUSDT", "BTCUSDT"],
        candidate_symbols=["BTCUSDT"],
        store=object(),
        environment=_environment("BTCUSDT"),
    )

    candidate = report["candidates"]["BTCUSDT"]
    assert candidate["promotion_eligible"] is True
    assert candidate["execution_enabled"] is False
    assert report["blocked_execution_symbols"] == []
    assert report["lookahead"] is False


def test_promotion_report_does_not_copy_unrelated_environment_values(monkeypatch):
    monkeypatch.setattr(
        execution_promotion,
        "_current_generation_status",
        lambda _store, _symbol: ("v12", "CONFIRMED"),
    )
    environment = _environment("BTCUSDT")
    environment["BINANCE_API_SECRET"] = "must-not-appear"

    report = execution_promotion.build_execution_promotion_report(
        execution_symbols=["SOLUSDT"],
        prediction_symbols=["SOLUSDT", "BTCUSDT"],
        candidate_symbols=["BTCUSDT"],
        store=object(),
        environment=environment,
    )

    assert "must-not-appear" not in json.dumps(report)


def test_premature_execution_scope_change_fails_closed(monkeypatch):
    monkeypatch.setattr(
        execution_promotion,
        "_current_generation_status",
        lambda _store, _symbol: ("v12", "SELECTION"),
    )
    report = execution_promotion.build_execution_promotion_report(
        execution_symbols=["SOLUSDT", "BTCUSDT"],
        prediction_symbols=["SOLUSDT", "BTCUSDT"],
        candidate_symbols=["BTCUSDT"],
        store=object(),
        environment={},
    )

    with pytest.raises(ValueError, match="blocked for staged symbols: BTCUSDT"):
        execution_promotion.require_safe_execution_scope(report)


def test_new_execution_symbol_cannot_bypass_an_empty_candidate_list(monkeypatch):
    monkeypatch.setattr(
        execution_promotion,
        "_current_generation_status",
        lambda _store, _symbol: ("v12", "SELECTION"),
    )

    with pytest.raises(ValueError, match="blocked for staged symbols: BTCUSDT"):
        execution_promotion.prepare_execution_promotion_report(
            execution_symbols=["SOLUSDT", "BTCUSDT"],
            prediction_symbols=["SOLUSDT", "BTCUSDT"],
            store=object(),
            environment={"BOT_EXECUTION_CANDIDATE_SYMBOLS": ""},
        )


def test_supervisor_checks_promotion_before_preflight_and_worker_loop():
    source = inspect.getsource(supervisor.main)

    promotion_gate = source.index("prepare_execution_promotion_report")
    preflight = source.index("_preflight_with_auth_backoff")
    worker_loop = source.index("while True:")

    assert promotion_gate < preflight < worker_loop
