import json

import pytest

from ai_advisor import (
    AIAdvisor,
    AdvisorConfig,
    MarketContext,
    limit_cap_by_recommendation,
    validate_recommendation,
)


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self.payload


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
    assert AIAdvisor(
        config(min_confidence=0.65),
        session=low_session,
        logger=lambda _: None,
        clock=lambda: now[0],
    ).recommend(context()) is None

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
    now[0] += 10
    assert advisor.recommend(context()) is not None
    assert len(session.calls) == 1


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


def test_ai_cap_can_reduce_but_never_expand_risk_manager_cap():
    assert limit_cap_by_recommendation(40.0, 0.5) == 20.0
    assert limit_cap_by_recommendation(40.0, 1.25) == 40.0
