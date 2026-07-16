"""Минимальный event-driven replay для записанных стаканов и trade prints.

Это отдельный слой над OHLC simulator: он не подменяет Binance, но позволяет
воспроизводимо проверить price/time priority, очередь, отмены, задержку и
rate-limit до подключения реального historical feed.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Iterable
import json
from pathlib import Path


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
    # Идентификаторы внешних заявок, снятых биржей/участником в этом тике.
    cancelled_order_ids: tuple[str, ...] = ()
    event_type: str = "depthUpdate"
    exchange_order_updates: tuple[dict, ...] = ()


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
    def __init__(self, *, latency_ms: int = 0, max_requests_per_minute: int = 1200,
                 maker_fee_pct: Decimal = Decimal("0.00075"), taker_fee_pct: Decimal = Decimal("0.001"),
                 market_impact_bps: Decimal = Decimal("0")) -> None:
        self.latency_ms = max(0, int(latency_ms))
        self.max_requests_per_minute = max(1, int(max_requests_per_minute))
        self.maker_fee_pct = Decimal(str(maker_fee_pct))
        self.taker_fee_pct = Decimal(str(taker_fee_pct))
        self.market_impact_bps = Decimal(str(market_impact_bps))
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
        # Внешние отмены меняют очередь до matching текущего события.
        for order in self.orders:
            if order.order_id in event.cancelled_order_ids:
                order.cancelled = True
        for update in event.exchange_order_updates:
            for order in self.orders:
                if str(update.get("orderId")) != order.order_id:
                    continue
                if str(update.get("status", "")).upper() in {"CANCELED", "EXPIRED", "REJECTED"}:
                    order.cancelled = True
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
                    impact = self.market_impact_bps / Decimal("100000")
                    fill_price = level.price * (Decimal("1") + impact if order.side == "BUY" else Decimal("1") - impact)
                    fills.append((order.order_id, qty, fill_price))
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
        result.append(MarketEvent(
            int(row.get("ts_ms", row.get("E", 0))), levels(row.get("bids", [])), levels(row.get("asks", [])),
            tuple(tuple(item) for item in row.get("trades", [])), tuple(str(item) for item in row.get("cancelled_order_ids", [])),
            str(row.get("event_type", row.get("e", "depthUpdate"))), tuple(row.get("exchange_order_updates", [])),
        ))
    return result


def load_jsonl_archive(path: str | Path) -> list[MarketEvent]:
    """Загрузить сохранённый Binance depth/trade/executionReport JSONL архив."""
    events: list[MarketEvent] = []
    with Path(path).open(encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                events.extend(load_events([json.loads(line)]))
    return sorted(events, key=lambda event: event.ts_ms)
