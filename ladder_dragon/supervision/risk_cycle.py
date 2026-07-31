# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: coordinate authoritative risk snapshots and exact risk calculations.

"""Exact risk calculations shared by the supervisor runtime."""

from decimal import Decimal
import os
import sqlite3
import time
from typing import Any, Dict, List, Mapping, Sequence

import requests

from ladder_dragon.risk.risk_manager import (
    RiskLimits,
    RiskSnapshot,
    money,
)
from ladder_dragon.risk.risk_statistics import (
    conversion_price_decimal,
    correlation_clusters_multi_window,
    covariance_var,
    expected_shortfall,
    liquidity_is_sufficient_decimal,
    marginal_risk_contribution_decimal,
    stress_loss_decimal,
)
from ladder_dragon.supervision.entry_policy import finite_decimal


def initial_runtime_risk_gate(
    *,
    live: bool,
    persistent_halt: bool,
) -> dict[str, object]:
    """Publish a fail-closed LIVE state until the first risk snapshot exists."""
    if not live:
        return {
            "state": "RUNNING",
            "buy_blocked": False,
            "halted": False,
            "reasons": (),
        }
    if persistent_halt:
        reasons = ("persistent circuit halt requires authoritative evaluation",)
    else:
        reasons = ("authoritative risk snapshot pending",)
    return {
        "state": "RISK_PENDING",
        "buy_blocked": True,
        "halted": persistent_halt,
        "reasons": reasons,
    }


def initial_runtime_risk_status(
    *,
    live: bool,
    persistent_halt: bool,
) -> dict[str, object]:
    """Return the startup heartbeat fields for the initial risk gate."""
    gate = initial_runtime_risk_gate(
        live=live,
        persistent_halt=persistent_halt,
    )
    return {
        "state": str(gate["state"]),
        "risk": {
            "buy_blocked": bool(gate["buy_blocked"]),
            "halted": bool(gate["halted"]),
            "reasons": list(gate["reasons"]),
        },
    }


def _runtime_dependency(runtime: Mapping[str, object], name: str) -> Any:
    """Resolve one explicit runtime adapter required by the risk coordinator."""
    try:
        return runtime[name]
    except KeyError as exc:
        raise RuntimeError(f"risk runtime dependency is unavailable: {name}") from exc


def remaining_order_budget_decimal(
    limits: RiskLimits,
    snapshot: RiskSnapshot,
) -> Decimal:
    """Return the smallest exact budget remaining across all BUY gates."""
    return min(
        money(limits.portfolio_cap_usdt) - money(snapshot.exposure_usdt),
        money(limits.daily_buy_cap_usdt) - money(snapshot.daily_buy_usdt),
        money(limits.correlated_cap_usdt)
        - money(snapshot.correlated_exposure_usdt),
        money(snapshot.free_usdt) - money(limits.reserve_usdt),
    )


def configured_price_shocks_decimal(
    symbols: Sequence[str],
    current_prices: Mapping[str, object],
    previous_prices: Mapping[str, object],
    threshold: object,
) -> tuple[list[str], dict[str, Decimal]]:
    """Detect configured-symbol shocks without mixing valuation price types."""
    threshold_exact = abs(finite_decimal(threshold, name="risk shock threshold"))
    normalized: dict[str, Decimal] = {}
    reasons: list[str] = []
    for raw_symbol in symbols:
        symbol = str(raw_symbol).upper()
        if symbol not in current_prices:
            continue
        current = finite_decimal(
            current_prices[symbol],
            name=f"{symbol} current shock price",
        )
        normalized[symbol] = current
        if symbol not in previous_prices:
            continue
        previous = finite_decimal(
            previous_prices[symbol],
            name=f"{symbol} previous shock price",
        )
        if current <= 0 or previous <= 0:
            continue
        change = abs(current / previous - Decimal("1"))
        if change >= threshold_exact:
            reasons.append(f"{symbol} moved {change:.2%}")
    return reasons, normalized

def build_risk_snapshot(
    symbols: List[str], limits: RiskLimits, *, runtime: Mapping[str, object]
) -> tuple[RiskSnapshot, List[Dict[str, Any]], Dict[str, object]]:
    """Build one authoritative risk snapshot from injected runtime adapters."""
    env_flag = _runtime_dependency(runtime, "env_flag")
    sync_recent_account_fills = _runtime_dependency(
        runtime, "_sync_recent_account_fills"
    )
    get_balances_full = _runtime_dependency(runtime, "get_balances_full")
    get_last_price = _runtime_dependency(runtime, "get_last_price")
    tools_market = _runtime_dependency(runtime, "TM")
    live_mode = bool(_runtime_dependency(runtime, "LIVE_MODE"))
    runtime_protection_gate = _runtime_dependency(
        runtime, "_runtime_protection_gate"
    )
    exact_decimal = _runtime_dependency(runtime, "_finite_decimal")
    symbol_assets = _runtime_dependency(runtime, "symbol_assets")
    configured_unvalued_assets = _runtime_dependency(
        runtime, "_configured_unvalued_assets"
    )
    get_last_price_decimal = _runtime_dependency(runtime, "get_last_price_decimal")
    control_mode = _runtime_dependency(runtime, "_control_mode")
    get_exchange_filters_cached = _runtime_dependency(runtime, "get_exchange_filters_cached")
    analytics_float = _runtime_dependency(runtime, "_analytics_float")
    correlated_symbols_multi_window = _runtime_dependency(
        runtime, "derive_correlated_symbols_multi_window"
    )
    load_trade_metrics = _runtime_dependency(
        runtime, "load_daily_trade_metrics"
    )
    log_info_rate_limited = _runtime_dependency(
        runtime, "_log_info_rate_limited"
    )

    if env_flag("RISK_RECONCILE_SYNC_FILLS", True):
        sync_recent_account_fills(symbols)
    balances = get_balances_full()
    prices = {symbol: get_last_price(symbol) for symbol in symbols}
    orders = tools_market._signed_get("/api/v3/openOrders") or []
    if live_mode:
        runtime_protection_gate(symbols, limits)

    # Strict reconciliation prevents a risk snapshot from mixing divergent
    # Binance account and local inventory-ledger data.
    if env_flag("RISK_RECONCILE_STRICT", True):
        tolerance = max(
            Decimal("0"),
            exact_decimal(
                os.getenv("RISK_RECONCILE_TOLERANCE_PCT", "0.02") or "0.02",
                name="reconciliation tolerance",
            ),
        )
        grace_sec = max(0.0, analytics_float(os.getenv("RISK_RECONCILE_GRACE_SEC", "5") or 5))
        retry_sec = max(0.05, analytics_float(os.getenv("RISK_RECONCILE_RETRY_SEC", "0.25") or 0.25))
        dust_steps = max(
            Decimal("0"),
            exact_decimal(
                os.getenv("RISK_RECONCILE_DUST_STEPS", "1") or "1",
                name="reconciliation dust steps",
            ),
        )
        deadline = time.monotonic() + grace_sec
        waited = False
        while True:
            with sqlite3.connect(f"file:{os.environ['BOT_STATS_DB']}?mode=ro", uri=True, timeout=5) as con:
                exact_inventory_view = con.execute(
                    "SELECT 1 FROM sqlite_master WHERE type='view' "
                    "AND name='inventory_exact'"
                ).fetchone()
                inventory_source = (
                    "SELECT symbol,qty_text FROM inventory_exact"
                    if exact_inventory_view
                    else "SELECT symbol,CAST(qty AS TEXT) FROM inventory"
                )
                inventory = {
                    str(symbol).upper(): exact_decimal(qty, name="ledger quantity")
                    for symbol, qty in con.execute(inventory_source).fetchall()
                }
            mismatches = []
            for symbol in symbols:
                base, _ = symbol_assets(symbol)
                account_qty = exact_decimal(
                    balances.get(base, {}).get("free", "0"), name="account free quantity"
                ) + exact_decimal(
                    balances.get(base, {}).get("locked", "0"), name="account locked quantity"
                )
                db_qty = inventory.get(symbol)
                filter_values = get_exchange_filters_cached(symbol)
                step_size = max(
                    Decimal("0"),
                    exact_decimal(
                        filter_values.get("stepSizeExact", filter_values.get("stepSize", "0")),
                        name="symbol quantity step",
                    ),
                )
                allowed = max(
                    Decimal("0.00000001"),
                    abs(account_qty) * tolerance,
                    step_size * dust_steps,
                )
                if db_qty is None:
                    if account_qty > allowed:
                        mismatches.append(f"{symbol}: account={account_qty:.8f}, ledger=missing")
                    continue
                if abs(account_qty - db_qty) > allowed:
                    mismatches.append(f"{symbol}: account={account_qty:.8f}, ledger={db_qty:.8f}")
            if not mismatches:
                break
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise RuntimeError("position reconciliation failed: " + "; ".join(mismatches))
            waited = True
            time.sleep(min(retry_sec, remaining))
            balances = get_balances_full()
        if waited:
            # While the ledger catches up, a worker may create an OCO. Reload
            # orders so exposure and order counts refer to one point in time.
            orders = tools_market._signed_get("/api/v3/openOrders") or []

    # Risk valuation must cover the whole account, not only strategy symbols.
    # Otherwise old or manual positions in another asset disappear from equity,
    # drawdown and portfolio CAP.
    stable_assets = {"USDT", "USDC", "FDUSD", "BUSD", "TUSD", "DAI"}
    unvalued_assets = configured_unvalued_assets()
    asset_values: Dict[str, Decimal] = {}
    equity = Decimal("0")
    holdings_exposure = Decimal("0")
    for asset, balance in balances.items():
        asset = str(asset).upper()
        qty = money(balance.get("free", 0)) + money(balance.get("locked", 0))
        if qty <= 0:
            continue
        if asset in stable_assets:
            value = qty
        else:
            # Try direct USDT first, then common cross-quotes. Stablecoin
            # conversion includes the configured haircut and exit fee.
            valuation_symbol = f"{asset}USDT"
            valuation_price = prices.get(valuation_symbol)
            if valuation_price is None:
                for quote in ("USDC", "FDUSD", "BTC", "ETH"):
                    candidate = f"{asset}{quote}"
                    try:
                        candidate_price = get_last_price_decimal(candidate)
                        if env_flag("RISK_CONVERSION_DEPTH_REQUIRED", False):
                            depth = tools_market._public_get(
                                "/api/v3/depth",
                                {"symbol": candidate, "limit": 20},
                            ) or {}
                            bid_levels = [(row[0], row[1]) for row in depth.get("bids", [])]
                            ask_levels = [(row[0], row[1]) for row in depth.get("asks", [])]
                            candidate_price = conversion_price_decimal(
                                asset_qty=qty, side="SELL",
                                bids=bid_levels, asks=ask_levels,
                                fee_pct=os.getenv("RISK_CONVERSION_FEE_PCT", "0.001"),
                            )
                    except (
                        RuntimeError,
                        ValueError,
                        KeyError,
                        requests.RequestException,
                    ):
                        continue
                    if candidate_price > 0:
                        if quote in stable_assets:
                            haircut = max(
                                Decimal("0"),
                                money(os.getenv("RISK_STABLECOIN_HAIRCUT_PCT", "0.002")),
                            )
                            candidate_price *= max(Decimal("0"), Decimal("1") - haircut)
                        else:
                            bridge = (
                                prices.get(f"{quote}USDT")
                                or get_last_price_decimal(f"{quote}USDT")
                            )
                            candidate_price *= money(bridge)
                        valuation_price = candidate_price
                        prices[valuation_symbol] = valuation_price
                        break
            if money(valuation_price) <= 0:
                if asset in unvalued_assets:
                    log_info_rate_limited(
                        f"unvalued-allowlisted:{asset}",
                        f"[RISK] unvalued asset {asset} explicitly allowlisted; "
                        "excluded from equity and exposure",
                        interval_sec=max(
                            60.0,
                            analytics_float(
                                os.getenv(
                                    "RISK_STABLE_INFO_LOG_INTERVAL_SEC",
                                    "3600",
                                )
                                or "3600"
                            ),
                        ),
                    )
                    continue
                raise RuntimeError(f"cannot value account asset {asset}")
            value = qty * money(valuation_price)
        asset_values[asset] = value
        equity += value
        if asset not in stable_assets:
            # Cash/reserve belongs to equity, but is not market exposure.
            holdings_exposure += value

    open_buy = sum(
        money(order.get("price")) * money(order.get("origQty"))
        for order in orders
        if str(order.get("side", "")).upper() == "BUY"
    )
    exposure = holdings_exposure + open_buy
    exposure_by_symbol = {
        symbol: asset_values.get(symbol_assets(symbol)[0], Decimal("0"))
        + sum(
            (
                money(order.get("price")) * money(order.get("origQty"))
                for order in orders
                if str(order.get("symbol", "")).upper() == symbol
                and str(order.get("side", "")).upper() == "BUY"
            ),
            Decimal("0"),
        )
        for symbol in symbols
    }
    correlated_symbols = {
        value.strip().upper()
        for value in os.getenv("RISK_CORRELATED_SYMBOLS", ",".join(symbols)).split(",")
        if value.strip()
    }
    histories: Dict[str, list[tuple[int, float]]] = {}
    correlation_mode = os.getenv(
        "RISK_CORRELATION_MODE",
        "rolling",
    ).lower()
    window = max(
        3,
        int(os.getenv("RISK_CORRELATION_WINDOW", "48") or 48),
    )
    var_enabled = money(limits.var_cap_usdt) > 0
    if (
        (correlation_mode == "rolling" and len(symbols) > 1)
        or var_enabled
    ):
        for symbol in symbols:
            klines = tools_market.get_klines(
                symbol,
                "15m",
                limit=min(1000, window * 2 + 1),
            )
            closes = [
                (int(row[0]), analytics_float(row[4]))
                for row in klines
                if (
                    len(row) > 4
                    and analytics_float(row[4]) > 0
                )
            ]
            if len(closes) >= 4:
                histories[symbol] = closes
        if var_enabled:
            missing_var_history = sorted(
                symbol
                for symbol in symbols
                if exposure_by_symbol.get(symbol, Decimal("0")) > 0
                and symbol not in histories
            )
            if missing_var_history:
                raise RuntimeError(
                    "VaR history unavailable for configured exposure: "
                    + ",".join(missing_var_history)
                )
    if correlation_mode == "rolling" and len(symbols) > 1:
        threshold = analytics_float(
            os.getenv("RISK_CORRELATION_THRESHOLD", "0.70") or 0.70
        )
        rolling = correlated_symbols_multi_window(
            histories, threshold=threshold,
            windows=(max(3, window // 2), window, window * 2), min_windows=2,
        )
        if rolling:
            correlated_symbols = rolling
    correlation_clusters = correlation_clusters_multi_window(
        histories,
        threshold=analytics_float(
            os.getenv("RISK_CORRELATION_THRESHOLD", "0.70") or "0.70"
        ),
        windows=(
            max(
                3,
                int(os.getenv("RISK_CORRELATION_WINDOW", "48") or "48")
                // 2,
            ),
            max(3, int(os.getenv("RISK_CORRELATION_WINDOW", "48") or "48")),
            max(3, int(os.getenv("RISK_CORRELATION_WINDOW", "48") or "48"))
            * 2,
        ),
        min_windows=2,
    )
    correlated = sum(
        asset_values.get(symbol_assets(symbol)[0], Decimal("0"))
        for symbol in symbols if symbol in correlated_symbols
    ) + sum(
        money(order.get("price")) * money(order.get("origQty"))
        for order in orders
        if str(order.get("side", "")).upper() == "BUY"
        and str(order.get("symbol", "")).upper() in correlated_symbols
    )

    metrics = load_trade_metrics(os.environ["BOT_STATS_DB"], symbols)
    stale_limit = max(0, int(os.getenv("RISK_STALE_ORDER_MAX_SEC", "0") or 0))
    stale_count = 0
    if stale_limit > 0:
        now_ms = int(time.time() * 1000)
        stale_count = sum(
            1 for order in orders
            if now_ms - int(order.get("updateTime") or order.get("time") or now_ms) > stale_limit * 1000
        )
    cluster_exposure = {
        ",".join(cluster): sum(
            (exposure_by_symbol.get(symbol, Decimal("0")) for symbol in cluster),
            Decimal("0"),
        )
        for cluster in correlation_clusters
    }
    liquidity_blocked: list[str] = []
    if control_mode("RISK_CLUSTER_GATE_MODE") != "OFF":
        max_spread_bps = os.getenv(
            "RISK_MAX_SYMBOL_SPREAD_BPS", "20"
        ) or "20"
        min_depth_quote = os.getenv(
            "RISK_MIN_SYMBOL_DEPTH_QUOTE", "5000"
        ) or "5000"
        for symbol in symbols:
            try:
                depth = tools_market._public_get(
                    "/api/v3/depth",
                    {"symbol": symbol, "limit": 20},
                )
                bids = depth.get("bids") if isinstance(depth, Mapping) else None
                asks = depth.get("asks") if isinstance(depth, Mapping) else None
                if (
                    not isinstance(bids, list)
                    or not isinstance(asks, list)
                    or not bids
                    or not asks
                ):
                    raise ValueError("depth is incomplete")
                bid_depth = sum(
                    (
                        exact_decimal(row[0], name="bid price")
                        * exact_decimal(row[1], name="bid quantity")
                        for row in bids
                        if isinstance(row, (list, tuple)) and len(row) >= 2
                    ),
                    Decimal("0"),
                )
                ask_depth = sum(
                    (
                        exact_decimal(row[0], name="ask price")
                        * exact_decimal(row[1], name="ask quantity")
                        for row in asks
                        if isinstance(row, (list, tuple)) and len(row) >= 2
                    ),
                    Decimal("0"),
                )
                if not liquidity_is_sufficient_decimal(
                    best_bid=bids[0][0],
                    best_ask=asks[0][0],
                    bid_depth_quote=bid_depth,
                    ask_depth_quote=ask_depth,
                    max_spread_bps=max_spread_bps,
                    min_depth_quote=min_depth_quote,
                ):
                    liquidity_blocked.append(symbol)
            except (
                ArithmeticError,
                KeyError,
                RuntimeError,
                TypeError,
                ValueError,
                requests.RequestException,
            ):
                liquidity_blocked.append(symbol)
    stress = stress_loss_decimal(
        exposure_by_symbol,
        price_shock=os.getenv("RISK_STRESS_PRICE_SHOCK", "-0.05"),
        spread_widening=os.getenv("RISK_STRESS_SPREAD_PCT", "0.01"),
    )
    analytics_exposure = {
        symbol: analytics_float(value) for symbol, value in exposure_by_symbol.items()
    }
    var_value = covariance_var(analytics_exposure, histories,
                               confidence=analytics_float(os.getenv("RISK_VAR_CONFIDENCE", "0.99")))
    # Gap risk includes an overnight jump, spread widening and execution latency.
    # The gap scenario is conservatively scaled by execution delay.
    gap_shock = abs(money(os.getenv("RISK_GAP_SHOCK_PCT", "0.10")))
    latency_bars = max(Decimal("1"), money(os.getenv("RISK_LATENCY_BARS", "1")))
    gap_value = sum(
        marginal_risk_contribution_decimal(
            exposure_by_symbol, shock=gap_shock * latency_bars
        ).values(),
        Decimal("0"),
    )
    scenario_losses_exact = [
        stress_loss_decimal(
            exposure_by_symbol, price_shock=shock,
            spread_widening=os.getenv("RISK_STRESS_SPREAD_PCT", "0.01"),
        )
        for shock in ("-0.03", "-0.05", "-0.10", "-0.15")
    ]
    scenario_losses = [analytics_float(value) for value in scenario_losses_exact]
    es_value = expected_shortfall(scenario_losses,
                                  confidence=analytics_float(os.getenv("RISK_ES_CONFIDENCE", "0.75")))
    snap = RiskSnapshot(
        equity_usdt=equity,
        exposure_usdt=exposure,
        free_usdt=money(balances.get("USDT", {}).get("free", 0)),
        open_order_count=len(orders),
        correlated_exposure_usdt=correlated,
        stress_loss_usdt=money(stress),
        var_usdt=money(var_value),
        gap_risk_usdt=money(gap_value),
        expected_shortfall_usdt=money(es_value),
        stale_order_count=stale_count,
        symbol_exposure_usdt={symbol: money(value) for symbol, value in exposure_by_symbol.items()},
        correlation_clusters=correlation_clusters,
        cluster_exposure_usdt=cluster_exposure,
        liquidity_blocked_symbols=tuple(sorted(set(liquidity_blocked))),
        **metrics,
    )
    return snap, orders, prices
