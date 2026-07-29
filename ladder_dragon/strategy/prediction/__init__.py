# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: preserve the public prediction API while implementation is modularized.

"""Compatibility facade for prediction services."""

from ladder_dragon.strategy.prediction.models import (
    HorizonPrediction,
    PredictionBar,
    PredictionFeatures,
    PredictionOutcome,
    ResolvedSample,
    TradePlan,
)
from ladder_dragon.strategy.prediction.runtime import (
    HORIZONS_MIN,
    PREDICTION_SCHEMA_VERSION,
    PredictionShadowStore,
    build_prediction_features,
    evaluate_plan,
    evaluation_end_ms,
    parse_closed_klines,
    predict_distribution,
    trade_flow_from_agg_trades,
)
from ladder_dragon.strategy.prediction.approval import prediction_apply_gate
from ladder_dragon.strategy.prediction.walk_forward import (
    walk_forward_prediction_report,
)

__all__ = [
    "HORIZONS_MIN",
    "PREDICTION_SCHEMA_VERSION",
    "HorizonPrediction",
    "PredictionBar",
    "PredictionFeatures",
    "PredictionOutcome",
    "PredictionShadowStore",
    "ResolvedSample",
    "TradePlan",
    "build_prediction_features",
    "evaluate_plan",
    "evaluation_end_ms",
    "parse_closed_klines",
    "predict_distribution",
    "prediction_apply_gate",
    "trade_flow_from_agg_trades",
    "walk_forward_prediction_report",
]
