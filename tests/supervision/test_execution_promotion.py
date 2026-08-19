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
    assert candidate["execution_policy_bound"] is False
    assert candidate["execution_permitted"] is False


def test_confirmed_candidate_needs_caps_consistent_with_total_limit(monkeypatch):
    monkeypatch.setattr(
        execution_promotion,
        "_current_generation_status",
        lambda _store, _symbol: ("v12", "CONFIRMED"),
    )
    monkeypatch.setattr(
        execution_promotion, "_current_method_passes", lambda *_args, **_kwargs: True
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
        "per-order CAP exceeds managed-inventory hard CAP",
    ]


def test_confirmation_can_be_activation_ready_without_enabling_execution(monkeypatch):
    monkeypatch.setattr(
        execution_promotion,
        "_current_generation_status",
        lambda _store, _symbol: ("v12", "CONFIRMED"),
    )
    monkeypatch.setattr(
        execution_promotion, "_current_method_passes", lambda *_args, **_kwargs: True
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
    assert candidate["execution_policy_status"] == "EXECUTION_POLICY_NOT_BOUND"
    assert candidate["execution_enabled"] is False
    assert candidate["execution_permitted"] is False
    assert report["blocked_execution_symbols"] == []
    assert report["lookahead"] is False


def test_legacy_confirmation_cannot_bypass_the_current_method(monkeypatch):
    monkeypatch.setattr(
        execution_promotion,
        "_current_generation_status",
        lambda _store, _symbol: ("v12", "CONFIRMED"),
    )
    monkeypatch.setattr(
        execution_promotion, "_current_method_passes", lambda *_args, **_kwargs: False
    )

    report = execution_promotion.build_execution_promotion_report(
        execution_symbols=["SOLUSDT"],
        prediction_symbols=["SOLUSDT", "BTCUSDT"],
        candidate_symbols=["BTCUSDT"],
        store=object(),
        environment=_environment("BTCUSDT"),
    )

    candidate = report["candidates"]["BTCUSDT"]
    assert candidate["promotion_eligible"] is False
    assert "current statistical method" in candidate["blocking_reasons"][0]


def test_promotion_report_does_not_copy_unrelated_environment_values(monkeypatch):
    monkeypatch.setattr(
        execution_promotion,
        "_current_generation_status",
        lambda _store, _symbol: ("v12", "CONFIRMED"),
    )
    monkeypatch.setattr(
        execution_promotion, "_current_method_passes", lambda *_args, **_kwargs: True
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


def test_only_active_champion_enters_the_execution_permitted_scope(monkeypatch):
    monkeypatch.setattr(
        execution_promotion,
        "_current_generation_status",
        lambda _store, _symbol: ("v13", "SELECTION"),
    )
    monkeypatch.setattr(
        execution_promotion,
        "_experiment_method_passes",
        lambda *_args, **_kwargs: True,
    )
    champion = {
        "activation_id": "champion:btcusdt:v1:0123456789abcdef",
        "experiment_id": "btc-v12-confirmed",
        "champion_fingerprint": "a" * 64,
        "execution_policy_fingerprint": "b" * 64,
        "execution_policy": {
            "maximum_order_notional_usdt": "10",
            "maximum_inventory_usdt": "30",
        },
    }
    monkeypatch.setattr(
        execution_promotion,
        "active_champion",
        lambda *_args, **_kwargs: champion,
    )

    report = execution_promotion.build_execution_promotion_report(
        execution_symbols=["BTCUSDT"],
        prediction_symbols=["BTCUSDT"],
        candidate_symbols=["BTCUSDT"],
        store=object(),
        environment=_environment("BTCUSDT"),
    )

    candidate = report["candidates"]["BTCUSDT"]
    assert candidate["execution_policy_bound"] is True
    assert candidate["execution_permitted"] is True
    assert report["execution_permitted_symbols"] == ["BTCUSDT"]
    assert report["active_champions"] == {"BTCUSDT": champion}


def test_new_execution_symbol_is_disabled_but_shadow_process_can_start(monkeypatch):
    monkeypatch.setattr(
        execution_promotion,
        "_current_generation_status",
        lambda _store, _symbol: ("v12", "SELECTION"),
    )

    report = execution_promotion.prepare_execution_promotion_report(
        execution_symbols=["SOLUSDT", "BTCUSDT"],
        prediction_symbols=["SOLUSDT", "BTCUSDT"],
        store=object(),
        environment={"BOT_EXECUTION_CANDIDATE_SYMBOLS": ""},
    )

    assert report["blocked_execution_symbols"] == ["SOLUSDT", "BTCUSDT"]
    assert report["execution_permitted_symbols"] == []


def test_supervisor_checks_promotion_before_preflight_and_worker_loop():
    source = inspect.getsource(supervisor.main)

    promotion_gate = source.index("prepare_execution_promotion_report")
    preflight = source.index("_preflight_with_auth_backoff")
    worker_loop = source.index("while True:")

    assert promotion_gate < preflight < worker_loop
