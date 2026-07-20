import json
from datetime import datetime, timezone
from decimal import Decimal

import pytest

from ladder_dragon.ai.ai_advisor import (
    AIAdvisor,
    AdvisorConfig,
    MarketContext,
    TokenUsage,
    estimate_usage_cost_usd,
    limit_cap_by_recommendation,
    limit_cap_by_recommendation_decimal,
    token_prices,
    validate_recommendation,
)


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return {
            **self.payload,
            "usage": {
                "prompt_tokens": 200,
                "prompt_cache_hit_tokens": 50,
                "prompt_cache_miss_tokens": 150,
                "completion_tokens": 40,
                "total_tokens": 240,
            },
        }


class FakeSession:
    def __init__(self, content):
        self.content = content
        self.calls = []

    def post(self, endpoint, **kwargs):
        self.calls.append((endpoint, kwargs))
        return FakeResponse(
            {"choices": [{"message": {"content": json.dumps(self.content)}}]}
        )


def config(**overrides):
    values = {
        "enabled": True,
        "provider": "deepseek",
        "model": "deepseek-v4-flash",
        "base_url": "https://api.deepseek.com",
        "api_key": "test-key",
        "cache_sec": 300,
    }
    values.update(overrides)
    return AdvisorConfig(**values)


def context():
    return MarketContext(
        symbol="SOLUSDT",
        price=150.0,
        atr_pct=0.012,
        deterministic_mode="FLAT",
        candidate_mode="UP",
        ema_gap_pct=0.004,
        ema_slope=0.0003,
        adx=23.0,
        ladder_low_pct=0.01,
        ladder_down_pct=0.03,
        ladder_up_pct=0.03,
        target_buys=3,
        risk_safe_cap_usdt=40.0,
    )


def test_deepseek_advisor_uses_json_mode_and_returns_strict_recommendation():
    session = FakeSession(
        {
            "mode": "UP",
            "ladder_width_scale": 1.2,
            "cap_scale": 0.8,
            "confidence": 0.83,
            "rationale": "Trend confirmed by EMA slope and ADX.",
        }
    )
    advisor = AIAdvisor(config(), session=session, logger=lambda _: None)

    result = advisor.recommend(context())

    assert result is not None
    assert result.mode == "UP"
    assert result.cap_scale == 0.8
    endpoint, request = session.calls[0]
    assert endpoint == "https://api.deepseek.com/chat/completions"
    assert request["headers"]["Authorization"] == "Bearer test-key"
    assert request["json"]["response_format"] == {"type": "json_object"}
    assert request["json"]["thinking"] == {"type": "disabled"}
    assert "tools" not in request["json"]
    user_content = request["json"]["messages"][1]["content"]
    assert '"win_rate_30d"' in user_content
    assert '"orderbook_imbalance_top20"' in user_content
    assert '"ai_accuracy_4h"' in user_content
    assert "orderId" not in user_content
    assert "clientOrderId" not in user_content
    assert "api_key" not in user_content


def test_rag_context_is_sent_as_historical_context_only():
    session = FakeSession(
        {
            "mode": "FLAT",
            "ladder_width_scale": 1.0,
            "cap_scale": 1.0,
            "confidence": 0.8,
            "rationale": "Historical regime matched.",
        }
    )
    advisor = AIAdvisor(config(), session=session, logger=lambda _: None)
    from dataclasses import replace

    advisor.recommend(
        replace(
            context(),
            rag_context=(
                {
                    "doc_id": "historical-1",
                    "context": "SOLUSDT historical regime: baseline=FLAT, return_1h=0.01200",
                    "score": 0.98,
                },
            ),
        )
    )
    user_content = session.calls[0][1]["json"]["messages"][1]["content"]
    assert "historical-1" in user_content
    assert "return_1h=0.01200" in user_content
    assert "orderId" not in user_content


def test_invalid_or_extra_model_fields_fail_safe():
    messages = []
    session = FakeSession(
        {
            "mode": "UP",
            "ladder_width_scale": 1.2,
            "cap_scale": 0.8,
            "confidence": 0.83,
            "rationale": "ok",
            "order": {"side": "BUY"},
        }
    )
    advisor = AIAdvisor(config(), session=session, logger=messages.append)

    assert advisor.recommend(context()) is None
    assert "using deterministic strategy" in messages[0]


def test_low_confidence_is_ignored_and_valid_result_is_cached():
    now = [100.0]
    low_session = FakeSession(
        {
            "mode": "FLAT",
            "ladder_width_scale": 1.0,
            "cap_scale": 0.5,
            "confidence": 0.4,
            "rationale": "Insufficient evidence.",
        }
    )
    low_advisor = AIAdvisor(
        config(min_confidence=0.65),
        session=low_session,
        logger=lambda _: None,
        clock=lambda: now[0],
    )
    assert low_advisor.recommend(context()) is None
    now[0] += 10
    assert low_advisor.recommend(context()) is None
    assert len(low_session.calls) == 1

    session = FakeSession(
        {
            "mode": "FLAT",
            "ladder_width_scale": 1.0,
            "cap_scale": 0.5,
            "confidence": 0.9,
            "rationale": "Stable range.",
        }
    )
    advisor = AIAdvisor(
        config(),
        session=session,
        logger=lambda _: None,
        clock=lambda: now[0],
    )
    assert advisor.recommend(context()) is not None
    assert advisor.last_was_cache_hit is False
    now[0] += 10
    assert advisor.recommend(context()) is not None
    assert advisor.last_was_cache_hit is True
    assert len(session.calls) == 1


def test_daily_budget_block_is_logged_once_until_utc_day_changes():
    now = [datetime(2026, 7, 16, 12, tzinfo=timezone.utc).timestamp()]
    messages = []
    advisor = AIAdvisor(
        config(),
        session=FakeSession({}),
        logger=messages.append,
        clock=lambda: now[0],
        budget_checker=lambda: (False, "daily token limit"),
    )

    assert advisor.recommend(context()) is None
    assert advisor.recommend(context()) is None
    assert len(messages) == 1

    now[0] += 24 * 60 * 60
    assert advisor.recommend(context()) is None
    assert len(messages) == 2


def test_schema_rejects_boolean_numbers_and_out_of_range_values():
    with pytest.raises(ValueError):
        validate_recommendation(
            {
                "mode": "FLAT",
                "ladder_width_scale": True,
                "cap_scale": 0.5,
                "confidence": 0.9,
                "rationale": "invalid",
            },
            config=config(),
        )


def test_schema_bounds_rationale_over_160_characters():
    recommendation = validate_recommendation(
        {
            "mode": "FLAT",
            "ladder_width_scale": 1.0,
            "cap_scale": 0.5,
            "confidence": 0.9,
            "rationale": "x" * 161,
        },
        config=config(),
    )
    assert len(recommendation.rationale) == 160
    assert recommendation.rationale.endswith("…")


def test_ai_cap_can_reduce_but_never_expand_risk_manager_cap():
    assert limit_cap_by_recommendation(40.0, 0.5) == 20.0
    assert limit_cap_by_recommendation(40.0, 1.25) == 40.0
    assert limit_cap_by_recommendation_decimal(
        "9.629230357428915089854829478", "0.33333333"
    ) == Decimal("3.209743420378870505188559526")


def test_deepseek_usage_is_logged_without_prompt_or_response(tmp_path):
    usage_log = tmp_path / "ai_usage.ndjson"
    session = FakeSession(
        {
            "mode": "UP",
            "ladder_width_scale": 1.0,
            "cap_scale": 0.8,
            "confidence": 0.9,
            "rationale": "Trend confirmed.",
        }
    )
    advisor = AIAdvisor(
        config(usage_log_path=str(usage_log)),
        session=session,
        logger=lambda _: None,
    )

    assert advisor.recommend(context()) is not None
    event = json.loads(usage_log.read_text().strip())

    assert event["prompt_cache_hit_tokens"] == 50
    assert event["prompt_cache_miss_tokens"] == 150
    assert event["completion_tokens"] == 40
    assert event["estimated_cost_usd"] == "0.0000323400"
    assert event["rationale"] == "Trend confirmed."
    assert event["rejection_reason"] == ""
    assert event["context_version"] == "ai-context-v3"
    assert len(event["context_hash"]) == 64
    assert "api_key" not in event
    assert "messages" not in event


def test_deepseek_flash_cost_uses_cache_hit_miss_and_output_rates():
    usage = TokenUsage(
        prompt_tokens=1_000_000,
        prompt_cache_hit_tokens=400_000,
        prompt_cache_miss_tokens=600_000,
        completion_tokens=100_000,
        total_tokens=1_100_000,
    )
    assert estimate_usage_cost_usd(
        usage, token_prices(config())
    ) == Decimal("0.1131200000")
