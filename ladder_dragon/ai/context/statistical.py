# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: train the chronological calibrated statistical AI challenger.

"""Statistical challenger repository query and chronological calibration."""

from __future__ import annotations

import json
from typing import Any, Callable

from ladder_dragon.ai.ai_statistical import (
    calibrated_logistic_prediction,
    context_vector,
    return_label,
)


def statistical_prediction(
    connect: Callable[[], Any],
    context: Any,
    *,
    min_samples: int,
    numeric: Callable[[object], float],
) -> dict[str, Any]:
    """Train on resolved history and reserve its latest 20% for calibration."""
    with connect() as connection:
        rows = connection.execute(
            """
            SELECT feature_json,
                   COALESCE(NULLIF(return_1h_text,''),CAST(return_1h AS TEXT))
            FROM ai_decisions
            WHERE return_1h IS NOT NULL AND feature_json!='[]'
            ORDER BY created_at DESC LIMIT 2000
            """
        ).fetchall()
    examples = []
    for feature_json, result in rows:
        try:
            vector = json.loads(feature_json)
            if isinstance(vector, list) and len(vector) == 10:
                examples.append((vector, return_label(numeric(result))))
        except (TypeError, ValueError, json.JSONDecodeError):
            continue
    # SQL returns newest first; reverse it so the final 20% is a genuine later
    # calibration window rather than a random/look-ahead split.
    examples.reverse()
    prediction = calibrated_logistic_prediction(
        examples,
        context_vector(context),
        min_samples=min_samples,
    )
    return {
        "mode": prediction.mode,
        "confidence": prediction.confidence,
        "samples": prediction.samples,
        "available": prediction.available,
        "calibrated": prediction.calibrated,
    }
