from decimal import Decimal

from ladder_dragon.strategy.prediction.control_approval import (
    control_specific_gate,
)
from ladder_dragon.strategy.prediction.models import (
    PredictionOutcome,
    ResolvedSample,
)


D = Decimal


def _samples(candidate_values, baseline_values):
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
            {
                "binding": True,
                "baseline_notional_quote": "10",
            },
        ))
    return output


def test_maker_control_cannot_pass_without_execution_evidence():
    gate = control_specific_gate("maker", _samples([1] * 120, [0] * 120))

    assert gate["approved"] is False
    assert gate["mode"] == "NOT_IMPLEMENTED"
    assert gate["status"] == "NOT_IMPLEMENTED"
    assert "missed fills" in gate["reasons"][0]


def test_inventory_control_uses_tail_and_drawdown_not_profit_superiority():
    baseline = [-0.02 if index % 10 == 0 else 0.01 for index in range(120)]
    candidate = [-0.01 if index % 10 == 0 else 0.0095 for index in range(120)]

    gate = control_specific_gate(
        "inventory", _samples(candidate, baseline)
    )

    assert gate["approved"] is True
    assert gate["profit_superiority_required"] is False
    assert D(gate["candidate_tail_quote"]) > D(gate["baseline_tail_quote"])


def test_inventory_control_blocks_unchanged_risk_profile():
    gate = control_specific_gate(
        "inventory", _samples([1] * 120, [1] * 120)
    )

    assert gate["approved"] is False
    assert "inventory tail loss did not improve" in gate["reasons"]


def test_noop_control_rows_cannot_prove_a_binding_effect():
    samples = _samples([1] * 120, [0] * 120)
    samples = [
        ResolvedSample(
            row.snapshot_ts_ms, row.regime, row.horizon_min, row.outcome,
            row.baseline_net_pnl_quote,
            {"binding": False, "baseline_notional_quote": "10"},
        )
        for row in samples
    ]

    gate = control_specific_gate("expectancy", samples)

    assert gate["approved"] is False
    assert gate["binding_independent_samples"] == 0
    assert "insufficient binding independent samples" in gate["reasons"]
