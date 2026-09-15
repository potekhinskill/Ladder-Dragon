# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: check causal reference prices without attesting historical fee ownership.
"""Pure valuation prerequisite, not an importer or selection authorization.

The caller must establish source authenticity and bind fee units to a fill.
A syntactically valid source reference alone proves neither fact.
"""

from dataclasses import dataclass
from decimal import Decimal
import re

from ladder_dragon.execution.buy_settlement import _amount
from ladder_dragon.execution.trade_accounting import symbol_assets
from ladder_dragon.strategy.prediction.historical_commission import exact_arithmetic


@dataclass(frozen=True)
class CausalCommission:
    quote_value: Decimal | None
    reason: str
    source_sha256: str | None = None


@exact_arithmetic
def value_bnb_commission(*, symbol, commission_amount, fill_time_ms,
                         max_age_ms, price_evidence) -> CausalCommission:
    """Value exact BNB units against one strictly earlier direct-market price.

    No inverse conversion, network fallback, inferred fee rate, or same-time
    ordering is allowed. Freshness starts at market time, not receipt time.
    Malformed request arguments raise; unusable evidence returns unknown.
    """
    amount = _amount(commission_amount)
    if (not isinstance(symbol, str) or symbol != symbol.strip().upper()
            or len(symbol) > 40):
        raise ValueError("invalid commission market")
    _, quote = symbol_assets(symbol)
    if quote == "BNB":
        raise ValueError("BNB quote fees require no conversion")
    if (type(fill_time_ms) is not int or fill_time_ms <= 0
            or type(max_age_ms) is not int or max_age_ms <= 0):
        raise ValueError("invalid commission temporal boundary")
    fields = {"symbol", "price", "market_time_ms", "available_at_ms", "source_sha256"}
    if not isinstance(price_evidence, dict) or set(price_evidence) != fields:
        return CausalCommission(None, "PRICE_SCHEMA_INVALID")
    if price_evidence["symbol"] != "BNB" + quote:
        return CausalCommission(None, "PRICE_MARKET_MISMATCH")
    reference = price_evidence["source_sha256"]
    if not isinstance(reference, str) or re.fullmatch(r"[0-9a-f]{64}", reference) is None:
        return CausalCommission(None, "PRICE_SOURCE_INVALID")
    market, available = price_evidence["market_time_ms"], price_evidence["available_at_ms"]
    if type(market) is not int or type(available) is not int or not 0 < market <= available:
        return CausalCommission(None, "PRICE_TIME_INVALID")
    # A same-millisecond observation has no proven order relative to the fill.
    if available >= fill_time_ms:
        return CausalCommission(None, "PRICE_NOT_AVAILABLE_BEFORE_FILL")
    if fill_time_ms - market >= max_age_ms:
        return CausalCommission(None, "PRICE_STALE")
    try:
        price = _amount(price_evidence["price"], positive=True)
    except ValueError:
        return CausalCommission(None, "PRICE_VALUE_INVALID")
    return CausalCommission(amount * price, "CAUSAL_REFERENCE_ONLY", reference)
