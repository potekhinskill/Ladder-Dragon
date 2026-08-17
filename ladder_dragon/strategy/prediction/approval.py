# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: apply statistically gated prediction approval.

"""Fail-closed statistical approval for counterfactual prediction samples."""

from __future__ import annotations

from decimal import Decimal, ROUND_CEILING
import math
import random
from typing import Sequence

from ladder_dragon.strategy.prediction.models import ResolvedSample
from ladder_dragon.strategy.prediction.statistical_units import (
    non_overlapping_timestamps,
    outcome_spacing_ms,
)


D = Decimal
ZERO = D("0")
DEFAULT_HORIZONS_MIN = (1, 5, 15)
ONE_SIDED_95_Z = D("1.6448536269514722")


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


def binomial_upper_rate(successes: int, observations: int) -> Decimal:
    """Return a one-sided Wilson upper rate for a rare pre-outcome event."""
    if observations <= 0:
        return D("1")
    n = D(observations)
    p = D(successes) / n
    z2 = ONE_SIDED_95_Z * ONE_SIDED_95_Z
    spread = ONE_SIDED_95_Z * (
        p * (D("1") - p) / n + z2 / (D("4") * n * n)
    ).sqrt()
    return min(
        D("1"),
        (p + z2 / (D("2") * n) + spread) / (D("1") + z2 / n),
    )


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


def configuration_edge_p_value(
    samples: Sequence[ResolvedSample],
    *,
    required_horizons_min: Sequence[int] = DEFAULT_HORIZONS_MIN,
) -> float:
    """Return one independent paired-edge hypothesis for one configuration."""
    grouped: dict[int, list[ResolvedSample]] = {}
    for sample in samples:
        grouped.setdefault(sample.snapshot_ts_ms, []).append(sample)
    selected = set(non_overlapping_timestamps(
        grouped, horizons_min=required_horizons_min
    ))
    edges = []
    for timestamp, rows in grouped.items():
        if timestamp not in selected:
            continue
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
    raw_snapshot_samples = len(grouped)
    # Treat all horizons from one snapshot as one unit. Keep the next unit
    # only after the longest prior outcome interval closes.
    selected_timestamps = set(non_overlapping_timestamps(
        grouped, horizons_min=required_horizons
    ))
    independent_rows = []
    for timestamp, rows in sorted(grouped.items()):
        if timestamp not in selected_timestamps:
            continue
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
    independent_samples = [
        row for row in ordered if row.snapshot_ts_ms in selected_timestamps
    ]
    for horizon in required_horizons:
        horizon_rows = [
            row for row in independent_samples if row.horizon_min == horizon
        ]
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
        "raw_snapshot_samples": raw_snapshot_samples,
        "independent_samples": independent,
        "excluded_overlapping_snapshots": raw_snapshot_samples - independent,
        "independence_spacing_ms": outcome_spacing_ms(required_horizons),
        "minimum_calendar_duration_ms": (
            max(0, min_independent_samples - 1)
            * outcome_spacing_ms(required_horizons)
            + max(required_horizons) * 60_000
        ),
        "calendar_minimum_excludes_regime_wait": True,
        "required_evaluation_independent_samples": min_independent_samples,
        "net_expectancy_ci": [format(ci[0], "f"), format(ci[1], "f")],
        "baseline_edge_ci": [format(edge_ci[0], "f"), format(edge_ci[1], "f")],
        "fill_rate": format(fill_rate, "f"),
        "max_drawdown_quote": format(max_drawdown, "f"),
        "regime_counts": regime_counts,
        "hypotheses": hypothesis_report,
    }


def regime_reachability_report(
    samples: Sequence[ResolvedSample],
    *,
    required_horizons_min: Sequence[int],
    minimum_per_regime: int = 20,
    minimum_observations: int = 20,
    maximum_duration_ms: int = 180 * 24 * 60 * 60_000,
) -> dict[str, object]:
    """Estimate regime coverage from pre-outcome decision frequencies."""
    required_horizons = _validated_horizons(required_horizons_min)
    grouped: dict[int, str] = {}
    for sample in sorted(samples, key=lambda row: row.snapshot_ts_ms):
        grouped.setdefault(sample.snapshot_ts_ms, sample.regime)
    selected = non_overlapping_timestamps(
        grouped, horizons_min=required_horizons
    )
    regimes = ("TREND_UP", "TREND_DOWN", "RANGE", "PANIC")
    counts = {
        regime: sum(grouped[timestamp] == regime for timestamp in selected)
        for regime in regimes
    }
    observed = len(selected)
    mature = observed >= minimum_observations
    spacing = outcome_spacing_ms(required_horizons)
    details: dict[str, object] = {}
    reachable = mature
    projected_total = observed
    last_timestamp = max(selected) if selected else None
    for regime in regimes:
        count = counts[regime]
        upper_rate = binomial_upper_rate(count, observed)
        if count:
            estimate = int(
                (D(str(minimum_per_regime)) * D(str(observed)) / D(str(count)))
                .to_integral_value(rounding=ROUND_CEILING)
            )
            duration = max(0, estimate - 1) * spacing + max(required_horizons) * 60_000
            regime_reachable = duration <= maximum_duration_ms
            projected_total = max(projected_total, estimate)
        else:
            estimate = (
                int((D(minimum_per_regime) / upper_rate).to_integral_value(
                    rounding=ROUND_CEILING
                ))
                if observed else None
            )
            duration = (
                max(0, estimate - 1) * spacing
                + max(required_horizons) * 60_000
                if estimate is not None else None
            )
            regime_reachable = (
                duration <= maximum_duration_ms
                if duration is not None else True
            )
            if estimate is not None:
                projected_total = max(projected_total, estimate)
        if mature and not regime_reachable:
            reachable = False
        details[regime] = {
            "observed": count,
            "observed_fraction": (
                format(D(str(count)) / D(str(observed)), "f") if observed else "0"
            ),
            "observed_fraction_upper_95": (
                format(upper_rate, "f") if observed else None
            ),
            "projected_required_independent_samples": estimate,
            "projected_duration_ms": duration,
            "projected_ready_ts_ms": (
                last_timestamp
                + max(0, estimate - observed) * spacing
                + max(required_horizons) * 60_000
                if last_timestamp is not None and estimate is not None
                else None
            ),
            "reachable_within_limit": regime_reachable,
        }
    return {
        "status": "READY" if mature else "INSUFFICIENT_HISTORY",
        "observed_independent_samples": observed,
        "minimum_observations": minimum_observations,
        "minimum_per_regime": minimum_per_regime,
        "maximum_duration_ms": maximum_duration_ms,
        "projected_required_independent_samples": projected_total if mature else None,
        "projected_ready_ts_ms": (
            last_timestamp
            + max(0, projected_total - observed) * spacing
            + max(required_horizons) * 60_000
            if mature and last_timestamp is not None else None
        ),
        "practically_reachable": reachable if mature else None,
        "regimes": details,
        "outcome_values_used": False,
    }

__all__ = [
    "binomial_upper_rate",
    "bootstrap_mean_ci",
    "configuration_edge_p_value",
    "holm_configuration_correction",
    "paired_sign_p_value",
    "prediction_apply_gate",
    "regime_reachability_report",
]
