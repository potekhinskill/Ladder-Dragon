# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: enforce concrete summary-route ownership and live dependencies.
"""Require concrete trade-summary presentation and current dependencies."""

import time
from ladder_dragon.verification.architecture.route_contracts import audit_route_group
from ladder_dragon.verification.models import CheckResult, Status, EXIT_CODES

SUMMARY_FIELDS = frozenset(('_EQUITY_SUMMARY_CACHE', '_database_unavailable_response', '_fee_pct_default', '_fifo_realized_pnl', '_load_trades', '_open_db', 'equity_pnl_usdt', 'time'))


def audit_summary_routes(root):
    return audit_route_group(root, group="summary",
                             paths={"trades_summary": "/api/trades/summary"},
                             fields=SUMMARY_FIELDS, bodies={"trades_summary": "try"})


def check_summary_routes(context):
    started = time.monotonic()
    try:
        violations = audit_summary_routes(context.root)
        status = Status.FAILED if violations else Status.PASS
    except (OSError, SyntaxError, ValueError, TypeError) as exc:
        violations = [type(exc).__name__]
        status = Status.BLOCKED
    return CheckResult(name="architecture_summary_routes", status=status, required=True,
                       duration_ms=int((time.monotonic() - started) * 1000),
                       summary="Concrete trade-summary handler and live dependencies",
                       exit_code=EXIT_CODES[status], metrics={"violations": violations})
