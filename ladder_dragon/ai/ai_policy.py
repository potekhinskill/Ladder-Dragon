# Copyright (c) 2026 IURII Potekhin / Ladder Dragon. All rights reserved.
# Purpose: implement the ai policy component of the ai layer.
"""Детерминированная политика применения AI-рекомендаций."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timezone
from decimal import Decimal
import json
from pathlib import Path
from typing import Iterable, Optional

from ladder_dragon.ai.ai_advisor import MarketContext, StrategyRecommendation


AI_MODES = {"DISABLED", "SHADOW", "APPLY"}


@dataclass(frozen=True)
class PolicyConfig:
    mode: str = "SHADOW"
    max_market_age_sec: float = 30.0
    max_portfolio_age_sec: float = 30.0
    max_spread_bps: float = 25.0
    high_volatility_pct: float = 0.04
    max_consecutive_losses: int = 3
    min_trade_sells: int = 20
    min_accuracy_samples: int = 30
    min_ai_accuracy: float = 0.50
    min_closed_decisions: int = 5
    max_realized_stop_rate: float = 0.60

    def validate(self) -> None:
        if self.mode not in AI_MODES:
            raise ValueError("AI mode must be DISABLED, SHADOW or APPLY")
        if min(
            self.max_market_age_sec,
            self.max_portfolio_age_sec,
            self.max_spread_bps,
            self.high_volatility_pct,
        ) <= 0:
            raise ValueError("AI policy thresholds must be > 0")
        if self.max_consecutive_losses < 0:
            raise ValueError("AI max consecutive losses must be >= 0")
        if not 0 <= self.min_ai_accuracy <= 1:
            raise ValueError("AI minimum accuracy must be in [0, 1]")
        if self.min_closed_decisions < 0 or not 0 <= self.max_realized_stop_rate <= 1:
            raise ValueError("AI realized-result thresholds are invalid")


@dataclass(frozen=True)
class PolicyDecision:
    recommendation: StrategyRecommendation
    apply: bool
    pause_buys: bool
    status: str
    reasons: tuple[str, ...]
    benchmark_mode: str


def numeric_regime_benchmark(context: MarketContext) -> str:
    """Простой интерпретируемый benchmark без LLM."""
    score = 0.0
    score += max(-2.0, min(2.0, context.return_1h / 0.01))
    score += max(-2.0, min(2.0, context.return_4h / 0.025))
    score += max(-1.5, min(1.5, context.ema_gap_pct / 0.005))
    score += max(-1.5, min(1.5, context.ema_slope / 0.0005))
    score += max(-1.0, min(1.0, context.orderbook_imbalance_top20))
    if context.adx < 15:
        score *= 0.5
    if score >= 1.5:
        return "UP"
    if score <= -1.5:
        return "DOWN"
    return "FLAT"


def apply_safety_policy(
    context: MarketContext,
    recommendation: StrategyRecommendation,
    config: PolicyConfig,
    *,
    benchmark_mode: Optional[str] = None,
) -> PolicyDecision:
    """Применить правила, которые нельзя оставить на усмотрение prompt."""
    config.validate()
    benchmark = benchmark_mode or numeric_regime_benchmark(context)
    reasons: list[str] = []
    result = recommendation
    apply = config.mode == "APPLY"
    pause = False

    data_ok = (
        context.market_data_available
        and context.orderbook_available
        and context.portfolio_data_available
        and context.market_data_age_sec <= config.max_market_age_sec
        and context.portfolio_data_age_sec <= config.max_portfolio_age_sec
    )
    if not data_ok:
        apply = False
        # Do not hide which source made the context unusable. These are
        # diagnostic markers and do not weaken the fail-closed rule.
        if not context.market_data_available:
            reasons.append("market_data_unavailable")
        if not context.orderbook_available:
            reasons.append("orderbook_unavailable")
        if not context.portfolio_data_available:
            reasons.append("portfolio_data_unavailable")
        if context.market_data_age_sec > config.max_market_age_sec:
            reasons.append("market_data_stale")
        if context.portfolio_data_age_sec > config.max_portfolio_age_sec:
            reasons.append("portfolio_data_stale")
        reasons.append("incomplete_or_stale_context")

    if config.mode == "SHADOW":
        apply = False
        reasons.append("shadow_mode")
    elif config.mode == "DISABLED":
        apply = False
        reasons.append("disabled")

    # Weak statistics forbid any increase in aggressiveness.
    if context.sell_count_30d < config.min_trade_sells:
        result = replace(
            result,
            ladder_width_scale=max(1.0, result.ladder_width_scale),
            cap_scale=min(1.0, result.cap_scale),
        )
        reasons.append("insufficient_trade_history")

    # High volatility must never narrow the ladder.
    if context.atr_pct >= config.high_volatility_pct:
        result = replace(result, ladder_width_scale=max(1.0, result.ladder_width_scale))
        reasons.append("high_volatility_no_narrowing")

    # Losses, a high CAP or a bad position allow only a CAP reduction.
    if (
        context.consecutive_losses >= config.max_consecutive_losses
        or context.portfolio_cap_used_pct >= 0.80
        or context.position_pnl_pct <= -0.05
    ):
        result = replace(result, cap_scale=min(result.cap_scale, 0.50))
        reasons.append("risk_pressure_cap_reduced")

    # An expensive market or nearly exhausted reserve means BUY must pause.
    if (
        context.spread_bps >= config.max_spread_bps
        or context.free_reserve_ratio < 1.0
    ):
        pause = True
        reasons.append("pause_buys_market_or_reserve")

    # When statistically significant poor accuracy accumulates, AI remains in shadow.
    if (
        context.ai_samples_1h >= config.min_accuracy_samples
        and context.ai_accuracy_1h < config.min_ai_accuracy
    ):
        apply = False
        reasons.append("ai_accuracy_below_threshold")

    # Production APPLY is allowed only after real positions close:
    # virtual candle estimates cannot pass this gate. The edge interval must
    # be strictly above zero, otherwise an advantage over baseline is unproven.
    if config.mode == "APPLY":
        if context.ai_closed_samples < config.min_closed_decisions:
            apply = False
            reasons.append("insufficient_realized_ai_samples")
        elif context.ai_realized_edge_ci_low <= 0:
            apply = False
            reasons.append("realized_edge_confidence_interval_includes_zero")
        if context.ai_realized_stop_rate > config.max_realized_stop_rate:
            apply = False
            reasons.append("realized_stop_rate_degraded")

    status = "APPLIED" if apply else ("SHADOW" if config.mode == "SHADOW" else "REJECTED")
    if pause and apply:
        status = "PAUSE_BUYS"
    return PolicyDecision(result, apply, pause and apply, status, tuple(reasons), benchmark)


@dataclass(frozen=True)
class UsageBudget:
    max_requests: int
    max_tokens: int
    max_cost_usd: Decimal


@dataclass(frozen=True)
class UsageToday:
    requests: int = 0
    tokens: int = 0
    cost_usd: Decimal = Decimal("0")


def read_usage_today(path: str, *, now: Optional[datetime] = None) -> UsageToday:
    now = now or datetime.now(timezone.utc)
    target = now.date()
    result = UsageToday()
    log_path = Path(path)
    if not log_path.exists():
        return result
    requests = tokens = 0
    cost = Decimal("0")
    for line in log_path.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            event = json.loads(line)
            stamp = datetime.fromisoformat(str(event["timestamp"]))
            if stamp.astimezone(timezone.utc).date() != target:
                continue
            requests += 1
            tokens += int(event.get("total_tokens") or 0)
            cost += Decimal(str(event.get("estimated_cost_usd") or "0"))
        except (KeyError, TypeError, ValueError, json.JSONDecodeError):
            continue
    return UsageToday(requests, tokens, cost)


def usage_budget_allows(today: UsageToday, budget: UsageBudget) -> tuple[bool, str]:
    if budget.max_requests > 0 and today.requests >= budget.max_requests:
        return False, "daily request limit"
    if budget.max_tokens > 0 and today.tokens >= budget.max_tokens:
        return False, "daily token limit"
    if budget.max_cost_usd > 0 and today.cost_usd >= budget.max_cost_usd:
        return False, "daily cost limit"
    return True, ""


def confidence_calibration(
    rows: Iterable[tuple[float, Optional[float], str]],
) -> list[dict[str, float | int | str]]:
    buckets = ((0.0, 0.65), (0.65, 0.70), (0.70, 0.80), (0.80, 1.01))
    output = []
    rows = list(rows)
    for low, high in buckets:
        values = [
            int(
                (mode == "UP" and ret > 0.001)
                or (mode == "DOWN" and ret < -0.001)
                or (mode == "FLAT" and abs(ret) <= 0.001)
            )
            for confidence, ret, mode in rows
            if low <= confidence < high and ret is not None
        ]
        output.append(
            {
                "bucket": f"{low:.2f}-{min(high, 1.0):.2f}",
                "samples": len(values),
                "accuracy": sum(values) / len(values) if values else 0.0,
            }
        )
    return output
