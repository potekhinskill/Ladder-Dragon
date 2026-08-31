# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: evaluate promotion expectancy with preregistered sequential tests.
"""Sequential net-expectancy evidence for complete execution attempts."""

from __future__ import annotations

from decimal import Decimal, ROUND_CEILING
import hashlib
import random
from typing import Iterable, Mapping

from ladder_dragon.strategy.prediction.execution_episode import (
    ExecutionEpisodeResult,
)
from ladder_dragon.strategy.prediction.episode_semantics import EXCURSION_POLICY


D = Decimal
ZERO = D("0")
ELIGIBLE_REGIMES = ("RANGE", "TREND_UP", "TREND_DOWN")
EVIDENCE_QUALITY_POLICY = {
    "schema_version": 1,
    "maximum_ineligible_fraction": "0.05",
    "allowed_ineligible_reasons": [
        "INCOMPLETE_TRADE_PAGE", "PROCESS_RESTART_DATA_GAP",
    ],
}
V23_FIXED_CONFIRMATION_PATHS = 42


def _evidence_quality(
    rows: list[ExecutionEpisodeResult],
) -> dict[str, object]:
    """Keep source attrition visible and bounded outside strategy outcomes."""
    from ladder_dragon.strategy.prediction.episode_semantics import canonical_digest

    ineligible = [row for row in rows if not row.eligible_for_promotion]
    allowed = set(EVIDENCE_QUALITY_POLICY["allowed_ineligible_reasons"])
    unknown = sorted({row.terminal_reason for row in ineligible} - allowed)
    fraction = D(len(ineligible)) / D(len(rows)) if rows else ZERO
    maximum = D(str(EVIDENCE_QUALITY_POLICY["maximum_ineligible_fraction"]))
    status = "PASS" if not unknown and fraction <= maximum else "BLOCKED"
    return {
        "status": status,
        "raw_terminal_episodes": len(rows),
        "ineligible_terminal_episodes": len(ineligible),
        "ineligible_fraction": format(fraction, "f"),
        "maximum_ineligible_fraction": format(maximum, "f"),
        "unknown_ineligible_reasons": unknown,
        "policy_sha256": canonical_digest(EVIDENCE_QUALITY_POLICY),
    }


def net_expectancy_criteria(
    *, anytime_valid: bool = False, exact_policy: bool = False,
    excursion_diagnostics: bool = False, economic_futility: bool = False,
    fixed_confirmation_cohort: bool = False,
) -> dict[str, object]:
    """Return one immutable net-expectancy statistical contract."""
    if anytime_valid:
        regimes = ("RANGE",) if exact_policy else ELIGIBLE_REGIMES
        if economic_futility and not (exact_policy and excursion_diagnostics):
            raise ValueError("economic futility requires the exact excursion policy")
        if fixed_confirmation_cohort and not economic_futility:
            raise ValueError("fixed confirmation requires economic futility")
        schema = (
            8 if fixed_confirmation_cohort else 7 if economic_futility
            else 6 if excursion_diagnostics else 5 if exact_policy else 4
        )
        criteria = {
            "criteria_schema_version": schema,
            "method": f"anytime_valid_betting_e_process_v{schema}",
            "trial_definition": "executable_terminal_attempts_net_of_fees_including_panic",
            "minimum_eligible_terminal_episodes": 24,
            "minimum_filled_episodes": 10,
            "minimum_fill_rate": "0.10",
            "maximum_drawdown_fraction": "0.25",
            "eligible_regimes": list(regimes),
            "minimum_regime_filled_episodes": 12 if exact_policy else 8,
            "minimum_confirmed_regimes": 1 if exact_policy else 2,
            "regime_noninferiority_fraction": "0",
            "regime_activation_policy": (
                "exact_preregistered_execution_regimes_v4"
                if exact_policy else "confirmed_execution_regime_only_v3"
            ),
            "maximum_terminal_episodes": (
                V23_FIXED_CONFIRMATION_PATHS
                if fixed_confirmation_cohort else 300
            ),
            "maximum_confirmation_duration_ms": 14 * 24 * 60 * 60_000,
            "panic_policy": "include_flatten_pnl_and_count_veto_attempt",
            "mean_lower_bound_method": "mixture_betting_e_process_v1",
            "confidence_alpha": "0.05",
            "evidence_notional_quote": "6",
            "outcome_lower_bound_quote": "-0.12",
            "outcome_upper_bound_quote": "0.06",
            "regime_confidence_policy": "bonferroni_mixture_e_process_v1",
            "design_effect_quote": "0.02",
            "design_effect_required_filled_episodes": (
                _minimum_passing_count(
                    value=D("0.02"),
                    alpha=D("0.05") / D(len(regimes)),
                    lower_bound=D("-0.12"),
                    upper_bound=D("0.06"),
                    threshold=D("0"),
                    maximum=300,
                )
            ),
            "best_case_required_filled_episodes": (
                _minimum_passing_count(
                    value=D("0.06"),
                    alpha=D("0.05") / D(len(regimes)),
                    lower_bound=D("-0.12"),
                    upper_bound=D("0.06"),
                    threshold=D("0"),
                    maximum=300,
                )
            ),
            "feasibility_policy": "bounded_e_process_reachability_v1",
        }
        if excursion_diagnostics:
            criteria["diagnostic_policy"] = EXCURSION_POLICY
        if economic_futility:
            # This threshold is frozen before future v23 confirmation. It is
            # five basis points of the fixed six-USDT evidence notional.
            criteria.update({
                "mean_upper_bound_method": "mixture_betting_e_process_v1",
                "minimum_useful_mean_quote": "0.003",
                "minimum_episodes_before_economic_reject": 24,
                "economic_futility_policy": "anytime_upper_below_useful_mean_v1",
            })
        if fixed_confirmation_cohort:
            criteria.update({
                "confirmation_cohort_policy": (
                    "fixed_provider_capacity_paths_v1"
                ),
                "fixed_confirmation_paths": V23_FIXED_CONFIRMATION_PATHS,
                "dynamic_confirmation_top_up_allowed": False,
                "design_effect_is_capacity_gate": False,
            })
        return criteria
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


def _anytime_upper(
    values: list[Decimal],
    *,
    alpha: Decimal,
    lower_bound: Decimal,
    upper_bound: Decimal,
) -> Decimal:
    """Return the symmetric anytime-valid upper bound for a bounded mean."""
    return -_anytime_lower(
        [-value for value in values],
        alpha=alpha,
        lower_bound=-upper_bound,
        upper_bound=-lower_bound,
    )


def _minimum_passing_count(
    *, value: Decimal, alpha: Decimal, lower_bound: Decimal,
    upper_bound: Decimal, threshold: Decimal, maximum: int,
) -> int | None:
    """Return the first sample count that can cross one frozen bound."""
    for count in range(1, maximum + 1):
        if _anytime_lower(
            [value] * count,
            alpha=alpha,
            lower_bound=lower_bound,
            upper_bound=upper_bound,
        ) > threshold:
            return count
    return None


def _additional_best_case_count(
    values: list[Decimal], *, alpha: Decimal, lower_bound: Decimal,
    upper_bound: Decimal, threshold: Decimal, maximum_additional: int,
) -> int | None:
    """Return the smallest best-case continuation that crosses the bound."""
    for additional in range(maximum_additional + 1):
        if _anytime_lower(
            values + [upper_bound] * additional,
            alpha=alpha,
            lower_bound=lower_bound,
            upper_bound=upper_bound,
        ) > threshold:
            return additional
    return None


def _additional_empirical_count(
    values: list[Decimal], *, alpha: Decimal, lower_bound: Decimal,
    upper_bound: Decimal, threshold: Decimal, maximum_additional: int,
) -> int | None:
    """Project a bound with the observed mean, without claiming readiness."""
    if not values:
        return None
    continuation = min(
        upper_bound,
        max(lower_bound, sum(values, ZERO) / D(len(values))),
    )
    for additional in range(maximum_additional + 1):
        if _anytime_lower(
            values + [continuation] * additional,
            alpha=alpha,
            lower_bound=lower_bound,
            upper_bound=upper_bound,
        ) > threshold:
            return additional
    return None


def anytime_design_feasibility(
    criteria: Mapping[str, object],
) -> dict[str, object]:
    """Prove that the frozen e-process design can reach every hard gate."""
    schema = int(criteria.get("criteria_schema_version", 0))
    if schema not in {5, 6, 7, 8}:
        raise ValueError(
            "exact anytime design requires criteria schema 5, 6, 7 or 8"
        )
    regimes = criteria.get("eligible_regimes")
    if not isinstance(regimes, list) or not regimes:
        raise ValueError("exact anytime design requires eligible regimes")
    maximum = int(criteria["maximum_terminal_episodes"])
    if schema == 8 and not (
        criteria.get("confirmation_cohort_policy")
        == "fixed_provider_capacity_paths_v1"
        and criteria.get("fixed_confirmation_paths")
        == V23_FIXED_CONFIRMATION_PATHS
        and criteria.get("dynamic_confirmation_top_up_allowed") is False
        and criteria.get("design_effect_is_capacity_gate") is False
        and maximum == V23_FIXED_CONFIRMATION_PATHS
    ):
        raise ValueError("fixed confirmation cohort contract is invalid")
    minimum_regime = int(criteria["minimum_regime_filled_episodes"])
    required_regimes = int(criteria["minimum_confirmed_regimes"])
    best_case = criteria.get("best_case_required_filled_episodes")
    design_effect = criteria.get("design_effect_required_filled_episodes")
    if (
        isinstance(best_case, bool)
        or not isinstance(best_case, int)
        or isinstance(design_effect, bool)
        or not isinstance(design_effect, int)
    ):
        raise ValueError("exact anytime confidence bounds are unreachable")
    capacity_design_effect = 0 if schema == 8 else design_effect
    required_total = max(
        int(criteria["minimum_eligible_terminal_episodes"]),
        minimum_regime * required_regimes,
        capacity_design_effect,
    )
    feasible = bool(
        0 < required_regimes <= len(regimes)
        and best_case <= minimum_regime
        and required_total <= maximum
    )
    if not feasible:
        raise ValueError("exact anytime design is mathematically unreachable")
    return {
        "schema_version": 1,
        "policy": "bounded_e_process_reachability_v1",
        "eligible_regimes": list(regimes),
        "required_confirmed_regimes": required_regimes,
        "best_case_required_per_regime": best_case,
        "design_effect_required_filled_episodes": design_effect,
        "design_effect_is_capacity_gate": schema != 8,
        "minimum_planned_terminal_episodes": required_total,
        "maximum_terminal_episodes": maximum,
        "feasible": True,
    }


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


def _excursion_diagnostics(
    rows: list[ExecutionEpisodeResult],
) -> dict[str, object]:
    """Summarize pre-exit bid excursions without changing the gate."""
    cohort = [
        row for row in rows
        if row.entry_filled_quantity > ZERO and row.excursion_evidence_available
    ]

    def summary(items: list[ExecutionEpisodeResult]) -> dict[str, object]:
        count = len(items)
        return {
            "filled_episodes": count,
            "mean_maximum_favorable_excursion_pct": format(
                sum((row.maximum_favorable_excursion_pct for row in items), ZERO)
                / D(count) if count else ZERO,
                "f",
            ),
            "mean_maximum_adverse_excursion_pct": format(
                sum((row.maximum_adverse_excursion_pct for row in items), ZERO)
                / D(count) if count else ZERO,
                "f",
            ),
        }

    terminal_reasons = sorted({row.terminal_reason for row in cohort})
    return {
        "policy": EXCURSION_POLICY,
        "available": bool(cohort),
        "filled_episodes": len(cohort),
        "overall": summary(cohort),
        "by_terminal_reason": {
            reason: summary([
                row for row in cohort if row.terminal_reason == reason
            ])
            for reason in terminal_reasons
        },
        "affects_promotion": False,
    }


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
    quality = _evidence_quality(rows_all)
    rows = [
        row for row in rows_all
        if row.eligible_for_promotion
        and row.evidence_semantics_fingerprint == required_semantics_fingerprint
    ]
    base = {
        "schema_version": int(criteria["criteria_schema_version"]),
        "method": criteria["method"],
        "raw_terminal_episodes": len(rows_all),
        "eligible_terminal_episodes": len(rows),
        "semantics_mismatch_episodes": len(mixed),
        "evidence_quality": quality,
        "excursion_diagnostics": _excursion_diagnostics(rows),
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
    economic_upper = (
        _anytime_upper(
            values,
            alpha=alpha,
            lower_bound=lower_bound,
            upper_bound=upper_bound,
        )
        if int(criteria["criteria_schema_version"]) in {7, 8} else None
    )
    economic_futile = bool(
        economic_upper is not None
        and len(rows) >= int(criteria["minimum_episodes_before_economic_reject"])
        and economic_upper <= D(str(criteria["minimum_useful_mean_quote"]))
    )
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
        and quality["status"] == "PASS"
    )
    fixed_paths = int(criteria.get("fixed_confirmation_paths", maximum))
    observed_paths = (
        len(rows_all)
        if int(criteria["criteria_schema_version"]) == 8 else len(rows)
    )
    optimistic = values + [upper_bound] * max(0, fixed_paths - observed_paths)
    optimistic_lower = _anytime_lower(
        optimistic,
        alpha=alpha,
        lower_bound=lower_bound,
        upper_bound=upper_bound,
    )
    remaining = max(0, fixed_paths - observed_paths)
    regime_alpha = alpha / D(len(criteria["eligible_regimes"]))
    regime_threshold = -notional * D(
        str(criteria["regime_noninferiority_fraction"])
    )
    regime_additional: dict[str, int | None] = {}
    for name, report in regime_report.items():
        cohort_values = [
            row.net_pnl_quote for row in rows
            if row.start_regime == name and row.entry_filled_quantity > ZERO
        ]
        bound_need = _additional_best_case_count(
            cohort_values,
            alpha=regime_alpha,
            lower_bound=lower_bound,
            upper_bound=upper_bound,
            threshold=regime_threshold,
            maximum_additional=remaining,
        )
        count_need = max(
            0,
            int(criteria["minimum_regime_filled_episodes"])
            - int(report["filled_episodes"]),
        )
        regime_additional[name] = (
            None if bound_need is None else max(count_need, bound_need)
        )
    required_regime_budget = sorted(
        value for value in regime_additional.values() if value is not None
    )[: int(criteria["minimum_confirmed_regimes"])]
    regimes_reachable = bool(
        len(required_regime_budget) >= int(criteria["minimum_confirmed_regimes"])
        and sum(required_regime_budget) <= remaining
    )
    # Reachability is valid from the first episode. Waiting for the nominal
    # minimum can waste the complete deadline after PASS becomes impossible.
    futile = bool(
        optimistic_lower <= ZERO or not regimes_reachable or economic_futile
    )
    status = (
        "PASS" if passed else "READY_TO_REJECT"
        if futile or observed_paths >= fixed_paths else "SHADOW"
    )
    cadence = (
        (rows[-1].terminal_at_ms - rows[0].terminal_at_ms) // (len(rows) - 1)
        if len(rows) > 1 else None
    )
    overall_additional = _additional_best_case_count(
        values,
        alpha=alpha,
        lower_bound=lower_bound,
        upper_bound=upper_bound,
        threshold=ZERO,
        maximum_additional=remaining,
    )
    empirical_additional = _additional_empirical_count(
        values,
        alpha=alpha,
        lower_bound=lower_bound,
        upper_bound=upper_bound,
        threshold=ZERO,
        maximum_additional=remaining,
    )
    minimum_additional = max(0, minimum - len(rows))
    statistical_additional = (
        None if overall_additional is None
        else max(minimum_additional, overall_additional)
    )
    observed_filled = len(filled)
    regime_additional_total = (
        sum(required_regime_budget)
        if len(required_regime_budget) >= int(criteria["minimum_confirmed_regimes"])
        else None
    )
    regime_terminal_additional = (
        int(
            (D(regime_additional_total) * D(len(rows)) / D(observed_filled))
            .to_integral_value(rounding=ROUND_CEILING)
        )
        if regime_additional_total is not None and observed_filled > 0
        else 0 if regime_additional_total == 0 else None
    )
    full_additional = (
        max(statistical_additional, regime_terminal_additional)
        if statistical_additional is not None
        and regime_terminal_additional is not None else None
    )
    next_count = len(rows) + full_additional if full_additional is not None else maximum
    statistics_eta = (
        rows[-1].terminal_at_ms + cadence * statistical_additional
        if rows and cadence is not None and statistical_additional is not None
        and status == "SHADOW" else None
    )
    empirical_statistics_eta = (
        rows[-1].terminal_at_ms + cadence * max(
            minimum_additional, empirical_additional
        )
        if rows and cadence is not None and empirical_additional is not None
        and status == "SHADOW" else None
    )
    regime_eta = (
        rows[-1].terminal_at_ms + cadence * regime_terminal_additional
        if rows and cadence is not None and regime_terminal_additional is not None
        and status == "SHADOW" else None
    )
    projected_ready = (
        max(statistics_eta, regime_eta)
        if statistics_eta is not None and regime_eta is not None else None
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
        "one_sided_mean_upper_bound_quote": (
            format(economic_upper, "f") if economic_upper is not None else None
        ),
        "minimum_useful_mean_quote": criteria.get("minimum_useful_mean_quote"),
        "economic_futility_reached": economic_futile,
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
        "fixed_confirmation_paths": (
            fixed_paths if int(criteria["criteria_schema_version"]) == 8
            else None
        ),
        "observed_confirmation_paths": observed_paths,
        "remaining_confirmation_paths": remaining,
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
        "statistics_earliest_possible_ts_ms": statistics_eta,
        "statistics_empirical_projected_ts_ms": empirical_statistics_eta,
        "regime_projected_ready_ts_ms": regime_eta,
        "execution_model_projected_ready_ts_ms": None,
        "execution_replay_ready_ts_ms": None,
        "expected_launch_ts_ms": None,
        "projected_ready_ts_ms": projected_ready,
        "regime_safety": regime_report,
        "regime_missing_filled_episodes": {
            name: max(0, int(criteria["minimum_regime_filled_episodes"]) - int(report["filled_episodes"]))
            for name, report in regime_report.items()
        },
        "regime_best_case_additional_episodes": regime_additional,
        "regime_best_case_additional_terminal_episodes": (
            regime_terminal_additional
        ),
        "confirmed_execution_regimes": confirmed,
        "required_confirmed_regimes": int(criteria["minimum_confirmed_regimes"]),
        "status": status,
        "approved": passed,
        "readiness_reason": (
            "all anytime-valid expectancy gates passed" if passed else
            "evidence attrition exceeds the promotion limit"
            if quality["status"] != "PASS" else
            "preregistered expectancy is mathematically futile"
            if status == "READY_TO_REJECT" else
            "waiting for anytime-valid expectancy and regime evidence"
        ),
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
    if criteria.get("criteria_schema_version") in {4, 5, 6, 7, 8}:
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
