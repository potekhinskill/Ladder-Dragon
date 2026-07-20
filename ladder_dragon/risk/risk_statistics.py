# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: implement the risk statistics component of the risk layer.
"""Pure portfolio statistics used by risk checks and stress tests."""

from __future__ import annotations

from math import sqrt
from statistics import NormalDist
from typing import Iterable, Mapping, Sequence
from decimal import Decimal, InvalidOperation
import json
from pathlib import Path


ZERO = Decimal("0")


def _decimal(value: object, *, field: str) -> Decimal:
    try:
        result = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValueError(f"{field} is not a decimal") from exc
    if not result.is_finite():
        raise ValueError(f"{field} must be finite")
    return result


def log_returns(prices: Sequence[float]) -> list[float]:
    """Handle log returns."""
    result: list[float] = []
    for previous, current in zip(prices, prices[1:]):
        if previous <= 0 or current <= 0:
            continue
        result.append(current / previous - 1.0)
    return result


def rolling_correlation(
    left: Sequence[float], right: Sequence[float], *, window: int = 48
) -> float:
    """Pearson correlation of recent returns; 0 means insufficient evidence."""
    values_left = log_returns(left)[-window:]
    values_right = log_returns(right)[-window:]
    size = min(len(values_left), len(values_right))
    if size < 3:
        return 0.0
    values_left = values_left[-size:]
    values_right = values_right[-size:]
    mean_left = sum(values_left) / size
    mean_right = sum(values_right) / size
    covariance = sum(
        (a - mean_left) * (b - mean_right)
        for a, b in zip(values_left, values_right)
    )
    variance_left = sum((a - mean_left) ** 2 for a in values_left)
    variance_right = sum((b - mean_right) ** 2 for b in values_right)
    denominator = sqrt(variance_left * variance_right)
    return covariance / denominator if denominator > 0 else 0.0


def correlated_symbols(
    histories: Mapping[str, Sequence[float]],
    *,
    threshold: float = 0.70,
    window: int = 48,
) -> set[str]:
    """Return symbols belonging to a positively correlated exposure cluster."""
    names = [str(name).upper() for name in histories]
    correlated: set[str] = set()
    for index, left_name in enumerate(names):
        for right_name in names[index + 1 :]:
            correlation = rolling_correlation(
                histories[left_name], histories[right_name], window=window
            )
            if correlation >= threshold:
                correlated.update((left_name, right_name))
    return correlated


def stress_exposure(exposure_usdt: float, shocks: Iterable[float]) -> list[float]:
    """Mark-to-market exposure after simultaneous percentage shocks."""
    return [exposure_usdt * (1.0 + float(shock)) for shock in shocks]


def correlated_symbols_multi_window(
    histories: Mapping[str, Sequence[float]], *, threshold: float = 0.70,
    windows: Sequence[int] = (24, 48, 96), min_windows: int = 2,
) -> set[str]:
    """Handle correlated symbols multi window."""
    names = [str(name).upper() for name in histories]
    result: set[str] = set()
    for i, left in enumerate(names):
        for right in names[i + 1:]:
            hits = sum(rolling_correlation(histories[left], histories[right], window=w) >= threshold for w in windows)
            if hits >= min_windows:
                result.update((left, right))
    return result


def covariance_var(
    exposures: Mapping[str, float], histories: Mapping[str, Sequence[float]],
    *, confidence: float = 0.99, horizon: int = 1,
) -> float:
    """Handle covariance var."""
    names = [name for name, value in exposures.items() if value > 0 and name in histories]
    if len(names) < 1:
        return 0.0
    # Equal series lengths are required for a valid covariance matrix.
    returns = {name: log_returns(histories[name])[-96:] for name in names}
    n = min((len(values) for values in returns.values()), default=0)
    if n < 3:
        return 0.0
    aligned = {name: values[-n:] for name, values in returns.items()}
    means = {name: sum(values) / n for name, values in aligned.items()}
    variances = {name: sum((v - means[name]) ** 2 for v in aligned[name]) / (n - 1) for name in names}
    sigma2 = 0.0
    for left in names:
        for right in names:
            cov = sum((aligned[left][i] - means[left]) * (aligned[right][i] - means[right]) for i in range(n)) / (n - 1)
            sigma2 += exposures[left] * exposures[right] * cov
    sigma = sqrt(max(0.0, sigma2)) * sqrt(max(1, horizon))
    return float(NormalDist().inv_cdf(confidence) * sigma)


def stress_loss(exposures: Mapping[str, float], *, price_shock: float = -0.05, spread_widening: float = 0.01) -> float:
    """Handle stress loss."""
    return float(stress_loss_decimal(
        exposures, price_shock=price_shock, spread_widening=spread_widening
    ))


def stress_loss_decimal(
    exposures: Mapping[str, object], *, price_shock: object = "-0.05",
    spread_widening: object = "0.01",
) -> Decimal:
    """Return an exact quote-currency stress loss."""
    gross = sum(
        (max(ZERO, _decimal(value, field="exposure")) for value in exposures.values()),
        ZERO,
    )
    shock = max(ZERO, -_decimal(price_shock, field="price shock"))
    spread = max(ZERO, _decimal(spread_widening, field="spread widening"))
    return gross * (shock + spread)


def expected_shortfall(losses: Sequence[float], *, confidence: float = 0.99) -> float:
    """Handle expected shortfall."""
    values = sorted(max(0.0, float(value)) for value in losses)
    if not values or not 0 < confidence < 1:
        return 0.0
    cutoff = max(0, int(len(values) * confidence))
    tail = values[cutoff:] or values[-1:]
    return sum(tail) / len(tail)


def marginal_risk_contribution(exposures: Mapping[str, float], *, shock: float = 0.05) -> dict[str, float]:
    """Handle marginal risk contribution."""
    return {symbol: max(0.0, float(value)) * max(0.0, shock) for symbol, value in exposures.items()}


def marginal_risk_contribution_decimal(
    exposures: Mapping[str, object], *, shock: object = "0.05",
) -> dict[str, Decimal]:
    """Return exact quote-currency contributions for a fixed shock."""
    shock_exact = max(ZERO, _decimal(shock, field="risk shock"))
    return {
        symbol: max(ZERO, _decimal(value, field="exposure")) * shock_exact
        for symbol, value in exposures.items()
    }


def conversion_price(*, asset_qty: float, side: str, bids: Sequence[tuple[float, float]],
                     asks: Sequence[tuple[float, float]], fee_pct: float = 0.0,
                     min_depth_ratio: float = 1.0) -> float:
    """Handle conversion price."""
    return float(conversion_price_decimal(
        asset_qty=asset_qty, side=side, bids=bids, asks=asks,
        fee_pct=fee_pct, min_depth_ratio=min_depth_ratio,
    ))


def conversion_price_decimal(
    *, asset_qty: object, side: str,
    bids: Sequence[tuple[object, object]], asks: Sequence[tuple[object, object]],
    fee_pct: object = "0", min_depth_ratio: object = "1",
) -> Decimal:
    """Calculate an exact volume-weighted conversion price from book depth."""
    levels = bids if side.upper() == "SELL" else asks
    total_quantity = max(ZERO, _decimal(asset_qty, field="asset quantity"))
    remaining = total_quantity
    notional = ZERO
    normalized = [
        (_decimal(price, field="book price"), max(ZERO, _decimal(qty, field="book quantity")))
        for price, qty in levels
    ]
    available = sum((qty for _, qty in normalized), ZERO)
    depth_ratio = max(Decimal("1"), _decimal(min_depth_ratio, field="minimum depth ratio"))
    if remaining <= ZERO or available < remaining * depth_ratio:
        raise ValueError("insufficient conversion-book depth")
    for price, quantity in normalized:
        used = min(remaining, quantity)
        notional += used * price
        remaining -= used
        if remaining <= ZERO:
            break
    if remaining > ZERO:
        raise ValueError("conversion book exhausted")
    fee_multiplier = max(ZERO, Decimal("1") - _decimal(fee_pct, field="conversion fee"))
    return notional * fee_multiplier / total_quantity


def allocate_cap_by_marginal_risk(total_cap: float, contributions: Mapping[str, float],
                                  minimum_cap: float = 0.0) -> dict[str, float]:
    """Return a legacy numeric view of exact marginal-risk allocation."""
    return {
        symbol: float(value)
        for symbol, value in allocate_cap_by_marginal_risk_decimal(
            total_cap, contributions, minimum_cap=minimum_cap
        ).items()
    }


def allocate_cap_by_marginal_risk_decimal(
    total_cap: object,
    contributions: Mapping[str, object],
    *,
    minimum_cap: object = "0",
) -> dict[str, Decimal]:
    """Allocate exact quote CAP inversely to marginal risk contributions."""
    total = max(ZERO, _decimal(total_cap, field="total CAP"))
    floor = max(ZERO, _decimal(minimum_cap, field="minimum CAP"))
    epsilon = Decimal("0.000000000001")
    weights = {
        symbol: Decimal("1") / max(
            _decimal(value, field=f"{symbol} marginal contribution"), epsilon
        )
        for symbol, value in contributions.items()
    }
    denominator = sum(weights.values(), ZERO)
    if denominator <= ZERO:
        return {symbol: floor for symbol in weights}
    return {
        symbol: max(floor, total * weight / denominator)
        for symbol, weight in weights.items()
    }


def load_tail_losses(path: str | Path) -> list[float]:
    """Load tail losses."""
    source = Path(path)
    if source.suffix.lower() == ".jsonl":
        return [float(json.loads(line)["loss"]) for line in source.read_text().splitlines() if line.strip()]
    payload = json.loads(source.read_text())
    values = payload.get("losses", payload) if isinstance(payload, (dict, list)) else []
    return [float(value) for value in values]
