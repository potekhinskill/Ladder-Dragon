# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: evaluate promotion expectancy with preregistered sequential tests.
"""Sequential net-expectancy evidence for complete execution attempts."""

from __future__ import annotations

from decimal import Decimal
import hashlib
import random
from typing import Iterable, Mapping

from ladder_dragon.strategy.prediction.execution_episode import (
    ExecutionEpisodeResult,
)


D = Decimal
ZERO = D("0")
ELIGIBLE_REGIMES = ("RANGE", "TREND_UP", "TREND_DOWN")


def net_expectancy_criteria(*, anytime_valid: bool = False) -> dict[str, object]:
    """Return one immutable net-expectancy statistical contract."""
    if anytime_valid:
        return {
            "criteria_schema_version": 4,
            "method": "anytime_valid_betting_e_process_v4",
            "trial_definition": "executable_terminal_attempts_net_of_fees_including_panic",
            "minimum_eligible_terminal_episodes": 24,
            "minimum_filled_episodes": 10,
            "minimum_fill_rate": "0.10",
            "maximum_drawdown_fraction": "0.25",
            "eligible_regimes": list(ELIGIBLE_REGIMES),
            "minimum_regime_filled_episodes": 8,
            "minimum_confirmed_regimes": 2,
            "regime_noninferiority_fraction": "0",
            "regime_activation_policy": "confirmed_execution_regime_only_v3",
            "maximum_terminal_episodes": 300,
            "maximum_confirmation_duration_ms": 14 * 24 * 60 * 60_000,
            "panic_policy": "include_flatten_pnl_and_count_veto_attempt",
            "mean_lower_bound_method": "mixture_betting_e_process_v1",
            "confidence_alpha": "0.05",
            "evidence_notional_quote": "6",
            "outcome_lower_bound_quote": "-0.12",
            "outcome_upper_bound_quote": "0.06",
            "regime_confidence_policy": "bonferroni_mixture_e_process_v1",
        }
    return {
        "criteria_schema_version": 3,
        "method": "group_sequential_net_expectancy_alpha_spending_v3",
        "trial_definition": "all_terminal_attempts_net_of_fees_including_panic",
        "sequential_looks": [
            {"sample_count": 12, "alpha_spend": "0.005"},
            {"sample_count": 24, "alpha_spend": "0.010"},
            {"sample_count": 34, "alpha_spend": "0.015"},
            {"sample_count": 43, "alpha_spend": "0.020"},
        ],
        "minimum_eligible_terminal_episodes": 12,
        "minimum_filled_episodes": 10,
        "minimum_fill_rate": "0.10",
        "maximum_drawdown_fraction": "0.25",
        "eligible_regimes": list(ELIGIBLE_REGIMES),
        "minimum_regime_filled_episodes": 3,
        "minimum_confirmed_regimes": 2,
        "regime_noninferiority_fraction": "0.02",
        "regime_activation_policy": "confirmed_execution_regime_only_v2",
        "maximum_terminal_episodes": 300,
        "maximum_confirmation_duration_ms": 14 * 24 * 60 * 60_000,
        "panic_policy": "include_flatten_pnl_and_count_veto_attempt",
        "mean_lower_bound_method": "deterministic_percentile_bootstrap_v1",
        "bootstrap_resamples": 10_000,
    }


def _drawdown(values: Iterable[Decimal]) -> Decimal:
    equity = peak = maximum = ZERO
    for value in values:
        equity += value
        peak = max(peak, equity)
        maximum = max(maximum, peak - equity)
    return maximum


def _bootstrap_lower(
    values: list[Decimal], *, alpha: Decimal, resamples: int
) -> Decimal:
    """Return a deterministic one-sided bootstrap lower mean bound."""
    if not values:
        return ZERO
    seed_material = "|".join(format(item, "f") for item in values)
    seed = int(hashlib.sha256(seed_material.encode("utf-8")).hexdigest()[:16], 16)
    generator = random.Random(seed)
    size = len(values)
    means = []
    for _index in range(resamples):
        total = sum((values[generator.randrange(size)] for _ in range(size)), ZERO)
        means.append(total / D(size))
    means.sort()
    quantile = max(0, min(resamples - 1, int(alpha * D(resamples))))
    return means[quantile]


def _e_value(
    values: list[Decimal],
    *,
    null_mean: Decimal,
    lower_bound: Decimal,
    upper_bound: Decimal,
) -> Decimal:
    """Return a nonnegative mixture betting e-value for a bounded mean."""
    if lower_bound >= null_mean or null_mean >= upper_bound:
        raise ValueError("e-process null mean is outside its bounds")
    if any(value < lower_bound or value > upper_bound for value in values):
        raise ValueError("episode outcome is outside preregistered bounds")
    width = upper_bound - lower_bound
    normalized_null = (null_mean - lower_bound) / width
    normalized = [(value - lower_bound) / width for value in values]
    maximum_bet = D("0.95") / normalized_null
    fractions = (D("0.1"), D("0.25"), D("0.5"), D("0.75"), D("1"))
    wealth = []
    for fraction in fractions:
        amount = maximum_bet * fraction
        product = D("1")
        for value in normalized:
            product *= D("1") + amount * (value - normalized_null)
        wealth.append(product)
    return sum(wealth, ZERO) / D(len(wealth))


def _anytime_lower(
    values: list[Decimal],
    *,
    alpha: Decimal,
    lower_bound: Decimal,
    upper_bound: Decimal,
) -> Decimal:
    """Invert a bounded betting e-process into a one-sided confidence bound."""
    if not values:
        return lower_bound
    if alpha <= ZERO or alpha >= D("1"):
        raise ValueError("anytime confidence alpha is invalid")
    threshold = D("1") / alpha
    epsilon = (upper_bound - lower_bound) / D("1000000000000")
    low = lower_bound + epsilon
    high = min(upper_bound - epsilon, sum(values, ZERO) / D(len(values)))
    if high <= low or _e_value(
        values,
        null_mean=low,
        lower_bound=lower_bound,
        upper_bound=upper_bound,
    ) < threshold:
        return lower_bound
    for _index in range(80):
        midpoint = (low + high) / D("2")
        if _e_value(
            values,
            null_mean=midpoint,
            lower_bound=lower_bound,
            upper_bound=upper_bound,
        ) >= threshold:
            low = midpoint
        else:
            high = midpoint
    return low


def _anytime_regimes(
    rows: list[ExecutionEpisodeResult], criteria: Mapping[str, object]
) -> tuple[dict[str, dict[str, object]], list[str]]:
    minimum = int(criteria["minimum_regime_filled_episodes"])
    fraction = D(str(criteria["regime_noninferiority_fraction"]))
    notional = D(str(criteria["evidence_notional_quote"]))
    lower_bound = D(str(criteria["outcome_lower_bound_quote"]))
    upper_bound = D(str(criteria["outcome_upper_bound_quote"]))
    alpha = D(str(criteria["confidence_alpha"])) / D(
        len(criteria["eligible_regimes"])
    )
    reports: dict[str, dict[str, object]] = {}
    confirmed: list[str] = []
    for regime in criteria["eligible_regimes"]:
        name = str(regime)
        cohort = [
            row for row in rows
            if row.start_regime == name and row.entry_filled_quantity > ZERO
        ]
        values = [row.net_pnl_quote for row in cohort]
        bound = _anytime_lower(
            values,
            alpha=alpha,
            lower_bound=lower_bound,
            upper_bound=upper_bound,
        )
        measured = len(cohort) >= minimum
        noninferior = bool(measured and bound >= -notional * fraction)
        if noninferior:
            confirmed.append(name)
        reports[name] = {
            "filled_episodes": len(cohort),
            "required_filled_episodes": minimum,
            "measured": measured,
            "net_pnl_quote": format(sum(values, ZERO), "f"),
            "one_sided_mean_lower_bound_quote": format(bound, "f"),
            "noninferior": noninferior,
        }
    return reports, confirmed


def _anytime_report(
    rows_all: list[ExecutionEpisodeResult],
    *,
    criteria: Mapping[str, object],
    required_semantics_fingerprint: str,
) -> dict[str, object]:
    """Evaluate an anytime-valid executable-policy cohort."""
    mixed = [
        row for row in rows_all
        if row.evidence_semantics_fingerprint != required_semantics_fingerprint
    ]
    rows = [
        row for row in rows_all
        if row.eligible_for_promotion
        and row.evidence_semantics_fingerprint == required_semantics_fingerprint
    ]
    base = {
        "schema_version": 4,
        "method": criteria["method"],
        "raw_terminal_episodes": len(rows_all),
        "eligible_terminal_episodes": len(rows),
        "semantics_mismatch_episodes": len(mixed),
    }
    if mixed:
        return {
            **base,
            "status": "BLOCKED",
            "approved": False,
            "readiness_reason": "mixed evidence semantics are forbidden",
            "looks": [],
            "projected_ready_ts_ms": None,
        }
    if any(row.start_regime not in criteria["eligible_regimes"] for row in rows):
        return {
            **base,
            "status": "BLOCKED",
            "approved": False,
            "readiness_reason": "evidence contains a non-executable entry regime",
            "looks": [],
            "projected_ready_ts_ms": None,
        }
    alpha = D(str(criteria["confidence_alpha"]))
    lower_bound = D(str(criteria["outcome_lower_bound_quote"]))
    upper_bound = D(str(criteria["outcome_upper_bound_quote"]))
    values = [row.net_pnl_quote for row in rows]
    try:
        lower = _anytime_lower(
            values,
            alpha=alpha,
            lower_bound=lower_bound,
            upper_bound=upper_bound,
        )
        regime_report, confirmed = _anytime_regimes(rows, criteria)
    except ValueError as exc:
        return {
            **base,
            "status": "READY_TO_REJECT",
            "approved": False,
            "readiness_reason": str(exc),
            "looks": [],
            "projected_ready_ts_ms": None,
        }
    filled = [row for row in rows if row.entry_filled_quantity > ZERO]
    fill_rate = D(len(filled)) / D(len(rows)) if rows else ZERO
    drawdown = _drawdown(values)
    notional = D(str(criteria["evidence_notional_quote"]))
    minimum = int(criteria["minimum_eligible_terminal_episodes"])
    maximum = int(criteria["maximum_terminal_episodes"])
    panic_rows = [row for row in rows if row.terminal_reason == "PANIC_FLATTEN"]
    panic_failures = [
        row for row in panic_rows
        if row.exit_filled_quantity < row.entry_filled_quantity
    ]
    passed = bool(
        len(rows) >= minimum
        and lower > ZERO
        and len(filled) >= int(criteria["minimum_filled_episodes"])
        and fill_rate >= D(str(criteria["minimum_fill_rate"]))
        and drawdown <= notional * D(str(criteria["maximum_drawdown_fraction"]))
        and len(confirmed) >= int(criteria["minimum_confirmed_regimes"])
        and not panic_failures
    )
    optimistic = values + [upper_bound] * max(0, maximum - len(rows))
    optimistic_lower = _anytime_lower(
        optimistic,
        alpha=alpha,
        lower_bound=lower_bound,
        upper_bound=upper_bound,
    )
    remaining = max(0, maximum - len(rows))
    possible_regimes = sum(
        int(report["filled_episodes"]) + remaining
        >= int(criteria["minimum_regime_filled_episodes"])
        for report in regime_report.values()
    )
    futile = bool(
        len(rows) >= minimum
        and (
            optimistic_lower <= ZERO
            or possible_regimes < int(criteria["minimum_confirmed_regimes"])
        )
    )
    status = "PASS" if passed else "READY_TO_REJECT" if futile or len(rows) >= maximum else "SHADOW"
    durations = [
        row.terminal_at_ms - row.started_at_ms
        for row in rows if row.terminal_at_ms > row.started_at_ms
    ]
    mean_duration = sum(durations) // len(durations) if durations else None
    next_count = minimum if len(rows) < minimum else min(maximum, len(rows) + 1)
    statistics_eta = (
        rows[-1].terminal_at_ms + mean_duration * (next_count - len(rows))
        if rows and mean_duration is not None and status == "SHADOW" else None
    )
    look = {
        "sample_count": len(rows),
        "reached": len(rows) >= minimum,
        "eligible_terminal_episodes": len(rows),
        "filled_episodes": len(filled),
        "fill_rate": format(fill_rate, "f"),
        "net_pnl_quote": format(sum(values, ZERO), "f"),
        "mean_net_pnl_quote": format(
            sum(values, ZERO) / D(len(values)) if values else ZERO, "f"
        ),
        "one_sided_mean_lower_bound_quote": format(lower, "f"),
        "optimistic_final_lower_bound_quote": format(optimistic_lower, "f"),
        "maximum_drawdown_quote": format(drawdown, "f"),
        "regime_safety": regime_report,
        "confirmed_execution_regimes": confirmed,
        "panic_exit_safe": not panic_failures,
        "passed": passed,
    }
    return {
        **base,
        "primary_horizon_min": 360,
        "diagnostic_horizons_min": [300],
        "filled_episodes": len(filled),
        "financial_outcomes": sum(value != ZERO for value in values),
        "panic_flatten_outcomes": len(panic_rows),
        "panic_veto_attempts": sum(
            row.terminal_reason == "PANIC_VETO" for row in rows
        ),
        "panic_safety": {
            "status": "PASS" if panic_rows and not panic_failures else "BLOCKED" if panic_failures else "NOT_OBSERVED",
            "observations": len(panic_rows),
            "residual_position_failures": len(panic_failures),
            "pnl_included_in_expectancy": True,
        },
        "net_pnl_quote": format(sum(values, ZERO), "f"),
        "looks": [look],
        "passed_at_episode": len(rows) if passed else None,
        "next_sequential_look": next_count if status == "SHADOW" else None,
        "data_collection_projected_ready_ts_ms": statistics_eta,
        "statistics_projected_ready_ts_ms": statistics_eta,
        "regime_projected_ready_ts_ms": None,
        "execution_model_projected_ready_ts_ms": None,
        "projected_ready_ts_ms": None,
        "regime_safety": regime_report,
        "regime_missing_filled_episodes": {
            name: max(0, int(criteria["minimum_regime_filled_episodes"]) - int(report["filled_episodes"]))
            for name, report in regime_report.items()
        },
        "confirmed_execution_regimes": confirmed,
        "required_confirmed_regimes": int(criteria["minimum_confirmed_regimes"]),
        "status": status,
        "approved": passed,
        "readiness_reason": "all anytime-valid expectancy gates passed" if passed else "preregistered expectancy is mathematically futile" if status == "READY_TO_REJECT" else "waiting for anytime-valid expectancy and regime evidence",
    }


def _regimes(
    rows: list[ExecutionEpisodeResult], criteria: Mapping[str, object]
) -> tuple[dict[str, dict[str, object]], list[str]]:
    minimum = int(criteria["minimum_regime_filled_episodes"])
    fraction = D(str(criteria["regime_noninferiority_fraction"]))
    reports: dict[str, dict[str, object]] = {}
    confirmed: list[str] = []
    for regime in criteria["eligible_regimes"]:
        name = str(regime)
        cohort = [
            row for row in rows
            if row.start_regime == name and row.entry_filled_quantity > ZERO
        ]
        pnl = sum((row.net_pnl_quote for row in cohort), ZERO)
        notional = sum((row.entry_notional_quote for row in cohort), ZERO)
        measured = len(cohort) >= minimum
        noninferior = bool(measured and pnl >= -notional * fraction)
        if noninferior:
            confirmed.append(name)
        reports[name] = {
            "filled_episodes": len(cohort),
            "required_filled_episodes": minimum,
            "measured": measured,
            "net_pnl_quote": format(pnl, "f"),
            "noninferior": noninferior,
        }
    return reports, confirmed


def sequential_net_expectancy_report(
    results: Iterable[ExecutionEpisodeResult],
    *,
    criteria: Mapping[str, object],
    required_semantics_fingerprint: str,
) -> dict[str, object]:
    """Evaluate complete attempts and reject mixed evidence semantics."""
    rows_all = sorted(results, key=lambda row: row.terminal_at_ms)
    if criteria.get("criteria_schema_version") == 4:
        return _anytime_report(
            rows_all,
            criteria=criteria,
            required_semantics_fingerprint=required_semantics_fingerprint,
        )
    mixed = [
        row for row in rows_all
        if row.evidence_semantics_fingerprint != required_semantics_fingerprint
    ]
    rows = [
        row for row in rows_all
        if row.eligible_for_promotion
        and row.evidence_semantics_fingerprint == required_semantics_fingerprint
    ]
    if mixed:
        return {
            "schema_version": 3,
            "method": criteria["method"],
            "status": "BLOCKED",
            "approved": False,
            "readiness_reason": "mixed evidence semantics are forbidden",
            "raw_terminal_episodes": len(rows_all),
            "eligible_terminal_episodes": len(rows),
            "semantics_mismatch_episodes": len(mixed),
            "looks": [],
            "projected_ready_ts_ms": None,
        }

    looks = [
        (int(item["sample_count"]), D(str(item["alpha_spend"])))
        for item in criteria["sequential_looks"]
    ]
    minimum_filled = int(criteria["minimum_filled_episodes"])
    minimum_fill_rate = D(str(criteria["minimum_fill_rate"]))
    maximum_drawdown_fraction = D(str(criteria["maximum_drawdown_fraction"]))
    minimum_confirmed = int(criteria["minimum_confirmed_regimes"])
    resamples = int(criteria["bootstrap_resamples"])
    reports = []
    passed_at: int | None = None
    passed_boundary: int | None = None
    for sample_count, alpha in looks:
        cohort = rows[:sample_count]
        reached = len(cohort) == sample_count
        values = [row.net_pnl_quote for row in cohort]
        filled = [row for row in cohort if row.entry_filled_quantity > ZERO]
        fill_rate = D(len(filled)) / D(len(cohort)) if cohort else ZERO
        lower = _bootstrap_lower(values, alpha=alpha, resamples=resamples)
        notional = max((row.entry_notional_quote for row in cohort), default=ZERO)
        drawdown = _drawdown(values)
        regime_report, confirmed = _regimes(cohort, criteria)
        panic_rows = [
            row for row in cohort if row.terminal_reason == "PANIC_FLATTEN"
        ]
        panic_safe = all(
            row.exit_filled_quantity >= row.entry_filled_quantity
            for row in panic_rows
        )
        passed = bool(
            reached
            and lower > ZERO
            and len(filled) >= minimum_filled
            and fill_rate >= minimum_fill_rate
            and notional > ZERO
            and drawdown <= notional * maximum_drawdown_fraction
            and len(confirmed) >= minimum_confirmed
            and panic_safe
        )
        reports.append({
            "sample_count": sample_count,
            "alpha_spend": format(alpha, "f"),
            "reached": reached,
            "eligible_terminal_episodes": len(cohort),
            "filled_episodes": len(filled),
            "fill_rate": format(fill_rate, "f"),
            "net_pnl_quote": format(sum(values, ZERO), "f"),
            "mean_net_pnl_quote": format(
                sum(values, ZERO) / D(len(values)) if values else ZERO, "f"
            ),
            "one_sided_mean_lower_bound_quote": format(lower, "f"),
            "maximum_drawdown_quote": format(drawdown, "f"),
            "regime_safety": regime_report,
            "confirmed_execution_regimes": confirmed,
            "panic_exit_safe": panic_safe,
            "passed": passed,
        })
        if passed and passed_at is None:
            passed_at = sample_count
            passed_boundary = cohort[-1].terminal_at_ms

    filled_all = [row for row in rows if row.entry_filled_quantity > ZERO]
    regime_report, confirmed = _regimes(
        [row for row in rows if passed_boundary is None or row.terminal_at_ms <= passed_boundary],
        criteria,
    )
    next_look = next((count for count, _alpha in looks if count > len(rows)), None)
    maximum = int(criteria["maximum_terminal_episodes"])
    status = "PASS" if passed_at is not None else "SHADOW"
    if status != "PASS" and (next_look is None or len(rows) >= maximum):
        status = "READY_TO_REJECT"
    durations = [
        row.terminal_at_ms - row.started_at_ms
        for row in rows if row.terminal_at_ms > row.started_at_ms
    ]
    mean_duration = sum(durations) // len(durations) if durations else None
    statistics_eta = (
        rows[-1].terminal_at_ms + mean_duration * (next_look - len(rows))
        if rows and mean_duration is not None and next_look is not None else None
    )
    regime_missing = {
        name: max(0, int(criteria["minimum_regime_filled_episodes"])
                  - int(report["filled_episodes"]))
        for name, report in regime_report.items()
    }
    regime_etas = []
    if rows and mean_duration is not None:
        for name, report in regime_report.items():
            observed = int(report["filled_episodes"])
            if report["noninferior"]:
                regime_etas.append(rows[-1].terminal_at_ms)
            elif observed > 0:
                regime_etas.append(
                    rows[-1].terminal_at_ms
                    + mean_duration * regime_missing[name] * len(rows) // observed
                )
    regime_etas.sort()
    regime_eta = (
        regime_etas[minimum_confirmed - 1]
        if len(regime_etas) >= minimum_confirmed else None
    )
    panic_rows = [
        row for row in rows if row.terminal_reason == "PANIC_FLATTEN"
    ]
    panic_failures = [
        row for row in panic_rows
        if row.exit_filled_quantity < row.entry_filled_quantity
    ]
    return {
        "schema_version": 3,
        "method": criteria["method"],
        "primary_horizon_min": 360,
        "diagnostic_horizons_min": [300],
        "raw_terminal_episodes": len(rows_all),
        "eligible_terminal_episodes": len(rows),
        "semantics_mismatch_episodes": 0,
        "filled_episodes": len(filled_all),
        "financial_outcomes": sum(row.net_pnl_quote != ZERO for row in rows),
        "panic_flatten_outcomes": sum(
            row.terminal_reason == "PANIC_FLATTEN" for row in rows
        ),
        "panic_veto_attempts": sum(
            row.terminal_reason == "PANIC_VETO" for row in rows
        ),
        "panic_safety": {
            "status": (
                "PASS" if panic_rows and not panic_failures
                else "BLOCKED" if panic_failures else "NOT_OBSERVED"
            ),
            "observations": len(panic_rows),
            "residual_position_failures": len(panic_failures),
            "pnl_included_in_expectancy": True,
        },
        "net_pnl_quote": format(
            sum((row.net_pnl_quote for row in rows), ZERO), "f"
        ),
        "looks": reports,
        "passed_at_episode": passed_at,
        "next_sequential_look": next_look,
        "data_collection_projected_ready_ts_ms": statistics_eta,
        "statistics_projected_ready_ts_ms": statistics_eta,
        "regime_projected_ready_ts_ms": regime_eta,
        "execution_model_projected_ready_ts_ms": None,
        "projected_ready_ts_ms": None,
        "regime_safety": regime_report,
        "regime_missing_filled_episodes": regime_missing,
        "confirmed_execution_regimes": confirmed,
        "required_confirmed_regimes": minimum_confirmed,
        "status": status,
        "approved": status == "PASS",
        "readiness_reason": (
            "all preregistered net expectancy gates passed"
            if status == "PASS" else
            "all sequential looks were exhausted"
            if status == "READY_TO_REJECT" else
            "waiting for net expectancy, regimes, and execution replay"
        ),
    }


__all__ = ["net_expectancy_criteria", "sequential_net_expectancy_report"]
