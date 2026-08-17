# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: enforce exact BUY sizing limits outside the worker event loop.

"""BUY sizing policy and placement service used by the execution worker."""

from __future__ import annotations

import os
from decimal import Decimal
from pathlib import Path
import time
from typing import Any, List, Mapping, Optional

import requests

from ladder_dragon.execution.orders.reconciliation import UncertainOrderSubmission
from ladder_dragon.execution.trade_accounting import DEFAULT_SPOT_FEE_PCT
from ladder_dragon.risk.inventory_caps import (
    open_buy_notional,
    remaining_inventory_budget,
)


def cap_decimal(name: str, raw: object) -> Decimal:
    """Parse a non-negative finite CAP or fail closed."""
    try:
        value = Decimal(str(raw))
    except (ArithmeticError, TypeError, ValueError) as exc:
        raise ValueError(f"{name} is not a valid decimal CAP") from exc
    if not value.is_finite() or value < 0:
        raise ValueError(f"{name} must be finite and non-negative")
    return value


def hard_buy_cap(
    symbol: str,
    proposed_cap: object,
    *,
    environment: Mapping[str, str] | None = None,
) -> tuple[Decimal, dict[str, Decimal]]:
    """Clamp strategy CAP by operator, Risk Manager and symbol budgets."""
    source = os.environ if environment is None else environment
    limits = {"strategy": cap_decimal("strategy CAP", proposed_cap)}
    variables = {
        "operator": "BOT_OPERATOR_CAP_PER_ORDER_USDT",
        "risk": "BOT_CAP_PER_ORDER",
        "symbol": f"RISK_SYMBOL_CAP_{symbol.upper()}",
    }
    for label, variable in variables.items():
        raw = source.get(variable)
        if raw is None or not raw.strip():
            continue
        limits[label] = cap_decimal(variable, raw)
    return min(limits.values()), limits


def _runtime_dependency(runtime: Mapping[str, object], name: str) -> Any:
    """Resolve one explicit compatibility adapter for BUY placement."""
    try:
        return runtime[name]
    except KeyError as exc:
        raise RuntimeError(
            f"BUY runtime dependency is unavailable: {name}"
        ) from exc


def place_buys(symbol: str,
                     ladder_prices: List[float],
                     cap_per_order_usdt: object,
                     *,
                     min_order_usdt: Optional[float] = None,
                     cap_floor_usdt: Optional[float] = None,
                     target_buy_per_symbol: Optional[int] = None,
                     enforce_limit: bool = False,
                     use_remainder_in_last: bool = False,
                     buy_limit_maker: bool = False,
                     live_mode: bool = False,
                     market_store: MarketSnapshotStore | None = None,
                     market_policy: DecisionFreshnessPolicy | None = None,
                     market_mode: str = "OFF",
                     otoco_mode: str = "OFF",
                     stop_limit_offset_pct: object = Decimal("0.0015"),
                     runtime: Mapping[str, object]) -> List[int]:
    """Place fail-closed BUY candidates through injected worker adapters."""
    LatencyTrace = _runtime_dependency(runtime, 'LatencyTrace')
    _cap_decimal = _runtime_dependency(runtime, '_cap_decimal')
    _filter_decimal = _runtime_dependency(runtime, '_filter_decimal')
    _non_fee_execution_cost_pct = _runtime_dependency(runtime, '_non_fee_execution_cost_pct')
    _pick_ladder_aligned_oco_prices = _runtime_dependency(runtime, '_pick_ladder_aligned_oco_prices')
    _profit_floor_pct = _runtime_dependency(runtime, '_profit_floor_pct')
    _round_price_exact = _runtime_dependency(runtime, '_round_price_exact')
    _round_qty_exact = _runtime_dependency(runtime, '_round_qty_exact')
    buy_candidates_decimal = _runtime_dependency(runtime, 'buy_candidates_decimal')
    dbg = _runtime_dependency(runtime, 'dbg')
    effective_remainder_policy = _runtime_dependency(runtime, 'effective_remainder_policy')
    evaluate_snapshot_gate = _runtime_dependency(runtime, 'evaluate_snapshot_gate')
    existing_prices_decimal = _runtime_dependency(runtime, 'existing_prices_decimal')
    fmt_price_sym = _runtime_dependency(runtime, 'fmt_price_sym')
    fmt_qty_sym = _runtime_dependency(runtime, 'fmt_qty_sym')
    get_balances = _runtime_dependency(runtime, 'get_balances')
    get_price_exact = _runtime_dependency(runtime, 'get_price_exact')
    get_symbol_assets = _runtime_dependency(runtime, 'get_symbol_assets')
    getenv_decimal = _runtime_dependency(runtime, 'getenv_decimal')
    list_open_orders = _runtime_dependency(runtime, 'list_open_orders')
    log = _runtime_dependency(runtime, 'log')
    place_limit_order = _runtime_dependency(runtime, 'place_limit_order')
    place_otoco_buy = _runtime_dependency(runtime, 'place_otoco_buy')
    plan_buy_order_decimal = _runtime_dependency(runtime, 'plan_buy_order_decimal')
    pull_filters = _runtime_dependency(runtime, 'pull_filters')
    def running() -> bool:
        """Read the mutable worker stop flag at each safety boundary."""
        return bool(_runtime_dependency(runtime, "RUN"))

    # Check the stop signal before any network request: after SIGTERM this function
    # must not even read balances or open orders.
    if not running():
        log(f"[STOP] {symbol} BUY placement skipped before exchange reads")
        return []
    base_asset, _quote_asset = get_symbol_assets(symbol)
    bals = get_balances()
    reserve = max(
        Decimal("0"),
        _cap_decimal("RISK_RESERVE_USDT", os.getenv("RISK_RESERVE_USDT", "0")),
    )
    usdt_free = max(
        Decimal("0"),
        Decimal(str(bals.get("USDT", {}).get("free", 0))) - reserve,
    )
    cap_exact = _cap_decimal("per-order CAP", cap_per_order_usdt)

    # Free-USDT threshold gate.
    floor_exact = (
        _cap_decimal("CAP floor", cap_floor_usdt)
        if cap_floor_usdt is not None else None
    )
    if floor_exact is not None and usdt_free < floor_exact:
        log(f"[CAP-FLOOR] free≈{usdt_free:.2f} < {floor_exact:.2f}; skip BUY this cycle")
        return []

    if usdt_free <= 0:
        return []

    pull_filters(symbol)
    placed_ids: List[int] = []
    local_inventory_commitments: dict[int, Decimal] = {}
    now = get_price_exact(symbol)

    # Prepare the limit and deduplication set.
    allowed_new: Optional[int] = None
    existing_buy_prices: set[Decimal] = set()
    if enforce_limit and (target_buy_per_symbol is not None):
        try:
            open_orders = list_open_orders(symbol) or []
        except (requests.RequestException, RuntimeError, ValueError) as exc:
            log(
                f"[BUY-BLOCK] {symbol} open-order state unavailable: "
                f"{type(exc).__name__}"
            )
            return []
        existing_buy_prices = existing_prices_decimal(
            open_orders,
            side="BUY",
            now_price=now,
            round_price=lambda value: _round_price_exact(symbol, value),
        )
        existing_cnt = len(existing_buy_prices)
        allowed_new = max(0, int(target_buy_per_symbol) - existing_cnt)
        log(f"[TARGET-LIMIT] {symbol} existing_buy={existing_cnt} target={int(target_buy_per_symbol)} → allow_new={allowed_new}")
        if allowed_new <= 0:
            return []

    candidates = buy_candidates_decimal(
        [Decimal(str(value)) for value in ladder_prices],
        now_price=now,
        occupied_prices=existing_buy_prices,
        round_price=lambda value: _round_price_exact(symbol, value),
        limit=allowed_new if enforce_limit else None,
    )

    total_slots = len(candidates)
    if total_slots <= 0:
        now = get_price_exact(symbol)
        log(f"[BUY-NONE] {symbol} has no levels below market (now≈{fmt_price_sym(symbol, now)}). "
            f"Check --ladder-prices and reduce-only mode.")
        return []
    selected_gap_pct = (
        (now - candidates[0]) / now * Decimal("100")
        if now > 0 else Decimal("0")
    )
    log(
        f"[BUY-PRIORITY] {symbol} selected="
        f"{fmt_price_sym(symbol, candidates[0])} "
        f"gap={selected_gap_pct:.4f}% candidates={total_slots}"
    )

    initial_market_snapshot = (
        market_store.snapshot() if market_store is not None else None
    )
    decision_reference_price = (
        initial_market_snapshot.best_bid
        if initial_market_snapshot is not None
        and initial_market_snapshot.best_bid > 0
        else now
    )

    def append_trace(trace: LatencyTrace) -> None:
        try:
            trace.append(
                os.getenv(
                    "BOT_LATENCY_TRACE_LOG",
                    str(
                        Path(__file__).resolve().parents[3]
                        / "logs"
                        / "latency_trace.ndjson"
                    ),
                )
            )
        except OSError as exc:
            dbg(
                "[LATENCY] trace unavailable="
                f"{type(exc).__name__}"
            )

    def inventory_buy_allowed(exchange_notional: Decimal) -> bool:
        """Recheck authoritative inventory immediately before a LIVE POST."""
        hard_cap_name = f"RISK_MANAGED_INVENTORY_HARD_CAP_{symbol.upper()}"
        hard_cap_raw = os.getenv(hard_cap_name)
        try:
            if hard_cap_raw is None or not hard_cap_raw.strip():
                raise ValueError("managed inventory hard CAP is missing")
            current_balances = get_balances()
            current_orders = list_open_orders(symbol) or []
            held_row = current_balances.get(base_asset, {})
            held_quantity = (
                Decimal(str(held_row.get("free", "0")))
                + Decimal(str(held_row.get("locked", "0")))
            )
            remaining = remaining_inventory_budget(
                hard_cap_quote=hard_cap_raw,
                held_base_quantity=held_quantity,
                market_price=get_price_exact(symbol),
                open_buy_notional_quote=open_buy_notional(current_orders),
            )
            visible_order_ids = {
                int(row["orderId"])
                for row in current_orders
                if row.get("orderId") is not None
            }
            unseen_commitment = sum(
                (
                    notional for order_id, notional
                    in local_inventory_commitments.items()
                    if order_id not in visible_order_ids
                ),
                Decimal("0"),
            )
            # Exchange visibility can lag the preceding successful POST.
            remaining = max(
                Decimal("0"), remaining - unseen_commitment
            )
            minimum = _filter_decimal(
                symbol, "minNotionalExact", "minNotional"
            )
            if remaining < minimum:
                log(
                    f"[INVENTORY-CAP-BLOCK] {symbol} remaining="
                    f"{remaining:.8f} below exchange minimum"
                )
                return False
            if exchange_notional > remaining:
                log(
                    f"[INVENTORY-CAP-BLOCK] {symbol} exchange="
                    f"{exchange_notional:.8f} remaining={remaining:.8f}"
                )
                return False
            return True
        except (
            ArithmeticError,
            requests.RequestException,
            RuntimeError,
            TypeError,
            ValueError,
        ) as exc:
            log(
                f"[INVENTORY-CAP-BLOCK] {symbol} state unavailable: "
                f"{type(exc).__name__}"
            )
            return False

    # Main candidate loop.
    for idx, p in enumerate(candidates, start=1):
        if not running():
            log(f"[STOP] {symbol} BUY placement interrupted before slot {idx}/{total_slots}")
            break
        if usdt_free <= 0:
            break
        remaining_slots = max(1, total_slots - idx + 1)
        local_cap = min(cap_exact, usdt_free / Decimal(remaining_slots))
        use_all_remaining = effective_remainder_policy(
            requested=use_remainder_in_last and idx == total_slots,
            live_mode=live_mode,
        )
        if use_all_remaining:
            local_cap = usdt_free

        dbg(f"[DYN-CAP] {symbol} slot {idx}/{total_slots} p≈{fmt_price_sym(symbol, p)} "
            f"local_cap≈{local_cap:.2f} free≈{usdt_free:.2f}")
        planned = plan_buy_order_decimal(
            p,
            free_quote=usdt_free,
            cap_per_order=cap_exact,
            remaining_slots=remaining_slots,
            use_all_remaining=use_all_remaining,
            min_order_notional=(
                _cap_decimal("minimum order", min_order_usdt)
                if min_order_usdt is not None else None
            ),
            min_quantity=_filter_decimal(symbol, "minQtyExact", "minQty"),
            min_notional=_filter_decimal(
                symbol, "minNotionalExact", "minNotional"
            ),
            round_price=lambda value: _round_price_exact(symbol, value),
            round_quantity=lambda value: _round_qty_exact(symbol, value),
        )
        if planned is None:
            continue
        pr, qty, cost = planned.price, planned.quantity, planned.notional
        # Final fail-closed boundary immediately before exchange mutation.
        # This catches future planning regressions as well as remainder flags.
        exchange_notional = _cap_decimal(
            "exchange BUY notional",
            pr * qty,
        )
        if exchange_notional > cap_exact:
            log(
                f"[CAP-HARD-BLOCK] {symbol} exchange={exchange_notional} "
                f"> limit={cap_exact:.8f}"
            )
            continue
        if (min_order_usdt is not None) and (cost < Decimal(str(min_order_usdt))):
            log(f"[MIN-ORDER] skip BUY {fmt_qty_sym(symbol, qty)} @ {fmt_price_sym(symbol, pr)} "
                f"(≈{cost:.2f} USDT < {Decimal(str(min_order_usdt)):.2f})")
            continue

        try:
            if not running():
                log(f"[STOP] {symbol} BUY placement interrupted before exchange POST")
                break
            maker_flag = (
                buy_limit_maker or
                os.getenv("BUY_LIMIT_MAKER", "").lower() in ("1", "true", "yes")
            )
            trace = LatencyTrace(symbol, "buy-submit")
            if market_store is not None and market_policy is not None:
                trace.mark("market_event_received")
                trace.mark("feature_start")
                latest_snapshot = market_store.snapshot()
                upper_levels = [
                    Decimal(str(level))
                    for level in ladder_prices
                    if Decimal(str(level)) > pr
                ]
                ladder_edge_pct = (
                    (min(upper_levels) - pr) / pr
                    if upper_levels and pr > 0
                    else Decimal("0")
                )
                expected_gross_edge = max(
                    _profit_floor_pct(),
                    ladder_edge_pct,
                ) * Decimal("10000")
                gate = evaluate_snapshot_gate(
                    latest_snapshot,
                    decision_reference_price=decision_reference_price,
                    expected_edge_bps=expected_gross_edge,
                    fee_bps=(
                        (
                            max(
                                Decimal("0"),
                                getenv_decimal(
                                    "BOT_BUY_FEE_PCT",
                                    getenv_decimal(
                                        "BOT_FEE_PCT",
                                        DEFAULT_SPOT_FEE_PCT,
                                    ),
                                ),
                            )
                            + max(
                                Decimal("0"),
                                getenv_decimal(
                                    "BOT_SELL_FEE_PCT",
                                    getenv_decimal(
                                        "BOT_FEE_PCT",
                                        DEFAULT_SPOT_FEE_PCT,
                                    ),
                                ),
                            )
                        )
                        * Decimal("10000")
                    ),
                    slippage_bps=(
                        _non_fee_execution_cost_pct()
                        * Decimal("10000")
                    ),
                    policy=market_policy,
                    now_monotonic_ns=time.monotonic_ns(),
                )
                trace.mark("feature_end")
                trace.mark("risk_decision")
                if not gate.approved:
                    log(
                        f"[FAST-MARKET-{market_mode}] {symbol} BUY gate="
                        f"{','.join(gate.reasons)} age_ms="
                        f"{gate.snapshot_age_ms:.3f} move_bps="
                        f"{gate.price_move_bps:.3f} net_edge_bps="
                        f"{gate.net_edge_bps:.3f}"
                    )
                    if market_mode == "APPLY":
                        append_trace(trace)
                        continue
            otoco_prices = None
            if otoco_mode != "OFF":
                otoco_prices = _pick_ladder_aligned_oco_prices(
                    symbol,
                    ladder_prices,
                    pr,
                    stop_limit_offset_pct,
                )
                if otoco_mode == "SHADOW":
                    log(
                        f"[OTOCO-SHADOW] {symbol} BUY="
                        f"{fmt_price_sym(symbol, pr)} TP="
                        f"{fmt_price_sym(symbol, otoco_prices[0])} STOP="
                        f"{fmt_price_sym(symbol, otoco_prices[1])}"
                    )
            if live_mode and not inventory_buy_allowed(exchange_notional):
                append_trace(trace)
                continue
            # IMPORTANT: place the order at the rounded price pr.
            if otoco_mode == "APPLY":
                if live_mode and os.getenv("BOT_OTOCO_APPROVED") != "YES":
                    raise RuntimeError(
                        "OTOCO APPLY requires BOT_OTOCO_APPROVED=YES"
                    )
                if otoco_prices is None:
                    raise RuntimeError("OTOCO prices are unavailable")
                j = place_otoco_buy(
                    symbol,
                    qty,
                    pr,
                    otoco_prices[0],
                    otoco_prices[1],
                    otoco_prices[2],
                    maker=maker_flag,
                    latency_trace=trace,
                )
            else:
                j = place_limit_order(
                    "BUY",
                    symbol,
                    qty,
                    pr,
                    maker=maker_flag,
                    latency_trace=trace,
                    maximum_notional=local_cap,
                )
            if j:
                oid = int(j.get("orderId"))
                placed_ids.append(oid)
                # Use the submitted values because the final exchange-filter
                # boundary can raise a BUY to the minimum notional.
                try:
                    submitted_notional = (
                        Decimal(str(j.get("origQty")))
                        * Decimal(str(j.get("price")))
                    )
                except (ArithmeticError, TypeError, ValueError):
                    submitted_notional = local_cap
                if (
                    not submitted_notional.is_finite()
                    or submitted_notional <= 0
                    or submitted_notional > local_cap
                ):
                    submitted_notional = local_cap
                usdt_free = max(Decimal("0"), usdt_free - submitted_notional)
                local_inventory_commitments[oid] = submitted_notional
                # Deduplicate by the already rounded price.
                existing_buy_prices.add(pr)
            append_trace(trace)
        except UncertainOrderSubmission as exc:
            # One unknown mutation invalidates every later inventory decision.
            # Stop this batch before another BUY can cross the absolute CAP.
            append_trace(trace)
            log(
                f"[BUY-BATCH-HALT] {symbol} price={fmt_price_sym(symbol, pr)} "
                f"reason={type(exc).__name__}"
            )
            break
        except (requests.RequestException, RuntimeError, ValueError, OSError) as exc:
            log(
                f"[BUY-PLACE-ERR] {symbol} price={fmt_price_sym(symbol, pr)} "
                f"reason={type(exc).__name__}"
            )

    return placed_ids
