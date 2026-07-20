# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: implement the ai advisor component of the ai layer.
"""Ladder Dragon ai advisor support."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
import json
import hashlib
import os
from pathlib import Path
import sqlite3
import time
from typing import Any, Callable, Mapping, Optional

import requests


ALLOWED_MODES = {"UP", "DOWN", "FLAT"}
MAX_RATIONALE_CHARS = 160


@dataclass(frozen=True)
class AdvisorConfig:
    enabled: bool
    provider: str
    model: str
    base_url: str
    api_key: str = field(repr=False)
    timeout_sec: float = 10.0
    cache_sec: int = 300
    min_confidence: float = 0.65
    width_scale_min: float = 0.75
    width_scale_max: float = 1.50
    cap_scale_min: float = 0.25
    cap_scale_max: float = 1.25
    usage_log_path: str = ""
    usage_log_max_bytes: int = 5_242_880
    input_cache_hit_usd_per_mtok: Optional[float] = None
    input_cache_miss_usd_per_mtok: Optional[float] = None
    output_usd_per_mtok: Optional[float] = None

    def validate(self) -> None:
        if not self.enabled:
            return
        if self.provider not in ("openai", "deepseek", "compatible"):
            raise ValueError("AI provider must be openai, deepseek or compatible")
        if not self.model.strip():
            raise ValueError("AI model is required")
        if not self.base_url.startswith("https://"):
            raise ValueError("AI base URL must use https://")
        if not self.api_key:
            raise ValueError("AI API key is required")
        if self.timeout_sec <= 0 or self.cache_sec < 0:
            raise ValueError("AI timeout must be > 0 and cache must be >= 0")
        if not 0 <= self.min_confidence <= 1:
            raise ValueError("AI minimum confidence must be in [0, 1]")
        if not 0 < self.width_scale_min <= self.width_scale_max <= 3:
            raise ValueError("AI ladder width bounds must satisfy 0 < min <= max <= 3")
        if not 0 < self.cap_scale_min <= self.cap_scale_max <= 2:
            raise ValueError("AI CAP bounds must satisfy 0 < min <= max <= 2")
        if self.usage_log_max_bytes <= 0:
            raise ValueError("AI usage log max bytes must be > 0")
        for value in (
            self.input_cache_hit_usd_per_mtok,
            self.input_cache_miss_usd_per_mtok,
            self.output_usd_per_mtok,
        ):
            if value is not None and value < 0:
                raise ValueError("AI token prices must be >= 0")


@dataclass(frozen=True)
class MarketContext:
    symbol: str
    price: float
    atr_pct: float
    deterministic_mode: str
    candidate_mode: str
    ema_gap_pct: float
    ema_slope: float
    adx: float
    ladder_low_pct: float
    ladder_down_pct: float
    ladder_up_pct: float
    target_buys: int
    risk_safe_cap_usdt: float
    trade_history_available: bool = False
    trade_count_30d: int = 0
    sell_count_30d: int = 0
    net_realized_pnl_30d: float = 0.0
    win_rate_30d: float = 0.0
    avg_win_usdt_30d: float = 0.0
    avg_loss_usdt_30d: float = 0.0
    consecutive_losses: int = 0
    fees_usdt_30d: float = 0.0
    turnover_usdt_30d: float = 0.0
    position_pnl_pct: float = 0.0
    market_data_available: bool = False
    orderbook_available: bool = False
    market_data_age_sec: float = 999999.0
    return_15m: float = 0.0
    return_1h: float = 0.0
    return_4h: float = 0.0
    return_24h: float = 0.0
    volume_ratio_1h: float = 1.0
    spread_bps: float = 0.0
    orderbook_imbalance_top5: float = 0.0
    orderbook_imbalance_top20: float = 0.0
    open_buy_count: int = 0
    open_sell_count: int = 0
    open_buy_exposure_usdt: float = 0.0
    portfolio_cap_used_pct: float = 0.0
    free_reserve_ratio: float = 0.0
    portfolio_data_available: bool = False
    portfolio_data_age_sec: float = 999999.0
    ai_samples_15m: int = 0
    ai_accuracy_15m: float = 0.0
    ai_samples_1h: int = 0
    ai_accuracy_1h: float = 0.0
    ai_samples_4h: int = 0
    ai_accuracy_4h: float = 0.0
    ai_vs_baseline_samples_1h: int = 0
    ai_edge_vs_baseline_1h: float = 0.0
    ai_closed_samples: int = 0
    ai_realized_net_pnl_quote: float = 0.0
    ai_realized_avg_pnl_quote: float = 0.0
    ai_realized_stop_rate: float = 0.0
    ai_realized_edge_ci_low: float = 0.0
    ai_realized_edge_ci_high: float = 0.0
    ai_unresolved_fills: int = 0
    real_rag_episode_count: int = 0
    # Short, verified historical cases for local RAG. This contains no API keys,
    # balances or order IDs; Risk Manager never reads this context.
    rag_context: tuple[Mapping[str, Any], ...] = ()


@dataclass(frozen=True)
class StrategyRecommendation:
    mode: str
    ladder_width_scale: float
    cap_scale: float
    confidence: float
    rationale: str
    provider: str
    model: str


@dataclass(frozen=True)
class TokenUsage:
    prompt_tokens: int
    prompt_cache_hit_tokens: int
    prompt_cache_miss_tokens: int
    completion_tokens: int
    total_tokens: int


class AIAdvisor:
    """Represent AIAdvisor."""

    def __init__(
        self,
        config: AdvisorConfig,
        *,
        session: requests.Session,
        logger: Callable[[str], None],
        clock: Callable[[], float] = time.time,
        decision_recorder: Optional[
            Callable[[MarketContext, StrategyRecommendation, bool], Optional[str]]
        ] = None,
        budget_checker: Optional[Callable[[], tuple[bool, str]]] = None,
    ) -> None:
        config.validate()
        self.config = config
        self.session = session
        self.logger = logger
        self.clock = clock
        self.decision_recorder = decision_recorder
        self.budget_checker = budget_checker
        self._budget_blocked_day: Optional[str] = None
        self._budget_blocked_reason = ""
        # The marker prevents the executor from creating a new history entry
        # on every cycle when the same cached recommendation is returned.
        self._last_was_cache_hit = False
        self._last_decision_id: Optional[str] = None
        # Cache both successful results and safe failures. This prevents an
        # unavailable API or low confidence from generating requests every second.
        self._cache: dict[
            str, tuple[float, Optional[StrategyRecommendation]]
        ] = {}

    def refresh_due(self, symbol: str) -> bool:
        cached = self._cache.get(symbol)
        return (
            cached is None
            or self.clock() - cached[0] > self.config.cache_sec
        )

    @property
    def last_was_cache_hit(self) -> bool:
        """Handle last was cache hit."""
        return self._last_was_cache_hit

    @property
    def last_decision_id(self) -> Optional[str]:
        """Handle last decision id."""
        return self._last_decision_id

    def recommend(
        self, context: MarketContext
    ) -> Optional[StrategyRecommendation]:
        self._last_was_cache_hit = False
        self._last_decision_id = None
        if not self.config.enabled:
            return None
        now = self.clock()
        utc_day = datetime.fromtimestamp(now, timezone.utc).date().isoformat()
        if self.budget_checker is not None:
            # Do not spam the journal with the same rejection every few seconds.
            # The block is cleared automatically at the next UTC day.
            if self._budget_blocked_day == utc_day:
                return None
            allowed, reason = self.budget_checker()
            if not allowed:
                self._budget_blocked_day = utc_day
                self._budget_blocked_reason = reason
                self.logger(
                    f"[AI-BUDGET] {context.symbol} disabled until next UTC day: {reason}"
                )
                return None
            self._budget_blocked_day = None
            self._budget_blocked_reason = ""
        cached = self._cache.get(context.symbol)
        if cached is not None and now - cached[0] <= self.config.cache_sec:
            self._last_was_cache_hit = True
            return cached[1]
        started = time.monotonic()
        usage: Optional[TokenUsage] = None
        try:
            payload, usage = self._request(context)
            recommendation = validate_recommendation(
                payload,
                config=self.config,
            )
            applied = recommendation.confidence >= self.config.min_confidence
            if self.decision_recorder is not None:
                try:
                    self._last_decision_id = self.decision_recorder(
                        context, recommendation, applied
                    )
                except (OSError, sqlite3.Error) as exc:
                    self.logger(f"[AI-DECISION] cannot record decision: {exc}")
            if not applied:
                self._log_usage(
                    context,
                    usage,
                    latency_ms=(time.monotonic() - started) * 1000,
                    outcome="low_confidence",
                    rationale=recommendation.rationale,
                    rejection_reason="confidence_below_threshold",
                )
                self.logger(
                    f"[AI-ADVISOR] {context.symbol} ignored: confidence "
                    f"{recommendation.confidence:.2f} < "
                    f"{self.config.min_confidence:.2f}"
                )
                self._cache[context.symbol] = (now, None)
                return None
            self._log_usage(
                context,
                usage,
                latency_ms=(time.monotonic() - started) * 1000,
                outcome="applied",
                rationale=recommendation.rationale,
            )
            self._cache[context.symbol] = (now, recommendation)
            return recommendation
        except (requests.RequestException, ValueError, KeyError, TypeError) as exc:
            # The advisory layer is fail-safe: any error selects the verified
            # deterministic strategy; trading never depends on the LLM.
            self._log_usage(
                context,
                usage,
                latency_ms=(time.monotonic() - started) * 1000,
                outcome="error",
                rejection_reason=type(exc).__name__,
            )
            self.logger(
                f"[AI-ADVISOR] {context.symbol} unavailable: {exc}; "
                "using deterministic strategy"
            )
            self._cache[context.symbol] = (now, None)
            return None

    def _request(
        self, context: MarketContext
    ) -> tuple[Mapping[str, object], TokenUsage]:
        endpoint = self.config.base_url.rstrip("/") + "/chat/completions"
        system_prompt = (
            "You are a conservative advisory component for a Binance Spot grid "
            "strategy. You never place orders and never propose quantities, "
            "prices, leverage, transfers, or bypassing risk controls. Return only "
            "one JSON object with exactly these fields: "
            '{"mode":"UP|DOWN|FLAT","ladder_width_scale":number,'
            f'"cap_scale":number,"confidence":number,"rationale":"one short '
            f'sentence, maximum {MAX_RATIONALE_CHARS} characters"}}. '
            "Prefer the deterministic mode unless the indicators provide clear "
            "evidence. cap_scale above 1 is only a preference and will still be "
            "capped by the local Risk Manager. Treat trade statistics with fewer "
            "than 20 sells and AI accuracy with fewer than 30 samples as weak "
            "evidence. High fees, drawdown, losing streaks, spread, volatility, "
            "portfolio utilization, or order-book imbalance may only justify a "
            "more conservative recommendation, never bypassing local limits."
        )
        body: dict[str, Any] = {
            "model": self.config.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {
                    "role": "user",
                    "content": (
                        "Analyze this market context and return JSON only:\n"
                        + json.dumps(
                            asdict(context),
                            ensure_ascii=False,
                            sort_keys=True,
                        )
                    ),
                },
            ],
            "response_format": {"type": "json_object"},
            "temperature": 0,
            # The response limit reduces long rationale and limits advisory cost.
            "max_tokens": 160,
            "stream": False,
        }
        if self.config.provider == "deepseek":
            # Advisory does not need hidden reasoning: short JSON is cheaper,
            # faster and easier to validate.
            body["thinking"] = {"type": "disabled"}
        response = self.session.post(
            endpoint,
            headers={
                "Authorization": f"Bearer {self.config.api_key}",
                "Content-Type": "application/json",
            },
            json=body,
            timeout=self.config.timeout_sec,
        )
        response.raise_for_status()
        envelope = response.json()
        usage = parse_token_usage(envelope)
        choices = envelope.get("choices") if isinstance(envelope, dict) else None
        if not isinstance(choices, list) or not choices:
            raise ValueError("AI response has no choices")
        message = choices[0].get("message")
        content = message.get("content") if isinstance(message, dict) else None
        if not isinstance(content, str) or not content.strip():
            raise ValueError("AI response content is empty")
        decoded = json.loads(content)
        if not isinstance(decoded, dict):
            raise ValueError("AI response must be a JSON object")
        return decoded, usage

    def _log_usage(
        self,
        context: MarketContext,
        usage: Optional[TokenUsage],
        *,
        latency_ms: float,
        outcome: str,
        rationale: str = "",
        rejection_reason: str = "",
    ) -> None:
        """Handle log usage."""
        if not self.config.usage_log_path:
            return
        rates = token_prices(self.config)
        estimated_usd = (
            estimate_usage_cost_usd(usage, rates) if usage is not None else None
        )
        event = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "provider": self.config.provider,
            "model": self.config.model,
            "symbol": context.symbol,
            "outcome": outcome,
            "latency_ms": round(latency_ms, 1),
            "prompt_tokens": usage.prompt_tokens if usage is not None else None,
            "prompt_cache_hit_tokens": (
                usage.prompt_cache_hit_tokens if usage is not None else None
            ),
            "prompt_cache_miss_tokens": (
                usage.prompt_cache_miss_tokens if usage is not None else None
            ),
            "completion_tokens": (
                usage.completion_tokens if usage is not None else None
            ),
            "total_tokens": usage.total_tokens if usage is not None else None,
            "estimated_cost_usd": (
                str(estimated_usd) if estimated_usd is not None else None
            ),
            "decision_id": self._last_decision_id,
            "rationale": rationale[:MAX_RATIONALE_CHARS],
            "rejection_reason": rejection_reason[:240],
            "context_version": "ai-context-v2",
            "context_hash": hashlib.sha256(
                json.dumps(asdict(context), ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")
            ).hexdigest(),
        }
        try:
            append_usage_event(
                Path(self.config.usage_log_path),
                event,
                max_bytes=self.config.usage_log_max_bytes,
            )
        except OSError as exc:
            # Cost telemetry must not influence strategy or trading.
            self.logger(f"[AI-USAGE] cannot write usage log: {exc}")


def validate_recommendation(
    payload: Mapping[str, object],
    *,
    config: AdvisorConfig,
) -> StrategyRecommendation:
    """Validate recommendation."""
    required = {
        "mode",
        "ladder_width_scale",
        "cap_scale",
        "confidence",
        "rationale",
    }
    if set(payload) != required:
        missing = sorted(required - set(payload))
        extra = sorted(set(payload) - required)
        raise ValueError(
            f"AI schema mismatch: missing={missing}, extra={extra}"
        )
    mode = str(payload["mode"]).upper()
    if mode not in ALLOWED_MODES:
        raise ValueError(f"invalid AI mode: {mode}")
    width = _strict_number(payload["ladder_width_scale"], "ladder_width_scale")
    cap = _strict_number(payload["cap_scale"], "cap_scale")
    confidence = _strict_number(payload["confidence"], "confidence")
    if not config.width_scale_min <= width <= config.width_scale_max:
        raise ValueError("AI ladder width scale is outside configured bounds")
    if not config.cap_scale_min <= cap <= config.cap_scale_max:
        raise ValueError("AI CAP scale is outside configured bounds")
    if not 0 <= confidence <= 1:
        raise ValueError("AI confidence must be in [0, 1]")
    rationale = payload["rationale"]
    if not isinstance(rationale, str) or not rationale.strip():
        raise ValueError("AI rationale must be a non-empty string")
    rationale = rationale.strip()
    if any(ord(char) < 32 for char in rationale):
        raise ValueError("AI rationale contains control characters")
    # Rationale does not participate in the trading decision. Limit it safely
    # after strict schema validation so a rare model overflow does not turn
    # valid mode/CAP/confidence into a failure of the whole AI cycle.
    if len(rationale) > MAX_RATIONALE_CHARS:
        rationale = rationale[: MAX_RATIONALE_CHARS - 1].rstrip() + "…"
    return StrategyRecommendation(
        mode=mode,
        ladder_width_scale=width,
        cap_scale=cap,
        confidence=confidence,
        rationale=rationale,
        provider=config.provider,
        model=config.model,
    )


def _strict_number(value: object, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"AI {name} must be a JSON number")
    result = float(value)
    if result != result or result in (float("inf"), float("-inf")):
        raise ValueError(f"AI {name} must be finite")
    return result


def _strict_decimal(value: object, name: str) -> Decimal:
    if isinstance(value, bool):
        raise ValueError(f"AI {name} must be a decimal number")
    try:
        result = Decimal(str(value))
    except (ArithmeticError, TypeError, ValueError) as exc:
        raise ValueError(f"AI {name} must be a decimal number") from exc
    if not result.is_finite():
        raise ValueError(f"AI {name} must be finite")
    return result


def parse_token_usage(envelope: object) -> TokenUsage:
    if not isinstance(envelope, dict) or not isinstance(envelope.get("usage"), dict):
        raise ValueError("AI response has no token usage")
    usage = envelope["usage"]

    def token_count(name: str, default: int = 0) -> int:
        value = usage.get(name, default)
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise ValueError(f"AI usage {name} must be a non-negative integer")
        return value

    prompt = token_count("prompt_tokens")
    hit = token_count("prompt_cache_hit_tokens")
    miss = token_count("prompt_cache_miss_tokens", max(0, prompt - hit))
    completion = token_count("completion_tokens")
    total = token_count("total_tokens", prompt + completion)
    if hit + miss != prompt or total != prompt + completion:
        raise ValueError("AI token usage totals are inconsistent")
    return TokenUsage(prompt, hit, miss, completion, total)


def token_prices(
    config: AdvisorConfig,
) -> Optional[tuple[Decimal, Decimal, Decimal]]:
    defaults = {
        ("deepseek", "deepseek-v4-flash"): ("0.0028", "0.14", "0.28"),
        ("deepseek", "deepseek-v4-pro"): ("0.003625", "0.435", "0.87"),
    }
    fallback = defaults.get((config.provider, config.model))
    values = (
        config.input_cache_hit_usd_per_mtok,
        config.input_cache_miss_usd_per_mtok,
        config.output_usd_per_mtok,
    )
    if all(value is not None for value in values):
        return tuple(Decimal(str(value)) for value in values)  # type: ignore[return-value]
    if fallback is None:
        return None
    return tuple(Decimal(value) for value in fallback)


def estimate_usage_cost_usd(
    usage: TokenUsage,
    rates: Optional[tuple[Decimal, Decimal, Decimal]],
) -> Optional[Decimal]:
    if rates is None:
        return None
    hit_rate, miss_rate, output_rate = rates
    million = Decimal("1000000")
    cost = (
        Decimal(usage.prompt_cache_hit_tokens) * hit_rate
        + Decimal(usage.prompt_cache_miss_tokens) * miss_rate
        + Decimal(usage.completion_tokens) * output_rate
    ) / million
    return cost.quantize(Decimal("0.0000000001"))


def append_usage_event(
    path: Path,
    event: Mapping[str, object],
    *,
    max_bytes: int,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and path.stat().st_size >= max_bytes:
        rotated = path.with_suffix(path.suffix + ".1")
        try:
            rotated.unlink()
        except FileNotFoundError:
            pass
        os.replace(path, rotated)
    line = json.dumps(event, ensure_ascii=False, sort_keys=True) + "\n"
    with path.open("a", encoding="utf-8") as handle:
        handle.write(line)


def limit_cap_by_recommendation_decimal(
    risk_safe_cap: object,
    cap_scale: object,
) -> Decimal:
    """Limit an exact risk-safe CAP without binary-float arithmetic."""
    safe_cap = _strict_decimal(risk_safe_cap, "risk_safe_cap")
    scale = _strict_decimal(cap_scale, "cap_scale")
    if safe_cap < 0 or scale <= 0:
        raise ValueError("AI CAP inputs must be non-negative and scale must be > 0")
    return min(safe_cap, safe_cap * scale)


def limit_cap_by_recommendation(risk_safe_cap: float, cap_scale: float) -> float:
    """Return the legacy numeric view of the exact CAP calculation."""
    return float(
        limit_cap_by_recommendation_decimal(risk_safe_cap, cap_scale)
    )
