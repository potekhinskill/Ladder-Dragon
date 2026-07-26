# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: provide exact, fail-closed expectancy and regime execution controls.
"""Pure controls for fee floors, market regimes and inventory sizing."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
import time
from typing import Mapping


ZERO = Decimal("0")
ONE = Decimal("1")
REGIMES = {"RANGE", "TREND_UP", "TREND_DOWN", "PANIC", "RECOVERY"}


def exact_decimal(value: object, *, field: str) -> Decimal:
    """Return one finite Decimal at a financial decision boundary."""
    try:
        result = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValueError(f"{field} is not a decimal") from exc
    if not result.is_finite():
        raise ValueError(f"{field} must be finite")
    return result


@dataclass(frozen=True)
class CommissionSchedule:
    """Conservative authoritative maker/taker rates for one Binance symbol."""

    maker_buy: Decimal
    maker_sell: Decimal
    taker_buy: Decimal
    taker_sell: Decimal
    discount_observed: bool

    def __post_init__(self) -> None:
        if min(
            self.maker_buy,
            self.maker_sell,
            self.taker_buy,
            self.taker_sell,
        ) < ZERO:
            raise ValueError("commission rates must be non-negative")


def _side_rate(
    payload: Mapping[str, object],
    *,
    liquidity_role: str,
    side: str,
) -> Decimal:
    side_key = "buyer" if side == "BUY" else "seller"
    total = ZERO
    for section_name in (
        "standardCommission",
        "taxCommission",
        "specialCommission",
    ):
        section = payload.get(section_name)
        if not isinstance(section, Mapping):
            raise ValueError(f"Binance {section_name} is unavailable")
        total += exact_decimal(
            section.get(liquidity_role, "0"),
            field=f"{section_name}.{liquidity_role}",
        )
        total += exact_decimal(
            section.get(side_key, "0"),
            field=f"{section_name}.{side_key}",
        )
    return total


def authoritative_commission_schedule(
    payload: Mapping[str, object],
) -> CommissionSchedule:
    """Parse the account/commission response without assuming a BNB discount.

    The exchange-provided undiscounted rates are intentionally retained as the
    safety bound: an enabled discount can still be unavailable at fill time.
    """
    if not isinstance(payload, Mapping):
        raise ValueError("Binance commission response is not an object")
    discount = payload.get("discount")
    discount_observed = bool(
        isinstance(discount, Mapping)
        and discount.get("enabledForAccount") is True
        and discount.get("enabledForSymbol") is True
    )
    return CommissionSchedule(
        maker_buy=_side_rate(
            payload, liquidity_role="maker", side="BUY"
        ),
        maker_sell=_side_rate(
            payload, liquidity_role="maker", side="SELL"
        ),
        taker_buy=_side_rate(
            payload, liquidity_role="taker", side="BUY"
        ),
        taker_sell=_side_rate(
            payload, liquidity_role="taker", side="SELL"
        ),
        discount_observed=discount_observed,
    )


def required_round_trip_edge(
    *,
    buy_fee: object,
    sell_fee: object,
    buy_slippage: object,
    sell_slippage: object,
    safety_margin: object,
    multiplier: object,
) -> Decimal:
    """Return ``k ×`` the complete two-sided execution cost."""
    values = {
        "BUY fee": exact_decimal(buy_fee, field="BUY fee"),
        "SELL fee": exact_decimal(sell_fee, field="SELL fee"),
        "BUY slippage": exact_decimal(
            buy_slippage, field="BUY slippage"
        ),
        "SELL slippage": exact_decimal(
            sell_slippage, field="SELL slippage"
        ),
        "safety margin": exact_decimal(
            safety_margin, field="safety margin"
        ),
    }
    factor = exact_decimal(multiplier, field="edge multiplier")
    if min(values.values()) < ZERO or factor < ONE:
        raise ValueError("execution costs must be non-negative and k must be >= 1")
    return sum(values.values(), ZERO) * factor


def inventory_skew_scale(
    managed_exposure: object,
    hard_cap: object,
    *,
    gamma: object = "2",
) -> Decimal:
    """Reduce new BUY size smoothly to zero at the immutable hard CAP."""
    exposure = max(
        ZERO, exact_decimal(managed_exposure, field="managed exposure")
    )
    cap = exact_decimal(hard_cap, field="hard CAP")
    exponent = exact_decimal(gamma, field="inventory skew gamma")
    if cap <= ZERO or exponent <= ZERO:
        raise ValueError("hard CAP and inventory skew gamma must be positive")
    utilization = min(ONE, exposure / cap)
    return max(ZERO, ONE - utilization**exponent)


def vwap_premium_blocked(
    *,
    previously_blocked: bool,
    price_to_vwap_ratio: object,
    premium: object,
    hysteresis: object,
) -> bool:
    """Apply an exact Schmitt gate around the maximum BUY VWAP premium."""
    ratio = exact_decimal(price_to_vwap_ratio, field="price/VWAP ratio")
    allowed_premium = exact_decimal(premium, field="VWAP premium")
    band = exact_decimal(hysteresis, field="VWAP hysteresis")
    if ratio <= ZERO or allowed_premium < ZERO or band < ZERO:
        raise ValueError("VWAP ratio must be positive and bounds non-negative")
    threshold = ONE + allowed_premium
    enter_threshold = threshold + band
    exit_threshold = max(ONE, threshold - band)
    if previously_blocked:
        return ratio > exit_threshold
    return ratio > enter_threshold


@dataclass(frozen=True)
class RegimePolicy:
    """The only execution permissions derived from a confirmed regime."""

    state: str
    buys_allowed: bool
    cap_scale: Decimal
    protection_required: bool = True


class RegimeExecutionStateMachine:
    """Confirm transitions and require recovery before BUY is re-enabled."""

    def __init__(
        self,
        *,
        initial: str = "RECOVERY",
        confirmations: int = 3,
        recovery_confirmations: int = 3,
        min_hold_sec: float = 300.0,
    ) -> None:
        normalized = str(initial).upper()
        if normalized not in REGIMES:
            raise ValueError("unknown initial regime")
        self.state = normalized
        self.confirmations = max(1, int(confirmations))
        self.recovery_confirmations = max(
            1, int(recovery_confirmations)
        )
        self.min_hold_sec = max(0.0, float(min_hold_sec))
        self._candidate = normalized
        self._candidate_count = 0
        self._changed_at = time.monotonic()

    def update(
        self,
        candidate: str,
        *,
        now: float,
        panic: bool = False,
    ) -> str:
        target = "PANIC" if panic else str(candidate).upper()
        if target not in REGIMES - {"RECOVERY"}:
            raise ValueError("unknown regime candidate")
        timestamp = float(now)
        if target == "PANIC":
            self.state = "PANIC"
            self._candidate = target
            self._candidate_count = 0
            self._changed_at = timestamp
            return self.state
        if self.state in {"PANIC", "TREND_DOWN"} and target not in {
            "PANIC",
            "TREND_DOWN",
        }:
            self.state = "RECOVERY"
            self._candidate = target
            self._candidate_count = 1
            self._changed_at = timestamp
            return self.state
        required = (
            self.recovery_confirmations
            if self.state == "RECOVERY"
            else self.confirmations
        )
        if target == self.state:
            self._candidate = target
            self._candidate_count = 0
            return self.state
        if target == self._candidate:
            self._candidate_count += 1
        else:
            self._candidate = target
            self._candidate_count = 1
        if (
            self._candidate_count >= required
            and (
                self.min_hold_sec == 0
                or timestamp - self._changed_at >= self.min_hold_sec
            )
        ):
            self.state = target
            self._candidate_count = 0
            self._changed_at = timestamp
        return self.state

    def policy(
        self,
        *,
        trend_up_cap_scale: object = "0.75",
    ) -> RegimePolicy:
        up_scale = exact_decimal(
            trend_up_cap_scale, field="TREND_UP CAP scale"
        )
        if not ZERO <= up_scale <= ONE:
            raise ValueError("TREND_UP CAP scale must be in [0, 1]")
        if self.state == "RANGE":
            return RegimePolicy(self.state, True, ONE)
        if self.state == "TREND_UP":
            return RegimePolicy(self.state, True, up_scale)
        return RegimePolicy(self.state, False, ZERO)
