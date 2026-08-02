# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: run a cutoff-bound monthly defensive prediction evaluation.

"""Permanent SHADOW evaluation contour for prediction challengers."""

from __future__ import annotations

from decimal import Decimal
import hashlib
import json
from typing import Sequence

from ladder_dragon.strategy.prediction.decision_value import (
    DecisionValueObservation,
    classifier_decision_value_report,
)
from ladder_dragon.strategy.prediction.challengers import (
    ChallengerObservation,
    challenger_comparison_report,
)
from ladder_dragon.strategy.prediction.historical_dataset import (
    HistoricalRegimeSample,
)
from ladder_dragon.strategy.prediction.statistical_models import (
    ShallowGradientBoostingRegime,
    ThreeStateRegimeHMM,
)


D = Decimal
SequenceKey = tuple[str, int]


def _fit_hmm_sequences(
    rows: Sequence[HistoricalRegimeSample],
) -> dict[SequenceKey, ThreeStateRegimeHMM]:
    """Fit one chronological HMM for each symbol and prediction horizon."""
    grouped: dict[SequenceKey, list[tuple[tuple[float, ...], str]]] = {}
    for row in sorted(
        rows,
        key=lambda item: (
            item.symbol,
            item.horizon_min,
            item.snapshot_ts_ms,
            item.label_ts_ms,
        ),
    ):
        key = (row.symbol, row.horizon_min)
        grouped.setdefault(key, []).append((
            tuple(float(value) for value in row.features.vector()),
            row.label,
        ))
    models = {}
    for key, examples in grouped.items():
        model = ThreeStateRegimeHMM()
        model.fit(examples)
        models[key] = model
    return models


def _walk_forward_predictions(
    samples: Sequence[HistoricalRegimeSample],
    *,
    cutoff_ts_ms: int,
    min_train_samples: int,
) -> list[dict[str, object]]:
    ordered = sorted(
        (row for row in samples if row.label_ts_ms <= cutoff_ts_ms),
        key=lambda item: (item.snapshot_ts_ms, item.symbol, item.horizon_min),
    )
    evaluated: list[dict[str, object]] = []
    # Monthly buckets avoid fitting a new model for every minute.
    test_months = sorted({
        row.snapshot_ts_ms // (30 * 24 * 60 * 60_000)
        for row in ordered
    })
    for month in test_months:
        start = month * 30 * 24 * 60 * 60_000
        end = start + 30 * 24 * 60 * 60_000
        train = [row for row in ordered if row.label_ts_ms < start]
        test = [row for row in ordered if start <= row.snapshot_ts_ms < end]
        if len(train) < min_train_samples:
            continue
        boosting = ShallowGradientBoostingRegime()
        training_rows = [
            (
                tuple(float(value) for value in row.features.vector()),
                row.label,
            )
            for row in train
        ]
        boosting.fit(training_rows)
        hmm_by_sequence = _fit_hmm_sequences(train)
        previous_by_sequence: dict[SequenceKey, tuple[float, float, float]] = {}
        for row in test:
            sequence = (row.symbol, row.horizon_min)
            hmm = hmm_by_sequence.get(sequence)
            # Keep both model scores on one cohort. A cold HMM sequence cannot
            # contribute a synthetic FLAT prediction to either model score.
            if hmm is None or hmm.samples < min_train_samples:
                continue
            vector = tuple(float(value) for value in row.features.vector())
            boost_prediction = boosting.predict(
                vector,
                min_samples=min_train_samples,
            )
            hmm_prediction = hmm.predict(
                vector,
                previous_probabilities=previous_by_sequence.get(
                    sequence,
                    (1 / 3, 1 / 3, 1 / 3),
                ),
                min_samples=min_train_samples,
            )
            previous_by_sequence[sequence] = hmm_prediction.probabilities
            evaluated.append({
                "symbol": row.symbol,
                "snapshot_ts_ms": row.snapshot_ts_ms,
                "label_ts_ms": row.label_ts_ms,
                "train_max_label_ts_ms": max(item.label_ts_ms for item in train),
                "actual": row.label,
                "boosting": boost_prediction.label,
                "boosting_confidence": boost_prediction.confidence,
                "hmm": hmm_prediction.label,
                "hmm_confidence": hmm_prediction.confidence,
            })
    return evaluated


def monthly_prediction_report(
    samples: Sequence[HistoricalRegimeSample],
    decision_values: Sequence[DecisionValueObservation],
    *,
    cutoff_ts_ms: int,
    min_train_samples: int = 120,
    challengers: Sequence[ChallengerObservation] = (),
) -> dict[str, object]:
    """Build a hash-bound report; it never enables APPLY or retrains on future data."""
    if cutoff_ts_ms <= 0:
        raise ValueError("cutoff_ts_ms must be positive")
    eligible_samples = [
        row for row in samples if row.label_ts_ms <= cutoff_ts_ms
    ]
    eligible_values = [
        row for row in decision_values if row.resolved_at_ms <= cutoff_ts_ms
    ]
    predictions = _walk_forward_predictions(
        eligible_samples,
        cutoff_ts_ms=cutoff_ts_ms,
        min_train_samples=min_train_samples,
    )
    correct_boost = sum(
        row["boosting"] == row["actual"] for row in predictions
    )
    correct_hmm = sum(row["hmm"] == row["actual"] for row in predictions)
    report: dict[str, object] = {
        "schema_version": 1,
        "mode": "SHADOW",
        "risk_expansion": False,
        "cutoff_ts_ms": cutoff_ts_ms,
        "training_rule": "label_ts_ms < test_window_start",
        "retraining": "artifact-only; operator approval required for APPLY",
        "samples_before_cutoff": len(eligible_samples),
        "evaluated": len(predictions),
        "models": {
            "shallow_gradient_boosting": {
                "correct": correct_boost,
                "evaluated": len(predictions),
            },
            "three_state_hmm": {
                "correct": correct_hmm,
                "evaluated": len(predictions),
            },
        },
        "decision_value": classifier_decision_value_report(eligible_values),
        "challenger_comparison": challenger_comparison_report(
            challengers,
            cutoff_ts_ms=cutoff_ts_ms,
        ),
        "lookahead_detected": any(
            int(row["train_max_label_ts_ms"]) >= int(row["snapshot_ts_ms"])
            for row in predictions
        ),
        "status": (
            "PASS"
            if predictions and not any(
                int(row["train_max_label_ts_ms"]) >= int(row["snapshot_ts_ms"])
                for row in predictions
            )
            else "BLOCKED"
        ),
    }
    canonical = json.dumps(report, sort_keys=True, separators=(",", ":"))
    report["report_sha256"] = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    return report


def report_status_changed(
    report: dict[str, object],
    previous_state: dict[str, object] | None,
) -> bool:
    """Notify only when the compact health state changes."""
    current = {
        "status": report.get("status"),
        "lookahead_detected": report.get("lookahead_detected"),
        "decision_value_quote": (
            report.get("decision_value", {}).get("decision_value_quote")
            if isinstance(report.get("decision_value"), dict) else None
        ),
    }
    return current != (previous_state or {})


def compact_report_state(report: dict[str, object]) -> dict[str, object]:
    decision_value = report.get("decision_value")
    return {
        "status": report.get("status"),
        "lookahead_detected": report.get("lookahead_detected"),
        "decision_value_quote": (
            decision_value.get("decision_value_quote")
            if isinstance(decision_value, dict) else None
        ),
    }
