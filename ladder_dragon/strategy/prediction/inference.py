# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: expose deterministic prediction inference without exchange access.

"""Prediction inference API."""

from ladder_dragon.strategy.prediction.runtime import predict_distribution

__all__ = ["predict_distribution"]
