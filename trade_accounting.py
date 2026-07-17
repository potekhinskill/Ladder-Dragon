# Copyright (c) 2026 IURII Potekhin / Ladder Dragon. All rights reserved.
# Назначение файла и опасные границы логики должны оставаться понятными при сопровождении.
"""Exact trade normalization and average-cost accounting."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Iterable


ZERO = Decimal("0")
KNOWN_QUOTES = ("USDT", "USDC", "FDUSD", "BUSD", "BTC", "ETH", "BNB", "EUR", "TRY")


def decimal(value: object) -> Decimal:
    if isinstance(value, Decimal):
        return value
    if value is None or value == "":
        return ZERO
    return Decimal(str(value))


def decimal_text(value: object) -> str:
    value = decimal(value)
    return format(value, "f")


def base_asset(symbol: str) -> str:
    normalized = symbol.strip().upper()
    for quote in KNOWN_QUOTES:
        if normalized.endswith(quote) and len(normalized) > len(quote):
            return normalized[: -len(quote)]
    raise ValueError(f"cannot determine base asset for {symbol}")


class UnpricedCommission(RuntimeError):
    pass


@dataclass(frozen=True)
class TradeExecution:
    symbol: str
    side: str
    price: Decimal
    gross_qty: Decimal
    net_qty: Decimal
    commission_asset: str
    commission_amount: Decimal
    commission_quote: Decimal | None
    commission_value_status: str

    @classmethod
    def create(
        cls,
        *,
        symbol: str,
        side: str,
        price: object,
        gross_qty: object,
        net_qty: object | None = None,
        commission_asset: str = "",
        commission_amount: object = 0,
        commission_quote: object | None = 0,
        commission_value_status: str = "exact",
    ) -> "TradeExecution":
        normalized_side = side.strip().upper()
        if normalized_side not in {"BUY", "SELL"}:
            raise ValueError(f"unsupported trade side: {side}")
        normalized_symbol = symbol.strip().upper()
        px = decimal(price)
        gross = decimal(gross_qty)
        amount = decimal(commission_amount)
        asset = commission_asset.strip().upper()
        if px <= ZERO or gross <= ZERO or amount < ZERO:
            raise ValueError("price/gross quantity must be positive and commission non-negative")
        if net_qty is None:
            net = gross
            if amount > ZERO and asset == base_asset(normalized_symbol):
                net = gross - amount if normalized_side == "BUY" else gross + amount
        else:
            net = decimal(net_qty)
        if net <= ZERO:
            raise ValueError("net inventory quantity must be positive")
        quote_value = None if commission_quote is None else decimal(commission_quote)
        if quote_value is not None and quote_value < ZERO:
            raise ValueError("commission quote value must be non-negative")
        status = commission_value_status.strip().lower() or "unpriced"
        return cls(
            symbol=normalized_symbol,
            side=normalized_side,
            price=px,
            gross_qty=gross,
            net_qty=net,
            commission_asset=asset,
            commission_amount=amount,
            commission_quote=quote_value,
            commission_value_status=status,
        )

    def valued_commission(self, *, allow_unpriced: bool = False) -> Decimal:
        if self.commission_quote is None:
            if self.commission_amount > ZERO:
                if allow_unpriced:
                    return ZERO
                raise UnpricedCommission(
                    f"unpriced {self.commission_asset or 'unknown'} commission "
                    f"for {self.symbol} {self.side}"
                )
            return ZERO
        return self.commission_quote

    def cash_fee_quote(self, *, allow_unpriced: bool = False) -> Decimal:
        fee = self.valued_commission(allow_unpriced=allow_unpriced)
        if self.commission_amount > ZERO and self.commission_asset == base_asset(self.symbol):
            # Base commission is already represented by net_qty. Adding its quote
            # value again would double-count the fee.
            return ZERO
        return fee

    def buy_cost_quote(self, *, allow_unpriced: bool = False) -> Decimal:
        return self.price * self.gross_qty + self.cash_fee_quote(allow_unpriced=allow_unpriced)

    def sell_proceeds_quote(self, *, allow_unpriced: bool = False) -> Decimal:
        return self.price * self.gross_qty - self.cash_fee_quote(allow_unpriced=allow_unpriced)


@dataclass(frozen=True)
class InventoryResult:
    qty: Decimal
    avg_cost: Decimal
    realized_pnl: Decimal
    sell_results: tuple[Decimal, ...]


def replay_average_cost(
    trades: Iterable[TradeExecution], *, allow_unpriced: bool = False
) -> InventoryResult:
    qty = ZERO
    avg = ZERO
    realized = ZERO
    sell_results: list[Decimal] = []
    for trade in trades:
        if trade.side == "BUY":
            new_qty = qty + trade.net_qty
            total_cost = avg * qty + trade.buy_cost_quote(allow_unpriced=allow_unpriced)
            qty = new_qty
            avg = total_cost / new_qty
            continue

        used = min(qty, trade.net_qty)
        if used <= ZERO:
            sell_results.append(ZERO)
            continue
        ratio = used / trade.net_qty
        proceeds = trade.sell_proceeds_quote(allow_unpriced=allow_unpriced) * ratio
        result = proceeds - avg * used
        realized += result
        sell_results.append(result)
        qty -= used
        if qty <= ZERO:
            qty, avg = ZERO, ZERO
    return InventoryResult(qty, avg, realized, tuple(sell_results))
