from decimal import Decimal
import json

import pytest

from ladder_dragon.strategy.prediction.control_evidence import (
    CONTROL_KINDS,
    record_control_evidence,
)
from ladder_dragon.strategy.prediction.models import PredictionFeatures, TradePlan
from ladder_dragon.supervision.strategy_control_gates import (
    control_apply_allowed,
    evaluate_control_requests,
    statistical_challenger_mode,
)


D = Decimal


def _features() -> PredictionFeatures:
    return PredictionFeatures(
        snapshot_ts_ms=1,
        last_closed_bar_ts_ms=1,
        price=D("100"),
        ema_slope=D("0"),
        ema_distance_pct=D("0"),
        adx=D("10"),
        plus_di=D("10"),
        minus_di=D("10"),
        atr_pct=D("0.01"),
        atr_change_pct=D("0"),
        vwap_deviation_pct=D("0"),
        rsi=D("50"),
        macd_histogram_pct=D("0"),
        volume_ratio=D("1"),
        orderbook_imbalance=D("0"),
        orderbook_available=True,
        trade_flow_imbalance=D("0"),
        trade_flow_available=True,
        spread_bps=D("1"),
        depth_quote=D("1000"),
        acceleration=D("0"),
        executor_panic_active=False,
        executor_panic_hits=0,
        regime="RANGE",
    )


def _plan() -> TradePlan:
    return TradePlan(
        entry_price=D("100"),
        take_profit_price=D("101"),
        stop_price=D("99"),
        notional_quote=D("10"),
        fee_pct=D("0.001"),
        slippage_pct=D("0.001"),
    )


def test_each_execution_control_records_a_separate_counterfactual(monkeypatch):
    records = []

    class Store:
        def resolved_samples(self, symbol, **kwargs):
            assert symbol == "SOLUSDT"
            return []

        def record(self, **kwargs):
            records.append(kwargs)
            return kwargs["kind"]

    monkeypatch.setattr(
        "ladder_dragon.strategy.prediction.control_evidence.predict_distribution",
        lambda *_args, **_kwargs: (),
    )
    baseline = _plan()

    identifiers = record_control_evidence(
        Store(),
        symbol="SOLUSDT",
        features=_features(),
        baseline_plan=baseline,
        required_edge_pct=D("0.02"),
        inventory_scale=D("0.5"),
        regime_buys_allowed=False,
    )

    modeled = {kind for name, kind in CONTROL_KINDS.items() if name != "maker"}
    assert set(identifiers) == modeled
    assert {row["kind"] for row in records} == modeled
    assert all(row["baseline_plan"] is baseline for row in records)
    assert len({row["algorithm_decision"] for row in records}) == 3
    metadata = [json.loads(row["algorithm_decision"]) for row in records]
    assert all(row["binding"] is True for row in metadata)
    assert all(row["reason"] == "plan_changed" for row in metadata)
    assert {row["field"] for row in metadata} == {
        "take_profit_price", "notional_quote", "entry_enabled"
    }
    assert all(row["rule"] == "v3" for row in metadata)
    assert not any(row["kind"] == CONTROL_KINDS["maker"] for row in records)


def test_unchanged_control_is_recorded_as_nonbinding(monkeypatch):
    records = []

    class Store:
        def resolved_samples(self, *_args, **_kwargs):
            return []

        def record(self, **kwargs):
            records.append(kwargs)
            return kwargs["kind"]

    monkeypatch.setattr(
        "ladder_dragon.strategy.prediction.control_evidence.predict_distribution",
        lambda *_args, **_kwargs: (),
    )
    baseline = _plan()
    record_control_evidence(
        Store(), symbol="SOLUSDT", features=_features(),
        baseline_plan=baseline, required_edge_pct=None,
        inventory_scale=D("1"), regime_buys_allowed=True,
    )

    metadata = {
        row["kind"]: json.loads(row["algorithm_decision"])
        for row in records
    }
    assert metadata[CONTROL_KINDS["expectancy"]]["binding"] is False
    assert metadata[CONTROL_KINDS["inventory"]]["binding"] is False
    assert metadata[CONTROL_KINDS["regime"]]["binding"] is False


def test_shadow_only_inventory_is_explicitly_not_applicable(monkeypatch):
    records = []

    class Store:
        def resolved_samples(self, *_args, **_kwargs):
            return []

        def record(self, **kwargs):
            records.append(kwargs)
            return kwargs["kind"]

    monkeypatch.setattr(
        "ladder_dragon.strategy.prediction.control_evidence.predict_distribution",
        lambda *_args, **_kwargs: (),
    )
    record_control_evidence(
        Store(), symbol="ETHUSDT", features=_features(), baseline_plan=_plan(),
        required_edge_pct=None, inventory_scale=D("0.5"),
        regime_buys_allowed=True, inventory_applicable=False,
    )

    row = next(item for item in records if item["kind"] == CONTROL_KINDS["inventory"])
    metadata = json.loads(row["algorithm_decision"])
    assert metadata["applicable"] is False
    assert metadata["binding"] is False


def test_one_control_approval_cannot_authorize_another_control():
    gate = lambda _symbol, _control: {"approved": True}
    allowed, _ = control_apply_allowed(
        "SOLUSDT", "maker", gate_loader=gate,
        environ={"BOT_EXPECTANCY_APPROVED": "YES"},
    )
    assert allowed is False

    allowed, _ = control_apply_allowed(
        "SOLUSDT", "maker", gate_loader=gate,
        environ={"BOT_MAKER_POLICY_APPROVED": "YES"},
    )
    assert allowed is True


def test_apply_request_fails_closed_when_its_own_gate_is_blocked():
    def gate(_symbol, control):
        return control != "maker", {"approved": control != "maker"}

    result = evaluate_control_requests(
        "SOLUSDT",
        {"maker": "APPLY", "regime": "SHADOW"},
        apply_allowed=gate,
    )

    assert result["approved"] is False
    assert result["blocked"] is True
    assert result["permissions"] == {"maker": False, "regime": True}


def test_statistical_regime_has_no_fictitious_apply_mode():
    assert statistical_challenger_mode("shadow") == "SHADOW"
    with pytest.raises(ValueError, match="only OFF or SHADOW"):
        statistical_challenger_mode("APPLY")
