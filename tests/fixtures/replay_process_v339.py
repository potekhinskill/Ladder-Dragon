# Frozen v2.20.339 matcher for differential financial regression tests.
from decimal import Decimal
from ladder_dragon.strategy.market_replay import MarketEvent, ReplayFill

def process(self, event: MarketEvent) -> list[ReplayFill]:
        """Apply one chronological market event without reusing its liquidity."""
        fills: list[ReplayFill] = []
        # A local cancel is not authoritative before its simulated exchange
        # arrival. Until this boundary the resting order remains fillable.
        for order in self.orders:
            if (
                not order.cancelled
                and order.cancel_effective_ts is not None
                and order.cancel_effective_ts <= event.ts_ms
            ):
                self._cancel_order(order)
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
                self._cancel_order(order)
        for update in event.exchange_order_updates:
            for order in self.orders:
                if str(update.get("orderId")) != order.order_id:
                    continue
                if str(update.get("status", "")).upper() in {"CANCELED", "EXPIRED", "REJECTED"}:
                    self._cancel_order(order)

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
                if order.remaining > 0:
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
                    if earlier_local:
                        # Public depth is shared by the local FIFO and belongs
                        # only to its first live order. Later local orders are
                        # already sequenced behind it by price-time priority.
                        order.queue_ahead = Decimal("0")
                    elif order.queue_ahead is None:
                        order.queue_ahead = own_side.get(
                            order.price, Decimal("0")
                        )

        # A public trade has one shared quantity. It first consumes the public
        # FIFO queue and then local orders at that price or a better resting
        # price that the aggressor must have crossed first.
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
                price_reached = (
                    trade_price <= order.price
                    if passive_side == "BUY"
                    else trade_price >= order.price
                )
                if not order.arrival_checked or not price_reached:
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
                # The counterfactual local maker executes at its own resting
                # limit, which may be better than the reported public print.
                fill_price = order.price
                fee = fill_price * quantity * self.maker_fee_pct
                fills.append(ReplayFill(
                    order.order_id, quantity, fill_price, fee, "MAKER"
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
