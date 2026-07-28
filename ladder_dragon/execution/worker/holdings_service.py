# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: keep holdings-sale policy independent from worker orchestration.

"""Holdings exit policy and placement service."""

from __future__ import annotations

from typing import Any, List, Mapping, Optional, Sequence


def effective_remainder_policy(*, requested: bool, live_mode: bool) -> bool:
    """Never allow remainder allocation to bypass per-order CAP in LIVE."""
    return bool(requested and not live_mode)


def protection_state_after_sweep(
    pending_before: Sequence[int],
    remaining: Sequence[int],
    terminal_unfilled: set[int],
) -> str:
    """Summarize protection without calling a zero-fill cancellation pending."""
    if remaining:
        return "pending"
    if pending_before and set(pending_before).issubset(terminal_unfilled):
        return "not_needed"
    return "confirmed" if pending_before else "not_needed"


def _runtime_dependency(runtime: Mapping[str, object], name: str) -> Any:
    """Resolve one explicit worker adapter for holdings placement."""
    try:
        return runtime[name]
    except KeyError as exc:
        raise RuntimeError(
            f"holdings runtime dependency is unavailable: {name}"
        ) from exc


def place_sells_from_holdings(
    symbol: str,
    ladder_prices: List[float],
    max_oco_per_symbol: Optional[int] = None,
    *,
    enforce_limit: bool = False,
    avg_entry_px: Optional[float] = None,
    panic_active: bool = False,
    sell_limit_maker: bool = False,
    panic_sell_floor_pct: Optional[float] = None,
    runtime: Mapping[str, object],
) -> int:
    """Place holdings exits through explicit worker adapters."""
    BinanceResponseError = _runtime_dependency(runtime, 'BinanceResponseError')
    Decimal = _runtime_dependency(runtime, 'Decimal')
    _clear_safety_control_failure = _runtime_dependency(runtime, '_clear_safety_control_failure')
    _holdings_cost_basis_covered = _runtime_dependency(runtime, '_holdings_cost_basis_covered')
    _profit_floor_pct = _runtime_dependency(runtime, '_profit_floor_pct')
    _record_safety_control_failure = _runtime_dependency(runtime, '_record_safety_control_failure')
    dbg = _runtime_dependency(runtime, 'dbg')
    existing_prices_decimal = _runtime_dependency(runtime, 'existing_prices_decimal')
    fmt_price_sym = _runtime_dependency(runtime, 'fmt_price_sym')
    fmt_qty_sym = _runtime_dependency(runtime, 'fmt_qty_sym')
    get_balances = _runtime_dependency(runtime, 'get_balances')
    get_price_exact = _runtime_dependency(runtime, 'get_price_exact')
    get_symbol_assets = _runtime_dependency(runtime, 'get_symbol_assets')
    guarded_sell_levels_decimal = _runtime_dependency(runtime, 'guarded_sell_levels_decimal')
    list_open_orders = _runtime_dependency(runtime, 'list_open_orders')
    log = _runtime_dependency(runtime, 'log')
    os = _runtime_dependency(runtime, 'os')
    place_limit_order = _runtime_dependency(runtime, 'place_limit_order')
    place_market_order = _runtime_dependency(runtime, 'place_market_order')
    plan_sell_order_decimal = _runtime_dependency(runtime, 'plan_sell_order_decimal')
    price_round_mode = _runtime_dependency(runtime, 'price_round_mode')
    pull_filters = _runtime_dependency(runtime, 'pull_filters')
    requests = _runtime_dependency(runtime, 'requests')
    round_step = _runtime_dependency(runtime, 'round_step')
    symbol_filters = _runtime_dependency(runtime, 'symbol_filters')
    validate_limit_sell_prices = _runtime_dependency(runtime, 'validate_limit_sell_prices')
    base, _ = get_symbol_assets(symbol)
    bals = get_balances()
    base_free = Decimal(str(bals.get(base, {}).get("free", "0")))
    if not base_free.is_finite():
        log(f"[HOLD-SELL-BLOCK] {symbol} non-finite free balance")
        return 0
    if base_free <= 0:
        dbg(f"[HOLD-SELL] {symbol} no free base (free={fmt_qty_sym(symbol, base_free)})")
        return 0
    pull_filters(symbol)

    # In panic, normal SELL levels can remain above the market indefinitely.
    # For legacy inventory without OCO, enable emergency market flattening (LIVE
    # by default), otherwise the position remains without a protective exit.
    if panic_active and os.getenv("PANIC_FLATTEN_HOLDINGS", "1").lower() in ("1", "true", "yes"):
        panic_qty = round_step(
            base_free,
            symbol_filters[symbol].get(
                "stepSizeExact", str(symbol_filters[symbol]["stepSize"])
            ),
            "floor",
        )
        if panic_qty > 0:
            try:
                result = place_market_order(symbol, "SELL", panic_qty,
                                            ref_price=get_price_exact(symbol),
                                            filters=symbol_filters.get(symbol))
                log(f"[PANIC-FLATTEN] {symbol} qty≈{fmt_qty_sym(symbol, panic_qty)} result={bool(result)}")
                return 1 if result else 0
            except (RuntimeError, ValueError, OSError) as exc:
                log(f"[PANIC-FLATTEN-ERR] {symbol}: {exc}")

    verified_average = _holdings_cost_basis_covered(symbol, bals)
    if verified_average is None:
        return 0
    # Normal holdings management uses the average reconstructed from exact,
    # sourced FIFO lots. A caller-provided historical average cannot authorize
    # or price a SELL for legacy inventory.
    average_entry = Decimal(str(verified_average))

    now = get_price_exact(symbol)
    decimal_levels = [Decimal(str(price)) for price in ladder_prices]
    if not any(price > now for price in decimal_levels):
        dbg(f"[HOLD-SELL] {symbol} no upper ladder above market (now≈{fmt_price_sym(symbol, now)})")
        return 0

    def round_price_exact(value: Decimal) -> Decimal:
        return round_step(
            value,
            symbol_filters[symbol].get(
                "tickSizeExact", str(symbol_filters[symbol]["tickSize"])
            ),
            price_round_mode(),
        )

    def round_quantity_exact(value: Decimal) -> Decimal:
        return round_step(
            value,
            symbol_filters[symbol].get(
                "stepSizeExact", str(symbol_filters[symbol]["stepSize"])
            ),
            "down",
        )

    minimum_quantity = Decimal(str(symbol_filters[symbol].get(
        "minQtyExact", symbol_filters[symbol]["minQty"]
    )))
    minimum_notional_exact = Decimal(str(symbol_filters[symbol].get(
        "minNotionalExact", symbol_filters[symbol]["minNotional"]
    )))

    # Collect existing SELL orders above the market and calculate how many new ones
    # are allowed.
    existing_sell_prices: set[Decimal] = set()
    allowed_new: Optional[int] = None
    if enforce_limit and (max_oco_per_symbol is not None):
        try:
            oo = list_open_orders(symbol) or []
        except (requests.RequestException, RuntimeError, ValueError) as exc:
            log(f"[HOLD-SELL-BLOCK] {symbol} open-order state unavailable: {type(exc).__name__}")
            return 0
        existing_sell_prices = existing_prices_decimal(
            oo,
            side="SELL",
            now_price=now,
            round_price=round_price_exact,
        )
        existing_cnt = len(existing_sell_prices)
        allowed_new = max(0, int(max_oco_per_symbol) - existing_cnt)
        log(f"[SELL-LIMIT] {symbol} existing_sell={existing_cnt} max_oco={int(max_oco_per_symbol)} → allow_new={allowed_new}")
        if allowed_new <= 0:
            return 0

    limit = allowed_new if enforce_limit else max_oco_per_symbol
    upper_guarded = guarded_sell_levels_decimal(
        decimal_levels,
        now_price=now,
        occupied_prices=existing_sell_prices if enforce_limit else set(),
        round_price=round_price_exact,
        limit=limit,
        average_entry=average_entry,
        panic_active=panic_active,
        panic_floor_pct=(
            None if panic_sell_floor_pct is None
            else Decimal(str(panic_sell_floor_pct))
        ),
        profit_floor_pct=_profit_floor_pct(),
    )
    if not upper_guarded:
        dbg(f"[HOLD-SELL] {symbol} empty after limits/GUARD")
        return 0

    # Validate the whole holdings plan before the first signed mutation. The
    # shared order boundary repeats this check for each final rounded SELL.
    try:
        validate_limit_sell_prices(symbol, list(upper_guarded))
        _clear_safety_control_failure("holdings-sell-filter", symbol)
    except (KeyError, TypeError, ValueError, ArithmeticError, RuntimeError, requests.RequestException) as exc:
        _record_safety_control_failure("holdings-sell-filter", symbol, exc)
        log(
            f"[HOLD-SELL-FILTER-BLOCK] {symbol} SELL mutation blocked: "
            f"{type(exc).__name__}"
        )
        return 0

    # Floor-to-step at each placement leaves only unavoidable sub-step dust.
    qty_left = max(Decimal("0"), base_free)
    if qty_left <= 0:
        dbg(f"[HOLD-SELL] {symbol} sellable≈{fmt_qty_sym(symbol, qty_left)} "
            f"(free={fmt_qty_sym(symbol, base_free)})")
        return 0

    n = len(upper_guarded)
    if n <= 0:
        dbg(f"[HOLD-SELL] {symbol} empty after GUARD/push (no unique levels above now)")
        return 0

    placed = 0
    share = qty_left / Decimal(n)

    for idx, p in enumerate(upper_guarded, start=1):
        if qty_left <= 0:
            break

        minimum_notional = minimum_notional_exact
        planned = plan_sell_order_decimal(
            p,
            quantity_left=qty_left,
            share=share,
            is_last=idx == n,
            min_quantity=minimum_quantity,
            min_notional=minimum_notional,
            round_quantity=round_quantity_exact,
        )
        if planned is None:
            need_q = round_quantity_exact(max(
                minimum_notional / p,
                minimum_quantity,
            ))
            dbg(f"[HOLD-SELL] {symbol} skip: remaining quantity cannot reach min {minimum_notional:.2f} "
                f"at {fmt_price_sym(symbol, p)} (need≥{fmt_qty_sym(symbol, need_q)})")
            continue
        q = planned.quantity

        try:
            maker_flag = (
                sell_limit_maker or
                os.getenv("SELL_LIMIT_MAKER", "").lower() in ("1", "true", "yes")
            )
            j = place_limit_order("SELL", symbol, q, p, maker=maker_flag)
            if j:
                oid = j.get("orderId")
                log(f"[HOLD-SELL] {symbol} placed {fmt_qty_sym(symbol, q)} @ {fmt_price_sym(symbol, p)} (order {oid})")
                qty_left = max(Decimal("0"), qty_left - planned.quantity)
                placed += 1
        except BinanceResponseError as exc:
            # A filter/business rejection is definitive. Stop this ladder pass
            # instead of retrying every level or converting it into a lost ACK.
            log(
                f"[HOLD-SELL-REJECTED] {symbol} status={exc.status} "
                f"code={exc.code} message={exc.binance_message or 'request rejected'}"
            )
            break
        except requests.RequestException as exc:
            # Network ambiguity is already recorded and halted by the order
            # layer. Avoid additional submissions during the same pass.
            log(f"[HOLD-SELL-ERROR] {symbol} network={exc.__class__.__name__}")
            break
        except (RuntimeError, ValueError, OSError) as exc:
            log(f"[HOLD-SELL-ERROR] {symbol} error={exc.__class__.__name__}")
            break

    return placed
