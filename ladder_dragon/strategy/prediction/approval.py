# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: apply statistically gated prediction approval.

"""Fail-closed statistical approval for counterfactual prediction samples."""

from __future__ import annotations

from decimal import Decimal
import math
import random
from typing import Sequence

from ladder_dragon.strategy.prediction.models import ResolvedSample


D = Decimal
ZERO = D("0")
DEFAULT_HORIZONS_MIN = (1, 5, 15)


def _validated_horizons(horizons_min: Sequence[int]) -> tuple[int, ...]:
    horizons = tuple(horizons_min)
    invalid_type = any(
        isinstance(value, bool) or not isinstance(value, int)
        for value in horizons
    )
    if (
        not horizons
        or invalid_type
        or any(value <= 0 for value in horizons)
        or tuple(sorted(set(horizons))) != horizons
    ):
        raise ValueError("approval horizons must be unique increasing positive integers")
    return horizons


def bootstrap_mean_ci(
    values: Sequence[Decimal], *, iterations: int = 1000, seed: int = 23
) -> tuple[Decimal, Decimal]:
    """Return a deterministic percentile bootstrap interval for the mean."""
    if not values:
        return ZERO, ZERO
    rng = random.Random(seed)
    means = []
    for _ in range(iterations):
        draw = [values[rng.randrange(len(values))] for _ in values]
        means.append(sum(draw, ZERO) / D(str(len(draw))))
    means.sort()
    return means[int(len(means) * 0.025)], means[int(len(means) * 0.975)]


def _paired_sign_p_value(edges: Sequence[Decimal]) -> float:
    nonzero = [value for value in edges if value != 0]
    if not nonzero:
        return 1.0
    wins = sum(value > 0 for value in nonzero)
    probability = sum(
        math.comb(len(nonzero), index) for index in range(wins, len(nonzero) + 1)
    ) / (2 ** len(nonzero))
    return min(1.0, probability)


def paired_sign_p_value(edges: Sequence[Decimal]) -> float:
    """Return the exact one-sided paired sign-test probability."""
    return _paired_sign_p_value(edges)


def _holm(p_values: Sequence[float], alpha: float = 0.05) -> list[bool]:
    indexed = sorted(enumerate(p_values), key=lambda item: item[1])
    accepted = [False] * len(p_values)
    for rank, (index, value) in enumerate(indexed):
        if value <= alpha / max(1, len(indexed) - rank):
            accepted[index] = True
        else:
            break
    return accepted


def configuration_edge_p_value(samples: Sequence[ResolvedSample]) -> float:
    """Return one independent paired-edge hypothesis for one configuration."""
    grouped: dict[int, list[ResolvedSample]] = {}
    for sample in samples:
        grouped.setdefault(sample.snapshot_ts_ms, []).append(sample)
    edges = []
    for rows in grouped.values():
        count = D(str(len(rows)))
        edges.append(sum(
            (
                row.outcome.net_pnl_quote - row.baseline_net_pnl_quote
                for row in rows
            ),
            ZERO,
        ) / count)
    return _paired_sign_p_value(edges)


def holm_configuration_correction(
    p_values: dict[str, float],
    *,
    alpha: float = 0.05,
) -> dict[str, bool]:
    """Correct distinct configuration hypotheses without duplicating p-values."""
    names = list(p_values)
    decisions = _holm([p_values[name] for name in names], alpha=alpha)
    return {name: decisions[index] for index, name in enumerate(names)}


def prediction_apply_gate(
    samples: Sequence[ResolvedSample],
    *,
    min_independent_samples: int = 120,
    min_regime_samples: int = 20,
    min_fill_rate: Decimal = D("0.10"),
    max_drawdown_quote: Decimal = D("25"),
    required_horizons_min: Sequence[int] = DEFAULT_HORIZONS_MIN,
) -> dict[str, object]:
    """Approve nothing unless net edge survives CI, Holm and every regime."""
    required_horizons = _validated_horizons(required_horizons_min)
    ordered = sorted(samples, key=lambda item: (item.snapshot_ts_ms, item.horizon_min))
    grouped: dict[int, list[ResolvedSample]] = {}
    for item in ordered:
        grouped.setdefault(item.snapshot_ts_ms, []).append(item)
    independent_rows = []
    for timestamp, rows in sorted(grouped.items()):
        count = D(str(len(rows)))
        independent_rows.append({
            "timestamp": timestamp,
            "regime": rows[0].regime,
            "pnl": sum((row.outcome.net_pnl_quote for row in rows), ZERO) / count,
            "edge": sum(
                (
                    row.outcome.net_pnl_quote - row.baseline_net_pnl_quote
                    for row in rows
                ),
                ZERO,
            ) / count,
            "fill": D(str(sum(row.outcome.buy_filled for row in rows))) / count,
        })
    independent = len(independent_rows)
    pnl = [row["pnl"] for row in independent_rows]
    edges = [row["edge"] for row in independent_rows]
    ci = bootstrap_mean_ci(pnl)
    edge_ci = bootstrap_mean_ci(edges)
    hypotheses: list[tuple[str, list[Decimal]]] = []
    for horizon in required_horizons:
        horizon_rows = [row for row in ordered if row.horizon_min == horizon]
        hypotheses.append((
            f"horizon_{horizon}",
            [
                row.outcome.net_pnl_quote - row.baseline_net_pnl_quote
                for row in horizon_rows
            ],
        ))
    regimes = sorted({str(row["regime"]) for row in independent_rows})
    for regime in regimes:
        hypotheses.append((
            f"regime_{regime}",
            [row["edge"] for row in independent_rows if row["regime"] == regime],
        ))
    p_values = [_paired_sign_p_value(edges) for _, edges in hypotheses]
    holm = _holm(p_values)
    hypothesis_report = {
        name: {
            "samples": len(hypothesis_edges),
            "p_value": p_values[index],
            "passed": holm[index],
        }
        for index, (name, hypothesis_edges) in enumerate(hypotheses)
    }
    cumulative = ZERO
    peak = ZERO
    max_drawdown = ZERO
    for value in pnl:
        cumulative += value
        peak = max(peak, cumulative)
        max_drawdown = max(max_drawdown, peak - cumulative)
    fill_rate = (
        sum((row["fill"] for row in independent_rows), ZERO) / D(str(independent))
        if independent_rows else ZERO
    )
    required_regimes = {"TREND_UP", "TREND_DOWN", "RANGE", "PANIC"}
    regime_counts = {
        regime: sum(row["regime"] == regime for row in independent_rows)
        for regime in required_regimes
    }
    reasons = []
    if independent < min_independent_samples:
        reasons.append("insufficient independent samples")
    if ci[0] <= 0:
        reasons.append("net expectancy lower CI is not positive")
    if edge_ci[0] <= 0:
        reasons.append("baseline edge lower CI is not positive")
    if any(count < min_regime_samples for count in regime_counts.values()):
        reasons.append("market regime coverage is incomplete")
    if hypotheses and not all(holm):
        reasons.append("Holm-corrected hypotheses did not all pass")
    if fill_rate < min_fill_rate:
        reasons.append("fill rate is below threshold")
    if max_drawdown > max_drawdown_quote:
        reasons.append("drawdown exceeds threshold")
    return {
        "approved": not reasons,
        "mode": "APPLY" if not reasons else "SHADOW",
        "reasons": reasons,
        "independent_samples": independent,
        "net_expectancy_ci": [format(ci[0], "f"), format(ci[1], "f")],
        "baseline_edge_ci": [format(edge_ci[0], "f"), format(edge_ci[1], "f")],
        "fill_rate": format(fill_rate, "f"),
        "max_drawdown_quote": format(max_drawdown, "f"),
        "regime_counts": regime_counts,
        "hypotheses": hypothesis_report,
    }

__all__ = [
    "bootstrap_mean_ci",
    "configuration_edge_p_value",
    "holm_configuration_correction",
    "paired_sign_p_value",
    "prediction_apply_gate",
]
