# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: classify advisory failures without exposing provider payloads.
"""Fixed diagnostic labels never grant strategy or execution permission."""

import json

import requests


class AdvisorResponseError(ValueError):
    """A locally classified response failure with a fixed reason code."""

    def __init__(self, reason: str):
        self.reason = reason
        super().__init__(reason)


REASONS = frozenset({"schema_mismatch", "mode_invalid", "number_invalid", "number_nonfinite",
                     "width_out_of_bounds", "cap_out_of_bounds", "confidence_out_of_bounds",
                     "rationale_invalid", "rationale_control_characters"})
LOCAL_ERRORS = {
    "AI response Content-Length is invalid": "content_length_invalid",
    "AI response exceeds the byte limit": "response_too_large",
    "AI response is not valid UTF-8": "encoding_invalid",
    "AI response yielded a non-byte chunk": "response_chunk_invalid",
    "AI response has no choices": "choices_missing",
    "AI response content is empty": "content_empty",
    "AI response must be a JSON object": "response_not_object",
}


def failure_reason(exc: Exception) -> str:
    """Classify known failures; unknown exception text is never returned."""
    if isinstance(exc, AdvisorResponseError):
        return exc.reason if exc.reason in REASONS else "response_invalid"
    if isinstance(exc, (json.JSONDecodeError, requests.exceptions.JSONDecodeError)):
        return "json_invalid"
    if isinstance(exc, requests.Timeout):
        return "request_timeout"
    if isinstance(exc, requests.HTTPError):
        return "http_error"
    if isinstance(exc, requests.RequestException):
        return "transport_error"
    return LOCAL_ERRORS.get(str(exc), "response_invalid")


def record_failure(exc, *, context, usage, elapsed_ms, phase, log_usage, log_diagnostic, error_label):
    """Publish failure evidence through current callbacks without owning cache state."""
    reason = failure_reason(exc)
    log_usage(
        context,
        usage,
        latency_ms=elapsed_ms,
        outcome="error",
        rejection_reason=type(exc).__name__,
        failure_phase=phase,
        failure_reason=reason,
    )
    safe_error = error_label(exc)
    log_diagnostic(
        context.symbol,
        f"provider_error:{phase}:{reason}:{safe_error}",
        f"[AI-ADVISOR] {context.symbol} unavailable: {safe_error}; "
        f"phase={phase} reason={reason} elapsed_ms={elapsed_ms:.1f}; "
        "using deterministic strategy",
    )
