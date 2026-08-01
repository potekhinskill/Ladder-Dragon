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
TP_TARGETS = (
    ("tp_115", D("0.0115")),
    ("tp_130", D("0.0130")),
    ("tp_150", D("0.0150")),
)
BUY_GAPS = (
    ("buy_gap_10bps", D("0.0010")),
    ("buy_gap_15bps", D("0.0015")),
    ("buy_gap_20bps", D("0.0020")),
)
ENTRY_TTLS = (
    ("ttl_5m", 300),
    ("ttl_10m", 600),
    ("ttl_15m", 900),
)
COMBINED_CANDIDATES = (
    ("range_ttl5_maker_tp115_gap10", D("0.0115"), D("0.0010")),
    ("range_ttl5_maker_tp130_gap15", D("0.0130"), D("0.0015")),
    ("range_ttl5_maker_tp150_gap20", D("0.0150"), D("0.0020")),
)


@dataclass(frozen=True)
class ShadowVariant:
    """One immutable candidate compared with the current strategy plan."""

    variant_id: str
    dimension: str
    kind: str
    plan: TradePlan
    baseline_plan: TradePlan
    maker_only: bool = False


def _candidate_plan(
    baseline: TradePlan,
    *,
    entry_price: Decimal,
    target_pct: Decimal,
    entry_ttl_sec: int | None = None,
    entry_enabled: bool = True,
    slippage_pct: Decimal | None = None,
) -> TradePlan:
    stop_distance = D("1") - baseline.stop_price / baseline.entry_price
    return TradePlan(
        entry_price=entry_price,
        take_profit_price=entry_price * (D("1") + target_pct),
        stop_price=entry_price * (D("1") - stop_distance),
        notional_quote=baseline.notional_quote,
        fee_pct=baseline.fee_pct,
        slippage_pct=(
            baseline.slippage_pct
            if slippage_pct is None
            else slippage_pct
        ),
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
    """Build isolated and combined candidates above the authoritative fee floor."""
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
    def variant(
        variant_id: str,
        dimension: str,
        *,
        entry_price: Decimal = baseline_plan.entry_price,
        candidate_target: Decimal = target_pct,
        entry_ttl_sec: int | None = None,
        entry_enabled: bool = True,
        maker_only: bool = False,
    ) -> ShadowVariant:
        return ShadowVariant(
            variant_id=variant_id,
            dimension=dimension,
            kind=f"EXPERIMENT_{variant_id.upper()}",
            plan=_candidate_plan(
                baseline_plan,
                entry_price=entry_price,
                target_pct=max(candidate_target, target_pct),
                entry_ttl_sec=entry_ttl_sec,
                entry_enabled=entry_enabled,
                slippage_pct=D("0") if maker_only else None,
            ),
            baseline_plan=baseline_plan,
            maker_only=maker_only,
        )

    variants = [
        variant(
            "range_only",
            "regime_gate",
            entry_enabled=str(regime).upper() == "RANGE",
        ),
        *(variant(name, "take_profit", candidate_target=value)
          for name, value in TP_TARGETS),
        variant("maker_only", "execution_policy", maker_only=True),
        *(variant(name, "entry_ttl", entry_ttl_sec=value)
          for name, value in ENTRY_TTLS),
        *(variant(
            name,
            "buy_distance",
            entry_price=max(
                baseline_plan.entry_price,
                market_price * (D("1") - value),
            ),
        ) for name, value in BUY_GAPS),
        *(variant(
            name,
            "combined_range_execution",
            entry_price=max(
                baseline_plan.entry_price,
                market_price * (D("1") - gap),
            ),
            candidate_target=take_profit,
            entry_ttl_sec=300,
            entry_enabled=str(regime).upper() == "RANGE",
            maker_only=True,
        ) for name, take_profit, gap in COMBINED_CANDIDATES),
    ]
    return tuple(variants)


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
            "entry_order_type": (
                "LIMIT_MAKER" if variant.maker_only else "BASELINE"
            ),
            "exit_order_type": (
                "LIMIT_MAKER" if variant.maker_only else "BASELINE"
            ),
            "target_pct": str(
                variant.plan.take_profit_price / variant.plan.entry_price
                - D("1")
            ),
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
    "BUY_GAPS",
    "COMBINED_CANDIDATES",
    "ENTRY_TTLS",
    "FEE_FLOOR_BUFFER_PCT",
    "TP_TARGETS",
    "ShadowVariant",
    "build_shadow_variants",
    "record_shadow_variants",
    "shadow_variant_report",
]
