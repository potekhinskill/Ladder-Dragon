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
V12_SPEC = ShadowExperimentSpec(
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

_GENERATION_SPECS = {
    V11_SPEC.generation: V11_SPEC,
    V12_SPEC.generation: V12_SPEC,
}
_SYMBOL_SPECS = {
    "ETHUSDT": V11_SPEC,
    "SOLUSDT": V12_SPEC,
}


def experiment_spec_for_generation(generation: str) -> ShadowExperimentSpec:
    """Return one known immutable generation or fail closed."""
    normalized = str(generation).strip().lower()
    try:
        return _GENERATION_SPECS[normalized]
    except KeyError as exc:
        raise ValueError("SHADOW experiment generation is unavailable") from exc


def experiment_spec_for_symbol(symbol: str) -> ShadowExperimentSpec:
    """Return the reviewed generation for one configured prediction symbol."""
    normalized = str(symbol).strip().upper()
    try:
        return _SYMBOL_SPECS[normalized]
    except KeyError as exc:
        raise ValueError("SHADOW experiment symbol is unavailable") from exc


def configured_entry_gap_bps(
    variant_id: str, *, generation: str = "v12"
) -> Decimal:
    """Return one configured entry gap without snapshot reconstruction."""
    try:
        spec = experiment_spec_for_generation(generation)
    except ValueError as exc:
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
    "configured_entry_gap_bps",
    "experiment_spec_for_generation",
    "experiment_spec_for_symbol",
]
