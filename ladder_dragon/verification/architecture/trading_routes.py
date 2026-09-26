# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: require read-only trading route ownership and live wiring.
"""Trading route policy uses the shared structural analyzer."""

import time
from ladder_dragon.verification.models import CheckResult, Status, EXIT_CODES
from ladder_dragon.verification.architecture.route_contracts import audit_route_group

TRADING_PATHS = {"trading_overview": "/api/trading/overview", "account_balances": "/api/account/balances",
                 "account_open_orders": "/api/account/open-orders", "market_scenarios": "/api/market/scenarios"}
TRADING_FIELDS = frozenset(["_BALANCE_CACHE","_BALANCE_CACHE_LOCK","_DATA_SOURCE_ERRORS","_OPEN_ORDERS_CACHE","_OPEN_ORDERS_CACHE_LOCK","_stale_binance_snapshot","account_balances_snapshot","account_open_orders_snapshot","market_analysis_snapshot","trading_overview_snapshot"])


def audit_trading_routes(root):
    return audit_route_group(root, group="trading", paths=TRADING_PATHS, fields=TRADING_FIELDS,
                             bodies={"trading_overview": "try", "account_balances": "try", "account_open_orders": "try",
                                     "market_scenarios": "return state.market_analysis_snapshot()"})


def check_trading_routes(context):
    started = time.monotonic()
    try:
        violations = audit_trading_routes(context.root)
        status = Status.FAILED if violations else Status.PASS
    except (OSError, SyntaxError, ValueError, TypeError) as exc:
        violations = [type(exc).__name__]
        status = Status.BLOCKED
    return CheckResult(name="architecture_trading_routes", status=status, required=True,
                       duration_ms=int((time.monotonic() - started) * 1000),
                       summary="Concrete read-only trading routes and live dependencies",
                       exit_code=EXIT_CODES[status], metrics={"violations": violations})
