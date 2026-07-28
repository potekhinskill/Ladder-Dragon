# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: expose chronological walk-forward prediction evaluation.

"""Prediction walk-forward API."""

from ladder_dragon.strategy.prediction.runtime import (
    walk_forward_prediction_report,
)

__all__ = ["walk_forward_prediction_report"]
