# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: maintain an immutable low-latency public market snapshot.
"""Public-only Binance market stream and fail-closed decision freshness gates."""

from __future__ import annotations

import json
import threading
import time
from collections import deque
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Callable, Mapping, Optional

from websocket import WebSocketException, WebSocketTimeoutException, create_connection


ZERO = Decimal("0")
TEN_THOUSAND = Decimal("10000")


def combined_market_stream_url(symbol: str, *, testnet: bool = False) -> str:
    lower = symbol.strip().lower()
    if not lower or not lower.isalnum():
        raise ValueError("market stream symbol is invalid")
    base = (
        "wss://stream.testnet.binance.vision/stream"
        if testnet
        else "wss://stream.binance.com:9443/stream"
    )
    streams = "/".join(
        (
            f"{lower}@bookTicker",
            f"{lower}@aggTrade",
            f"{lower}@depth20@100ms",
            f"{lower}@kline_1m",
        )
    )
    return f"{base}?streams={streams}"


def _decimal(value: object, *, name: str) -> Decimal:
    try:
        result = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValueError(f"{name} is not a decimal") from exc
    if not result.is_finite() or result < 0:
        raise ValueError(f"{name} must be finite and non-negative")
    return result


@dataclass(frozen=True)
class MarketSnapshot:
    symbol: str
    received_monotonic_ns: int
    received_at_ms: int
    best_bid: Decimal
    best_ask: Decimal
    bid_quantity: Decimal
    ask_quantity: Decimal
    spread_bps: Decimal
    depth_imbalance: Decimal
    trade_flow_quote: Decimal
    last_trade_price: Decimal
    ema20: Decimal | None
    atr14: Decimal | None
    vwap: Decimal | None
    depth_update_id: int | None
    sequence_ok: bool
    ready: bool


@dataclass(frozen=True)
class DecisionFreshnessPolicy:
    max_age_ms: int = 500
    max_spread_bps: Decimal = Decimal("25")
    max_price_move_bps: Decimal = Decimal("8")
    minimum_net_edge_bps: Decimal = Decimal("2")


@dataclass(frozen=True)
class DecisionGate:
    approved: bool
    reasons: tuple[str, ...]
    snapshot_age_ms: Decimal
    price_move_bps: Decimal
    net_edge_bps: Decimal


def evaluate_snapshot_gate(
    snapshot: MarketSnapshot | None,
    *,
    decision_reference_price: object,
    expected_edge_bps: object,
    fee_bps: object,
    slippage_bps: object,
    policy: DecisionFreshnessPolicy,
    now_monotonic_ns: int,
) -> DecisionGate:
    """Reject stale or uneconomic decisions before any exchange mutation."""
    if snapshot is None:
        return DecisionGate(
            approved=False,
            reasons=("market snapshot unavailable",),
            snapshot_age_ms=Decimal("Infinity"),
            price_move_bps=Decimal("Infinity"),
            net_edge_bps=Decimal("-Infinity"),
        )
    decision_reference = _decimal(
        decision_reference_price,
        name="decision reference price",
    )
    expected = _decimal(expected_edge_bps, name="expected edge")
    fees = _decimal(fee_bps, name="fee bps")
    slippage = _decimal(slippage_bps, name="slippage bps")
    age_ns = max(0, int(now_monotonic_ns) - snapshot.received_monotonic_ns)
    age_ms = Decimal(age_ns) / Decimal("1000000")
    reference = snapshot.best_bid if snapshot.best_bid > 0 else snapshot.last_trade_price
    move_bps = (
        abs(decision_reference - reference) / decision_reference
        * TEN_THOUSAND
        if reference > 0 and decision_reference > 0
        else Decimal("Infinity")
    )
    net_edge = expected - fees - slippage
    reasons: list[str] = []
    if not snapshot.ready:
        reasons.append("market snapshot not ready")
    if not snapshot.sequence_ok:
        reasons.append("market sequence invalid")
    if age_ms > max(0, int(policy.max_age_ms)):
        reasons.append("market snapshot stale")
    if snapshot.spread_bps > policy.max_spread_bps:
        reasons.append("spread above limit")
    if move_bps > policy.max_price_move_bps:
        reasons.append("planned price moved")
    if net_edge < policy.minimum_net_edge_bps:
        reasons.append("net edge below minimum")
    return DecisionGate(
        approved=not reasons,
        reasons=tuple(reasons),
        snapshot_age_ms=age_ms,
        price_move_bps=move_bps,
        net_edge_bps=net_edge,
    )


class MarketSnapshotStore:
    """Thread-safe actor state; readers receive frozen snapshots only."""

    def __init__(
        self,
        symbol: str,
        *,
        monotonic_ns: Callable[[], int] = time.monotonic_ns,
        wall_time_ms: Callable[[], int] = lambda: int(time.time() * 1000),
        flow_window_ms: int = 2000,
    ) -> None:
        self.symbol = symbol.strip().upper()
        self._monotonic_ns = monotonic_ns
        self._wall_time_ms = wall_time_ms
        self._flow_window_ms = max(100, int(flow_window_ms))
        self._lock = threading.Lock()
        self._condition = threading.Condition(self._lock)
        self._best_bid = ZERO
        self._best_ask = ZERO
        self._bid_quantity = ZERO
        self._ask_quantity = ZERO
        self._depth_imbalance = ZERO
        self._last_trade_price = ZERO
        self._trade_flow: deque[tuple[int, Decimal]] = deque(maxlen=10_000)
        self._trade_flow_quote = ZERO
        self._ema20: Decimal | None = None
        self._atr14: Decimal | None = None
        self._vwap: Decimal | None = None
        self._previous_close: Decimal | None = None
        self._depth_update_id: int | None = None
        self._sequence_ok = True
        self._book_received_monotonic_ns = 0
        self._book_received_at_ms = 0
        self._depth_received_monotonic_ns = 0
        self._depth_received_at_ms = 0

    def update(self, raw_payload: Mapping[str, object]) -> None:
        payload = raw_payload.get("data", raw_payload)
        if not isinstance(payload, Mapping):
            raise ValueError("market stream payload is invalid")
        event = str(payload.get("e", ""))
        now_ns = int(self._monotonic_ns())
        now_ms = int(self._wall_time_ms())
        with self._condition:
            if "lastUpdateId" in payload and "bids" in payload:
                update_id = int(payload["lastUpdateId"])
                if (
                    self._depth_update_id is not None
                    and update_id <= self._depth_update_id
                ):
                    self._sequence_ok = False
                else:
                    self._depth_update_id = update_id
                    bids = payload.get("bids")
                    asks = payload.get("asks")
                    if not isinstance(bids, list) or not isinstance(asks, list):
                        raise ValueError("depth snapshot is invalid")
                    bid_quote = sum(
                        (
                            _decimal(row[0], name="bid price")
                            * _decimal(row[1], name="bid quantity")
                            for row in bids
                            if isinstance(row, list) and len(row) >= 2
                        ),
                        ZERO,
                    )
                    ask_quote = sum(
                        (
                            _decimal(row[0], name="ask price")
                            * _decimal(row[1], name="ask quantity")
                            for row in asks
                            if isinstance(row, list) and len(row) >= 2
                        ),
                        ZERO,
                    )
                    total = bid_quote + ask_quote
                    self._depth_imbalance = (
                        (bid_quote - ask_quote) / total if total > 0 else ZERO
                    )
                    self._depth_received_monotonic_ns = now_ns
                    self._depth_received_at_ms = now_ms
            elif event == "aggTrade":
                price = _decimal(payload.get("p"), name="trade price")
                quantity = _decimal(payload.get("q"), name="trade quantity")
                trade_time = int(payload.get("T", now_ms) or now_ms)
                signed_quote = price * quantity
                if bool(payload.get("m")):
                    signed_quote = -signed_quote
                if self._trade_flow.maxlen is not None and (
                    len(self._trade_flow) == self._trade_flow.maxlen
                ):
                    self._trade_flow_quote -= self._trade_flow[0][1]
                self._trade_flow.append((trade_time, signed_quote))
                self._trade_flow_quote += signed_quote
                self._last_trade_price = price
                cutoff = trade_time - self._flow_window_ms
                while self._trade_flow and self._trade_flow[0][0] < cutoff:
                    _, expired_quote = self._trade_flow.popleft()
                    self._trade_flow_quote -= expired_quote
            elif event == "kline":
                kline = payload.get("k")
                if isinstance(kline, Mapping) and bool(kline.get("x")):
                    close = _decimal(kline.get("c"), name="kline close")
                    high = _decimal(kline.get("h"), name="kline high")
                    low = _decimal(kline.get("l"), name="kline low")
                    volume = _decimal(kline.get("v"), name="kline volume")
                    quote_volume = _decimal(
                        kline.get("q"), name="kline quote volume"
                    )
                    alpha = Decimal("2") / Decimal("21")
                    self._ema20 = (
                        close
                        if self._ema20 is None
                        else self._ema20 + alpha * (close - self._ema20)
                    )
                    previous = self._previous_close or close
                    true_range = max(
                        high - low,
                        abs(high - previous),
                        abs(low - previous),
                    )
                    self._atr14 = (
                        true_range
                        if self._atr14 is None
                        else (
                            self._atr14 * Decimal("13") + true_range
                        )
                        / Decimal("14")
                    )
                    self._vwap = (
                        quote_volume / volume if volume > 0 else close
                    )
                    self._previous_close = close
            elif "b" in payload and "a" in payload:
                self._best_bid = _decimal(payload.get("b"), name="best bid")
                self._bid_quantity = _decimal(
                    payload.get("B"), name="best bid quantity"
                )
                self._best_ask = _decimal(payload.get("a"), name="best ask")
                self._ask_quantity = _decimal(
                    payload.get("A"), name="best ask quantity"
                )
                self._book_received_monotonic_ns = now_ns
                self._book_received_at_ms = now_ms
            else:
                return
            self._condition.notify_all()

    def snapshot(self) -> MarketSnapshot:
        with self._lock:
            required_received_ns = (
                min(
                    self._book_received_monotonic_ns,
                    self._depth_received_monotonic_ns,
                )
                if self._book_received_monotonic_ns > 0
                and self._depth_received_monotonic_ns > 0
                else 0
            )
            required_received_at_ms = (
                min(
                    self._book_received_at_ms,
                    self._depth_received_at_ms,
                )
                if self._book_received_at_ms > 0
                and self._depth_received_at_ms > 0
                else 0
            )
            midpoint = (
                (self._best_bid + self._best_ask) / Decimal("2")
                if self._best_bid > 0 and self._best_ask > 0
                else ZERO
            )
            spread = (
                (self._best_ask - self._best_bid) / midpoint * TEN_THOUSAND
                if midpoint > 0 and self._best_ask >= self._best_bid
                else Decimal("Infinity")
            )
            ready = (
                self._best_bid > 0
                and self._best_ask > 0
                and self._depth_update_id is not None
                and required_received_ns > 0
            )
            return MarketSnapshot(
                symbol=self.symbol,
                received_monotonic_ns=required_received_ns,
                received_at_ms=required_received_at_ms,
                best_bid=self._best_bid,
                best_ask=self._best_ask,
                bid_quantity=self._bid_quantity,
                ask_quantity=self._ask_quantity,
                spread_bps=spread,
                depth_imbalance=self._depth_imbalance,
                trade_flow_quote=self._trade_flow_quote,
                last_trade_price=self._last_trade_price,
                ema20=self._ema20,
                atr14=self._atr14,
                vwap=self._vwap,
                depth_update_id=self._depth_update_id,
                sequence_ok=self._sequence_ok,
                ready=ready,
            )

    def wait(self, timeout: float) -> bool:
        with self._condition:
            return bool(
                self._condition.wait(timeout=max(0.0, float(timeout)))
            )


class BinanceMarketDataObserver:
    """Reconnectable public stream that cannot access order credentials."""

    def __init__(
        self,
        store: MarketSnapshotStore,
        *,
        testnet: bool,
        logger: Callable[[str], None],
        connect: Optional[Callable[..., object]] = None,
    ) -> None:
        self.store = store
        self.url = combined_market_stream_url(
            store.symbol, testnet=testnet
        )
        self.logger = logger
        self._connect = connect or create_connection
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._connection: object | None = None

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._run,
            name=f"market-stream-{self.store.symbol.lower()}",
            daemon=True,
        )
        self._thread.start()

    def stop(self, timeout: float = 3.0) -> None:
        self._stop.set()
        connection = self._connection
        if connection is not None:
            try:
                connection.close()
            except (OSError, RuntimeError, WebSocketException):
                pass
        if self._thread is not None:
            self._thread.join(timeout=max(0.0, timeout))

    def _run(self) -> None:
        delay = 1.0
        while not self._stop.is_set():
            try:
                connection = self._connect(self.url, timeout=10)
                self._connection = connection
                self.logger(
                    f"[MARKET-STREAM] {self.store.symbol} connected"
                )
                delay = 1.0
                while not self._stop.is_set():
                    raw = connection.recv()
                    payload = json.loads(raw)
                    if not isinstance(payload, Mapping):
                        raise ValueError("market stream frame is not an object")
                    self.store.update(payload)
            except (
                OSError,
                RuntimeError,
                ValueError,
                TypeError,
                WebSocketException,
                WebSocketTimeoutException,
            ) as exc:
                if self._stop.is_set():
                    break
                self.logger(
                    f"[MARKET-STREAM] reconnect={type(exc).__name__}"
                )
                self._stop.wait(delay)
                delay = min(30.0, delay * 2)
