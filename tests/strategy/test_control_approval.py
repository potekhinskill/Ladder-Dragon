from decimal import Decimal
import hashlib
import json

from ladder_dragon.strategy.prediction.control_approval import (
    control_specific_gate,
)
from ladder_dragon.strategy.prediction.models import (
    PredictionOutcome,
    ResolvedSample,
)


D = Decimal


def _metadata(control="expectancy", *, binding=True, applicable=True):
    fields = {
        "expectancy": "take_profit_price",
        "inventory": "notional_quote",
        "regime": "entry_enabled",
    }
    field = fields[control]
    baseline_plan = {
        "take_profit_price": "10",
        "notional_quote": "10",
        "entry_enabled": True,
    }
    candidate_plan = dict(baseline_plan)
    if binding:
        candidate_plan[field] = False if field == "entry_enabled" else "9"
    canonical = lambda value: hashlib.sha256(json.dumps(
        value, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")).hexdigest()
    before = baseline_plan[field]
    after = candidate_plan[field]
    return {
        "applicable": applicable,
        "baseline_notional_quote": "10",
        "binding": binding,
        "control": control,
        "field": field,
        "from": str(before).lower() if isinstance(before, bool) else before,
        "reason": "plan_changed" if binding else "no_plan_change",
        "rule": "v4",
        "to": str(after).lower() if isinstance(after, bool) else after,
        "baseline_plan_fingerprint": canonical(baseline_plan),
        "candidate_plan_fingerprint": canonical(candidate_plan),
        "_authoritative_baseline_plan": baseline_plan,
        "_authoritative_candidate_plan": candidate_plan,
        "_authoritative_baseline_plan_fingerprint": canonical(baseline_plan),
        "_authoritative_candidate_plan_fingerprint": canonical(candidate_plan),
    }


def _samples(candidate_values, baseline_values, control="expectancy"):
    output = []
    regimes = ("TREND_UP", "TREND_DOWN", "RANGE", "PANIC")
    for index, (candidate, baseline) in enumerate(
        zip(candidate_values, baseline_values)
    ):
        outcome = PredictionOutcome(
            15, candidate != 0, candidate > 0, D(str(candidate)), D("0"),
            1, "TP" if candidate > 0 else "STOP", index,
        )
        output.append(ResolvedSample(
            index * 900_001,
            regimes[index % len(regimes)],
            15,
            outcome,
            D(str(baseline)),
            _metadata(control),
        ))
    return output


def test_maker_control_cannot_pass_without_execution_evidence():
    gate = control_specific_gate("maker", _samples([1] * 120, [0] * 120))

    assert gate["approved"] is False
    assert gate["mode"] == "NOT_IMPLEMENTED"
    assert gate["status"] == "NOT_IMPLEMENTED"
    assert "missed fills" in gate["reasons"][0]


def test_inventory_control_requires_a_stateful_portfolio_model():
    baseline = [-0.02 if index % 10 == 0 else 0.01 for index in range(120)]
    candidate = [-0.01 if index % 10 == 0 else 0.0095 for index in range(120)]

    gate = control_specific_gate(
        "inventory", _samples(candidate, baseline, "inventory")
    )

    assert gate["approved"] is False
    assert gate["status"] == "STATEFUL_MODEL_REQUIRED"


def test_shadow_only_inventory_is_not_applicable():
    samples = _samples([1] * 2, [1] * 2, "inventory")
    samples = [
        ResolvedSample(
            row.snapshot_ts_ms, row.regime, row.horizon_min, row.outcome,
            row.baseline_net_pnl_quote,
            _metadata("inventory", binding=False, applicable=False),
        )
        for row in samples
    ]
    gate = control_specific_gate("inventory", samples, applicable=False)

    assert gate["approved"] is False
    assert gate["status"] == "NOT_APPLICABLE"


def test_noop_control_rows_cannot_prove_a_binding_effect():
    samples = _samples([1] * 120, [0] * 120)
    samples = [
        ResolvedSample(
            row.snapshot_ts_ms, row.regime, row.horizon_min, row.outcome,
            row.baseline_net_pnl_quote,
            _metadata("expectancy", binding=False),
        )
        for row in samples
    ]

    gate = control_specific_gate("expectancy", samples)

    assert gate["approved"] is False
    assert gate["binding_independent_samples"] == 0
    assert "insufficient binding independent samples" in gate["reasons"]


def test_malformed_binding_metadata_blocks_the_gate():
    samples = _samples([1], [0])
    samples[0].decision_metadata["binding"] = "false"

    import pytest
    with pytest.raises(ValueError, match="booleans"):
        control_specific_gate("expectancy", samples)


def test_metadata_transition_must_match_authoritative_plans():
    samples = _samples([1], [0])
    samples[0].decision_metadata["to"] = "garbage"

    import pytest
    with pytest.raises(ValueError, match="journal plans"):
        control_specific_gate("expectancy", samples)
