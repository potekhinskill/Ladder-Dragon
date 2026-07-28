# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: expose counterfactual outcome evaluation.

"""Prediction outcome API."""

from ladder_dragon.strategy.prediction.runtime import (
    evaluate_plan,
    evaluation_end_ms,
)

__all__ = ["evaluate_plan", "evaluation_end_ms"]
