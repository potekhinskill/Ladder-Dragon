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

import requests

from websocket import WebSocketException, WebSocketTimeoutException, create_connection

from ladder_dragon.strategy.depth_segments import MAX_FRAME_BYTES, PublicBook
from ladder_dragon.strategy.prediction.entry_veto_replay import _ofi_increment


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
            f"{lower}@aggTrade",
            f"{lower}@depth@100ms",
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
    depth_update_id: int | None
    sequence_ok: bool
    ready: bool
    veto_ready: bool
    prefill_price_change_bps: Decimal
    prefill_signed_trade_flow: Decimal
    prefill_order_flow_imbalance: Decimal


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


@dataclass(frozen=True)
class EntryVetoDecision:
    cancel: bool
    reason: str
    signal_observed: bool


def evaluate_entry_veto(
    snapshot: MarketSnapshot | None,
    rule: Mapping[str, object],
    *,
    now_monotonic_ns: int,
    maximum_age_ms: int = 500,
) -> EntryVetoDecision:
    """Cancel on an adverse signal or unavailable frozen market evidence."""
    from ladder_dragon.strategy.prediction.entry_diagnostics import (
        normalize_entry_veto_rule,
    )

    normalized = normalize_entry_veto_rule(rule)
    if snapshot is None:
        return EntryVetoDecision(True, "entry-veto-market-unavailable", False)
    age_ms = Decimal(
        max(0, int(now_monotonic_ns) - snapshot.received_monotonic_ns)
    ) / Decimal("1000000")
    if (
        not snapshot.ready
        or not snapshot.veto_ready
        or not snapshot.sequence_ok
        or age_ms > max(0, int(maximum_age_ms))
    ):
        return EntryVetoDecision(True, "entry-veto-evidence-unavailable", False)
    signal = bool(
        snapshot.prefill_price_change_bps
        <= Decimal(str(normalized["prefill_price_change_max_bps"]))
        and snapshot.prefill_signed_trade_flow
        <= Decimal(str(normalized["prefill_signed_trade_flow_max"]))
        and snapshot.prefill_order_flow_imbalance
        <= Decimal(str(normalized["prefill_order_flow_imbalance_max"]))
    )
    return EntryVetoDecision(
        signal,
        "entry-veto-adverse-selection" if signal else "entry-veto-clear",
        signal,
    )


def public_depth_snapshot(
    symbol: str, *, testnet: bool = False
) -> dict[str, object]:
    """Read one public snapshot with a strict decoded-byte ceiling."""
    with requests.get(
        (
            "https://testnet.binance.vision/api/v3/depth"
            if testnet else "https://data-api.binance.vision/api/v3/depth"
        ),
        params={"symbol": symbol, "limit": 5000},
        timeout=15,
        stream=True,
    ) as response:
        response.raise_for_status()
        body = bytearray()
        for chunk in response.iter_content(65_536):
            body.extend(chunk)
            if len(body) > MAX_FRAME_BYTES:
                raise ValueError("public depth response exceeds byte limit")
    payload = json.loads(body)
    if not isinstance(payload, dict) or "lastUpdateId" not in payload:
        raise ValueError("public depth snapshot is invalid")
    return payload


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
        flow_window_ms: int = 300_000,
    ) -> None:
        self.symbol = symbol.strip().upper()
        self._monotonic_ns = monotonic_ns
        self._wall_time_ms = wall_time_ms
        self._flow_window_ms = max(100, int(flow_window_ms))
        self._lock = threading.Lock()
        self._condition = threading.Condition(self._lock)
        self._book = PublicBook()
        self._synchronized = False
        self._best_bid = ZERO
        self._best_ask = ZERO
        self._bid_quantity = ZERO
        self._ask_quantity = ZERO
        self._depth_imbalance = ZERO
        self._last_trade_price = ZERO
        self._signal_rows: deque[
            tuple[int, Decimal, Decimal, Decimal, Decimal, Decimal, Decimal]
        ] = deque(maxlen=100_000)
        self._trade_flow_quote = ZERO
        self._buy_quantity = ZERO
        self._sell_quantity = ZERO
        self._ofi = ZERO
        self._ofi_scale = ZERO
        self._previous_top: tuple[Decimal, Decimal, Decimal, Decimal] | None = None
        self._depth_update_id: int | None = None
        self._sequence_ok = True
        self._book_received_monotonic_ns = 0
        self._book_received_at_ms = 0
        self._depth_received_monotonic_ns = 0
        self._depth_received_at_ms = 0

    def begin_stream_session(self) -> None:
        """Invalidate connection-scoped book evidence before a new session."""

        with self._condition:
            # Snapshot identifiers are not continuous across WebSocket sessions.
            # Require fresh book and depth frames before BUY can resume.
            self._depth_update_id = None
            self._sequence_ok = True
            self._book = PublicBook()
            self._synchronized = False
            self._signal_rows.clear()
            self._trade_flow_quote = ZERO
            self._buy_quantity = ZERO
            self._sell_quantity = ZERO
            self._ofi = ZERO
            self._ofi_scale = ZERO
            self._previous_top = None
            self._book_received_monotonic_ns = 0
            self._book_received_at_ms = 0
            self._depth_received_monotonic_ns = 0
            self._depth_received_at_ms = 0
            self._condition.notify_all()

    def initialize_depth(self, snapshot: Mapping[str, object]) -> None:
        """Seed a session from REST before accepting any diff-depth event."""
        now_ns = int(self._monotonic_ns())
        now_ms = int(self._wall_time_ms())
        row = {
            "s": self.symbol,
            "E": now_ms,
            "_received_at_ms": now_ms,
            "lastUpdateId": snapshot.get("lastUpdateId"),
            "bids": snapshot.get("bids"),
            "asks": snapshot.get("asks"),
        }
        with self._condition:
            event = self._book.apply(row)
            self._depth_update_id = self._book.update_id
            self._refresh_top(event)
            self._depth_received_monotonic_ns = now_ns
            self._depth_received_at_ms = now_ms
            self._condition.notify_all()

    def _refresh_top(self, event) -> None:
        current = (
            event.bids[0].price,
            event.bids[0].quantity,
            event.asks[0].price,
            event.asks[0].quantity,
        )
        increment = (
            _ofi_increment(self._previous_top, current)
            if self._previous_top is not None else ZERO
        )
        self._previous_top = current
        self._best_bid, self._bid_quantity = current[0], current[1]
        self._best_ask, self._ask_quantity = current[2], current[3]
        self._ofi += increment
        self._ofi_scale += abs(increment)
        buy = sell = ZERO
        for _price, quantity, aggressor in event.trades:
            if aggressor == "BUY":
                buy += quantity
            elif aggressor == "SELL":
                sell += quantity
        self._buy_quantity += buy
        self._sell_quantity += sell
        self._trade_flow_quote += sum(
            (
                price * quantity if aggressor == "BUY" else -price * quantity
                for price, quantity, aggressor in event.trades
            ),
            ZERO,
        )
        signed_quote = sum(
            (
                price * quantity if aggressor == "BUY" else -price * quantity
                for price, quantity, aggressor in event.trades
            ),
            ZERO,
        )
        bid_quote = sum(
            (level.price * level.quantity for level in event.bids), ZERO
        )
        ask_quote = sum(
            (level.price * level.quantity for level in event.asks), ZERO
        )
        total_quote = bid_quote + ask_quote
        self._depth_imbalance = (
            (bid_quote - ask_quote) / total_quote if total_quote > 0 else ZERO
        )
        self._signal_rows.append(
            (
                event.ts_ms, current[0], increment, abs(increment), buy, sell,
                signed_quote,
            )
        )
        cutoff = event.ts_ms - self._flow_window_ms
        while len(self._signal_rows) > 1 and self._signal_rows[1][0] <= cutoff:
            _, _, old_ofi, old_scale, old_buy, old_sell, old_quote = (
                self._signal_rows.popleft()
            )
            self._ofi -= old_ofi
            self._ofi_scale -= old_scale
            self._buy_quantity -= old_buy
            self._sell_quantity -= old_sell
            self._trade_flow_quote -= old_quote
        if self._signal_rows and self._signal_rows[0][0] < cutoff:
            stamp, bid, old_ofi, old_scale, old_buy, old_sell, old_quote = (
                self._signal_rows[0]
            )
            self._ofi -= old_ofi
            self._ofi_scale -= old_scale
            self._buy_quantity -= old_buy
            self._sell_quantity -= old_sell
            self._trade_flow_quote -= old_quote
            # Retain only the last pre-window bid as the causal price anchor.
            self._signal_rows[0] = (stamp, bid, ZERO, ZERO, ZERO, ZERO, ZERO)

    def update(self, raw_payload: Mapping[str, object]) -> None:
        payload = raw_payload.get("data", raw_payload)
        if not isinstance(payload, Mapping):
            raise ValueError("market stream payload is invalid")
        event = str(payload.get("e", ""))
        now_ns = int(self._monotonic_ns())
        now_ms = int(self._wall_time_ms())
        with self._condition:
            if "lastUpdateId" in payload:
                update_id = int(payload["lastUpdateId"])
                if (
                    self._book.update_id is not None
                    and update_id < self._book.update_id
                ):
                    self._sequence_ok = False
                    self._condition.notify_all()
                    return
                row = dict(payload)
                row.setdefault("s", self.symbol)
                row["_received_at_ms"] = now_ms
                market_event = self._book.apply(row)
                self._synchronized = True
                self._depth_update_id = self._book.update_id
                self._refresh_top(market_event)
                self._depth_received_monotonic_ns = now_ns
                self._depth_received_at_ms = now_ms
                self._book_received_monotonic_ns = now_ns
                self._book_received_at_ms = now_ms
                self._sequence_ok = True
            elif event == "depthUpdate":
                if self._book.update_id is None:
                    raise ValueError("public depth snapshot is unavailable")
                if int(payload.get("u", 0)) <= self._book.update_id:
                    return
                row = dict(payload)
                row["_received_at_ms"] = now_ms
                market_event = self._book.apply(row)
                self._synchronized = True
                self._depth_update_id = self._book.update_id
                self._refresh_top(market_event)
                self._depth_received_monotonic_ns = now_ns
                self._depth_received_at_ms = now_ms
                self._book_received_monotonic_ns = now_ns
                self._book_received_at_ms = now_ms
                self._sequence_ok = True
            elif event == "aggTrade":
                row = dict(payload)
                row["_received_at_ms"] = now_ms
                market_event = self._book.apply(row)
                self._refresh_top(market_event)
                self._last_trade_price = _decimal(
                    payload.get("p"), name="trade price"
                )
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
                and self._synchronized
                and required_received_ns > 0
            )
            trade_total = self._buy_quantity + self._sell_quantity
            price_change = (
                (self._best_bid / self._signal_rows[0][1] - Decimal("1"))
                * TEN_THOUSAND
                if self._signal_rows and self._signal_rows[0][1] > 0 else ZERO
            )
            signed_flow = (
                (self._buy_quantity - self._sell_quantity) / trade_total
                if trade_total > 0 else ZERO
            )
            normalized_ofi = (
                self._ofi / self._ofi_scale if self._ofi_scale > 0 else ZERO
            )
            veto_ready = bool(
                ready and self._signal_rows
                and self._signal_rows[-1][0] - self._signal_rows[0][0]
                >= self._flow_window_ms
                and trade_total > 0 and self._ofi_scale > 0
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
                depth_update_id=self._depth_update_id,
                sequence_ok=self._sequence_ok,
                ready=ready,
                veto_ready=veto_ready,
                prefill_price_change_bps=price_change,
                prefill_signed_trade_flow=signed_flow,
                prefill_order_flow_imbalance=normalized_ofi,
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
        snapshot_fetcher: Optional[Callable[[str], Mapping[str, object]]] = None,
    ) -> None:
        self.store = store
        self.url = combined_market_stream_url(
            store.symbol, testnet=testnet
        )
        self.logger = logger
        self._connect = connect or create_connection
        self._snapshot_fetcher = snapshot_fetcher or (
            lambda symbol: public_depth_snapshot(symbol, testnet=testnet)
        )
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
                self.store.begin_stream_session()
                self.store.initialize_depth(
                    self._snapshot_fetcher(self.store.symbol)
                )
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
