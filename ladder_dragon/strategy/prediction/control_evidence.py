# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: collect separate counterfactual evidence for each strategy control.
"""Build independent SHADOW journals for execution-changing strategy controls."""

from __future__ import annotations

from dataclasses import replace
from decimal import Decimal
from typing import Mapping

from ladder_dragon.strategy.prediction.models import PredictionFeatures, TradePlan
from ladder_dragon.strategy.prediction.runtime import (
    PredictionShadowStore,
    predict_distribution,
)


CONTROL_KINDS: Mapping[str, str] = {
    "expectancy": "CONTROL_EXPECTANCY",
    "inventory": "CONTROL_INVENTORY",
    "maker": "CONTROL_MAKER",
    "regime": "CONTROL_REGIME",
}


def _candidate_plans(
    baseline: TradePlan,
    *,
    required_edge_pct: Decimal | None,
    inventory_scale: Decimal,
    regime_buys_allowed: bool,
) -> dict[str, TradePlan]:
    baseline_target = baseline.take_profit_price / baseline.entry_price - Decimal("1")
    expectancy_target = max(
        baseline_target,
        required_edge_pct if required_edge_pct is not None else baseline_target,
    )
    bounded_scale = min(Decimal("1"), max(Decimal("0"), inventory_scale))
    inventory_enabled = bounded_scale > 0
    inventory_notional = (
        baseline.notional_quote * bounded_scale
        if inventory_enabled
        else baseline.notional_quote
    )
    return {
        "expectancy": replace(
            baseline,
            take_profit_price=baseline.entry_price * (
                Decimal("1") + expectancy_target
            ),
        ),
        "inventory": replace(
            baseline,
            notional_quote=inventory_notional,
            entry_enabled=inventory_enabled,
        ),
        "maker": replace(baseline, slippage_pct=Decimal("0")),
        "regime": replace(
            baseline, entry_enabled=bool(regime_buys_allowed)
        ),
    }


def record_control_evidence(
    store: PredictionShadowStore,
    *,
    symbol: str,
    features: PredictionFeatures,
    baseline_plan: TradePlan,
    required_edge_pct: Decimal | None,
    inventory_scale: Decimal,
    regime_buys_allowed: bool,
) -> tuple[str, ...]:
    """Record one explicit candidate and baseline for each control."""
    identifiers: list[str] = []
    for control, plan in _candidate_plans(
        baseline_plan,
        required_edge_pct=required_edge_pct,
        inventory_scale=inventory_scale,
        regime_buys_allowed=regime_buys_allowed,
    ).items():
        kind = CONTROL_KINDS[control]
        history = store.resolved_samples(
            symbol, before_ts_ms=features.snapshot_ts_ms, kind=kind
        )
        predictions = predict_distribution(features, plan, history)
        identifiers.append(store.record(
            kind=kind,
            symbol=symbol,
            features=features,
            plan=plan,
            baseline_plan=baseline_plan,
            predictions=predictions,
            algorithm_decision=f"control={control};rule=v1",
        ))
    return tuple(identifiers)


__all__ = ["CONTROL_KINDS", "record_control_evidence"]
