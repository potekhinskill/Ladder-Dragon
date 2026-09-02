from __future__ import annotations

from types import SimpleNamespace

import pytest

from ladder_dragon.strategy.prediction import champion_registry
from ladder_dragon.supervision import runtime as supervisor


def test_supervisor_authority_binding_has_canonical_runtime_identity():
    assert (
        supervisor.verify_active_champion_lifecycle
        is champion_registry.verify_active_champion_lifecycle
    )


def test_runtime_revokes_execution_before_plan_when_champion_loses_eligibility(
    monkeypatch,
):
    champion = {
        "activation_id": "champion:solusdt:v1:0123456789abcdef",
        "champion_fingerprint": "a" * 64,
        "execution_policy_fingerprint": "b" * 64,
    }
    report = {
        "execution_permitted_symbols": ["SOLUSDT"],
        "blocked_execution_symbols": [],
        "active_champions": {"SOLUSDT": champion},
        "candidates": {
            "SOLUSDT": {
                "execution_permitted": True,
                "execution_blocking_reasons": [],
            }
        },
    }
    monkeypatch.setattr(supervisor, "_ACTIVE_CHAMPIONS", {"SOLUSDT": champion})
    monkeypatch.setattr(supervisor, "_PREDICTION_SHADOW", object())
    monkeypatch.setattr(
        supervisor, "_AI_RUNTIME_STATUS", {"execution_promotion": report}
    )
    monkeypatch.setattr(
        supervisor, "require_runtime_regime_contract", lambda *_args: None
    )

    def reject_superseded(*_args, **_kwargs):
        raise ValueError("experiment is SUPERSEDED")

    monkeypatch.setattr(
        supervisor,
        "verify_active_champion_lifecycle",
        reject_superseded,
    )
    monkeypatch.setattr(
        supervisor,
        "require_supervisor_authority_binding",
        lambda _call: None,
    )
    stopped: list[str] = []
    monkeypatch.setattr(supervisor, "_stop_children", stopped.append)

    with pytest.raises(RuntimeError, match="eligibility changed during runtime"):
        supervisor.run_for_symbol(
            "SOLUSDT", SimpleNamespace(), execution_allowed=True
        )

    assert supervisor._ACTIVE_CHAMPIONS == {}
    assert stopped == ["active CHAMPION eligibility changed during runtime"]
    assert report["execution_permitted_symbols"] == []
    assert report["blocked_execution_symbols"] == ["SOLUSDT"]


def test_runtime_rejects_rebound_authority_before_call(monkeypatch):
    champion = {
        "activation_id": "champion:solusdt:v1:0123456789abcdef",
        "champion_fingerprint": "a" * 64,
        "execution_policy_fingerprint": "b" * 64,
    }
    report = {
        "execution_permitted_symbols": ["SOLUSDT"],
        "blocked_execution_symbols": [],
        "active_champions": {"SOLUSDT": champion},
        "candidates": {"SOLUSDT": {"execution_permitted": True}},
    }
    monkeypatch.setattr(supervisor, "_ACTIVE_CHAMPIONS", {"SOLUSDT": champion})
    monkeypatch.setattr(supervisor, "_PREDICTION_SHADOW", object())
    monkeypatch.setattr(
        supervisor, "_AI_RUNTIME_STATUS", {"execution_promotion": report}
    )
    monkeypatch.setattr(
        supervisor, "require_runtime_regime_contract", lambda *_args: None
    )
    rebound_calls = []
    monkeypatch.setattr(
        supervisor,
        "verify_active_champion_lifecycle",
        lambda *_args, **_kwargs: rebound_calls.append(True),
    )
    stopped = []
    monkeypatch.setattr(supervisor, "_stop_children", stopped.append)

    with pytest.raises(RuntimeError, match="eligibility changed during runtime"):
        supervisor.run_for_symbol(
            "SOLUSDT", SimpleNamespace(), execution_allowed=True
        )

    assert rebound_calls == []
    assert stopped == ["active CHAMPION eligibility changed during runtime"]
