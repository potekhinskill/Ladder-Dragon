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

# Preserve the public historical name for callers that inspect SOL v12.
V12_SPEC = SOL_V12_SPEC

_SYMBOL_GENERATION_SPECS = {
    ("BTCUSDT", "v11"): V11_SPEC,
    ("BTCUSDT", "v12"): BTC_V12_SPEC,
    ("ETHUSDT", "v11"): V11_SPEC,
    ("ETHUSDT", "v12"): ETH_V12_SPEC,
    ("ETHUSDT", "v13"): ETH_V13_SPEC,
    ("SOLUSDT", "v11"): V11_SPEC,
    ("SOLUSDT", "v12"): SOL_V12_SPEC,
    ("SOLUSDT", "v13"): SOL_V13_SPEC,
    ("SOLUSDT", "v14"): SOL_V14_SPEC,
}
_SYMBOL_SPECS = {
    "BTCUSDT": BTC_V12_SPEC,
    "ETHUSDT": ETH_V13_SPEC,
    "SOLUSDT": SOL_V14_SPEC,
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
    variant_id: str, *, generation: str = "v14", symbol: str | None = None
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
    "SOL_V12_SPEC",
    "SOL_V13_SPEC",
    "SOL_V14_SPEC",
    "configured_entry_gap_bps",
    "experiment_dimension",
    "experiment_spec_for_generation",
    "experiment_spec_for_symbol",
]
