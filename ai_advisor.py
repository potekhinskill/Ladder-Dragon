"""Безопасный рекомендательный слой стратегии на основе LLM.

Модель не получает торговых инструментов и не создаёт ордера. Она может только
предложить режим рынка, масштаб ширины лестницы и коэффициент CAP. Ответ
проходит строгую локальную валидацию, а итоговый CAP дополнительно ограничивает
существующий Risk Manager.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
import json
import time
from typing import Any, Callable, Mapping, Optional

import requests


ALLOWED_MODES = {"UP", "DOWN", "FLAT"}


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


@dataclass(frozen=True)
class StrategyRecommendation:
    mode: str
    ladder_width_scale: float
    cap_scale: float
    confidence: float
    rationale: str
    provider: str
    model: str


class AIAdvisor:
    """Запрашивает и кэширует только рекомендации со строгой схемой."""

    def __init__(
        self,
        config: AdvisorConfig,
        *,
        session: requests.Session,
        logger: Callable[[str], None],
        clock: Callable[[], float] = time.time,
    ) -> None:
        config.validate()
        self.config = config
        self.session = session
        self.logger = logger
        self.clock = clock
        # Кэшируем и успешный результат, и безопасный отказ. Это не позволяет
        # недоступному API или низкой confidence создавать запрос каждую секунду.
        self._cache: dict[
            str, tuple[float, Optional[StrategyRecommendation]]
        ] = {}

    def recommend(
        self, context: MarketContext
    ) -> Optional[StrategyRecommendation]:
        if not self.config.enabled:
            return None
        now = self.clock()
        cached = self._cache.get(context.symbol)
        if cached is not None and now - cached[0] <= self.config.cache_sec:
            return cached[1]
        try:
            payload = self._request(context)
            recommendation = validate_recommendation(
                payload,
                config=self.config,
            )
            if recommendation.confidence < self.config.min_confidence:
                self.logger(
                    f"[AI-ADVISOR] {context.symbol} ignored: confidence "
                    f"{recommendation.confidence:.2f} < "
                    f"{self.config.min_confidence:.2f}"
                )
                self._cache[context.symbol] = (now, None)
                return None
            self._cache[context.symbol] = (now, recommendation)
            return recommendation
        except (requests.RequestException, ValueError, KeyError, TypeError) as exc:
            # Рекомендательный слой fail-safe: при любой ошибке используется
            # проверенная детерминированная стратегия, торговля не зависит от LLM.
            self.logger(
                f"[AI-ADVISOR] {context.symbol} unavailable: {exc}; "
                "using deterministic strategy"
            )
            self._cache[context.symbol] = (now, None)
            return None

    def _request(self, context: MarketContext) -> Mapping[str, object]:
        endpoint = self.config.base_url.rstrip("/") + "/chat/completions"
        system_prompt = (
            "You are a conservative advisory component for a Binance Spot grid "
            "strategy. You never place orders and never propose quantities, "
            "prices, leverage, transfers, or bypassing risk controls. Return only "
            "one JSON object with exactly these fields: "
            '{"mode":"UP|DOWN|FLAT","ladder_width_scale":number,'
            '"cap_scale":number,"confidence":number,"rationale":"short text"}. '
            "Prefer the deterministic mode unless the indicators provide clear "
            "evidence. cap_scale above 1 is only a preference and will still be "
            "capped by the local Risk Manager."
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
            "max_tokens": 220,
            "stream": False,
        }
        if self.config.provider == "deepseek":
            # Для advisory не нужен скрытый reasoning: короткий JSON дешевле,
            # быстрее и проще проверяется.
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
        return decoded


def validate_recommendation(
    payload: Mapping[str, object],
    *,
    config: AdvisorConfig,
) -> StrategyRecommendation:
    """Строго проверить типы, поля и диапазоны ответа модели."""
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
    if len(rationale) > 240:
        raise ValueError("AI rationale is too long")
    if any(ord(char) < 32 for char in rationale):
        raise ValueError("AI rationale contains control characters")
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


def limit_cap_by_recommendation(risk_safe_cap: float, cap_scale: float) -> float:
    """Не позволить рекомендации расширить CAP, одобренный Risk Manager."""
    safe_cap = _strict_number(risk_safe_cap, "risk_safe_cap")
    scale = _strict_number(cap_scale, "cap_scale")
    if safe_cap < 0 or scale <= 0:
        raise ValueError("AI CAP inputs must be non-negative and scale must be > 0")
    return min(safe_cap, safe_cap * scale)
