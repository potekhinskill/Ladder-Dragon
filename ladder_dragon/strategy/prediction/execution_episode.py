# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: replay one promotion-grade maker entry and protected spot exit.
"""Compact sequential execution episodes for promotion evidence."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from decimal import Decimal
from typing import Mapping

from ladder_dragon.strategy.market_replay import (
    MarketEvent,
    OrderBookReplay,
    ReplayFill,
    ReplayOrder,
)


D = Decimal
ZERO = D("0")
ONE = D("1")


@dataclass(frozen=True)
class ExecutionEpisodeSpec:
    """Freeze the execution semantics for one independent SHADOW episode."""

    episode_id: str
    symbol: str
    generation: str
    variant_id: str
    candidate_fingerprint: str
    execution_model_rule: str
    start_regime: str
    started_at_ms: int
    entry_deadline_ms: int
    diagnostic_at_ms: int
    primary_deadline_ms: int
    entry_price: Decimal
    take_profit_price: Decimal
    stop_trigger_price: Decimal
    stop_limit_price: Decimal
    quantity: Decimal
    maker_buy_fee_pct: Decimal
    maker_sell_fee_pct: Decimal
    taker_sell_fee_pct: Decimal
    taker_buy_fee_pct: Decimal = ZERO
    stop_unfilled_grace_ms: int = 60_000
    maximum_event_gap_ms: int = 120_000
    latency_ms: int = 0
    market_impact_bps: Decimal = ZERO
    evidence_semantics_fingerprint: str = ""

    def __post_init__(self) -> None:
        prices = (
            self.entry_price,
            self.take_profit_price,
            self.stop_trigger_price,
            self.stop_limit_price,
        )
        fees = (
            self.maker_buy_fee_pct,
            self.maker_sell_fee_pct,
            self.taker_buy_fee_pct,
            self.taker_sell_fee_pct,
            self.market_impact_bps,
        )
        if not (
            self.episode_id and self.symbol and self.variant_id
            and self.execution_model_rule and self.start_regime
        ):
            raise ValueError("execution episode identity is incomplete")
        if (
            len(self.candidate_fingerprint) != 64
            or self.evidence_semantics_fingerprint
            and len(self.evidence_semantics_fingerprint) != 64
        ):
            raise ValueError("episode fingerprints must be SHA-256")
        if any(not value.is_finite() or value <= 0 for value in prices):
            raise ValueError("execution episode prices must be positive")
        if not (
            self.stop_limit_price < self.stop_trigger_price < self.entry_price
            < self.take_profit_price
        ):
            raise ValueError("execution episode OCO prices are inconsistent")
        if not self.quantity.is_finite() or self.quantity <= 0:
            raise ValueError("execution episode quantity must be positive")
        if any(not value.is_finite() or value < 0 for value in fees):
            raise ValueError("execution episode costs must be non-negative")
        if not (
            self.started_at_ms < self.entry_deadline_ms
            <= self.diagnostic_at_ms < self.primary_deadline_ms
        ):
            raise ValueError("execution episode deadlines are inconsistent")
        if min(
            self.stop_unfilled_grace_ms,
            self.maximum_event_gap_ms,
        ) <= 0 or self.latency_ms < 0:
            raise ValueError("execution episode timing is invalid")


@dataclass(frozen=True)
class ExecutionEpisodeResult:
    """Store one terminal result without retaining raw order-book events."""

    episode_id: str
    symbol: str
    generation: str
    variant_id: str
    candidate_fingerprint: str
    execution_model_rule: str
    start_regime: str
    started_at_ms: int
    terminal_at_ms: int
    terminal_reason: str
    entry_filled_quantity: Decimal
    entry_fill_fraction: Decimal
    entry_notional_quote: Decimal
    exit_filled_quantity: Decimal
    gross_pnl_quote: Decimal
    net_pnl_quote: Decimal
    total_fee_quote: Decimal
    adverse_selection_pct: Decimal
    diagnostic_300m_net_pnl_quote: Decimal | None
    stop_triggered: bool
    stop_limit_unfilled: bool
    panic_veto: bool
    eligible_for_promotion: bool
    evidence_semantics_fingerprint: str = ""

    def payload(self) -> dict[str, object]:
        """Return a stable JSON-compatible result."""
        output: dict[str, object] = {}
        for key, value in asdict(self).items():
            output[key] = format(value, "f") if isinstance(value, D) else value
        return output


class ExecutionEpisode:
    """Replay one entry and one protected exit with no exchange capability."""

    ENTRY_ID = "entry"
    TAKE_PROFIT_ID = "take-profit"
    STOP_LIMIT_ID = "stop-limit"

    def __init__(self, spec: ExecutionEpisodeSpec, seed: MarketEvent) -> None:
        self.spec = spec
        self.replay = OrderBookReplay(
            latency_ms=spec.latency_ms,
            maker_fee_pct=ZERO,
            taker_fee_pct=ZERO,
            market_impact_bps=ZERO,
            # This value is part of the hashed execution-semantics contract.
            queue_cancellation_ahead_ratio=ZERO,
        )
        self.phase = "ENTRY"
        self.last_event_ms = int(seed.ts_ms)
        self.entry_quantity = ZERO
        self.entry_cost = ZERO
        self.entry_fees = ZERO
        self.exit_quantity = ZERO
        self.exit_proceeds = ZERO
        self.exit_fees = ZERO
        self.minimum_bid_after_entry: Decimal | None = None
        self.diagnostic_net_pnl: Decimal | None = None
        self.stop_triggered_at_ms: int | None = None
        self.stop_limit_had_fill = False
        self.panic_veto = False
        self.result: ExecutionEpisodeResult | None = None
        seed_without_trades = MarketEvent(
            ts_ms=seed.ts_ms,
            bids=seed.bids,
            asks=seed.asks,
            event_type="episodeSeed",
        )
        self.replay.process(seed_without_trades)
        best_ask = self._best_ask(seed)
        if spec.entry_price >= best_ask:
            self._finish(seed.ts_ms, "ENTRY_REJECTED_POST_ONLY", eligible=False)
            return
        queue_ahead = self._book_quantity(seed, "BUY", spec.entry_price)
        accepted = self.replay.submit(
            ReplayOrder(
                self.ENTRY_ID,
                "BUY",
                spec.entry_price,
                spec.quantity,
                spec.started_at_ms,
            ),
            spec.started_at_ms,
            queue_ahead=queue_ahead,
        )
        if not accepted:
            self._finish(seed.ts_ms, "ENTRY_SUBMISSION_REJECTED", eligible=False)
            return
        # Confirm post-only arrival against the same authoritative book. This
        # prevents a later snapshot from misclassifying a resting maker as taker.
        arrival_fills = self.replay.process(MarketEvent(
            ts_ms=seed.ts_ms + spec.latency_ms,
            bids=seed.bids,
            asks=seed.asks,
            event_type="entryArrival",
        ))
        if arrival_fills:
            self._finish(seed.ts_ms, "ENTRY_POST_ONLY_CROSSED", eligible=False)

    @staticmethod
    def _best_bid(event: MarketEvent) -> Decimal:
        if not event.bids:
            raise ValueError("execution episode requires a bid book")
        return max(level.price for level in event.bids)

    @staticmethod
    def _best_ask(event: MarketEvent) -> Decimal:
        if not event.asks:
            raise ValueError("execution episode requires an ask book")
        return min(level.price for level in event.asks)

    @staticmethod
    def _book_quantity(event: MarketEvent, side: str, price: Decimal) -> Decimal:
        levels = event.bids if side == "BUY" else event.asks
        return sum(
            (level.quantity for level in levels if level.price == price), ZERO
        )

    def _order(self, order_id: str) -> ReplayOrder | None:
        return next(
            (order for order in self.replay.orders if order.order_id == order_id),
            None,
        )

    def _fee(self, fill: ReplayFill) -> Decimal:
        if fill.order_id == self.ENTRY_ID:
            rate = (
                self.spec.maker_buy_fee_pct
                if fill.liquidity == "MAKER" else self.spec.taker_buy_fee_pct
            )
        else:
            rate = (
                self.spec.maker_sell_fee_pct
                if fill.liquidity == "MAKER" else self.spec.taker_sell_fee_pct
            )
        return fill.price * fill.quantity * rate

    def _apply_fills(self, fills: list[ReplayFill]) -> None:
        for fill in fills:
            fee = self._fee(fill)
            if fill.order_id == self.ENTRY_ID:
                self.entry_quantity += fill.quantity
                self.entry_cost += fill.price * fill.quantity
                self.entry_fees += fee
            else:
                self.exit_quantity += fill.quantity
                self.exit_proceeds += fill.price * fill.quantity
                self.exit_fees += fee
                if fill.order_id == self.STOP_LIMIT_ID:
                    self.stop_limit_had_fill = True

    def _remaining_position(self) -> Decimal:
        return max(ZERO, self.entry_quantity - self.exit_quantity)

    def _mark_net_pnl(self, bid: Decimal) -> Decimal:
        remaining = self._remaining_position()
        marked_proceeds = self.exit_proceeds + remaining * bid
        marked_fee = self.exit_fees + remaining * bid * self.spec.taker_sell_fee_pct
        return marked_proceeds - self.entry_cost - self.entry_fees - marked_fee

    def _market_flatten(self, bid: Decimal) -> None:
        quantity = self._remaining_position()
        if quantity <= 0:
            return
        impact = self.spec.market_impact_bps / D("10000")
        price = bid * max(ZERO, ONE - impact)
        self.exit_quantity += quantity
        self.exit_proceeds += quantity * price
        self.exit_fees += quantity * price * self.spec.taker_sell_fee_pct

    def _start_protection(self, now_ms: int, event: MarketEvent) -> None:
        quantity = self._remaining_position()
        if quantity <= 0:
            self._finish(now_ms, "MISSED_FILL", eligible=True)
            return
        self.phase = "PROTECTED"
        queue_ahead = self._book_quantity(
            event, "SELL", self.spec.take_profit_price
        )
        accepted = self.replay.submit(
            ReplayOrder(
                self.TAKE_PROFIT_ID,
                "SELL",
                self.spec.take_profit_price,
                quantity,
                now_ms,
            ),
            now_ms,
            queue_ahead=queue_ahead,
        )
        if not accepted:
            self._finish(now_ms, "PROTECTION_SUBMISSION_REJECTED", eligible=False)
            return
        arrival = MarketEvent(
            ts_ms=now_ms + self.spec.latency_ms,
            bids=event.bids,
            asks=event.asks,
            event_type="protectionArrival",
        )
        fills = self.replay.process(arrival)
        if fills:
            # Production fails closed when a newly built OCO is already crossed.
            self._market_flatten(self._best_bid(event))
            self._finish(now_ms, "PROTECTION_CROSSED_FLATTEN", eligible=True)

    def _trigger_stop(self, now_ms: int, event: MarketEvent) -> None:
        remaining = self._remaining_position()
        if remaining <= 0:
            return
        take_profit = self._order(self.TAKE_PROFIT_ID)
        if take_profit is not None and take_profit.remaining > 0:
            self.replay.cancel(self.TAKE_PROFIT_ID, now_ms)
        self.stop_triggered_at_ms = now_ms
        self.phase = "STOP_ACTIVE"
        queue_ahead = self._book_quantity(
            event, "SELL", self.spec.stop_limit_price
        )
        accepted = self.replay.submit(
            ReplayOrder(
                self.STOP_LIMIT_ID,
                "SELL",
                self.spec.stop_limit_price,
                remaining,
                now_ms,
            ),
            now_ms,
            queue_ahead=queue_ahead,
        )
        if not accepted:
            self._finish(now_ms, "STOP_SUBMISSION_REJECTED", eligible=False)
            return
        arrival = MarketEvent(
            ts_ms=now_ms + self.spec.latency_ms,
            bids=event.bids,
            asks=event.asks,
            event_type="stopArrival",
        )
        self._apply_fills(self.replay.process(arrival))

    def _finish(
        self,
        now_ms: int,
        reason: str,
        *,
        eligible: bool,
    ) -> ExecutionEpisodeResult:
        if self.result is not None:
            return self.result
        gross = self.exit_proceeds - self.entry_cost
        total_fee = self.entry_fees + self.exit_fees
        average_entry = (
            self.entry_cost / self.entry_quantity
            if self.entry_quantity > 0 else self.spec.entry_price
        )
        adverse = (
            max(ZERO, ONE - self.minimum_bid_after_entry / average_entry)
            if self.minimum_bid_after_entry is not None else ZERO
        )
        self.phase = "TERMINAL"
        self.result = ExecutionEpisodeResult(
            episode_id=self.spec.episode_id,
            symbol=self.spec.symbol,
            generation=self.spec.generation,
            variant_id=self.spec.variant_id,
            candidate_fingerprint=self.spec.candidate_fingerprint,
            execution_model_rule=self.spec.execution_model_rule,
            evidence_semantics_fingerprint=(
                self.spec.evidence_semantics_fingerprint
            ),
            start_regime=self.spec.start_regime,
            started_at_ms=self.spec.started_at_ms,
            terminal_at_ms=int(now_ms),
            terminal_reason=reason,
            entry_filled_quantity=self.entry_quantity,
            entry_fill_fraction=min(ONE, self.entry_quantity / self.spec.quantity),
            entry_notional_quote=self.entry_cost,
            exit_filled_quantity=self.exit_quantity,
            gross_pnl_quote=gross,
            net_pnl_quote=gross - total_fee,
            total_fee_quote=total_fee,
            adverse_selection_pct=adverse,
            diagnostic_300m_net_pnl_quote=self.diagnostic_net_pnl,
            stop_triggered=self.stop_triggered_at_ms is not None,
            stop_limit_unfilled=(
                self.stop_triggered_at_ms is not None
                and not self.stop_limit_had_fill
            ),
            panic_veto=self.panic_veto,
            eligible_for_promotion=eligible,
        )
        return self.result

    def process(
        self,
        event: MarketEvent,
        *,
        panic_active: bool = False,
    ) -> ExecutionEpisodeResult | None:
        """Apply one new market interval and return only a terminal result."""
        if self.result is not None:
            return self.result
        if event.ts_ms <= self.last_event_ms:
            raise ValueError("execution episode events must be chronological")
        if event.ts_ms - self.last_event_ms > self.spec.maximum_event_gap_ms:
            return self._finish(event.ts_ms, "DATA_GAP", eligible=False)
        bid = self._best_bid(event)
        self._best_ask(event)
        self.last_event_ms = int(event.ts_ms)
        self._apply_fills(self.replay.process(event))
        if self.entry_quantity > 0:
            self.minimum_bid_after_entry = (
                bid if self.minimum_bid_after_entry is None
                else min(self.minimum_bid_after_entry, bid)
            )
        if (
            self.diagnostic_net_pnl is None
            and event.ts_ms >= self.spec.diagnostic_at_ms
            and self.entry_quantity > 0
        ):
            self.diagnostic_net_pnl = self._mark_net_pnl(bid)

        if panic_active:
            self.panic_veto = True
            if self.entry_quantity <= 0:
                entry = self._order(self.ENTRY_ID)
                if entry is not None and entry.remaining > 0:
                    self.replay.cancel(self.ENTRY_ID, event.ts_ms)
                # A veto is a terminal no-fill attempt. It belongs in the fill
                # denominator, but contributes zero to net expectancy.
                return self._finish(event.ts_ms, "PANIC_VETO", eligible=True)
            self._market_flatten(bid)
            # Protective exits are real financial outcomes. Excluding their
            # losses would bias expectancy toward ordinary take-profit exits.
            return self._finish(event.ts_ms, "PANIC_FLATTEN", eligible=True)

        if self.phase == "ENTRY":
            entry = self._order(self.ENTRY_ID)
            entry_complete = entry is not None and entry.remaining <= 0
            deadline = event.ts_ms >= self.spec.entry_deadline_ms
            if entry_complete or deadline:
                if entry is not None and entry.remaining > 0:
                    self.replay.cancel(self.ENTRY_ID, event.ts_ms)
                self._start_protection(event.ts_ms, event)
                if self.result is not None:
                    return self.result

        if self.phase == "PROTECTED":
            if self._remaining_position() <= 0:
                return self._finish(event.ts_ms, "TAKE_PROFIT", eligible=True)
            trigger_print = any(
                price <= self.spec.stop_trigger_price
                for price, _quantity, _aggressor in event.trades
            )
            if trigger_print:
                self._trigger_stop(event.ts_ms, event)
                if self.result is not None:
                    return self.result

        if self.phase == "STOP_ACTIVE":
            if self._remaining_position() <= 0:
                return self._finish(event.ts_ms, "STOP_LIMIT", eligible=True)
            trigger_ms = self.stop_triggered_at_ms or event.ts_ms
            if event.ts_ms - trigger_ms >= self.spec.stop_unfilled_grace_ms:
                self._market_flatten(bid)
                return self._finish(
                    event.ts_ms, "STOP_LIMIT_GAP_FLATTEN", eligible=True
                )

        if event.ts_ms >= self.spec.primary_deadline_ms:
            entry = self._order(self.ENTRY_ID)
            if entry is not None and entry.remaining > 0:
                self.replay.cancel(self.ENTRY_ID, event.ts_ms)
            if self.entry_quantity <= 0:
                return self._finish(event.ts_ms, "MISSED_FILL", eligible=True)
            self._market_flatten(bid)
            return self._finish(event.ts_ms, "TIME_STOP_360M", eligible=True)
        return None

    def abort(self, now_ms: int, reason: str) -> ExecutionEpisodeResult:
        """Terminate damaged evidence without treating it as a trading result."""
        if int(now_ms) < self.last_event_ms:
            raise ValueError("execution episode abort time moved backwards")
        return self._finish(int(now_ms), str(reason), eligible=False)


def result_from_payload(payload: Mapping[str, object]) -> ExecutionEpisodeResult:
    """Parse one immutable stored result with strict Decimal fields."""
    decimal_fields = {
        "entry_filled_quantity",
        "entry_fill_fraction",
        "entry_notional_quote",
        "exit_filled_quantity",
        "gross_pnl_quote",
        "net_pnl_quote",
        "total_fee_quote",
        "adverse_selection_pct",
    }
    values = dict(payload)
    # Historical records remain readable as pilot evidence. A missing
    # fingerprint prevents promotion under the current contract.
    values.setdefault("evidence_semantics_fingerprint", "")
    for field in decimal_fields:
        values[field] = D(str(values[field]))
    diagnostic = values.get("diagnostic_300m_net_pnl_quote")
    values["diagnostic_300m_net_pnl_quote"] = (
        D(str(diagnostic)) if diagnostic is not None else None
    )
    return ExecutionEpisodeResult(**values)


__all__ = [
    "ExecutionEpisode",
    "ExecutionEpisodeResult",
    "ExecutionEpisodeSpec",
    "result_from_payload",
]
