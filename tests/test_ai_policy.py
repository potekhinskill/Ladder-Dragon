from datetime import datetime, timezone
from decimal import Decimal
import json

from ladder_dragon.ai.ai_advisor import AdvisorConfig, MarketContext, StrategyRecommendation
from ladder_dragon.ai.ai_policy import (
    PolicyConfig,
    UsageBudget,
    UsageToday,
    apply_safety_policy,
    confidence_calibration,
    numeric_regime_benchmark,
    read_usage_today,
    usage_budget_allows,
)


def context(**overrides):
    values = dict(
        symbol="SOLUSDT",
        price=100,
        atr_pct=.01,
        deterministic_mode="FLAT",
        candidate_mode="UP",
        ema_gap_pct=.01,
        ema_slope=.001,
        adx=30,
        ladder_low_pct=-.5,
        ladder_down_pct=-20,
        ladder_up_pct=20,
        target_buys=4,
        risk_safe_cap_usdt=40,
        trade_history_available=True,
        sell_count_30d=30,
        market_data_available=True,
        orderbook_available=True,
        market_data_age_sec=1,
        portfolio_data_available=True,
        portfolio_data_age_sec=1,
        free_reserve_ratio=2,
        ai_samples_1h=40,
        ai_accuracy_1h=.60,
        real_rag_episode_count=5,
        return_1h=.02,
        return_4h=.04,
    )
    values.update(overrides)
    return MarketContext(**values)


def recommendation(**overrides):
    values = dict(
        mode="UP",
        ladder_width_scale=.8,
        cap_scale=1.2,
        confidence=.8,
        rationale="test",
        provider="deepseek",
        model="deepseek-v4-flash",
    )
    values.update(overrides)
    return StrategyRecommendation(**values)


def test_shadow_never_applies_but_keeps_recommendation_for_measurement():
    result = apply_safety_policy(
        context(), recommendation(), PolicyConfig(mode="SHADOW")
    )
    assert result.apply is False
    assert result.status == "SHADOW"
    assert "shadow_mode" in result.reasons


def test_policy_rejects_stale_context_and_prevents_aggressive_low_sample_change():
    result = apply_safety_policy(
        context(
            market_data_age_sec=100,
            sell_count_30d=3,
            atr_pct=.08,
        ),
        recommendation(ladder_width_scale=.75, cap_scale=1.25),
        PolicyConfig(mode="APPLY"),
    )
    assert result.apply is False
    assert result.recommendation.ladder_width_scale >= 1
    assert result.recommendation.cap_scale <= 1


def test_policy_reports_each_missing_context_source_without_opening_gate():
    result = apply_safety_policy(
        context(
            market_data_available=False,
            orderbook_available=False,
            portfolio_data_available=False,
            market_data_age_sec=100,
            portfolio_data_age_sec=100,
        ),
        recommendation(),
        PolicyConfig(mode="APPLY"),
    )
    assert result.apply is False
    assert {
        "market_data_unavailable",
        "orderbook_unavailable",
        "portfolio_data_unavailable",
        "market_data_stale",
        "portfolio_data_stale",
        "incomplete_or_stale_context",
    } <= set(result.reasons)


def test_risk_pressure_reduces_cap_and_spread_pauses_buys():
    result = apply_safety_policy(
        context(
            consecutive_losses=4,
            spread_bps=30,
            position_pnl_pct=-.06,
        ),
        recommendation(cap_scale=1.2),
        PolicyConfig(mode="APPLY"),
    )
    assert result.apply is False
    assert result.pause_buys is False
    assert result.status == "REJECTED"
    assert result.recommendation.cap_scale == .5
    assert "insufficient_realized_ai_samples" in result.reasons


def test_bad_historical_ai_accuracy_disables_application():
    result = apply_safety_policy(
        context(ai_samples_1h=50, ai_accuracy_1h=.4),
        recommendation(),
        PolicyConfig(mode="APPLY"),
    )
    assert result.apply is False
    assert "ai_accuracy_below_threshold" in result.reasons


def test_apply_requires_realized_positive_edge_and_stop_rate_gate():
    result = apply_safety_policy(
        context(
            ai_closed_samples=5,
            ai_realized_edge_ci_low=-.1,
            ai_realized_edge_ci_high=.2,
            ai_realized_stop_rate=.2,
        ),
        recommendation(),
        PolicyConfig(mode="APPLY"),
    )
    assert result.apply is False
    assert "realized_edge_confidence_interval_includes_zero" in result.reasons

    result = apply_safety_policy(
        context(
            ai_closed_samples=5,
            ai_realized_edge_ci_low=.1,
            ai_realized_edge_ci_high=.2,
            ai_realized_stop_rate=.9,
        ),
        recommendation(),
        PolicyConfig(mode="APPLY"),
    )
    assert result.apply is False
    assert "realized_stop_rate_degraded" in result.reasons


def test_numeric_benchmark_is_interpretable():
    assert numeric_regime_benchmark(context()) == "UP"
    assert numeric_regime_benchmark(
        context(return_1h=-.03, return_4h=-.06, ema_gap_pct=-.02, ema_slope=-.002)
    ) == "DOWN"


def test_daily_budget_and_usage_log(tmp_path):
    stamp = datetime(2026, 7, 16, 10, tzinfo=timezone.utc)
    path = tmp_path / "usage.ndjson"
    path.write_text(json.dumps({
        "timestamp": stamp.isoformat(),
        "total_tokens": 900,
        "estimated_cost_usd": "0.04",
    }) + "\n")
    today = read_usage_today(str(path), now=stamp)
    assert today == UsageToday(1, 900, Decimal("0.04"))
    assert usage_budget_allows(
        today, UsageBudget(10, 1000, Decimal(".05"))
    ) == (True, "")
    assert usage_budget_allows(
        UsageToday(1, 1000, Decimal(".04")),
        UsageBudget(10, 1000, Decimal(".05")),
    ) == (False, "daily token limit")


def test_confidence_calibration_uses_actual_accuracy():
    result = confidence_calibration([
        (.68, .01, "UP"),
        (.69, -.01, "UP"),
        (.85, 0, "FLAT"),
    ])
    assert result[1]["samples"] == 2
    assert result[1]["accuracy"] == .5
    assert result[3]["accuracy"] == 1
