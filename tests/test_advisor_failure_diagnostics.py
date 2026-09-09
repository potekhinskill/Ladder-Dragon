"""Failure diagnostics preserve fallback without exposing provider material."""

import json

import pytest
import requests

from ladder_dragon.ai.ai_advisor import AIAdvisor
from ladder_dragon.ai.advisor_diagnostics import AdvisorResponseError, failure_reason, record_failure
from tests.test_ai_advisor import config, context, FakeSession


@pytest.mark.parametrize("field,value,reason", [
    ("mode", "PRIVATE_MARKER", "mode_invalid"),
    ("cap_scale", 100, "cap_out_of_bounds"),
    ("confidence", "PRIVATE_MARKER", "number_invalid"),
    ("PRIVATE_MARKER", "PRIVATE_MARKER", "schema_mismatch"),
])
def test_validation_failures_have_fixed_codes_phase_and_elapsed(tmp_path, field, value, reason):
    payload = dict(mode="UP", ladder_width_scale=1.0, cap_scale=0.8, confidence=0.9, rationale="ok")
    payload[field] = value
    session, messages = FakeSession(payload), []
    path = tmp_path / "usage.ndjson"
    advisor = AIAdvisor(config(usage_log_path=str(path)), session=session, logger=messages.append)
    assert advisor.recommend(context()) is None
    assert advisor.recommend(context()) is None
    assert len(session.calls) == 1
    event = json.loads(path.read_text())
    assert event["failure_phase"] == "recommendation_validation"
    assert event["failure_reason"] == reason
    assert event["latency_ms"] >= 0
    assert f"reason={reason}" in messages[0] and "elapsed_ms=" in messages[0]
    assert "using deterministic strategy" in messages[0]
    assert "PRIVATE_MARKER" not in path.read_text() + str(messages)


@pytest.mark.parametrize("error,reason", [
    (requests.Timeout("PRIVATE_MARKER"), "request_timeout"),
    (json.JSONDecodeError("PRIVATE_MARKER", "PRIVATE_MARKER", 0), "json_invalid"),
    (ValueError("PRIVATE_MARKER"), "response_invalid"),
    (ValueError("AI response content is empty"), "content_empty"),
])
def test_request_failures_preserve_safe_durable_evidence(tmp_path, monkeypatch, error, reason):
    messages = []
    path = tmp_path / "usage.ndjson"
    advisor = AIAdvisor(config(usage_log_path=str(path)), session=FakeSession({}), logger=messages.append)
    def fail(_context):
        raise error
    monkeypatch.setattr(advisor, "_request", fail)
    assert advisor.recommend(context()) is None
    event = json.loads(path.read_text())
    assert event["failure_phase"] == "request"
    assert event["failure_reason"] == reason
    assert event["latency_ms"] >= 0
    assert "PRIVATE_MARKER" not in path.read_text() + str(messages)


def test_unrecognized_typed_reason_cannot_leak():
    assert failure_reason(AdvisorResponseError("PRIVATE_MARKER")) == "response_invalid"


def test_failure_publisher_preserves_callback_order_and_exact_fields():
    events = []
    ctx = context()
    error = requests.Timeout("PRIVATE_MARKER")
    def log_usage(*args, **kwargs):
        events.append(("usage", args, kwargs))
    def label(exc):
        assert exc is error
        events.append(("label",))
        return "Timeout"
    record_failure(error, context=ctx, usage=None, elapsed_ms=12.5, phase="request",
                   log_usage=log_usage, log_diagnostic=lambda *args: events.append(("diagnostic", args)),
                   error_label=label)
    assert [event[0] for event in events] == ["usage", "label", "diagnostic"]
    assert events[0][1] == (ctx, None)
    assert events[0][2] == {"latency_ms": 12.5, "outcome": "error", "rejection_reason": "Timeout",
                            "failure_phase": "request", "failure_reason": "request_timeout"}
    assert events[2][1] == (ctx.symbol, "provider_error:request:request_timeout:Timeout",
                           f"[AI-ADVISOR] {ctx.symbol} unavailable: Timeout; phase=request "
                           "reason=request_timeout elapsed_ms=12.5; using deterministic strategy")
    assert "PRIVATE_MARKER" not in str(events)


def test_failure_publisher_does_not_hide_callback_failure():
    def fail(*args, **kwargs):
        raise OSError("test log failure")
    with pytest.raises(OSError, match="test log failure"):
        record_failure(ValueError("bad"), context=context(), usage=None, elapsed_ms=0, phase="request",
                       log_usage=fail, log_diagnostic=lambda *args: pytest.fail("unexpected diagnostic"),
                       error_label=lambda exc: pytest.fail("unexpected label"))
