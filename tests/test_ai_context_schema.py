from dataclasses import fields

from ladder_dragon.ai.ai_advisor import MarketContext
from ladder_dragon.ai.ai_context import (
    AdvisorPerformance,
    MarketFeatures,
    PortfolioFeatures,
    TradeFeatures,
)


def test_market_context_accepts_every_aggregated_feature_field():
    """Keep the supervisor's merged AI feature schema constructor-safe."""
    context_fields = {field.name for field in fields(MarketContext)}

    for feature_type in (
        TradeFeatures,
        MarketFeatures,
        PortfolioFeatures,
        AdvisorPerformance,
    ):
        feature_fields = {field.name for field in fields(feature_type)}
        assert feature_fields <= context_fields, (
            f"{feature_type.__name__} fields missing from MarketContext: "
            f"{sorted(feature_fields - context_fields)}"
        )
