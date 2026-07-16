"""Минимальный event-driven replay для записанных стаканов и trade prints.

Это отдельный слой над OHLC simulator: он не подменяет Binance, но позволяет
воспроизводимо проверить price/time priority, очередь, отмены, задержку и
rate-limit до подключения реального historical feed.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Iterable


@dataclass(frozen=True)
class BookLevel:
    """Один уровень стакана: цена и доступный объём."""
    price: Decimal
    quantity: Decimal


@dataclass(frozen=True)
class MarketEvent:
    """Снимок стакана и публичных сделок в один момент времени."""
    ts_ms: int
    bids: tuple[BookLevel, ...] = ()
    asks: tuple[BookLevel, ...] = ()
    trades: tuple[tuple[Decimal, Decimal, str], ...] = ()


@dataclass
class ReplayOrder:
    """Локальная заявка, ожидающая исполнения в replay."""
    order_id: str
    side: str
    price: Decimal
    quantity: Decimal
    created_ts: int
    remaining: Decimal = field(init=False)
    cancelled: bool = False
    queue_ahead: Decimal = Decimal("0")

    def __post_init__(self) -> None:
        # Все сравнения стороны ниже выполняются в верхнем регистре.
        self.side = self.side.upper()
        self.remaining = self.quantity


class OrderBookReplay:
    """Упрощённый, но детерминированный matching engine для backtest."""
    def __init__(self, *, latency_ms: int = 0, max_requests_per_minute: int = 1200) -> None:
        self.latency_ms = max(0, int(latency_ms))
        self.max_requests_per_minute = max(1, int(max_requests_per_minute))
        self.orders: list[ReplayOrder] = []
        self._request_times: list[int] = []

    def submit(self, order: ReplayOrder, now_ms: int, *, queue_ahead: Decimal = Decimal("0")) -> None:
        # Задержка имитирует время доставки заявки до биржи.
        self._rate_gate(now_ms)
        order.created_ts = int(now_ms) + self.latency_ms
        order.queue_ahead = max(Decimal("0"), queue_ahead)
        self.orders.append(order)

    def cancel(self, order_id: str, now_ms: int) -> bool:
        # Отмена также расходует API-бюджет и может быть отклонена rate limit.
        self._rate_gate(now_ms)
        for order in self.orders:
            if order.order_id == order_id and not order.cancelled and order.remaining > 0:
                order.cancelled = True
                return True
        return False

    def process(self, event: MarketEvent) -> list[tuple[str, Decimal, Decimal]]:
        fills: list[tuple[str, Decimal, Decimal]] = []
        # Публичные сделки сначала съедают очередь перед нашей заявкой.
        for trade_price, trade_qty, aggressor in event.trades:
            for order in self.orders:
                if order.cancelled or order.created_ts > event.ts_ms:
                    continue
                crosses = (order.side == "BUY" and aggressor.upper() == "SELL" and trade_price <= order.price) or \
                          (order.side == "SELL" and aggressor.upper() == "BUY" and trade_price >= order.price)
                if crosses and order.queue_ahead > 0:
                    order.queue_ahead = max(Decimal("0"), order.queue_ahead - trade_qty)
        # Затем заявки обслуживаются по цене и времени поступления.
        for order in sorted(self.orders, key=lambda item: (item.price, item.created_ts)):
            if order.cancelled or order.remaining <= 0 or order.created_ts > event.ts_ms or order.queue_ahead > 0:
                continue
            levels = event.asks if order.side == "BUY" else event.bids
            for level in levels:
                crosses = level.price <= order.price if order.side == "BUY" else level.price >= order.price
                if not crosses:
                    continue
                qty = min(order.remaining, level.quantity)
                if qty > 0:
                    order.remaining -= qty
                    fills.append((order.order_id, qty, level.price))
                if order.remaining <= 0:
                    break
        return fills

    def _rate_gate(self, now_ms: int) -> None:
        cutoff = int(now_ms) - 60_000
        self._request_times = [ts for ts in self._request_times if ts >= cutoff]
        if len(self._request_times) >= self.max_requests_per_minute:
            raise RuntimeError("replay rate limit exceeded")
        self._request_times.append(int(now_ms))


def load_events(rows: Iterable[dict]) -> list[MarketEvent]:
    """Нормализовать JSON fixture стакана в детерминированные события."""
    result = []
    for row in rows:
        def levels(items):
            return tuple(BookLevel(Decimal(str(item[0])), Decimal(str(item[1]))) for item in items)
        result.append(MarketEvent(int(row["ts_ms"]), levels(row.get("bids", [])), levels(row.get("asks", []))))
    return result
