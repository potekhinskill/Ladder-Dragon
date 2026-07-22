# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: implement the market replay component of the strategy layer.
"""Ladder Dragon market replay support."""
from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Iterable, Mapping, NamedTuple
import json
import hashlib
from pathlib import Path


@dataclass(frozen=True)
class BookLevel:
    """Represent BookLevel."""
    price: Decimal
    quantity: Decimal


@dataclass(frozen=True)
class MarketEvent:
    """Represent MarketEvent."""
    ts_ms: int
    bids: tuple[BookLevel, ...] = ()
    asks: tuple[BookLevel, ...] = ()
    trades: tuple[tuple[Decimal, Decimal, str], ...] = ()
    # External order IDs canceled by the exchange or another participant in this tick.
    cancelled_order_ids: tuple[str, ...] = ()
    event_type: str = "depthUpdate"
    exchange_order_updates: tuple[dict, ...] = ()
    received_ts_ms: int | None = None


@dataclass
class ReplayOrder:
    """Represent ReplayOrder."""
    order_id: str
    side: str
    price: Decimal
    quantity: Decimal
    created_ts: int
    remaining: Decimal = field(init=False)
    cancelled: bool = False
    queue_ahead: Decimal | None = None
    arrival_checked: bool = False

    def __post_init__(self) -> None:
        # All side comparisons below use uppercase values.
        self.side = self.side.upper()
        if self.side not in {"BUY", "SELL"}:
            raise ValueError("replay order side must be BUY or SELL")
        if self.price <= 0 or self.quantity <= 0:
            raise ValueError("replay order price and quantity must be positive")
        self.remaining = self.quantity


class ReplayFill(NamedTuple):
    """Deterministic replay fill with explicit fee and liquidity role."""

    order_id: str
    quantity: Decimal
    price: Decimal
    fee_quote: Decimal
    liquidity: str


class OrderBookReplay:
    """Represent OrderBookReplay."""
    def __init__(self, *, latency_ms: int = 0, max_requests_per_minute: int = 1200,
                 maker_fee_pct: Decimal = Decimal("0.00075"), taker_fee_pct: Decimal = Decimal("0.001"),
                 market_impact_bps: Decimal = Decimal("0"),
                 queue_cancellation_ahead_ratio: Decimal = Decimal("0.5"),
                 volume_impact_scale: Decimal = Decimal("1")) -> None:
        self.latency_ms = max(0, int(latency_ms))
        self.max_requests_per_minute = max(1, int(max_requests_per_minute))
        self.maker_fee_pct = Decimal(str(maker_fee_pct))
        self.taker_fee_pct = Decimal(str(taker_fee_pct))
        self.market_impact_bps = Decimal(str(market_impact_bps))
        self.queue_cancellation_ahead_ratio = Decimal(
            str(queue_cancellation_ahead_ratio)
        )
        self.volume_impact_scale = Decimal(str(volume_impact_scale))
        if min(self.maker_fee_pct, self.taker_fee_pct, self.market_impact_bps) < 0:
            raise ValueError("replay fees and market impact must be non-negative")
        if not Decimal("0") <= self.queue_cancellation_ahead_ratio <= Decimal("1"):
            raise ValueError("queue cancellation ratio must be in [0,1]")
        if self.volume_impact_scale < 0:
            raise ValueError("volume impact scale must be non-negative")
        self.orders: list[ReplayOrder] = []
        self._request_times: list[int] = []
        self._previous_bids: dict[Decimal, Decimal] = {}
        self._previous_asks: dict[Decimal, Decimal] = {}

    def submit(
        self,
        order: ReplayOrder,
        now_ms: int,
        *,
        queue_ahead: Decimal | None = None,
    ) -> None:
        # Delay simulates order delivery time to the exchange.
        self._rate_gate(now_ms)
        order.created_ts = int(now_ms) + self.latency_ms
        order.queue_ahead = (
            None
            if queue_ahead is None
            else max(Decimal("0"), Decimal(str(queue_ahead)))
        )
        self.orders.append(order)

    def cancel(self, order_id: str, now_ms: int) -> bool:
        # Cancellation also consumes API budget and may be rejected by a rate limit.
        self._rate_gate(now_ms)
        for order in self.orders:
            if order.order_id == order_id and not order.cancelled and order.remaining > 0:
                order.cancelled = True
                self._transfer_public_queue(order)
                return True
        return False

    @staticmethod
    def _priority(order: ReplayOrder, sequence: int) -> tuple[int, Decimal, int, int]:
        return (
            0 if order.side == "BUY" else 1,
            -order.price if order.side == "BUY" else order.price,
            order.created_ts,
            sequence,
        )

    def _eligible(self, side: str, event: MarketEvent) -> list[ReplayOrder]:
        indexed = [
            (sequence, order)
            for sequence, order in enumerate(self.orders)
            if order.side == side
            and not order.cancelled
            and order.remaining > 0
            and order.created_ts <= event.ts_ms
        ]
        return [
            order
            for sequence, order in sorted(
                indexed, key=lambda item: self._priority(item[1], item[0])
            )
        ]

    def process(self, event: MarketEvent) -> list[ReplayFill]:
        fills: list[ReplayFill] = []
        current_bids = {level.price: level.quantity for level in event.bids}
        current_asks = {level.price: level.quantity for level in event.asks}
        # A depth reduction at our passive price may be a cancellation ahead
        # of us. Only the configured conservative fraction advances our queue;
        # public depth cannot prove whose order disappeared.
        for order in self.orders:
            queue_ahead = order.queue_ahead or Decimal("0")
            if order.cancelled or queue_ahead <= 0:
                continue
            previous = (
                self._previous_bids if order.side == "BUY" else self._previous_asks
            )
            current = current_bids if order.side == "BUY" else current_asks
            reduced = max(
                Decimal("0"),
                previous.get(order.price, Decimal("0"))
                - current.get(order.price, Decimal("0")),
            )
            if reduced > 0:
                order.queue_ahead = max(
                    Decimal("0"),
                    queue_ahead
                    - reduced * self.queue_cancellation_ahead_ratio,
                )
        # External cancellations change the queue before matching the current event.
        for order in self.orders:
            if order.order_id in event.cancelled_order_ids:
                order.cancelled = True
                self._transfer_public_queue(order)
        for update in event.exchange_order_updates:
            for order in self.orders:
                if str(update.get("orderId")) != order.order_id:
                    continue
                if str(update.get("status", "")).upper() in {"CANCELED", "EXPIRED", "REJECTED"}:
                    order.cancelled = True
                    self._transfer_public_queue(order)

        # An order can consume displayed liquidity as taker only once, when it
        # reaches the venue. A resting order is never reclassified by a later
        # depth movement; it then needs a public trade at its exact price.
        available = {
            "BUY": [[price, quantity] for price, quantity in sorted(current_asks.items())],
            "SELL": [[price, quantity] for price, quantity in sorted(current_bids.items(), reverse=True)],
        }
        impact_divisor = Decimal("10000")
        for side in ("BUY", "SELL"):
            for order in self._eligible(side, event):
                if order.arrival_checked:
                    continue
                order.arrival_checked = True
                for level in available[side]:
                    level_price, level_quantity = level
                    crosses = (
                        level_price <= order.price
                        if side == "BUY"
                        else level_price >= order.price
                    )
                    if not crosses:
                        break
                    if level_quantity <= 0:
                        continue
                    quantity = min(order.remaining, level_quantity)
                    level[1] -= quantity
                    order.remaining -= quantity
                    participation = quantity / max(level_quantity, quantity)
                    dynamic_impact_bps = self.market_impact_bps * (
                        Decimal("1") + self.volume_impact_scale * participation
                    )
                    impact = dynamic_impact_bps / impact_divisor
                    fill_price = level_price * (
                        Decimal("1") + impact
                        if side == "BUY"
                        else Decimal("1") - impact
                    )
                    fee = fill_price * quantity * self.taker_fee_pct
                    fills.append(ReplayFill(
                        order.order_id, quantity, fill_price, fee, "TAKER"
                    ))
                    opposite = current_asks if side == "BUY" else current_bids
                    opposite[level_price] = max(
                        Decimal("0"), opposite.get(level_price, Decimal("0")) - quantity
                    )
                    if opposite[level_price] == 0:
                        opposite.pop(level_price)
                    if order.remaining <= 0:
                        break
                if order.remaining > 0 and order.queue_ahead is None:
                    own_side = current_bids if side == "BUY" else current_asks
                    earlier_local = any(
                        candidate is not order
                        and candidate.side == order.side
                        and candidate.price == order.price
                        and candidate.arrival_checked
                        and not candidate.cancelled
                        and candidate.remaining > 0
                        for candidate in self.orders
                    )
                    order.queue_ahead = (
                        Decimal("0")
                        if earlier_local
                        else own_side.get(order.price, Decimal("0"))
                    )

        # A public trade has one shared quantity. It first consumes the public
        # FIFO queue and then local orders at exactly that reported price.
        for trade_price, trade_qty, aggressor in event.trades:
            trade_price = Decimal(str(trade_price))
            available_trade = Decimal(str(trade_qty))
            aggressor = str(aggressor).upper()
            passive_side = (
                "BUY" if aggressor == "SELL"
                else "SELL" if aggressor == "BUY"
                else ""
            )
            if not passive_side or available_trade <= 0:
                continue
            for order in self._eligible(passive_side, event):
                if not order.arrival_checked or trade_price != order.price:
                    continue
                queue_ahead = order.queue_ahead or Decimal("0")
                queued = min(queue_ahead, available_trade)
                order.queue_ahead = queue_ahead - queued
                available_trade -= queued
                if available_trade <= 0:
                    break
                quantity = min(order.remaining, available_trade)
                order.remaining -= quantity
                available_trade -= quantity
                fee = trade_price * quantity * self.maker_fee_pct
                fills.append(ReplayFill(
                    order.order_id, quantity, trade_price, fee, "MAKER"
                ))
                if available_trade <= 0:
                    break
            passive_book = current_bids if passive_side == "BUY" else current_asks
            if trade_price in passive_book:
                passive_book[trade_price] = max(
                    Decimal("0"), passive_book[trade_price] - Decimal(str(trade_qty))
                )
                if passive_book[trade_price] == 0:
                    passive_book.pop(trade_price)
        self._previous_bids = current_bids
        self._previous_asks = current_asks
        return fills

    def _transfer_public_queue(self, cancelled: ReplayOrder) -> None:
        queued = cancelled.queue_ahead or Decimal("0")
        if queued <= 0:
            return
        cancelled.queue_ahead = Decimal("0")
        for order in self.orders:
            if (
                order is not cancelled
                and order.side == cancelled.side
                and order.price == cancelled.price
                and order.arrival_checked
                and not order.cancelled
                and order.remaining > 0
            ):
                order.queue_ahead = (order.queue_ahead or Decimal("0")) + queued
                return

    def _rate_gate(self, now_ms: int) -> None:
        cutoff = int(now_ms) - 60_000
        self._request_times = [ts for ts in self._request_times if ts >= cutoff]
        if len(self._request_times) >= self.max_requests_per_minute:
            raise RuntimeError("replay rate limit exceeded")
        self._request_times.append(int(now_ms))


def load_events(rows: Iterable[dict]) -> list[MarketEvent]:
    """Load events."""
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
    """Load normalized or raw Binance snapshot/depth/trade JSONL safely.

    Raw depth diffs are accepted only after a snapshot. Sequence gaps abort the
    load so calibration cannot silently use a corrupted order book.
    """
    bids: dict[Decimal, Decimal] = {}
    asks: dict[Decimal, Decimal] = {}
    last_update_id: int | None = None
    events: list[MarketEvent] = []

    def update_side(side: dict[Decimal, Decimal], rows: object) -> None:
        if not isinstance(rows, list):
            raise ValueError("archive book side must be a list")
        for item in rows:
            if not isinstance(item, (list, tuple)) or len(item) < 2:
                raise ValueError("archive book level is malformed")
            price = Decimal(str(item[0]))
            quantity = Decimal(str(item[1]))
            if price <= 0 or quantity < 0:
                raise ValueError("archive book level is invalid")
            if quantity == 0:
                side.pop(price, None)
            else:
                side[price] = quantity

    def current_levels(side: Mapping[Decimal, Decimal], reverse: bool):
        prices = sorted(side, reverse=reverse)[:100]
        return tuple(BookLevel(price, side[price]) for price in prices)

    with Path(path).open(encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            payload = json.loads(line)
            if not isinstance(payload, dict):
                raise ValueError(f"archive line {line_number} is not an object")
            row = payload.get("data", payload)
            if not isinstance(row, dict):
                raise ValueError(f"archive line {line_number} data is invalid")
            event_type = str(row.get("e", row.get("event_type", "")))
            ts_ms = int(row.get("E", row.get("T", row.get("ts_ms", 0))))

            # REST/WebSocket snapshot fixture.
            if "lastUpdateId" in row and "bids" in row and "asks" in row:
                bids.clear()
                asks.clear()
                update_side(bids, row["bids"])
                update_side(asks, row["asks"])
                last_update_id = int(row["lastUpdateId"])
                events.append(MarketEvent(
                    ts_ms,
                    current_levels(bids, True),
                    current_levels(asks, False),
                    event_type="depthSnapshot",
                    received_ts_ms=int(row.get("_received_at_ms", 0)) or None,
                ))
                continue

            is_depth_diff = event_type == "depthUpdate" or (
                "U" in row
                and "u" in row
                and ("b" in row or "a" in row)
            )
            if is_depth_diff:
                if last_update_id is None:
                    raise ValueError(
                        f"depth diff before snapshot at line {line_number}"
                    )
                first_id = int(row.get("U", row.get("u", 0)))
                final_id = int(row.get("u", first_id))
                previous_id = row.get("pu")
                if final_id <= last_update_id:
                    continue
                contiguous = first_id <= last_update_id + 1 <= final_id
                if previous_id is not None:
                    contiguous = contiguous and int(previous_id) == last_update_id
                if not contiguous:
                    raise ValueError(
                        f"depth sequence gap at line {line_number}: "
                        f"last={last_update_id} U={first_id} u={final_id}"
                    )
                update_side(bids, row.get("b", []))
                update_side(asks, row.get("a", []))
                last_update_id = final_id
                events.append(MarketEvent(
                    ts_ms,
                    current_levels(bids, True),
                    current_levels(asks, False),
                    event_type="depthUpdate",
                    received_ts_ms=int(row.get("_received_at_ms", 0)) or None,
                ))
                continue

            trades: tuple[tuple[Decimal, Decimal, str], ...] = ()
            updates: tuple[dict, ...] = ()
            if event_type in {"aggTrade", "trade"}:
                aggressor = "SELL" if bool(row.get("m")) else "BUY"
                trades = ((
                    Decimal(str(row["p"])),
                    Decimal(str(row["q"])),
                    aggressor,
                ),)
            elif event_type == "executionReport":
                updates = (dict(row),)
            elif "bids" in row or "asks" in row:
                # Existing normalized fixtures are full snapshots.
                update_side(bids, row.get("bids", []))
                update_side(asks, row.get("asks", []))
                trades = tuple(
                    (
                        Decimal(str(item[0])),
                        Decimal(str(item[1])),
                        str(item[2]),
                    )
                    for item in row.get("trades", [])
                )
                updates = tuple(row.get("exchange_order_updates", []))
            else:
                raise ValueError(
                    f"unsupported archive event at line {line_number}: {event_type}"
                )
            events.append(MarketEvent(
                ts_ms,
                current_levels(bids, True),
                current_levels(asks, False),
                trades,
                tuple(str(item) for item in row.get("cancelled_order_ids", [])),
                event_type or "normalized",
                updates,
                int(row.get("_received_at_ms", 0)) or None,
            ))
    return sorted(events, key=lambda event: event.ts_ms)


def archive_sha256(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _quantile(values: list[Decimal], numerator: int, denominator: int) -> Decimal:
    if not values:
        return Decimal("0")
    ordered = sorted(values)
    index = (len(ordered) - 1) * numerator // denominator
    return ordered[index]


@dataclass(frozen=True)
class ReplayCalibration:
    schema_version: int
    archive_sha256: str
    first_ts_ms: int
    last_ts_ms: int
    event_count: int
    book_event_count: int
    trade_count: int
    execution_sample_count: int
    eligible: bool
    reasons: tuple[str, ...]
    spread_pct: Decimal
    slippage_pct: Decimal
    participation_rate: Decimal
    partial_fill_ratio: Decimal
    latency_ms_p95: int
    market_impact_bps: Decimal
    volatility_bps_p95: Decimal = Decimal("0")
    latency_source: str = "execution_report"

    def as_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "archive_sha256": self.archive_sha256,
            "first_ts_ms": self.first_ts_ms,
            "last_ts_ms": self.last_ts_ms,
            "event_count": self.event_count,
            "book_event_count": self.book_event_count,
            "trade_count": self.trade_count,
            "execution_sample_count": self.execution_sample_count,
            "eligible": self.eligible,
            "reasons": list(self.reasons),
            "parameters": {
                "spread_pct": format(self.spread_pct, "f"),
                "slippage_pct": format(self.slippage_pct, "f"),
                "participation_rate": format(self.participation_rate, "f"),
                "partial_fill_ratio": format(self.partial_fill_ratio, "f"),
                "latency_ms_p95": self.latency_ms_p95,
                "market_impact_bps": format(self.market_impact_bps, "f"),
                "volatility_bps_p95": format(self.volatility_bps_p95, "f"),
                "latency_source": self.latency_source,
            },
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "ReplayCalibration":
        params = payload.get("parameters")
        schema_version = int(payload.get("schema_version", 0))
        if schema_version not in {1, 2, 3} or not isinstance(params, Mapping):
            raise ValueError("unsupported replay calibration schema")
        return cls(
            schema_version=schema_version,
            archive_sha256=str(payload["archive_sha256"]),
            first_ts_ms=int(payload["first_ts_ms"]),
            last_ts_ms=int(payload["last_ts_ms"]),
            event_count=int(payload["event_count"]),
            book_event_count=int(payload["book_event_count"]),
            trade_count=int(payload["trade_count"]),
            execution_sample_count=int(payload["execution_sample_count"]),
            eligible=bool(payload["eligible"]),
            reasons=tuple(str(item) for item in payload.get("reasons", [])),
            spread_pct=Decimal(str(params["spread_pct"])),
            slippage_pct=Decimal(str(params["slippage_pct"])),
            participation_rate=Decimal(str(params["participation_rate"])),
            partial_fill_ratio=Decimal(str(params["partial_fill_ratio"])),
            latency_ms_p95=int(params["latency_ms_p95"]),
            market_impact_bps=Decimal(str(params["market_impact_bps"])),
            volatility_bps_p95=Decimal(
                str(params.get("volatility_bps_p95", "0"))
            ),
            latency_source=str(
                params.get("latency_source", "execution_report")
            ),
        )


def calibrate_market_events(
    events: Iterable[MarketEvent],
    *,
    source_sha256: str,
    min_book_events: int = 100,
    min_trades: int = 50,
    measured_order_latencies_ms: Iterable[int] = (),
) -> ReplayCalibration:
    rows = list(events)
    if not rows:
        raise ValueError("cannot calibrate an empty replay")
    spreads: list[Decimal] = []
    slippages: list[Decimal] = []
    participation: list[Decimal] = []
    partials: list[Decimal] = []
    latencies: list[int] = [int(value) for value in measured_order_latencies_ms]
    if any(value < 0 or value > 300_000 for value in latencies):
        raise ValueError("measured order latency is out of range")
    has_measured_order_latency = bool(latencies)
    receive_latencies: list[int] = []
    impacts: list[Decimal] = []
    mid_moves_bps: list[Decimal] = []
    previous_mid: Decimal | None = None
    trade_count = 0
    book_events = 0
    for event in rows:
        if (
            event.received_ts_ms is not None
            and event.received_ts_ms >= event.ts_ms
            and event.ts_ms > 0
        ):
            receive_latencies.append(event.received_ts_ms - event.ts_ms)
        if event.bids and event.asks:
            bid = event.bids[0]
            ask = event.asks[0]
            mid = (bid.price + ask.price) / Decimal("2")
            if mid <= 0 or ask.price < bid.price:
                raise ValueError("replay contains a crossed or invalid book")
            spread = (ask.price - bid.price) / mid
            spreads.append(spread)
            if previous_mid is not None and previous_mid > 0:
                mid_moves_bps.append(
                    abs(mid / previous_mid - Decimal("1")) * Decimal("10000")
                )
            previous_mid = mid
            book_events += 1
            for price, quantity, aggressor in event.trades:
                if price <= 0 or quantity <= 0:
                    raise ValueError("replay contains an invalid public trade")
                trade_count += 1
                adverse = abs(price - mid) / mid
                slippages.append(max(Decimal("0"), adverse - spread / Decimal("2")))
                top = ask if aggressor.upper() == "BUY" else bid
                participation.append(min(Decimal("1"), quantity / top.quantity))
                impacts.append(adverse * Decimal("10000"))
        for update in event.exchange_order_updates:
            try:
                original = Decimal(str(update.get("q", update.get("origQty", "0"))))
                last_qty = Decimal(str(update.get("l", update.get("lastQty", "0"))))
                transaction_ts = int(update.get("T", update.get("updateTime", event.ts_ms)))
                order_ts = int(update.get("O", update.get("workingTime", 0)))
            except (ArithmeticError, TypeError, ValueError):
                continue
            if original > 0 and last_qty > 0:
                partials.append(min(Decimal("1"), last_qty / original))
            if (
                not has_measured_order_latency
                and order_ts > 0
                and transaction_ts >= order_ts
            ):
                latencies.append(transaction_ts - order_ts)
    reasons = []
    if book_events < min_book_events:
        reasons.append(f"book samples {book_events} < {min_book_events}")
    if trade_count < min_trades:
        reasons.append(f"trade samples {trade_count} < {min_trades}")
    latency_source = (
        "intent_to_execution_report_receive"
        if has_measured_order_latency else "execution_report"
    )
    if not latencies:
        latencies = receive_latencies
        latency_source = "public_event_receive"
    if not latencies:
        reasons.append("latency samples unavailable")
    return ReplayCalibration(
        schema_version=3,
        archive_sha256=source_sha256,
        first_ts_ms=min(event.ts_ms for event in rows),
        last_ts_ms=max(event.ts_ms for event in rows),
        event_count=len(rows),
        book_event_count=book_events,
        trade_count=trade_count,
        execution_sample_count=max(len(partials), len(latencies)),
        eligible=not reasons,
        reasons=tuple(reasons),
        spread_pct=_quantile(spreads, 1, 2),
        slippage_pct=_quantile(slippages, 3, 4),
        participation_rate=_quantile(participation, 1, 4),
        partial_fill_ratio=_quantile(partials, 1, 4) if partials else Decimal("0"),
        latency_ms_p95=int(_quantile([Decimal(value) for value in latencies], 95, 100)),
        market_impact_bps=_quantile(impacts, 3, 4),
        volatility_bps_p95=_quantile(mid_moves_bps, 95, 100),
        latency_source=latency_source,
    )


def write_calibration(path: str | Path, report: ReplayCalibration) -> None:
    Path(path).write_text(
        json.dumps(report.as_dict(), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def read_calibration(path: str | Path) -> ReplayCalibration:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("calibration must be a JSON object")
    return ReplayCalibration.from_dict(payload)
