# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: implement the trade accounting component of the execution layer.
"""Exact trade normalization and average-cost accounting."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Iterable


ZERO = Decimal("0")
VALUED_COMMISSION_STATUSES = frozenset(
    {
        "basis-import",
        "converted",
        "exact",
        "legacy",
        "none",
        "not_applicable",
        "quote",
    }
)
KNOWN_QUOTES = (
    "FDUSD",
    "USDT",
    "USDC",
    "TUSD",
    "BUSD",
    "BTC",
    "ETH",
    "BNB",
    "EUR",
    "GBP",
    "AUD",
    "BRL",
    "JPY",
    "DAI",
    "TRY",
)


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


class InventoryShortfall(RuntimeError):
    pass


def commission_status_is_valued(status: object) -> bool:
    """Return true only for recognized commission-value provenance."""
    return str(status).strip().lower() in VALUED_COMMISSION_STATUSES


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
        commission_quote: object | None = None,
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
        if amount > ZERO and quote_value is None:
            status = "unpriced"
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
        valued_status = commission_status_is_valued(
            self.commission_value_status
        )
        if self.commission_amount > ZERO and (
            self.commission_quote is None or not valued_status
        ):
            if allow_unpriced:
                return ZERO
            raise UnpricedCommission(
                f"unpriced {self.commission_asset or 'unknown'} commission "
                f"for {self.symbol} {self.side}"
            )
        if self.commission_quote is None:
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


@dataclass(frozen=True)
class FifoLotCost:
    """Represent one remaining FIFO quantity and its exact unit cost."""

    qty: Decimal
    unit_cost: Decimal


@dataclass(frozen=True)
class FifoConsumption:
    """Describe one read-only FIFO SELL allocation plan."""

    result: Decimal
    allocations: tuple[Decimal, ...]


def fifo_sell_consumption(
    lots: Iterable[FifoLotCost],
    trade: TradeExecution,
    *,
    allow_unpriced: bool = False,
    strict_inventory: bool = True,
) -> FifoConsumption:
    """Plan one FIFO SELL without changing the supplied lot state."""
    if trade.side != "SELL":
        raise ValueError("FIFO consumption requires a SELL trade")
    remaining = trade.net_qty
    proceeds = trade.sell_proceeds_quote(allow_unpriced=allow_unpriced)
    result = ZERO
    allocations: list[Decimal] = []
    for lot in lots:
        if remaining <= ZERO:
            break
        if lot.qty <= ZERO or lot.unit_cost <= ZERO:
            raise ValueError("FIFO lot quantity and unit cost must be positive")
        used = min(remaining, lot.qty)
        result += proceeds * used / trade.net_qty - lot.unit_cost * used
        allocations.append(used)
        remaining -= used
    if strict_inventory and remaining > ZERO:
        raise InventoryShortfall(
            f"SELL quantity exceeds replay inventory for {trade.symbol}"
        )
    return FifoConsumption(result=result, allocations=tuple(allocations))


def replay_average_cost(
    trades: Iterable[TradeExecution],
    *,
    allow_unpriced: bool = False,
    strict_inventory: bool = True,
) -> InventoryResult:
    """Replay average cost, rejecting SELL inventory gaps by default."""
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

        if strict_inventory and trade.net_qty > qty:
            raise InventoryShortfall(
                f"SELL quantity exceeds replay inventory for {trade.symbol}"
            )
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


def replay_fifo(
    trades: Iterable[TradeExecution],
    *,
    allow_unpriced: bool = False,
    strict_inventory: bool = True,
) -> InventoryResult:
    """Replay exact first-in, first-out lots and return each SELL result."""
    lots: list[list[Decimal]] = []
    realized = ZERO
    sell_results: list[Decimal] = []
    for trade in trades:
        if trade.side == "BUY":
            cost = trade.buy_cost_quote(allow_unpriced=allow_unpriced)
            lots.append([trade.net_qty, cost / trade.net_qty])
            continue

        consumption = fifo_sell_consumption(
            (FifoLotCost(lot[0], lot[1]) for lot in lots),
            trade,
            allow_unpriced=allow_unpriced,
            strict_inventory=strict_inventory,
        )
        result = consumption.result
        for take in consumption.allocations:
            lot_qty = lots[0][0] - take
            if lot_qty <= ZERO:
                lots.pop(0)
            else:
                lots[0][0] = lot_qty
        realized += result
        sell_results.append(result)

    qty = sum((lot[0] for lot in lots), ZERO)
    cost = sum((lot[0] * lot[1] for lot in lots), ZERO)
    avg = cost / qty if qty > ZERO else ZERO
    return InventoryResult(qty, avg, realized, tuple(sell_results))
