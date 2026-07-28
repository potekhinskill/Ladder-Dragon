# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: expose statistically gated prediction approval.

"""Prediction approval API."""

from ladder_dragon.strategy.prediction.runtime import prediction_apply_gate

__all__ = ["prediction_apply_gate"]
