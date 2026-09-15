# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: replay actual historical opportunities with delayed cancellation.
"""Selection-only spot execution with one slot and no exchange capability."""

from __future__ import annotations

from decimal import Decimal, ROUND_CEILING, ROUND_FLOOR

from ladder_dragon.strategy.market_replay import OrderBookReplay, ReplayOrder
from ladder_dragon.strategy.prediction.historical_policy import HistoricalPolicy
from ladder_dragon.strategy.prediction.historical_commission import buy_inventory, exact_arithmetic
from ladder_dragon.execution.buy_settlement import require_full_inventory_coverage

D = Decimal
ZERO = D("0")


class HistoricalExecution:
    """Consume each real event once; never synthesize an arrival book or fill."""

    @exact_arithmetic
    def __init__(
        self,
        event,
        policy: HistoricalPolicy,
        context: dict,
        identifier: str,
        *,
        pre_submit_veto: bool = False,
    ) -> None:
        self.policy, self.context, self.identifier = policy, context, identifier
        self.started_ms = event.ts_ms
        self.entry_qty = self.entry_cost = self.exit_qty = self.exit_proceeds = self.fees = ZERO
        self.entry_net_qty = self.base_fee_quote = ZERO
        self.phase = "ENTRY"
        self.cancel_reason = None
        self.panic_latched = False
        self.signal_ms = self.cancel_effective_ms = self.stop_ms = None
        self.minimum_bid_after_entry = self.maximum_bid_after_entry = None
        self.result = None
        self.event_bid_consumption = {}
        self.entry_order_submitted = False
        self.orders = OrderBookReplay(latency_ms=policy.latency_ms, maker_fee_pct=ZERO,
                                     taker_fee_pct=ZERO, queue_cancellation_ahead_ratio=ZERO)
        tick, step = D(context["tick_size"]), D(context["step_size"])

        def price(value, *, up=False):
            return (value / tick).to_integral_value(rounding=ROUND_CEILING if up else ROUND_FLOOR) * tick

        # The midpoint anchor is explicit in this separate selection model.
        # It does not claim compatibility with a live champion fingerprint.
        midpoint = (event.bids[0].price + event.asks[0].price) / 2
        self.entry = price(midpoint * (1 - D(policy.entry_gap_bps) / 10000))
        self.target = price(self.entry * (1 + D(policy.take_profit_bps) / 10000), up=True)
        self.trigger = price(self.entry * (1 - D(policy.stop_trigger_bps) / 10000), up=True)
        self.stop_limit = price(self.entry * (1 - D(policy.stop_limit_bps) / 10000))
        if not ZERO < self.stop_limit < self.trigger < self.entry < self.target:
            raise ValueError("historical rounded prices are inconsistent")
        self.quantity = (D(policy.notional_quote) / self.entry / step).to_integral_value(rounding=ROUND_FLOOR) * step
        if pre_submit_veto:
            self.signal_ms = event.ts_ms
            self.cancel_reason = "ENTRY_VETO"
            self.finish(event.ts_ms, "ENTRY_VETO")
        elif self.quantity < D(context["minimum_quantity"]) or self.quantity * self.entry < D(context["minimum_notional_quote"]):
            self.finish(event.ts_ms, "BELOW_EXCHANGE_MINIMUM")
        else:
            self.submit("entry", "BUY", self.entry, self.quantity, event.ts_ms)

    def submit(self, identifier, side, price, qty, now) -> None:
        # Queue size uses the first observed arrival book, not the decision book.
        order = ReplayOrder(identifier, side, price, qty, now)
        if not self.orders.submit(order, now):
            raise ValueError("historical request budget exceeded")
        if identifier == "entry":
            self.entry_order_submitted = True
        # Millisecond timestamps cannot prove that a same-time trade followed
        # submission. Exclude that tie instead of awarding an optimistic fill.
        order.created_ts += 1

    def order(self, identifier) -> ReplayOrder | None:
        return next((order for order in self.orders.orders if order.order_id == identifier), None)

    def request_cancel(self, now, reason) -> None:
        entry = self.order("entry")
        if entry and entry.remaining > 0 and not entry.cancelled and self.cancel_reason is None:
            if not self.orders.cancel("entry", now):
                raise ValueError("historical cancel was not accepted")
            self.signal_ms = now
            self.cancel_reason = reason
            self.cancel_effective_ms = now + self.policy.cancel_latency_ms
            # At a cancel-time tie the trade wins. This conservative ordering
            # preserves exposure until the next observable millisecond.
            entry.cancel_effective_ts = self.cancel_effective_ms + 1

    @exact_arithmetic
    def finish(self, now, reason, *, censored=False) -> dict:
        self.phase = "TERMINAL"
        unknown_inventory = self.entry_qty > ZERO and self.policy.commission_asset_scenario == "UNSPECIFIED"
        gross = self.exit_proceeds - self.entry_cost + self.base_fee_quote
        average_entry = (
            self.entry_cost / self.entry_qty
            if self.entry_qty > ZERO else self.entry
        )
        adverse = (
            max(ZERO, D("1") - self.minimum_bid_after_entry / average_entry)
            if self.minimum_bid_after_entry is not None else ZERO
        )
        favorable = (
            max(ZERO, self.maximum_bid_after_entry / average_entry - D("1"))
            if self.maximum_bid_after_entry is not None else ZERO
        )
        self.result = {
            "episode_id": self.identifier, "started_at_ms": self.started_ms,
            "terminal_at_ms": now, "terminal_reason": reason,
            "start_regime": self.context["regime"], "context_source_sha256": self.context["source_sha256"],
            "signal_ts_ms": self.signal_ms, "cancel_effective_ts_ms": self.cancel_effective_ms,
            "entry_price": str(self.entry), "quantity": str(self.quantity),
            "entry_order_submitted": self.entry_order_submitted,
            "take_profit_price": str(self.target),
            "stop_trigger_price": str(self.trigger),
            "stop_limit_price": str(self.stop_limit),
            "entry_filled_quantity": str(self.entry_qty), "exit_filled_quantity": str(self.exit_qty),
            "entry_net_quantity": None if unknown_inventory else str(self.entry_net_qty),
            "unresolved_quantity": None if unknown_inventory else str(self.entry_net_qty - self.exit_qty),
            "unsettled_gross_quantity": str(self.entry_qty) if unknown_inventory else "0",
            "commission_asset_scenario": self.policy.commission_asset_scenario,
            "commission_asset_evidence": "UNSPECIFIED" if self.policy.commission_asset_scenario == "UNSPECIFIED" else "POLICY_ASSUMPTION",
            "base_paid_fee_quote": None if unknown_inventory else str(self.base_fee_quote),
            "entry_notional_quote": str(self.entry_cost),
            "gross_pnl_quote": None if unknown_inventory else str(gross),
            "net_pnl_quote": None if censored else str(gross - self.fees),
            "fee_quote": None if unknown_inventory else str(self.fees), "censored": censored,
            "fee_schedule": {
                name: str(self.context[name])
                for name in (
                    "maker_buy_fee_pct", "maker_sell_fee_pct",
                    "taker_buy_fee_pct", "taker_sell_fee_pct",
                )
            },
            "stop_triggered": self.stop_ms is not None,
            "stop_limit_unfilled": bool(
                self.stop_ms is not None
                and reason == "STOP_LIMIT_GAP_FLATTEN"
            ),
            "panic_veto": reason == "PANIC_VETO",
            "maximum_favorable_excursion_pct": str(favorable),
            "maximum_adverse_excursion_pct": str(adverse),
            "excursion_evidence_available": bool(
                self.entry_qty > ZERO
                and self.minimum_bid_after_entry is not None
                and self.maximum_bid_after_entry is not None
            ),
            "eligible_for_promotion": False,
        }
        return self.result

    @exact_arithmetic
    def flatten(self, event, reason) -> dict:
        if self.result is not None:
            return self.result
        remaining = self.entry_net_qty - self.exit_qty
        # Visible depth is capacity, not proof of liquidity beyond the archive.
        previous = None
        for level in event.bids:
            if (not level.price.is_finite() or not level.quantity.is_finite()
                    or level.price <= ZERO or level.quantity < ZERO
                    or (previous is not None and level.price >= previous)):
                raise ValueError("historical liquidation book is invalid")
            previous = level.price
        for level in event.bids:
            available = max(ZERO, level.quantity - self.event_bid_consumption.get(level.price, ZERO))
            quantity = min(remaining, available)
            price = level.price * (1 - D(self.policy.market_impact_bps) / 10000)
            self.exit_qty += quantity
            self.exit_proceeds += price * quantity
            self.fees += price * quantity * D(self.context["taker_sell_fee_pct"])
            remaining -= quantity
            if remaining == ZERO:
                break
        return self.finish(event.ts_ms, reason, censored=remaining > ZERO)

    @exact_arithmetic
    def process(self, event, *, veto: bool, panic: bool) -> dict | None:
        if self.result is not None:
            return self.result
        now = event.ts_ms
        self.event_bid_consumption = {}
        self.panic_latched = self.panic_latched or panic
        # Post-only checks use the first observed book after modeled arrival.
        for order in self.orders.orders:
            if order.cancelled or order.arrival_checked or order.created_ts > now:
                continue
            crossed = (order.price >= event.asks[0].price if order.side == "BUY"
                       else order.price <= event.bids[0].price)
            if not crossed and (
                order.side == "BUY" and order.price < min(level.price for level in event.bids)
                or order.side == "SELL" and order.price > max(level.price for level in event.asks)
            ):
                raise ValueError("historical book does not cover the passive queue price")
            if order.order_id in {"entry", "target"} and crossed:
                order.cancelled = True
                if order.order_id == "entry":
                    return self.finish(now, "ENTRY_REJECTED_POST_ONLY")
                return self.flatten(event, "PROTECTION_REJECTED_FLATTEN")

        for fill in self.orders.process(event):
            if fill.order_id == "entry":
                self.entry_qty += fill.quantity
                self.entry_cost += fill.price * fill.quantity
                rate = self.context["maker_buy_fee_pct"] if fill.liquidity == "MAKER" else self.context["taker_buy_fee_pct"]
                if self.policy.commission_asset_scenario == "UNSPECIFIED":
                    # Retain every gross fill from this event without inventing net inventory.
                    continue
                net, base_fee = buy_inventory(self.policy.symbol, fill.price, fill.quantity,
                                               D(rate), self.policy.commission_asset_scenario)
                self.entry_net_qty += net
                self.base_fee_quote += base_fee
            else:
                self.exit_qty += fill.quantity
                self.exit_proceeds += fill.price * fill.quantity
                rate = self.context["maker_sell_fee_pct"] if fill.liquidity == "MAKER" else self.context["taker_sell_fee_pct"]
                if fill.liquidity == "TAKER":
                    self.event_bid_consumption[fill.price] = self.event_bid_consumption.get(fill.price, ZERO) + fill.quantity
            self.fees += fill.price * fill.quantity * D(rate)
        if self.entry_qty > ZERO and self.policy.commission_asset_scenario == "UNSPECIFIED":
            return self.finish(now, "COMMISSION_ASSET_UNSPECIFIED", censored=True)
        for trade_price, quantity, aggressor in event.trades:
            if aggressor == "SELL":
                self.event_bid_consumption[trade_price] = self.event_bid_consumption.get(trade_price, ZERO) + quantity
        if self.exit_qty > self.entry_net_qty:
            raise ValueError("historical exit exceeds filled quantity")
        if self.entry_qty > ZERO:
            bid = event.bids[0].price
            self.minimum_bid_after_entry = (
                bid if self.minimum_bid_after_entry is None
                else min(self.minimum_bid_after_entry, bid)
            )
            self.maximum_bid_after_entry = (
                bid if self.maximum_bid_after_entry is None
                else max(self.maximum_bid_after_entry, bid)
            )

        if self.phase == "ENTRY":
            entry = self.order("entry")
            if self.panic_latched:
                self.request_cancel(now, "PANIC_VETO")
            elif self.entry_qty > ZERO and entry.remaining > ZERO:
                # Match runtime: settle the remainder before sizing protection.
                self.request_cancel(now, "PARTIAL_ENTRY")
            elif now >= self.started_ms + self.policy.entry_ttl_ms:
                self.request_cancel(now, "MISSED_FILL")
            elif veto:
                self.request_cancel(now, "ENTRY_VETO")
            if entry.cancelled or entry.remaining <= 0:
                if self.entry_qty == ZERO:
                    return self.finish(now, self.cancel_reason or "MISSED_FILL")
                step = D(self.context["step_size"])
                normalized = (self.entry_net_qty / step).to_integral_value(rounding=ROUND_FLOOR) * step
                try:
                    require_full_inventory_coverage(self.entry_net_qty, normalized)
                except RuntimeError:
                    return self.finish(now, "UNREPRESENTABLE_NET_INVENTORY", censored=True)
                if (normalized < D(self.context["minimum_quantity"])
                        or normalized * self.stop_limit < D(self.context["minimum_notional_quote"])):
                    return self.finish(now, "NET_INVENTORY_BELOW_MINIMUM", censored=True)
                if self.panic_latched:
                    return self.flatten(event, "PANIC_FLATTEN")
                # Partial fills remain real positions. A cancel never erases them.
                self.phase = "PROTECTED"
                self.submit("target", "SELL", self.target, self.entry_net_qty, now)

        if self.phase in {"PROTECTED", "STOP_ACTIVE"}:
            if self.exit_qty == self.entry_net_qty:
                return self.finish(now, "STOP_LIMIT" if self.phase == "STOP_ACTIVE" else "TAKE_PROFIT")
            if self.panic_latched:
                return self.flatten(event, "PANIC_FLATTEN")
            if (self.phase == "PROTECTED"
                    and self.order("target").created_ts <= now
                    and any(p <= self.trigger for p, _, _ in event.trades)):
                # OCO sibling removal is atomic at the exchange trigger.
                target = self.order("target")
                target.cancelled = True
                self.stop_ms, self.phase = now, "STOP_ACTIVE"
                # This is exchange-resident activation, not a second HTTP POST.
                stop = ReplayOrder("stop", "SELL", self.stop_limit, self.entry_net_qty - self.exit_qty, now)
                self.orders.activate_exchange_conditional(stop, now)
                # Preserve the conservative ambiguity boundary: no trigger-event reuse.
                stop.created_ts += 1
            if self.stop_ms is not None and now - self.stop_ms >= self.policy.stop_grace_ms:
                return self.flatten(event, "STOP_LIMIT_GAP_FLATTEN")
            if now >= self.started_ms + self.policy.holding_ms:
                return self.flatten(event, "TIME_STOP")
        return None
