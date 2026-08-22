# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: define immutable per-symbol SHADOW experiment generations.
"""Select one reviewed SHADOW experiment specification for each symbol."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal


D = Decimal


@dataclass(frozen=True)
class ShadowExperimentSpec:
    """Immutable strategy semantics for one symbol generation."""

    generation: str
    horizons_min: tuple[int, ...]
    maker_ttls: tuple[tuple[str, int], ...]
    maker_entry_gaps: tuple[tuple[str, Decimal], ...]
    superseded_selection_generations: tuple[str, ...] = ()
    regime_policy: str = "always_active"
    statistical_design_version: str = "fixed_60_120_v1"
    evidence_semantics_version: str = "configured_fee_touch_model_v1"
    lifecycle_mode: str = "DIAGNOSTIC_ONLY"
    execution_model_rule: str = "ohlc_touch_diagnostic_v1"
    primary_horizon_min: int | None = None
    diagnostic_horizons_min: tuple[int, ...] = ()
    stop_limit_offset_pct: Decimal = D("0.0015")
    maximum_holding_min: int | None = None
    target_return: Decimal | None = None
    stop_limit_distance: Decimal | None = None
    evidence_notional_quote: Decimal | None = None


V11_SPEC = ShadowExperimentSpec(
    generation="v11",
    horizons_min=(300, 360),
    maker_ttls=(("ttl60", 3_600),),
    maker_entry_gaps=(
        ("gap38", D("0.0038")),
        ("gap42", D("0.0042")),
        ("gap44", D("0.0044")),
    ),
)
SOL_V12_SPEC = ShadowExperimentSpec(
    generation="v12",
    horizons_min=(300, 360),
    maker_ttls=(("ttl60", 3_600),),
    maker_entry_gaps=(
        ("gap44", D("0.0044")),
        ("gap46", D("0.0046")),
        ("gap48", D("0.0048")),
    ),
    superseded_selection_generations=("v11",),
)
ETH_V12_SPEC = ShadowExperimentSpec(
    generation="v12",
    horizons_min=(300, 360),
    maker_ttls=(("ttl60", 3_600),),
    maker_entry_gaps=(
        ("gap19", D("0.0019")),
        ("gap22", D("0.0022")),
        ("gap27", D("0.0027")),
    ),
    superseded_selection_generations=("v11",),
)
ETH_V13_SPEC = ShadowExperimentSpec(
    generation="v13",
    horizons_min=(300, 360),
    maker_ttls=(("ttl60", 3_600),),
    maker_entry_gaps=(
        ("gap20", D("0.0020")),
        ("gap21", D("0.0021")),
        ("gap22", D("0.0022")),
    ),
    superseded_selection_generations=("v11", "v12"),
)
SOL_V13_SPEC = ShadowExperimentSpec(
    generation="v13",
    horizons_min=(300, 360),
    maker_ttls=(("ttl60", 3_600),),
    maker_entry_gaps=(
        ("gap48", D("0.0048")),
        ("gap50", D("0.0050")),
        ("gap52", D("0.0052")),
    ),
    superseded_selection_generations=("v11", "v12"),
)
SOL_V14_SPEC = ShadowExperimentSpec(
    generation="v14",
    horizons_min=(300, 360),
    maker_ttls=(
        ("ttl60", 3_600),
        ("ttl75", 4_500),
        ("ttl90", 5_400),
    ),
    maker_entry_gaps=(("gap48", D("0.0048")),),
    superseded_selection_generations=("v11", "v12", "v13"),
)
BTC_V12_SPEC = ShadowExperimentSpec(
    generation="v12",
    horizons_min=(300, 360),
    maker_ttls=(("ttl60", 3_600),),
    maker_entry_gaps=(
        ("gap8p4", D("0.00084")),
        ("gap9p4", D("0.00094")),
        ("gap10p3", D("0.00103")),
    ),
    superseded_selection_generations=("v11",),
)
SOL_V15_SPEC = ShadowExperimentSpec(
    generation="v15",
    horizons_min=(300, 360),
    maker_ttls=SOL_V14_SPEC.maker_ttls,
    maker_entry_gaps=SOL_V14_SPEC.maker_entry_gaps,
    superseded_selection_generations=("v11", "v12", "v13", "v14"),
    regime_policy="block_panic",
    statistical_design_version="powered_historical_cold_start_v1",
)
ETH_V14_SPEC = ShadowExperimentSpec(
    generation="v14",
    horizons_min=(300, 360),
    maker_ttls=ETH_V13_SPEC.maker_ttls,
    maker_entry_gaps=ETH_V13_SPEC.maker_entry_gaps,
    superseded_selection_generations=("v11", "v12", "v13"),
    regime_policy="block_panic",
    statistical_design_version="powered_historical_cold_start_v1",
)
BTC_V13_SPEC = ShadowExperimentSpec(
    generation="v13",
    horizons_min=(300, 360),
    maker_ttls=BTC_V12_SPEC.maker_ttls,
    maker_entry_gaps=BTC_V12_SPEC.maker_entry_gaps,
    superseded_selection_generations=("v11", "v12"),
    regime_policy="block_panic",
    statistical_design_version="powered_historical_cold_start_v1",
)
SOL_V16_SPEC = ShadowExperimentSpec(
    generation="v16",
    horizons_min=SOL_V15_SPEC.horizons_min,
    maker_ttls=SOL_V15_SPEC.maker_ttls,
    maker_entry_gaps=SOL_V15_SPEC.maker_entry_gaps,
    superseded_selection_generations=("v11", "v12", "v13", "v14", "v15"),
    regime_policy="block_panic",
    statistical_design_version="powered_historical_cold_start_v1",
    evidence_semantics_version="authoritative_fee_oco_touch_model_v2",
)
ETH_V15_SPEC = ShadowExperimentSpec(
    generation="v15",
    horizons_min=ETH_V14_SPEC.horizons_min,
    maker_ttls=ETH_V14_SPEC.maker_ttls,
    maker_entry_gaps=ETH_V14_SPEC.maker_entry_gaps,
    superseded_selection_generations=("v11", "v12", "v13", "v14"),
    regime_policy="block_panic",
    statistical_design_version="powered_historical_cold_start_v1",
    evidence_semantics_version="authoritative_fee_oco_touch_model_v2",
)
BTC_V14_SPEC = ShadowExperimentSpec(
    generation="v14",
    horizons_min=BTC_V13_SPEC.horizons_min,
    maker_ttls=BTC_V13_SPEC.maker_ttls,
    maker_entry_gaps=BTC_V13_SPEC.maker_entry_gaps,
    superseded_selection_generations=("v11", "v12", "v13"),
    regime_policy="block_panic",
    statistical_design_version="powered_historical_cold_start_v1",
    evidence_semantics_version="authoritative_fee_oco_touch_model_v2",
)
SOL_V17_SPEC = ShadowExperimentSpec(
    generation="v17",
    horizons_min=(300, 360),
    maker_ttls=(("ttl90", 5_400),),
    maker_entry_gaps=(("gap48", D("0.0048")),),
    superseded_selection_generations=(
        "v11", "v12", "v13", "v14", "v15", "v16",
    ),
    regime_policy="block_panic",
    statistical_design_version="episode_alpha_spending_v1",
    evidence_semantics_version="minute_l2_episode_execution_v1",
    lifecycle_mode="PROMOTION",
    execution_model_rule="minute_l2_fifo_oco_gap_v1",
    primary_horizon_min=360,
    diagnostic_horizons_min=(300,),
    stop_limit_offset_pct=D("0.0015"),
    maximum_holding_min=360,
    target_return=D("0.0060"),
    stop_limit_distance=D("0.01035"),
    evidence_notional_quote=D("6"),
)
SOL_V18_SPEC = ShadowExperimentSpec(
    generation="v18",
    horizons_min=SOL_V17_SPEC.horizons_min,
    maker_ttls=SOL_V17_SPEC.maker_ttls,
    maker_entry_gaps=SOL_V17_SPEC.maker_entry_gaps,
    superseded_selection_generations=(
        "v11", "v12", "v13", "v14", "v15", "v16", "v17",
    ),
    regime_policy=SOL_V17_SPEC.regime_policy,
    statistical_design_version="episode_combined_alpha_spending_v2",
    evidence_semantics_version=SOL_V17_SPEC.evidence_semantics_version,
    lifecycle_mode=SOL_V17_SPEC.lifecycle_mode,
    execution_model_rule=SOL_V17_SPEC.execution_model_rule,
    primary_horizon_min=SOL_V17_SPEC.primary_horizon_min,
    diagnostic_horizons_min=SOL_V17_SPEC.diagnostic_horizons_min,
    stop_limit_offset_pct=SOL_V17_SPEC.stop_limit_offset_pct,
    maximum_holding_min=SOL_V17_SPEC.maximum_holding_min,
    target_return=SOL_V17_SPEC.target_return,
    stop_limit_distance=SOL_V17_SPEC.stop_limit_distance,
    evidence_notional_quote=SOL_V17_SPEC.evidence_notional_quote,
)

# Preserve the public historical name for callers that inspect SOL v12.
V12_SPEC = SOL_V12_SPEC

_SYMBOL_GENERATION_SPECS = {
    ("BTCUSDT", "v11"): V11_SPEC,
    ("BTCUSDT", "v12"): BTC_V12_SPEC,
    ("BTCUSDT", "v13"): BTC_V13_SPEC,
    ("BTCUSDT", "v14"): BTC_V14_SPEC,
    ("ETHUSDT", "v11"): V11_SPEC,
    ("ETHUSDT", "v12"): ETH_V12_SPEC,
    ("ETHUSDT", "v13"): ETH_V13_SPEC,
    ("ETHUSDT", "v14"): ETH_V14_SPEC,
    ("ETHUSDT", "v15"): ETH_V15_SPEC,
    ("SOLUSDT", "v11"): V11_SPEC,
    ("SOLUSDT", "v12"): SOL_V12_SPEC,
    ("SOLUSDT", "v13"): SOL_V13_SPEC,
    ("SOLUSDT", "v14"): SOL_V14_SPEC,
    ("SOLUSDT", "v15"): SOL_V15_SPEC,
    ("SOLUSDT", "v16"): SOL_V16_SPEC,
    ("SOLUSDT", "v17"): SOL_V17_SPEC,
    ("SOLUSDT", "v18"): SOL_V18_SPEC,
}
_SYMBOL_SPECS = {
    "BTCUSDT": BTC_V14_SPEC,
    "ETHUSDT": ETH_V15_SPEC,
    "SOLUSDT": SOL_V18_SPEC,
}


def experiment_spec_for_generation(
    generation: str, *, symbol: str | None = None
) -> ShadowExperimentSpec:
    """Return one immutable symbol generation or reject ambiguous semantics."""
    normalized = str(generation).strip().lower()
    if symbol is not None:
        key = (str(symbol).strip().upper(), normalized)
        try:
            return _SYMBOL_GENERATION_SPECS[key]
        except KeyError as exc:
            raise ValueError("SHADOW experiment generation is unavailable") from exc
    matches = {
        spec for (_symbol, known_generation), spec
        in _SYMBOL_GENERATION_SPECS.items()
        if known_generation == normalized
    }
    if len(matches) == 1:
        return matches.pop()
    if len(matches) > 1:
        raise ValueError("SHADOW experiment generation requires a symbol")
    raise ValueError("SHADOW experiment generation is unavailable")


def experiment_spec_for_symbol(symbol: str) -> ShadowExperimentSpec:
    """Return the reviewed generation for one configured prediction symbol."""
    normalized = str(symbol).strip().upper()
    try:
        return _SYMBOL_SPECS[normalized]
    except KeyError as exc:
        raise ValueError("SHADOW experiment symbol is unavailable") from exc


def experiment_dimension(
    generation: str, *, symbol: str | None = None
) -> str:
    """Name the single parameter axis changed by one experiment."""
    spec = experiment_spec_for_generation(generation, symbol=symbol)
    if len(spec.maker_ttls) > 1 and len(spec.maker_entry_gaps) == 1:
        return "maker_entry_ttl"
    return "maker_entry_gap"


def configured_entry_gap_bps(
    variant_id: str, *, generation: str = "v16", symbol: str | None = None
) -> Decimal:
    """Return one configured entry gap without snapshot reconstruction."""
    try:
        spec = experiment_spec_for_generation(generation, symbol=symbol)
    except ValueError as exc:
        if "requires a symbol" in str(exc):
            raise
        raise ValueError(
            "configured entry gap is unavailable for generation"
        ) from exc
    normalized_variant = str(variant_id).strip().lower()
    configured = {
        f"{spec.generation}_maker_{ttl_name}_{gap_name}": gap_pct * D("10000")
        for ttl_name, _ttl_sec in spec.maker_ttls
        for gap_name, gap_pct in spec.maker_entry_gaps
    }
    try:
        return configured[normalized_variant]
    except KeyError as exc:
        raise ValueError("configured entry gap is unavailable for variant") from exc


__all__ = [
    "ShadowExperimentSpec",
    "V11_SPEC",
    "V12_SPEC",
    "ETH_V12_SPEC",
    "ETH_V13_SPEC",
    "BTC_V12_SPEC",
    "BTC_V13_SPEC",
    "BTC_V14_SPEC",
    "SOL_V12_SPEC",
    "SOL_V13_SPEC",
    "SOL_V14_SPEC",
    "SOL_V15_SPEC",
    "SOL_V16_SPEC",
    "SOL_V17_SPEC",
    "SOL_V18_SPEC",
    "ETH_V14_SPEC",
    "ETH_V15_SPEC",
    "configured_entry_gap_bps",
    "experiment_dimension",
    "experiment_spec_for_generation",
    "experiment_spec_for_symbol",
]
