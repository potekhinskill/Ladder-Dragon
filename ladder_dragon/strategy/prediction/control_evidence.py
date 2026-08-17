# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: collect separate counterfactual evidence for each strategy control.
"""Build independent SHADOW journals for execution-changing strategy controls."""

from __future__ import annotations

from dataclasses import replace
from decimal import Decimal
import json
from typing import Mapping

from ladder_dragon.strategy.prediction.models import PredictionFeatures, TradePlan
from ladder_dragon.strategy.prediction.runtime import (
    PredictionShadowStore,
    predict_distribution,
)


CONTROL_KINDS: Mapping[str, str] = {
    "expectancy": "CONTROL_EXPECTANCY_V3",
    "inventory": "CONTROL_INVENTORY_V3",
    "maker": "CONTROL_MAKER_V3",
    "regime": "CONTROL_REGIME_V3",
}


def _control_metadata(
    control: str, baseline: TradePlan, candidate: TradePlan, *, applicable: bool
) -> dict[str, object]:
    """Describe whether one control changed its pre-outcome plan."""
    fields = {
        "expectancy": "take_profit_price",
        "inventory": (
            "entry_enabled"
            if candidate.entry_enabled != baseline.entry_enabled
            else "notional_quote"
        ),
        "regime": "entry_enabled",
    }
    field = fields[control]
    before = getattr(baseline, field)
    after = getattr(candidate, field)
    binding = applicable and candidate != baseline
    return {
        "binding": binding,
        "applicable": applicable,
        "control": control,
        "field": field,
        "from": str(before).lower() if isinstance(before, bool) else format(before, "f"),
        "reason": "plan_changed" if binding else "no_plan_change",
        "rule": "v3",
        "to": str(after).lower() if isinstance(after, bool) else format(after, "f"),
        "baseline_notional_quote": format(baseline.notional_quote, "f"),
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
    # Change one control dimension against the same baseline. Evidence for
    # one control must never authorize a different execution change.
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
    inventory_applicable: bool = True,
) -> tuple[str, ...]:
    """Record modeled controls; omit maker until an execution model exists."""
    identifiers: list[str] = []
    for control, plan in _candidate_plans(
        baseline_plan,
        required_edge_pct=required_edge_pct,
        inventory_scale=inventory_scale,
        regime_buys_allowed=regime_buys_allowed,
    ).items():
        applicable = control != "inventory" or inventory_applicable
        if not applicable:
            plan = baseline_plan
        kind = CONTROL_KINDS[control]
        metadata = _control_metadata(
            control, baseline_plan, plan, applicable=applicable
        )
        encoded_metadata = json.dumps(
            metadata, sort_keys=True, separators=(",", ":")
        )
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
            algorithm_decision=encoded_metadata,
        ))
    return tuple(identifiers)


__all__ = ["CONTROL_KINDS", "record_control_evidence"]
