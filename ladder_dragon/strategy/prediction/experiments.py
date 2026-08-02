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
EDGE_EPSILON_PCT = D("0.000001")
TP_TARGETS = (
    ("v2_tp_100", D("0.0100")),
    ("v2_tp_105", D("0.0105")),
    ("v2_tp_110", D("0.0110")),
)
BUY_GAPS = (
    ("v2_buy_gap_5bps", D("0.0005")),
    ("v2_buy_gap_8bps", D("0.0008")),
    ("v2_buy_gap_10bps", D("0.0010")),
)
ENTRY_TTLS = (
    ("v2_ttl_3m", 180),
    ("v2_ttl_5m", 300),
    ("v2_ttl_8m", 480),
)
COMBINED_CANDIDATES = (
    ("v2_a_range_ttl5_maker_tp100_gap5", D("0.0100"), 300, D("0.0005")),
    ("v2_b_range_ttl5_maker_tp105_gap8", D("0.0105"), 300, D("0.0008")),
    ("v2_c_range_ttl5_maker_tp110_gap10", D("0.0110"), 300, D("0.0010")),
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
    entry_gap_bps: Decimal | None = None


def dynamic_entry_gap_pct(
    *, spread_bps: Decimal, atr_pct: Decimal
) -> Decimal:
    """Clamp spread plus one-quarter ATR to a five-to-fifteen basis-point gap."""
    if (
        not spread_bps.is_finite()
        or spread_bps < 0
        or not atr_pct.is_finite()
        or atr_pct < 0
    ):
        raise ValueError("dynamic gap inputs must be finite and non-negative")
    proposed = spread_bps / D("10000") + atr_pct / D("4")
    return min(D("0.0015"), max(D("0.0005"), proposed))


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
    spread_bps: Decimal = D("0"),
    atr_pct: Decimal = D("0"),
) -> tuple[ShadowVariant, ...]:
    """Build isolated and combined candidates above the authoritative fee floor."""
    if not market_price.is_finite() or market_price <= 0:
        raise ValueError("market price must be positive and finite")
    if not required_edge_pct.is_finite() or required_edge_pct <= 0:
        raise ValueError("required edge must be positive and finite")
    baseline_target = (
        baseline_plan.take_profit_price / baseline_plan.entry_price - D("1")
    )
    target_pct = max(baseline_target, required_edge_pct + EDGE_EPSILON_PCT)
    dynamic_gap = dynamic_entry_gap_pct(
        spread_bps=spread_bps,
        atr_pct=atr_pct,
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
        entry_gap_pct: Decimal | None = None,
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
            entry_gap_bps=(
                entry_gap_pct * D("10000")
                if entry_gap_pct is not None else None
            ),
        )

    variants = [
        variant(
            "v2_range_only",
            "regime_gate",
            entry_enabled=str(regime).upper() == "RANGE",
        ),
        *(variant(name, "take_profit", candidate_target=value)
          for name, value in TP_TARGETS),
        variant("v2_maker_only", "execution_policy", maker_only=True),
        *(variant(name, "entry_ttl", entry_ttl_sec=value)
          for name, value in ENTRY_TTLS),
        *(variant(
            name,
            "buy_distance",
            entry_price=max(
                baseline_plan.entry_price,
                market_price * (D("1") - value),
            ),
            entry_gap_pct=value,
        ) for name, value in BUY_GAPS),
        *(variant(
            name,
            "combined_range_execution",
            entry_price=max(
                baseline_plan.entry_price,
                market_price * (D("1") - gap),
            ),
            candidate_target=take_profit,
            entry_ttl_sec=ttl,
            entry_enabled=str(regime).upper() == "RANGE",
            maker_only=True,
            entry_gap_pct=gap,
        ) for name, take_profit, ttl, gap in COMBINED_CANDIDATES),
        variant(
            "v2_d_range_ttl8_maker_tp105_dynamic",
            "combined_range_execution",
            entry_price=max(
                baseline_plan.entry_price,
                market_price * (D("1") - dynamic_gap),
            ),
            candidate_target=D("0.0105"),
            entry_ttl_sec=480,
            entry_enabled=str(regime).upper() == "RANGE",
            maker_only=True,
            entry_gap_pct=dynamic_gap,
        ),
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
        outcome_counts = store.outcome_status_counts(
            symbol,
            variant.kind,
            as_of_ms=before_ts_ms,
        )
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
            "resolved_horizon_samples": len(samples),
            "independent_samples": int(gate.get("independent_samples", 0)),
            "outcomes": outcome_counts,
            "entry_gap_bps": (
                str(variant.entry_gap_bps)
                if variant.entry_gap_bps is not None else None
            ),
            "gate": gate,
            "configuration_p_value": p_values[variant_id],
            "configuration_holm_passed": holm_passed,
            "promotion_eligible": bool(gate.get("approved")) and holm_passed,
            "apply_allowed": False,
            "lookahead": False,
        }
    return {
        "mode": "SHADOW",
        "generation": "v2",
        "baseline": "current_strategy_plan",
        "same_snapshot": True,
        "can_change_orders": False,
        "variants": reports,
    }


__all__ = [
    "BUY_GAPS",
    "COMBINED_CANDIDATES",
    "ENTRY_TTLS",
    "EDGE_EPSILON_PCT",
    "TP_TARGETS",
    "ShadowVariant",
    "build_shadow_variants",
    "dynamic_entry_gap_pct",
    "record_shadow_variants",
    "shadow_variant_report",
]
