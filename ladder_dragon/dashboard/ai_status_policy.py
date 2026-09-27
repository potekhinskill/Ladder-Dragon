# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: preserve AI-status presentation through explicit component ownership.

from decimal import Decimal


def policy_summary(deps, runtime, runtime_budgets, runtime_stale, effective_mode, usage, recent):
    request_limit = int(
        runtime_budgets.get("max_requests_per_day", deps.AI_MAX_REQUESTS_PER_DAY)
    )
    token_limit = int(
        runtime_budgets.get("max_tokens_per_day", deps.AI_DAILY_TOKEN_LIMIT)
    )
    cost_limit = Decimal(
        str(runtime_budgets.get("max_cost_usd_per_day", deps.AI_DAILY_COST_LIMIT_USD))
    )
    budget_exhausted = (
        (request_limit > 0 and usage["requests"] >= request_limit)
        or (token_limit > 0 and usage["tokens"] >= token_limit)
        or (cost_limit > 0 and Decimal(usage["cost_usd"]) >= cost_limit)
    )
    runtime_reason = deps.runtime_degraded_reason(
        runtime, follow_bot_paths=deps.DASHBOARD_FOLLOW_BOT_PATHS, stale=runtime_stale
    )
    degraded_reasons = []
    if budget_exhausted:
        degraded_reasons.append("daily_budget_exhausted")
    if usage.get("recent_errors", 0) >= deps.AI_ERROR_DEGRADED_MIN:
        degraded_reasons.append("recent_ai_errors")
    if effective_mode == "APPLY":
        # A production-gate rejection in APPLY is an independent DEGRADED reason:
        # the model may respond, but its statistics do not yet permit strategy impact.
        for row in recent:
            if str(row.get("status", "")).upper() != "REJECTED":
                continue
            for reason in str(row.get("policy_reasons", "")).split(","):
                reason = reason.strip()
                if reason and f"policy:{reason}" not in degraded_reasons:
                    degraded_reasons.append(f"policy:{reason}")
    if runtime_reason:
        degraded_reasons.append(runtime_reason)
    degraded = bool(degraded_reasons)
    state = (
        "DISABLED" if effective_mode == "DISABLED"
        else "DEGRADED" if degraded
        else "ACTIVE" if effective_mode == "APPLY"
        else "SHADOW"
    )
    return request_limit, token_limit, cost_limit, budget_exhausted, degraded_reasons, state
