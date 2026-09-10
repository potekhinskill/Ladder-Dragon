# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: keep risk alert identity independent of diagnostic timing.
"""Stable alert identity without suppressing changes in risk state."""

import re

from ladder_dragon.risk.risk_manager import RiskDecision

_ATTEMPT = re.compile(r"^(risk telemetry unavailable) \(\d+/\d+\):\s*")
_TRANSPORT = re.compile(
    r"^(risk telemetry unavailable: market transport failed reason=[a-z_]+ "
    r"endpoint=(?:/api/v3/[A-Za-z/]+|unknown) stage=(?:body|headers) "
    r"attempts=\d+) elapsed_ms=\d+$"
)


def risk_alert_signature(decision: RiskDecision) -> tuple[bool, bool, tuple[str, ...]]:
    """Keep reason, endpoint, stage, and risk flags; ignore timing and cycle counts."""
    reasons = tuple(
        _TRANSPORT.sub(r"\1", _ATTEMPT.sub(r"\1: ", str(reason)).strip())
        for reason in decision.reasons
    )
    return decision.halted, decision.buy_blocked, reasons
