# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: compare immutable SHADOW strategy variants on identical market windows.
"""Parallel counterfactual experiments with no execution or exchange capability."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Iterable

from ladder_dragon.strategy.prediction.models import (
    PredictionFeatures,
    TradePlan,
)
from ladder_dragon.strategy.prediction.approval import (
    configuration_edge_p_value,
    holm_configuration_correction,
)
from ladder_dragon.strategy.prediction.runtime import (
    PredictionShadowStore,
    predict_distribution,
)
from ladder_dragon.strategy.prediction.walk_forward import (
    walk_forward_prediction_report,
)


D = Decimal
FEE_FLOOR_BUFFER_PCT = D("0.0010")
CLOSE_ENTRY_GAP_PCT = D("0.0015")
REANCHOR_TARGET_GAP_PCT = D("0.0005")
REANCHOR_MAX_STEP_PCT = D("0.0015")
ENTRY_TTL_SEC = 300


@dataclass(frozen=True)
class ShadowVariant:
    """One immutable candidate compared with the current strategy plan."""

    variant_id: str
    dimension: str
    kind: str
    plan: TradePlan
    baseline_plan: TradePlan


def _candidate_plan(
    baseline: TradePlan,
    *,
    entry_price: Decimal,
    target_pct: Decimal,
    entry_ttl_sec: int | None = None,
    entry_enabled: bool = True,
) -> TradePlan:
    stop_distance = D("1") - baseline.stop_price / baseline.entry_price
    return TradePlan(
        entry_price=entry_price,
        take_profit_price=entry_price * (D("1") + target_pct),
        stop_price=entry_price * (D("1") - stop_distance),
        notional_quote=baseline.notional_quote,
        fee_pct=baseline.fee_pct,
        slippage_pct=baseline.slippage_pct,
        entry_ttl_sec=entry_ttl_sec,
        entry_enabled=entry_enabled,
    )


def build_shadow_variants(
    *,
    market_price: Decimal,
    baseline_plan: TradePlan,
    required_edge_pct: Decimal,
    regime: str,
) -> tuple[ShadowVariant, ...]:
    """Build one-factor candidates that all clear the authoritative fee floor."""
    if not market_price.is_finite() or market_price <= 0:
        raise ValueError("market price must be positive and finite")
    if not required_edge_pct.is_finite() or required_edge_pct <= 0:
        raise ValueError("required edge must be positive and finite")
    baseline_target = (
        baseline_plan.take_profit_price / baseline_plan.entry_price - D("1")
    )
    target_pct = max(
        baseline_target,
        required_edge_pct + FEE_FLOOR_BUFFER_PCT,
    )
    close_entry = max(
        baseline_plan.entry_price,
        market_price * (D("1") - CLOSE_ENTRY_GAP_PCT),
    )
    reanchor_entry = max(
        baseline_plan.entry_price,
        min(
            market_price * (D("1") - REANCHOR_TARGET_GAP_PCT),
            baseline_plan.entry_price * (D("1") + REANCHOR_MAX_STEP_PCT),
        ),
    )
    veto = str(regime).upper() in {"TREND_DOWN", "PANIC"}
    definitions = (
        ("tp_floor", "take_profit", baseline_plan.entry_price, None, True),
        ("buy_gap_15bps", "buy_distance", close_entry, None, True),
        ("ttl_5m", "entry_ttl", baseline_plan.entry_price, ENTRY_TTL_SEC, True),
        ("reanchor_15bps", "reanchor", reanchor_entry, None, True),
        ("regime_veto", "regime_gate", baseline_plan.entry_price, None, not veto),
    )
    return tuple(
        ShadowVariant(
            variant_id=variant_id,
            dimension=dimension,
            kind=f"EXPERIMENT_{variant_id.upper()}",
            plan=_candidate_plan(
                baseline_plan,
                entry_price=entry,
                target_pct=target_pct,
                entry_ttl_sec=ttl,
                entry_enabled=enabled,
            ),
            baseline_plan=baseline_plan,
        )
        for variant_id, dimension, entry, ttl, enabled in definitions
    )


def record_shadow_variants(
    store: PredictionShadowStore,
    *,
    symbol: str,
    features: PredictionFeatures,
    variants: Iterable[ShadowVariant],
) -> tuple[str, ...]:
    """Record every candidate against the same immutable feature snapshot."""
    decision_ids = []
    for variant in variants:
        history = store.resolved_samples(
            symbol,
            before_ts_ms=features.snapshot_ts_ms,
            kind=variant.kind,
        )
        predictions = predict_distribution(features, variant.plan, history)
        decision_ids.append(store.record(
            kind=variant.kind,
            symbol=symbol,
            features=features,
            plan=variant.plan,
            baseline_plan=variant.baseline_plan,
            predictions=predictions,
            algorithm_decision=(
                f"variant={variant.variant_id};dimension={variant.dimension}"
            ),
        ))
    return tuple(decision_ids)


def shadow_variant_report(
    store: PredictionShadowStore,
    *,
    symbol: str,
    variants: Iterable[ShadowVariant],
    before_ts_ms: int,
) -> dict[str, object]:
    """Return independent walk-forward gates; never authorize APPLY."""
    evidence: dict[str, tuple[ShadowVariant, list[object], dict[str, object]]] = {}
    p_values: dict[str, float] = {}
    for variant in variants:
        samples = store.resolved_samples(
            symbol,
            before_ts_ms=before_ts_ms,
            kind=variant.kind,
        )
        walk_forward = walk_forward_prediction_report(samples)
        evidence[variant.variant_id] = (variant, samples, walk_forward)
        p_values[variant.variant_id] = configuration_edge_p_value(samples)
    configuration_holm = holm_configuration_correction(p_values)
    reports: dict[str, object] = {}
    for variant_id, (variant, samples, walk_forward) in evidence.items():
        gate = walk_forward["gate"]
        holm_passed = configuration_holm[variant_id]
        reports[variant.variant_id] = {
            "dimension": variant.dimension,
            "kind": variant.kind,
            "entry_ttl_sec": variant.plan.entry_ttl_sec,
            "entry_enabled": variant.plan.entry_enabled,
            "samples": len(samples),
            "gate": gate,
            "configuration_p_value": p_values[variant_id],
            "configuration_holm_passed": holm_passed,
            "promotion_eligible": bool(gate.get("approved")) and holm_passed,
            "apply_allowed": False,
            "lookahead": False,
        }
    return {
        "mode": "SHADOW",
        "baseline": "current_strategy_plan",
        "same_snapshot": True,
        "can_change_orders": False,
        "variants": reports,
    }


__all__ = [
    "ENTRY_TTL_SEC",
    "FEE_FLOOR_BUFFER_PCT",
    "ShadowVariant",
    "build_shadow_variants",
    "record_shadow_variants",
    "shadow_variant_report",
]
