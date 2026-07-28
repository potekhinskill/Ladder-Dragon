#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: plan and execute the spot ladder for one symbol.
"""Ladder Dragon worker runtime."""
from __future__ import annotations

import os
import json
import sys
import time
import signal
import sqlite3
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from ladder_dragon.execution import tools_market as TM
from ladder_dragon.execution.order_recovery import (
    TERMINAL_EXCHANGE_STATES,
    OrderIntent,
    OrderJournal,
)
from ladder_dragon.execution.exchange_math import format_step, round_step
from ladder_dragon.execution.exchange_filters import (
    filter_map as exchange_filter_map,
    symbol_row as exchange_symbol_row,
    validate_sell_percent_prices,
)
from ladder_dragon.risk.risk_manager import create_manual_halt
from ladder_dragon.execution.time_safety import assess_exchange_clock
from ladder_dragon.execution.user_stream import (
    BinanceUserDataObserver,
    OrderEventMailbox,
    reconciliation_due,
)
from ladder_dragon.execution.execution_latency import (
    append_execution_latency_sample,
)
from ladder_dragon.execution.latency_trace import LatencyTrace
from ladder_dragon.execution.market_data_stream import (
    BinanceMarketDataObserver,
    DecisionFreshnessPolicy,
    MarketSnapshotStore,
    evaluate_snapshot_gate,
)
from ladder_dragon.execution.websocket_trading import (
    BinanceWebSocketTradingTransport,
    WS_METHODS,
    build_websocket_trading_transport,
)
from product_version import product_label, user_agent
from ladder_dragon.execution.executor_config import build_executor_parser, validate_executor_args
from ladder_dragon.strategy.strategy_math import atr_from_klines as _atr_from_klines
from ladder_dragon.strategy.strategy_math import clamp, ema_value as _ema, panic_triggered as panic_raw
from ladder_dragon.strategy.strategy_math import shift_buy_levels
from ladder_dragon.strategy.expectancy_controls import (
    exact_decimal,
    vwap_premium_blocked,
)
from ladder_dragon.numeric_compat import compatibility_float as _compat_float
from ladder_dragon.execution.binance_transport import (
    BinanceResponseError,
    BinanceTransport,
)
from ladder_dragon.execution.executor_market import get_balances as market_get_balances
from ladder_dragon.execution.executor_market import get_price as market_get_price
from ladder_dragon.execution.executor_market import get_price_decimal as market_get_price_decimal
from ladder_dragon.execution.executor_market import get_symbol_assets as market_get_symbol_assets
from ladder_dragon.execution.orders.runtime import OrderDependencies
from ladder_dragon.execution.orders.runtime import place_limit_order as orders_place_limit_order
from ladder_dragon.execution.orders.runtime import place_market_order as orders_place_market_order
from ladder_dragon.execution.orders.runtime import place_oco_sell as orders_place_oco_sell
from ladder_dragon.execution.orders.runtime import place_otoco_buy as orders_place_otoco_buy
from ladder_dragon.execution.executor_planning import (
    buy_candidates,
    existing_prices,
    existing_prices_decimal,
    guarded_sell_levels,
    guarded_sell_levels_decimal,
    plan_sell_order_decimal,
    buy_candidates_decimal,
    plan_buy_order_decimal,
)
from ladder_dragon.execution.executor_planning import plan_buy_order
from ladder_dragon.execution.protection.runtime import (
    BreakevenRuntime,
    BreakevenStateStore,
    ProtectionConfig,
    ProtectionDependencies,
    maintain_breakeven,
    protect_filled_buys,
    emergency_gap_flatten,
)
from ladder_dragon.execution.executor_runtime import (
    status_due,
    trading_wakeups,
)
from ladder_dragon.execution.executor_recovery import RecoveryDependencies
from ladder_dragon.execution.executor_recovery import cancel_oco as recovery_cancel_oco
from ladder_dragon.execution.executor_recovery import cancel_order as recovery_cancel_order
from ladder_dragon.execution.executor_recovery import get_order as recovery_get_order
from ladder_dragon.execution.executor_recovery import get_order_by_client_id as recovery_get_order_by_client_id
from ladder_dragon.execution.executor_recovery import get_order_list_by_client_id as recovery_get_order_list_by_client_id
from ladder_dragon.execution.executor_recovery import list_open_orders as recovery_list_open_orders
from ladder_dragon.execution.executor_recovery import reconcile_nonterminal_orders as recovery_reconcile_nonterminal_orders
from ladder_dragon.execution.executor_recovery import record_order_payload as recovery_record_order_payload
from ladder_dragon.execution.executor_recovery import recover_existing_protection as recovery_existing_protection
from ladder_dragon.execution.executor_recovery import recover_pending_buy_order_ids as recovery_pending_buy_order_ids
from ladder_dragon.execution.executor_recovery import verify_oco_legs as recovery_verify_oco_legs
from ladder_dragon.execution.executor_stats import commission_quote_value, poll_mytrades_once
from ladder_dragon.execution.inventory_lots import (
    cost_basis_coverage,
    ensure_schema as ensure_lots_schema,
    oldest_lots,
    lot_for_order,
    sync_exchange_fill,
)
from ladder_dragon.execution.worker.buy_service import (
    cap_decimal as _cap_decimal,
    hard_buy_cap,
    place_buys as service_place_buys,
)
from ladder_dragon.execution.worker.holdings_service import (
    effective_remainder_policy,
    place_sells_from_holdings,
    protection_state_after_sweep as _protection_state_after_sweep,
)
from ladder_dragon.execution.worker.panic_control import (
    panic_buy_block_reason as _panic_buy_block_reason,
    panic_recovery_restart_required as _panic_recovery_restart_required,
)
from ladder_dragon.execution.worker.stats_sync import sync_account_trades

import requests
# per-symbol lock
import fcntl  # Linux/Unix

RUN = True
LIVE_MODE = False
_ORDER_JOURNAL: Optional[OrderJournal] = None
_WS_TRADING_TRANSPORT: BinanceWebSocketTradingTransport | None = None
WS_TRADING_MODE = "OFF"

# ------------------- ENV / config -------------------

BINANCE_API_BASE = (os.getenv("BINANCE_API_BASE") or os.getenv("BINANCE_BASE_URL") or "https://api.binance.com").rstrip("/")
API_KEY = os.getenv("BINANCE_API_KEY", "")
API_SECRET = os.getenv("BINANCE_API_SECRET", "")
USER_AGENT = os.getenv("USER_AGENT", user_agent("worker"))

LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()

def log(msg: str) -> None:
    print(msg, flush=True)

def dbg(msg: str) -> None:
    if LOG_LEVEL in ("DEBUG", "TRACE"):
        print(msg, flush=True)


SESSION = requests.Session()
if API_KEY:
    SESSION.headers.update({"X-MBX-APIKEY": API_KEY})
SESSION.headers.update({"User-Agent": USER_AGENT})

TRANSPORT = BinanceTransport(
    SESSION,
    base_url=lambda: BINANCE_API_BASE,
    api_key=lambda: API_KEY,
    api_secret=lambda: API_SECRET,
    live=lambda: LIVE_MODE,
    recv_window=lambda: getenv_int("RECV_WINDOW_MS", 15000),
    logger=log,
)


def _order_journal() -> Optional[OrderJournal]:
    """Handle order journal."""
    global _ORDER_JOURNAL
    if not LIVE_MODE:
        return None
    if _ORDER_JOURNAL is None:
        stats_db = os.getenv("BOT_STATS_DB", "").strip()
        default_path = (
            f"{stats_db}.orders.sqlite3"
            if stats_db
            else os.path.join(bot_run_dir(), "order_intents.sqlite3")
        )
        path = os.getenv("BOT_ORDER_JOURNAL", default_path)
        venue = "testnet" if "testnet" in BINANCE_API_BASE.lower() else "mainnet"
        _ORDER_JOURNAL = OrderJournal(path, venue=venue)
    return _ORDER_JOURNAL


def _trip_execution_halt(reason: str, **metadata: Any) -> None:
    """Handle trip execution halt."""
    path = create_manual_halt(reason, metadata=metadata)
    log(f"[EXECUTION-HALT] {reason}; marker={path}")


_SAFETY_CONTROL_FAILURES: Dict[tuple[str, str], int] = {}
_SELL_PERCENT_REFERENCE_CACHE: Dict[str, Tuple[float, Decimal]] = {}


def _record_safety_control_failure(
    control: str,
    symbol: str,
    error: BaseException,
) -> int:
    """Block unsafe decisions and escalate repeated control failures in LIVE."""
    key = (control, symbol.upper())
    count = _SAFETY_CONTROL_FAILURES.get(key, 0) + 1
    _SAFETY_CONTROL_FAILURES[key] = count
    threshold = max(1, getenv_int("BOT_SAFETY_FAILURE_HALT_THRESHOLD", 3))
    log(
        "[SAFETY-CONTROL] "
        + json.dumps(
            {
                "control": control,
                "symbol": symbol.upper(),
                "status": "unavailable",
                "buy_blocked": True,
                "failure_count": count,
                "halt_threshold": threshold,
                "error_type": error.__class__.__name__,
            },
            sort_keys=True,
        )
    )
    if LIVE_MODE and count >= threshold:
        _trip_execution_halt(
            f"{control} unavailable after {count} consecutive checks",
            symbol=symbol.upper(),
            control=control,
            error_type=error.__class__.__name__,
        )
    return count


def _clear_safety_control_failure(control: str, symbol: str) -> None:
    _SAFETY_CONTROL_FAILURES.pop((control, symbol.upper()), None)


def validate_limit_sell_prices(symbol: str, prices: List[object]) -> None:
    """Validate every LIMIT/OCO SELL at the shared pre-mutation boundary."""
    pull_filters(symbol)
    row = symbol_exchange_info.get(symbol.upper())
    if row is None:
        raise RuntimeError(f"exchangeInfo snapshot unavailable for {symbol}")
    now = time.time()
    cache_ttl = max(1, getenv_int("BOT_PERCENT_PRICE_CACHE_SEC", 5))
    cached = _SELL_PERCENT_REFERENCE_CACHE.get(symbol.upper())
    if cached is not None and now - cached[0] <= cache_ttl:
        reference_price = cached[1]
    else:
        payload = _public_get("/api/v3/avgPrice", {"symbol": symbol.upper()})
        reference_price = Decimal(str(payload["price"]))
        if not reference_price.is_finite() or reference_price <= 0:
            raise RuntimeError(f"invalid avgPrice for {symbol}")
        _SELL_PERCENT_REFERENCE_CACHE[symbol.upper()] = (now, reference_price)
    validate_sell_percent_prices(
        {"symbols": [row]},
        symbol=symbol,
        reference_price=reference_price,
        prices=prices,
    )


def _panic_state_fail_closed(
    control: str,
    symbol: str,
    evaluator: Callable[[], bool],
) -> tuple[bool, Optional[str]]:
    """Return an explicit BUY block when panic state cannot be evaluated."""
    try:
        active = bool(evaluator())
        _clear_safety_control_failure(control, symbol)
        return active, None
    except Exception as exc:  # deliberate fail-closed boundary for injected controls
        _record_safety_control_failure(control, symbol, exc)
        return True, f"{control}-unavailable"


def _gap_watchdog_fail_closed(
    symbol: str,
    price: float,
    *,
    dependencies: ProtectionDependencies,
    gap_tolerance_pct: float,
) -> Optional[str]:
    """Run the gap control and return a BUY-block reason on unsafe state."""
    try:
        flattened = emergency_gap_flatten(
            symbol,
            price,
            dependencies=dependencies,
            gap_tolerance_pct=gap_tolerance_pct,
        )
        _clear_safety_control_failure("gap-watchdog", symbol)
        return "gap-emergency-flattened" if flattened else None
    except Exception as exc:  # deliberate fail-closed boundary for protection code
        _record_safety_control_failure("gap-watchdog", symbol, exc)
        return "gap-watchdog-unavailable"


# ------------------- helpers: rounding & env -------------------

def _round(x: float, step: float, mode: str = "nearest") -> float:
    return _compat_float(round_step(x, step, mode))

def fmt(v, n=8):
    try:
        return f"{_compat_float(v):.{n}f}"
    except (TypeError, ValueError, OverflowError):
        return str(v)

def parse_comma_floats(s: str) -> List[float]:
    return [_compat_float(x.strip()) for x in s.split(",") if x.strip()]

def getenv_float(name, default):
    v = os.getenv(name)
    try:
        return _compat_float(v) if v is not None else default
    except (TypeError, ValueError, OverflowError):
        return default

def getenv_decimal(name: str, default: object) -> Decimal:
    """Read a finite decimal configuration value without binary conversion."""
    value = os.getenv(name)
    try:
        result = Decimal(str(default if value is None else value))
    except (InvalidOperation, TypeError, ValueError):
        result = Decimal(str(default))
    return result if result.is_finite() else Decimal(str(default))

def getenv_int(name, default):
    v = os.getenv(name)
    try:
        return int(v) if v is not None else default
    except (TypeError, ValueError, OverflowError):
        return default

def getenv_str(name, default):
    v = os.getenv(name)
    return v if v is not None else default

def price_round_mode():
    return getenv_str("PRICE_ROUND_MODE", "nearest")

def price_eps_mult():
    return getenv_float("PRICE_EPS_MULT", 1.0)

def cleanup_warmup_sec():
    return getenv_int("CLEANUP_WARMUP_SEC", 900)

def bot_run_dir() -> str:
    return getenv_str("BOT_RUN_DIR", "/run/mybot")

def install_signal_handlers():
    def handler(sig, frame):
        global RUN
        RUN = False
        print("[EXIT] KeyboardInterrupt")
    signal.signal(signal.SIGINT, handler)
    signal.signal(signal.SIGTERM, handler)

# ------------------- per-symbol single-instance lock -------------------
class SymbolLock:
    """Represent SymbolLock."""
    def __init__(self, symbol: str):
        self.symbol = symbol
        self.path = os.path.join(bot_run_dir(), f"lock_{symbol}.pid")
        self.fd: Optional[int] = None

    def acquire(self) -> bool:
        os.makedirs(os.path.dirname(self.path) or bot_run_dir(), exist_ok=True)
        # Open (or create) the file and attempt a non-blocking exclusive lock.
        self.fd = os.open(self.path, os.O_RDWR | os.O_CREAT, 0o644)
        try:
            fcntl.flock(self.fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            # Another live process already owns the lock.
            try:
                with open(self.path, "r", encoding="utf-8") as f:
                    pid_txt = f.read().strip()
            except OSError:
                pid_txt = "?"
            log(f"[LOCK] {self.symbol} is already running (pid={pid_txt}); exiting.")
            return False

        # The lock is acquired; write the current PID for observability.
        try:
            os.ftruncate(self.fd, 0)
            os.write(self.fd, f"{os.getpid()}\n".encode("utf-8"))
        except OSError:
            pass
        return True

    def release(self) -> None:
        # Closing the descriptor releases flock automatically; the file may be
        # removed for cleanliness, but it is not required.
        try:
            if self.fd is not None:
                os.close(self.fd)
                self.fd = None
                try:
                    os.unlink(self.path)
                except OSError:
                    pass
        except OSError:
            pass

# --- profit floor helpers ---

def _tp1_max_pct() -> Decimal:
    # Upper bound for the nearest target (zero means no cap).
    return max(Decimal("0"), getenv_decimal("TP1_MAX", "0.040"))

def _fee_floor_pct() -> Decimal:
    # The supervisor supplies side-specific authoritative account rates.
    buy_fee = max(
        Decimal("0"),
        getenv_decimal(
            "BOT_BUY_FEE_PCT",
            getenv_decimal("BOT_FEE_PCT", "0.001"),
        ),
    )
    sell_fee = max(
        Decimal("0"),
        getenv_decimal(
            "BOT_SELL_FEE_PCT",
            getenv_decimal("BOT_FEE_PCT", "0.001"),
        ),
    )
    return (buy_fee + sell_fee) * Decimal("1.05")

def _execution_cost_floor_pct() -> Decimal:
    """Handle execution cost floor pct."""
    fee = max(Decimal("0"), getenv_decimal("BOT_FEE_PCT", "0.001"))
    spread = max(Decimal("0"), getenv_decimal(
        "BOT_SPREAD_PCT", getenv_decimal("RISK_SPREAD_PCT", "0")
    ))
    slippage = max(Decimal("0"), getenv_decimal(
        "BOT_SLIPPAGE_PCT", getenv_decimal("RISK_SLIPPAGE_PCT", "0")
    ))
    latency = max(Decimal("0"), getenv_decimal("BOT_LATENCY_COST_PCT", "0"))
    stop_cost = max(Decimal("0"), getenv_decimal("BOT_STOP_EXECUTION_COST_PCT", "0"))
    partial = max(Decimal("0"), getenv_decimal("BOT_PARTIAL_FILL_COST_PCT", "0"))
    min_edge = max(Decimal("0"), getenv_decimal(
        "BOT_MIN_NET_EDGE_PCT", getenv_decimal("MIN_NET_EDGE_PCT", "0")
    ))
    return (
        Decimal("2") * fee + spread + Decimal("2") * slippage
        + latency + stop_cost + partial + min_edge
    )


def _non_fee_execution_cost_pct() -> Decimal:
    """Return conservative slippage/latency costs without round-trip fees."""
    spread = max(Decimal("0"), getenv_decimal(
        "BOT_SPREAD_PCT", getenv_decimal("RISK_SPREAD_PCT", "0")
    ))
    slippage = max(Decimal("0"), getenv_decimal(
        "BOT_SLIPPAGE_PCT", getenv_decimal("RISK_SLIPPAGE_PCT", "0")
    ))
    latency = max(Decimal("0"), getenv_decimal("BOT_LATENCY_COST_PCT", "0"))
    stop_cost = max(
        Decimal("0"),
        getenv_decimal("BOT_STOP_EXECUTION_COST_PCT", "0"),
    )
    partial = max(
        Decimal("0"),
        getenv_decimal("BOT_PARTIAL_FILL_COST_PCT", "0"),
    )
    return spread + Decimal("2") * slippage + latency + stop_cost + partial


def _profit_floor_pct() -> Decimal:
    # Combined floor: never below MIN_PROFIT_OVER_AVG or the fee floor.
    min_edge = max(Decimal("0"), getenv_decimal("MIN_PROFIT_OVER_AVG", "0"))
    authoritative = max(
        Decimal("0"),
        getenv_decimal("BOT_REQUIRED_EDGE_PCT", "0"),
    )
    return max(
        min_edge,
        authoritative,
        _fee_floor_pct(),
        _execution_cost_floor_pct(),
    )

# ------------------- HTTP / signed / backoff -------------------

def _request_with_backoff(method: str,
                          url: str,
                          *,
                          params: Dict[str, Any] | None = None,
                          data: Dict[str, Any] | None = None,
                          timeout: float = 15.0,
                          max_tries: int = 8) -> Any:
    return TRANSPORT.request_with_backoff(
        method, url, params=params, data=data, timeout=timeout, max_tries=max_tries
    )


def _public_get(path: str, params: Dict[str, Any] | None = None, timeout: float = 15.0):
    return TRANSPORT.public_get(path, params=params, timeout=timeout)


def _signed_request(method: str, path: str, params: Dict[str, Any] | None = None, timeout: float = 15.0):
    global _WS_TRADING_TRANSPORT
    normalized_method = method.upper()
    if (
        WS_TRADING_MODE == "APPLY"
        and (normalized_method, path) in WS_METHODS
    ):
        # Repeat the approval at the last transport boundary. This protects
        # direct worker invocation and future callers that skip CLI validation.
        if LIVE_MODE and os.getenv("BOT_WS_TRADING_APPROVED") != "YES":
            raise RuntimeError(
                "WebSocket trading APPLY requires "
                "BOT_WS_TRADING_APPROVED=YES"
            )
        if _WS_TRADING_TRANSPORT is None:
            _WS_TRADING_TRANSPORT = build_websocket_trading_transport(
                api_key=lambda: API_KEY,
                api_secret=lambda: API_SECRET,
                recv_window=lambda: getenv_int("RECV_WINDOW_MS", 15000),
                live=lambda: LIVE_MODE,
                timestamp_ms=TM._timestamp_ms,
                testnet="testnet" in BINANCE_API_BASE.lower(),
            )
        return _WS_TRADING_TRANSPORT.request(
            normalized_method,
            path,
            params,
            timeout=timeout,
        )
    return TRANSPORT.signed_request(method, path, params=params, timeout=timeout)

# ------------------- Indicators / averages / panic -------------------

# Indicator cache to avoid excessive klines requests.
_IND_CACHE: Dict[tuple[str, str], Dict[str, float]] = {}
_IND_TS: Dict[tuple[str, str], float] = {}

# VWAP cache (similar logic, with separate TTL and keys).
_VWAP_CACHE: Dict[tuple[str, str, int], Dict[str, float | None]] = {}
_VWAP_TS: Dict[tuple[str, str, int], float] = {}
_VWAP_PREMIUM_BLOCKED: Dict[str, bool] = {}

def _get_klines(symbol: str, interval: str = "1m", limit: int = 120):
    # Use the shared client with alias normalization and the -1120 -> 15m fallback.
    limit = max(20, min(1000, int(limit)))
    return TM.get_klines(symbol, interval, limit=limit)

def get_indicators_cached(symbol: str, interval: str = "1m", ttl_sec: int = 20) -> tuple[float | None, float | None, float | None]:
    key = (symbol, interval)
    now_ts = time.time()
    if key in _IND_CACHE and (now_ts - _IND_TS.get(key, 0)) < ttl_sec:
        d = _IND_CACHE[key]
        return d.get("ema20"), d.get("atr"), d.get("prev_close")
    kl = _get_klines(symbol, interval, limit=120)
    if not isinstance(kl, list) or len(kl) < 30:
        _IND_CACHE[key] = {"ema20": None, "atr": None, "prev_close": None}
        _IND_TS[key] = now_ts
        return None, None, None
    closes = [_compat_float(x[4]) for x in kl[:-1]]
    ema20 = _ema(closes[-60:], 20) if len(closes) >= 20 else None
    atr14 = _atr_from_klines(kl, 14)
    prev_close = closes[-1] if closes else None
    _IND_CACHE[key] = {"ema20": ema20, "atr": atr14 if atr14 > 0 else None, "prev_close": prev_close}
    _IND_TS[key] = now_ts
    return ema20, (atr14 if atr14 > 0 else None), prev_close


def get_vwap_cached(symbol: str,
                    interval: str = "1m",
                    window: int = 180,
                    ttl_sec: int = 15) -> Optional[float]:
    key = (symbol, interval, max(1, int(window)))
    now_ts = time.time()
    if key in _VWAP_CACHE and (now_ts - _VWAP_TS.get(key, 0.0)) < ttl_sec:
        return _VWAP_CACHE[key].get("vwap")  # type: ignore[return-value]

    win = max(5, int(window))
    limit = max(win + 5, win)
    kl = _get_klines(symbol, interval, limit=limit)
    if not isinstance(kl, list) or len(kl) < 10:
        _VWAP_CACHE[key] = {"vwap": None}
        _VWAP_TS[key] = now_ts
        return None

    candles = kl[:-1] if len(kl) > 1 else kl
    if len(candles) > win:
        candles = candles[-win:]

    vol_sum = 0.0
    weighted_sum = 0.0
    for bar in candles:
        try:
            high = _compat_float(bar[2])
            low = _compat_float(bar[3])
            close = _compat_float(bar[4])
            volume = _compat_float(bar[5])
        except (TypeError, ValueError):
            continue
        if volume <= 0:
            continue
        price = (high + low + close) / 3.0
        vol_sum += volume
        weighted_sum += price * volume

    vwap = (weighted_sum / vol_sum) if vol_sum > 0 else None
    _VWAP_CACHE[key] = {"vwap": vwap}
    _VWAP_TS[key] = now_ts
    return vwap

# Average position entry from the verified exact-lot ledger (cached).
_AVG_CACHE: Dict[str, Dict[str, object]] = {}

def avg_entry(
    symbol: str,
    cache_ttl: int = 30,
    lookback: int = 1000,
) -> Optional[Decimal]:
    """Return only a locally verified average without blocking BUY startup.

    The previous implementation replayed up to 1,000 Binance trades and could
    issue one historical conversion request per third-asset commission.  On a
    Raspberry Pi that delayed replacement BUYs for several minutes.  The exact
    lot ledger is already the authorization boundary for holdings cost basis,
    so an incomplete or legacy ledger now returns ``None`` fail-closed instead
    of consulting slow, potentially truncated exchange history.
    """
    del lookback  # Retained for CLI/API compatibility.
    base, _ = get_symbol_assets(symbol)
    bals = get_balances()
    pos_free = Decimal(str(bals.get(base, {}).get("free", "0") or "0"))
    pos_locked = Decimal(str(bals.get(base, {}).get("locked", "0") or "0"))
    pos = pos_free + pos_locked
    if not pos.is_finite() or pos <= 0:
        return None

    ent = _AVG_CACHE.get(symbol)
    now_ns = time.monotonic_ns()
    if ent:
        cached_at_ns = int(ent.get("ts_ns", 0) or 0)
        cached_position = Decimal(str(ent.get("pos", "0") or "0"))
        cached_average = Decimal(str(ent.get("avg", "0") or "0"))
        if (
            now_ns - cached_at_ns < max(0, cache_ttl) * 1_000_000_000
            and cached_position == pos
        ):
            return (
                cached_average
                if cached_average.is_finite() and cached_average > 0
                else None
            )

    avg_px: Optional[Decimal] = None
    try:
        _stats_init_if_needed()
        if STATS_CON is None:
            raise RuntimeError("stats database unavailable")
        step = Decimal(str(pull_filters(symbol)["stepSize"]))
        tolerance_pct = Decimal(
            os.getenv("BOT_COST_BASIS_QTY_TOLERANCE_PCT", "0.002")
        )
        if not tolerance_pct.is_finite() or tolerance_pct < 0:
            raise ValueError("invalid cost-basis quantity tolerance")
        coverage = cost_basis_coverage(
            STATS_CON,
            symbol,
            pos,
            tolerance_qty=max(step * Decimal("2"), pos * tolerance_pct),
        )
        if (
            coverage.covered
            and coverage.average_price is not None
            and coverage.average_price.is_finite()
            and coverage.average_price > 0
        ):
            avg_px = coverage.average_price
    except (
        KeyError,
        TypeError,
        ValueError,
        ArithmeticError,
        RuntimeError,
        OSError,
        sqlite3.Error,
    ) as exc:
        dbg(f"[AVG] {symbol} verified ledger unavailable: {type(exc).__name__}")

    _AVG_CACHE[symbol] = {
        "ts_ns": now_ns,
        "avg": str(avg_px or Decimal("0")),
        "pos": str(pos),
    }
    return avg_px

# --- PANIC state ---

_panic: Dict[str, Dict[str, float | int | bool]] = {}
_panic_loaded: set[str] = set()
_PANIC_PERSISTED: Dict[str, tuple[bool, float, int]] = {}
_ORDER_OBSERVATION_LAST_WRITE: Dict[int, float] = {}


def _panic_state_path(symbol: str) -> Path:
    safe_symbol = symbol.strip().upper()
    if (
        not safe_symbol
        or len(safe_symbol) > 20
        or any(
            character not in "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
            for character in safe_symbol
        )
    ):
        raise ValueError("invalid symbol for panic state")
    return Path(bot_run_dir()) / f"panic_state_{safe_symbol}.json"


def _load_panic_state(symbol: str) -> Dict[str, float | int | bool]:
    """Restore the debounce/cooldown state before evaluating a new BUY."""
    safe_symbol = symbol.upper()
    if safe_symbol in _panic_loaded:
        return _panic.get(
            safe_symbol,
            {"on": False, "since": 0.0, "last_trig": 0.0, "hits": 0},
        )
    path = _panic_state_path(safe_symbol)
    state: Dict[str, float | int | bool] = {
        "on": False,
        "since": 0.0,
        "last_trig": 0.0,
        "hits": 0,
    }
    if path.exists():
        raw = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict) or int(raw.get("schema_version", 0)) != 1:
            raise ValueError("unsupported panic state schema")
        if not isinstance(raw.get("on"), bool):
            raise ValueError("invalid panic state flag")
        if not isinstance(raw.get("hits"), int):
            raise ValueError("invalid panic state hit counter")
        since = Decimal(str(raw.get("since", "0")))
        last_trig = Decimal(str(raw.get("last_trig", "0")))
        if not since.is_finite() or not last_trig.is_finite():
            raise ValueError("invalid panic state timestamp")
        state = {
            "on": raw["on"],
            "since": max(0.0, _compat_float(since)),
            "last_trig": max(0.0, _compat_float(last_trig)),
            "hits": max(0, int(raw.get("hits", 0))),
        }
        log(
            f"[PANIC-STATE] {safe_symbol} restored "
            f"on={state['on']} hits={state['hits']}"
        )
    _panic[safe_symbol] = state
    _panic_loaded.add(safe_symbol)
    if path.exists():
        _PANIC_PERSISTED[safe_symbol] = (
            bool(state["on"]),
            _compat_float(state["since"]),
            int(state["hits"]),
        )
    return state


def _save_panic_state(
    symbol: str,
    state: Dict[str, float | int | bool],
) -> None:
    """Atomically persist non-secret PANIC state for the next executor."""
    path = _panic_state_path(symbol)
    signature = (
        bool(state.get("on", False)),
        _compat_float(state.get("since", 0.0)),
        max(0, int(state.get("hits", 0))),
    )
    if _PANIC_PERSISTED.get(symbol.upper()) == signature and path.exists():
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": 1,
        "symbol": symbol.upper(),
        "on": bool(state.get("on", False)),
        "since": _compat_float(state.get("since", 0.0)),
        "last_trig": _compat_float(state.get("last_trig", 0.0)),
        "hits": max(0, int(state.get("hits", 0))),
        "updated_at": time.time(),
    }
    temporary = path.with_name(f".{path.name}.{os.getpid()}.{time.time_ns()}.tmp")
    descriptor = os.open(
        temporary,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL,
        0o600,
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, sort_keys=True, separators=(",", ":"))
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        os.chmod(path, 0o600)
        _PANIC_PERSISTED[symbol.upper()] = signature
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


def _observe_buy_market(
    symbol: str,
    order_ids: List[int],
    market_price: float,
) -> None:
    """Persist a throttled market range for later non-fill diagnostics."""
    journal = _order_journal()
    if journal is None or market_price <= 0:
        return
    observed_at = time.time()
    market = Decimal(str(market_price))
    for order_id in order_ids:
        intent = journal.get_by_exchange_order_id(int(order_id))
        if intent is None or intent.side.upper() != "BUY":
            continue
        metadata = dict(intent.metadata or {})
        previous_min = Decimal(str(metadata.get("market_min_price", market)))
        previous_max = Decimal(str(metadata.get("market_max_price", market)))
        new_min = min(previous_min, market)
        new_max = max(previous_max, market)
        last_write = _ORDER_OBSERVATION_LAST_WRITE.get(int(order_id), 0.0)
        changed_range = new_min != previous_min or new_max != previous_max
        if not changed_range and observed_at - last_write < 15.0:
            continue
        first_price = metadata.get("market_first_price", str(market))
        first_at = metadata.get("market_first_observed_at", observed_at)
        journal.update_metadata(
            intent.client_order_id,
            {
                "market_first_price": first_price,
                "market_last_price": str(market),
                "market_min_price": str(new_min),
                "market_max_price": str(new_max),
                "market_observation_count": int(
                    metadata.get("market_observation_count", 0)
                ) + 1,
                "market_first_observed_at": first_at,
                "market_last_observed_at": observed_at,
            },
        )
        _ORDER_OBSERVATION_LAST_WRITE[int(order_id)] = observed_at


def update_panic_state(symbol: str,
                       now_px: float,
                       ema20: float | None,
                       atr: float | None,
                       prev_close: float | None,
                       avg_entry_px: object | None,
                       panic_drop_pct: float = 0.02,
                       panic_k_atr: float = 2.0,
                       debounce_checks: int = 2,
                       cooldown_sec: int = 180) -> bool:
    safe_symbol = symbol.upper()
    s = _load_panic_state(safe_symbol)
    now_ts = time.time()

    trig = panic_raw(now_px, ema20, atr, prev_close, panic_drop_pct, panic_k_atr)

    if trig:
        s["hits"] = min(
            max(1, int(debounce_checks)),
            int(s.get("hits", 0)) + 1,
        )
        s["last_trig"] = now_ts
        if (not s.get("on", False)) and s["hits"] >= debounce_checks:
            s["on"] = True
            s["since"] = now_ts
            log(f"[PANIC] {symbol} ON (now≈{fmt(now_px, 6)}, ema20≈{fmt(ema20 or 0, 6)}, ATR≈{fmt(atr or 0, 6)})")
    else:
        s["hits"] = 0

    if s.get("on", False):
        # Leave panic after cooldown and recovery to EMA-1*ATR or the average entry.
        recovered_ema = False
        recovered_avg = False
        if ema20 is not None and atr is not None and atr > 0:
            recovered_ema = now_px >= (ema20 - 1.0 * atr)
        if avg_entry_px is not None:
            recovered_avg = Decimal(str(now_px)) >= Decimal(str(avg_entry_px))
        if (now_ts - _compat_float(s.get("since", 0.0)) >= cooldown_sec) and (recovered_ema or recovered_avg):
            s["on"] = False
            s["hits"] = 0
            log(f"[PANIC] {symbol} OFF (recover: ema_ok={recovered_ema}, avg_ok={recovered_avg})")

    _panic[safe_symbol] = s
    _save_panic_state(safe_symbol, s)
    return bool(s["on"])


# ------------------- Exchange info / filters -------------------

symbol_filters: Dict[str, Dict[str, Any]] = {}
symbol_exchange_info: Dict[str, Dict[str, Any]] = {}
_symbol_assets_cache: Dict[str, Tuple[str, str]] = {}

def exchange_info(symbol: str):
    return _public_get("/api/v3/exchangeInfo", {"symbol": symbol})

def pull_filters(symbol: str) -> Dict[str, Any]:
    global symbol_filters, symbol_exchange_info
    if symbol in symbol_filters:
        return symbol_filters[symbol]
    j = exchange_info(symbol)
    try:
        row = exchange_symbol_row(j, symbol)
        filters = exchange_filter_map(row)
        price_filter = filters["PRICE_FILTER"]
        lot_filter = filters["LOT_SIZE"]
        notional_filter = filters.get("NOTIONAL") or filters["MIN_NOTIONAL"]
        flt = {
            "tickSize": _compat_float(price_filter["tickSize"]),
            "stepSize": _compat_float(lot_filter["stepSize"]),
            "minQty": _compat_float(lot_filter["minQty"]),
            "minNotional": _compat_float(notional_filter["minNotional"]),
            "tickSizeExact": str(price_filter["tickSize"]),
            "stepSizeExact": str(lot_filter["stepSize"]),
            "minQtyExact": str(lot_filter["minQty"]),
            "minNotionalExact": str(notional_filter["minNotional"]),
        }
        if any(
            flt[name] <= 0
            for name in ("tickSize", "stepSize", "minQty", "minNotional")
        ):
            raise RuntimeError(f"invalid non-positive exchange filters for {symbol}")
    except (KeyError, TypeError, ValueError, RuntimeError) as exc:
        raise RuntimeError(f"invalid exchange filters for {symbol}: {exc}") from exc

    symbol_filters[symbol] = flt
    symbol_exchange_info[symbol] = dict(row)
    log(f"[FILTERS] {symbol} tickSize={flt['tickSize']:.8f} stepSize={flt['stepSize']:.8f} "
        f"minQty={flt['minQty']:.6f} minNotional={flt['minNotional']}")
    return flt

def _decimals_from_step(step: float) -> int:
    """Handle decimals from step."""
    if step <= 0:
        return 8
    s = f"{step:.12f}".rstrip("0")
    if "." in s:
        return max(0, len(s.split(".")[1]))
    return 0

def fmt_price_sym(symbol: str, p: float) -> str:
    tick = symbol_filters.get(symbol, {}).get("tickSize", 0.01)
    dec = _decimals_from_step(tick)
    return f"{p:.{dec}f}"

def fmt_qty_sym(symbol: str, q: float) -> str:
    step = symbol_filters.get(symbol, {}).get("stepSize", 0.0001)
    dec = _decimals_from_step(step)
    return f"{q:.{dec}f}"


def _round_price_exact(symbol: str, value: object) -> Decimal:
    """Round a BUY price on the exchange tick without a float conversion."""
    filters = symbol_filters.get(symbol) or pull_filters(symbol)
    tick = filters.get("tickSizeExact", filters.get("tickSize"))
    return round_step(value, tick, "floor")


def _round_qty_exact(symbol: str, value: object) -> Decimal:
    """Round a quantity down on the exchange step without binary floats."""
    filters = symbol_filters.get(symbol) or pull_filters(symbol)
    step = filters.get("stepSizeExact", filters.get("stepSize"))
    return round_step(value, step, "floor")


def _filter_decimal(symbol: str, exact_name: str, legacy_name: str) -> Decimal:
    filters = symbol_filters.get(symbol) or pull_filters(symbol)
    return Decimal(str(filters.get(exact_name, filters.get(legacy_name))))


def _format_price_exact(symbol: str, value: object) -> str:
    """Format an exchange price without converting it through binary float."""
    return format_step(
        value,
        _filter_decimal(symbol, "tickSizeExact", "tickSize"),
    )


def _format_qty_exact(symbol: str, value: object) -> str:
    """Format an exchange quantity without converting it through binary float."""
    return format_step(
        value,
        _filter_decimal(symbol, "stepSizeExact", "stepSize"),
    )


def _minimum_qty_exact(symbol: str, _hint: object = None) -> Decimal:
    return _filter_decimal(symbol, "minQtyExact", "minQty")


def _minimum_notional_exact(symbol: str, _price: object = None) -> Decimal:
    return _filter_decimal(symbol, "minNotionalExact", "minNotional")

def dedup_ladder(symbol: str, ladder_prices: List[float], now_price: float) -> List[float]:
    try:
        tick = _compat_float(symbol_filters[symbol]["tickSize"])
    except (KeyError, TypeError, ValueError, ArithmeticError):
        tick = 0.0
    if tick <= 0 or not ladder_prices:
        return ladder_prices

    seen: set[tuple[int, str]] = set()
    dedup: List[float] = []
    for raw_p in ladder_prices:
        try:
            pr = round_price(symbol, _compat_float(raw_p))
        except (KeyError, TypeError, ValueError, ArithmeticError):
            continue
        side = "B" if pr <= now_price else "S"
        key = (round(pr / tick), side)
        if key in seen:
            continue
        seen.add(key)
        dedup.append(pr)
    return dedup

def adjust_buy_ladder(symbol: str,
                      ladder_prices: List[float],
                      now_price: float,
                      shift_pct: float) -> List[float]:
    del symbol
    return shift_buy_levels(ladder_prices, now_price, shift_pct)

def round_price(symbol: str, p: float) -> float:
    step = symbol_filters[symbol]["tickSize"]
    return _round(p, step, price_round_mode())

def round_qty(symbol: str, q: float) -> float:
    step = symbol_filters[symbol]["stepSize"]
    return _round(q, step, "down")

def min_qty(symbol: str, q_hint: float) -> float:
    return symbol_filters[symbol]["minQty"]

def min_notional(symbol: str, p: float) -> float:
    return symbol_filters[symbol]["minNotional"]

# ------------------- Market / account -------------------

def get_price(symbol: str) -> float:
    return market_get_price(symbol, public_get=_public_get, logger=log)


def get_price_exact(symbol: str) -> Decimal:
    """Return the authoritative exact price for financial decisions."""
    return market_get_price_decimal(
        symbol,
        public_get=_public_get,
        logger=log,
    )

def get_balances() -> Dict[str, Dict[str, Decimal]]:
    return market_get_balances(signed_request=_signed_request)

def get_symbol_assets(symbol: str) -> Tuple[str, str]:
    return market_get_symbol_assets(
        symbol,
        exchange_info=exchange_info,
        cache=_symbol_assets_cache,
    )

def list_open_orders(symbol: str) -> List[Dict[str, Any]]:
    return recovery_list_open_orders(
        symbol, signed_request=_signed_request, logger=log
    )

def cancel_order(symbol: str, oid: int):
    recovery_cancel_order(
        symbol, oid, signed_request=_signed_request, logger=log
    )

def cancel_oco(symbol: str, order_list_id: int) -> None:
    recovery_cancel_oco(
        symbol,
        order_list_id,
        signed_request=_signed_request,
        logger=log,
    )

def get_order_by_client_id(symbol: str, client_id: str) -> Dict[str, Any] | None:
    return recovery_get_order_by_client_id(
        symbol, client_id, signed_request=_signed_request
    )


def get_order_list_by_client_id(client_id: str) -> Dict[str, Any] | None:
    return recovery_get_order_list_by_client_id(
        client_id, signed_request=_signed_request
    )


def verify_oco_legs(symbol: str, order_list: Dict[str, Any]) -> List[Dict[str, Any]]:
    return recovery_verify_oco_legs(
        symbol, order_list, signed_request=_signed_request
    )


def _record_order_payload(payload: Dict[str, Any] | None) -> Optional[OrderIntent]:
    return recovery_record_order_payload(payload, journal=_order_journal())


def cancel_open_buys_for_panic(symbol: str, order_ids: List[int]) -> List[int]:
    """Cancel open BUY exposure when PANIC is active and reconcile every result."""
    remaining = list(order_ids)
    open_states = {"NEW", "PARTIALLY_FILLED", "PENDING_CANCEL"}
    try:
        cancellation_market_price: Optional[float] = get_price(symbol)
        _observe_buy_market(symbol, remaining, cancellation_market_price)
    except (
        requests.RequestException,
        RuntimeError,
        ValueError,
        ArithmeticError,
        OSError,
        sqlite3.Error,
    ):
        cancellation_market_price = None

    for order_id in list(remaining):
        order = get_order(symbol, order_id)
        if not order:
            reason = f"panic cancel cannot confirm BUY order {order_id}"
            _trip_execution_halt(reason, symbol=symbol, order_id=order_id)
            raise RuntimeError(reason)

        side = str(order.get("side") or "BUY").upper()
        status = str(order.get("status") or "").upper()
        original_order = dict(order)
        if side != "BUY":
            continue

        if status in open_states:
            try:
                cancelled = _signed_request(
                    "DELETE",
                    "/api/v3/order",
                    {"symbol": symbol, "orderId": int(order_id)},
                )
            except (
                requests.RequestException,
                RuntimeError,
                ValueError,
                ArithmeticError,
                OSError,
            ) as exc:
                # A lost cancellation response is uncertain until Binance is
                # queried again. Never assume that the BUY disappeared.
                cancelled = get_order(symbol, order_id)
                verified_status = str(
                    (cancelled or {}).get("status") or ""
                ).upper()
                if verified_status not in TERMINAL_EXCHANGE_STATES:
                    reason = (
                        f"panic cancel unconfirmed for BUY order {order_id}"
                    )
                    _trip_execution_halt(
                        reason, symbol=symbol, order_id=order_id
                    )
                    raise RuntimeError(reason) from exc
            status = str((cancelled or {}).get("status") or "").upper()
            if status not in TERMINAL_EXCHANGE_STATES:
                reason = (
                    f"panic cancel returned nonterminal state {status or 'UNKNOWN'} "
                    f"for BUY order {order_id}"
                )
                _trip_execution_halt(reason, symbol=symbol, order_id=order_id)
                raise RuntimeError(reason)
            order = cancelled

        if status in TERMINAL_EXCHANGE_STATES:
            updated = _record_order_payload(order)
            if updated is None:
                reason = f"panic cancel cannot update journal for BUY order {order_id}"
                _trip_execution_halt(reason, symbol=symbol, order_id=order_id)
                raise RuntimeError(reason)
            executed_qty = Decimal(str(order.get("executedQty") or "0"))
            log(
                f"[PANIC-CANCEL] {symbol} BUY order={order_id} "
                f"state={updated.state} executed={executed_qty}"
            )
            limit_price = Decimal(str(original_order.get("price") or "0"))
            market_price = (
                Decimal(str(cancellation_market_price))
                if cancellation_market_price is not None
                else None
            )
            created_ms = int(
                original_order.get("time")
                or original_order.get("workingTime")
                or original_order.get("updateTime")
                or int(time.time() * 1000)
            )
            distance_pct = None
            if market_price is not None and market_price > 0 and limit_price > 0:
                distance_pct = (
                    (market_price - limit_price) / market_price * Decimal("100")
                ).quantize(Decimal("0.0001"))
            metadata = dict(updated.metadata or {})
            log(
                "[ORDER-LIFETIME] "
                + json.dumps(
                    {
                        "symbol": symbol,
                        "order_id": int(order_id),
                        "cancel_reason": "panic",
                        "age_sec": max(
                            0,
                            int((time.time() * 1000 - created_ms) / 1000),
                        ),
                        "ttl_sec": None,
                        "limit_price": str(limit_price),
                        "market_price_at_cancel": (
                            str(market_price) if market_price is not None else None
                        ),
                        "limit_below_market_pct": (
                            str(distance_pct) if distance_pct is not None else None
                        ),
                        "minimum_observed_market_price": metadata.get(
                            "market_min_price"
                        ),
                        "market_observation_count": metadata.get(
                            "market_observation_count", 0
                        ),
                        "executed_qty": str(executed_qty),
                    },
                    sort_keys=True,
                    separators=(",", ":"),
                )
            )
            # A cancelled partial fill remains in the protection pipeline. A
            # zero-fill cancellation is terminal and needs no OCO.
            if executed_qty <= 0:
                remaining.remove(order_id)
            continue

        if status == "FILLED":
            continue

        reason = (
            f"panic cancel found unsupported state {status or 'UNKNOWN'} "
            f"for BUY order {order_id}"
        )
        _trip_execution_halt(reason, symbol=symbol, order_id=order_id)
        raise RuntimeError(reason)

    return remaining


def _recovery_dependencies() -> RecoveryDependencies:
    # The facade connects the pure recovery module to the process transport,
    # journal, and halt state without exposing executor globals directly.
    return RecoveryDependencies(
        journal=_order_journal,
        get_order_by_client_id=lambda symbol, client_id: get_order_by_client_id(
            symbol, client_id
        ),
        get_order_list_by_client_id=lambda client_id: get_order_list_by_client_id(
            client_id
        ),
        verify_oco_legs=lambda symbol, payload: verify_oco_legs(symbol, payload),
        cancel_oco=lambda symbol, order_list_id: cancel_oco(
            symbol, order_list_id
        ),
        halt=_trip_execution_halt,
        logger=log,
    )


def recover_pending_buy_order_ids(symbol: str) -> List[int]:
    return recovery_pending_buy_order_ids(
        symbol, dependencies=_recovery_dependencies()
    )


def reconcile_nonterminal_orders(symbol: str) -> List[OrderIntent]:
    return recovery_reconcile_nonterminal_orders(
        symbol, dependencies=_recovery_dependencies()
    )


def recover_existing_protection(parent_client_order_id: str) -> bool:
    return recovery_existing_protection(
        parent_client_order_id,
        dependencies=_recovery_dependencies(),
    )


def get_order(symbol: str, order_id: int) -> Dict[str, Any] | None:
    return recovery_get_order(
        symbol,
        order_id,
        signed_request=_signed_request,
        record_payload=_record_order_payload,
        logger=log,
    )


def _order_dependencies() -> OrderDependencies:
    # The order module receives late-bound functions: LIVE_MODE is checked at POST
    # time rather than frozen when the executor is imported.
    return OrderDependencies(
        live=lambda: LIVE_MODE,
        logger=log,
        pull_filters=pull_filters,
        round_price=_round_price_exact,
        round_qty=_round_qty_exact,
        min_qty=_minimum_qty_exact,
        min_notional=_minimum_notional_exact,
        format_price=_format_price_exact,
        format_qty=_format_qty_exact,
        journal=_order_journal,
        signed_request=_signed_request,
        get_order_by_client_id=get_order_by_client_id,
        get_order_list_by_client_id=get_order_list_by_client_id,
        verify_oco_legs=verify_oco_legs,
        cancel_oco=cancel_oco,
        halt=_trip_execution_halt,
        validate_limit_sell_prices=validate_limit_sell_prices,
    )



def place_market_order(
    symbol: str,
    side: str,
    quantity: float,
    *,
    ref_price: float | None = None,
    filters: Dict[str, Any] | None = None,
    parent_client_order_id: Optional[str] = None,
) -> Dict[str, Any] | None:
    """Place a MARKET flatten through the shared idempotent order layer."""
    return orders_place_market_order(
        symbol,
        side,
        quantity,
        dependencies=_order_dependencies(),
        ref_price=ref_price,
        filters=filters,
        parent_client_order_id=parent_client_order_id,
    )

def _protection_dependencies() -> ProtectionDependencies:
    # Position protection receives the same late-bound boundaries as orders and
    # recovery: actual HTTP, journal, and halt state remain owned by the executor.
    def lot_id_for_fill(symbol: str, fill_price: float, order_id: int | None = None) -> int | None:
        if STATS_CON is None:
            return None
        try:
            if order_id is not None:
                exact = lot_for_order(STATS_CON, symbol, order_id)
                if exact is not None:
                    return exact.lot_id
            lots = oldest_lots(STATS_CON, symbol)
            return lots[0].lot_id if lots else None
        except sqlite3.Error:
            return None

    return ProtectionDependencies(
        logger=log,
        debugger=dbg,
        journal=_order_journal,
        get_order=get_order,
        recover_existing_protection=recover_existing_protection,
        poll_trades=lambda symbol: sync_account_trades(
            symbol,
            runtime=globals(),
        ),
        pick_oco_prices=_pick_ladder_aligned_oco_prices,
        average_entry=lambda symbol, ttl, lookback: avg_entry(
            symbol, cache_ttl=ttl, lookback=lookback
        ),
        profit_floor_pct=_profit_floor_pct,
        pull_filters=pull_filters,
        get_symbol_assets=get_symbol_assets,
        get_balances=get_balances,
        round_price=_round_price_exact,
        round_quantity=_round_qty_exact,
        min_quantity=_minimum_qty_exact,
        min_notional=_minimum_notional_exact,
        format_price=_format_price_exact,
        format_quantity=_format_qty_exact,
        halt=_trip_execution_halt,
        place_oco_sell=place_oco_sell,
        place_limit_order=place_limit_order,
        list_open_orders=list_open_orders,
        tick_size=lambda symbol: _filter_decimal(
            symbol, "tickSizeExact", "tickSize"
        ),
        price_eps_mult=price_eps_mult,
        round_step=round_step,
        cancel_oco=cancel_oco,
        place_market_order=place_market_order,
        market_price=get_price_exact,
        lot_id_for_fill=lot_id_for_fill,
    )


def place_limit_order(side: str,
                      symbol: str,
                      qty: float,
                      price: float,
                      *,
                      maker: bool = False,
                      purpose: str = "ladder",
                      parent_client_order_id: Optional[str] = None,
                      latency_trace: LatencyTrace | None = None) -> Dict[str, Any] | None:
    return orders_place_limit_order(
        side,
        symbol,
        qty,
        price,
        dependencies=_order_dependencies(),
        maker=maker,
        purpose=purpose,
        parent_client_order_id=parent_client_order_id,
        latency_trace=latency_trace,
    )

def place_oco_sell(symbol: str,
                   qty: float,
                   tp_limit_price: float,
                   sl_stop_price: float,
                   sl_limit_price: float,
                   *,
                   parent_client_order_id: Optional[str] = None,
                   lot_id: int | None = None) -> Dict[str, Any] | None:
    return orders_place_oco_sell(
        symbol,
        qty,
        tp_limit_price,
        sl_stop_price,
        sl_limit_price,
        dependencies=_order_dependencies(),
        parent_client_order_id=parent_client_order_id,
        lot_id=lot_id,
    )


def place_otoco_buy(
    symbol: str,
    qty: object,
    buy_price: object,
    tp_limit_price: object,
    sl_stop_price: object,
    sl_limit_price: object,
    *,
    maker: bool = False,
    latency_trace: LatencyTrace | None = None,
) -> Dict[str, Any] | None:
    return orders_place_otoco_buy(
        symbol,
        qty,
        buy_price,
        tp_limit_price,
        sl_stop_price,
        sl_limit_price,
        dependencies=_order_dependencies(),
        maker=maker,
        latency_trace=latency_trace,
    )


# ------------------- STATS (optional) -------------------

STATS_ENABLE = getenv_int("STATS_ENABLE", 0) == 1
STATS_DB = getenv_str("BOT_STATS_DB", "")

TOOLS_STATS = None
STATS_CON: Optional[sqlite3.Connection] = None
_COMMISSION_QUOTE_CACHE: Dict[Tuple[str, str, int], Decimal] = {}
_ACCOUNT_FEE_CACHE: Dict[str, Tuple[float, Decimal]] = {}


def account_fee_pct(symbol: str) -> Decimal:
    """Handle account fee pct."""
    now = time.time()
    cached = _ACCOUNT_FEE_CACHE.get(symbol.upper())
    if cached and now - cached[0] < 300:
        return cached[1]
    fallback = max(Decimal("0"), getenv_decimal("BOT_FEE_PCT", "0.001"))
    try:
        rows = _signed_request("GET", "/sapi/v1/asset/tradeFee", {"symbol": symbol.upper()}) or []
        row = rows[0] if isinstance(rows, list) and rows else rows
        fee = max(Decimal("0"), Decimal(str(
            row.get("takerCommission", row.get("makerCommission", fallback))
        )))
    except (OSError, RuntimeError, ValueError, TypeError, KeyError, InvalidOperation):
        fee = fallback
    _ACCOUNT_FEE_CACHE[symbol.upper()] = (now, fee)
    return fee

def _stats_init_if_needed():
    """Handle stats init if needed."""
    global TOOLS_STATS, STATS_CON
    if not STATS_ENABLE or not STATS_DB:
        return
    if TOOLS_STATS is None:
        try:
            from ladder_dragon.execution import tools_stats as TOOLS_STATS  # type: ignore
        except ImportError as e:
            log(f"[STATS] import error: {e}")
            return
    if STATS_CON is None:
        try:
            os.makedirs(os.path.dirname(STATS_DB) or ".", exist_ok=True)
            STATS_CON = TOOLS_STATS.init_db(STATS_DB)
        except (OSError, RuntimeError, ValueError, sqlite3.Error) as e:
            log(f"[STATS] open error: {e}")
            STATS_CON = None


def _commission_quote_value(
    symbol: str,
    commission_asset: str,
    commission_amount: Decimal,
    trade_price: Decimal,
    trade_time_ms: int,
) -> Tuple[Optional[Decimal], str]:
    return commission_quote_value(
        symbol,
        commission_asset,
        commission_amount,
        trade_price,
        trade_time_ms,
        symbol_assets=get_symbol_assets,
        public_get=_public_get,
        cache=_COMMISSION_QUOTE_CACHE,
    )


def _holdings_cost_basis_covered(
    symbol: str,
    balances: Dict[str, Dict[str, Decimal]],
) -> Optional[Decimal]:
    """Require full quantity/provenance coverage before normal holdings SELL."""
    try:
        _stats_init_if_needed()
        if STATS_CON is None:
            raise RuntimeError("stats database unavailable")
        base, _ = get_symbol_assets(symbol)
        row = balances.get(base) or {}
        account_qty = Decimal(str(row.get("free", 0))) + Decimal(
            str(row.get("locked", 0))
        )
        step = Decimal(str(pull_filters(symbol)["stepSize"]))
        tolerance_pct = Decimal(
            os.getenv("BOT_COST_BASIS_QTY_TOLERANCE_PCT", "0.002")
        )
        if not tolerance_pct.is_finite() or tolerance_pct < 0:
            raise ValueError("invalid cost-basis quantity tolerance")
        tolerance = max(step * Decimal("2"), account_qty * tolerance_pct)
        coverage = cost_basis_coverage(
            STATS_CON,
            symbol,
            account_qty,
            tolerance_qty=tolerance,
        )
        if not coverage.covered:
            raise RuntimeError(coverage.reason)
        if coverage.average_price is None or coverage.average_price <= 0:
            raise RuntimeError("covered lots do not provide a positive average price")
        _clear_safety_control_failure("legacy-cost-basis", symbol)
        return coverage.average_price
    except (
        KeyError,
        TypeError,
        ValueError,
        ArithmeticError,
        RuntimeError,
        OSError,
        sqlite3.Error,
    ) as exc:
        _record_safety_control_failure("legacy-cost-basis", symbol, exc)
        log(
            f"[HOLD-SELL-BLOCK] {symbol} cost basis unavailable: "
            f"{type(exc).__name__}"
        )
        return None



# ------------------- OCO price picker (ladder-aligned + TP-floor) -------------------

def _pick_ladder_aligned_oco_prices(symbol: str,
                                    ladder_prices: List[float],
                                    fill_price: object,
                                    stop_limit_offset_pct: object) -> tuple[Decimal, Decimal, Decimal]:
    """Select OCO prices with exact arithmetic before exchange rounding."""
    pull_filters(symbol)
    tick = _filter_decimal(symbol, "tickSizeExact", "tickSize")
    fill = Decimal(str(fill_price))
    levels = [Decimal(str(price)) for price in ladder_prices]
    eps_mult = max(Decimal("1"), Decimal(str(price_eps_mult())))

    def round_price_exact(value: Decimal) -> Decimal:
        return round_step(value, tick, "nearest")

    # Split the ladder around the fill.
    lower = [price for price in levels if price < fill]
    upper = [price for price in levels if price > fill]

    # Basic fallbacks when no ladder levels are available.
    ladder_tp = upper[0] if upper else round_price_exact(fill * Decimal("1.01"))
    sl_limit = lower[-1] if lower else round_price_exact(fill * Decimal("0.99"))

    # Profit floor and cap.
    floor_pct = max(Decimal("0"), _profit_floor_pct())
    cap_pct = max(Decimal("0"), _tp1_max_pct())

    floor_price = round_price_exact(fill * (Decimal("1") + floor_pct))
    cap_price = (
        round_price_exact(fill * (Decimal("1") + cap_pct))
        if cap_pct > 0 else None
    )

    # Final TP: not below the floor/ladder, but limited by the cap.
    tp_limit = max(ladder_tp, floor_price)
    if cap_price is not None and tp_limit > cap_price:
        tp_limit = cap_price

    # stopPrice is slightly above sl_limit for a SELL stop-limit.
    offset = max(Decimal("0"), Decimal(str(stop_limit_offset_pct)))
    sl_stop = round_price_exact(sl_limit + max(tick * eps_mult, fill * offset))

    dbg("[TP-PICK] %s fill=%s ladder_tp=%s floor=%s cap=%s -> TP=%s; SLlim=%s, SLstop=%s" % (
        symbol,
        fmt_price_sym(symbol, fill),
        fmt_price_sym(symbol, ladder_tp),
        fmt_price_sym(symbol, floor_price),
        ("∞" if cap_price is None else fmt_price_sym(symbol, cap_price)),
        fmt_price_sym(symbol, tp_limit),
        fmt_price_sym(symbol, sl_limit),
        fmt_price_sym(symbol, sl_stop),
    ))

    return tp_limit, sl_stop, sl_limit

# ------------------- Core logic: BUY / SELL -------------------


# ------------------- CLI / main -------------------

def main():
    """Handle main."""
    parser = build_executor_parser()
    args = validate_executor_args(parser, parser.parse_args())
    log(f"[VERSION] {product_label('executor')}")
    global LIVE_MODE, WS_TRADING_MODE
    LIVE_MODE = bool(args.live)
    WS_TRADING_MODE = args.ws_trading_mode
    if LIVE_MODE:
        # Supervisor risk calculation treats target-buy as a hard maximum.
        # Therefore LIVE always checks existing BUY orders.
        args.enforce_target_buys = True

    if LIVE_MODE:
        # Repeat preflight even after supervisor validation: a worker can be started
        # independently or long after the original check.
        halt_file = Path(
            os.getenv(
                "CB_HALT_FILE",
                os.path.join(bot_run_dir(), "circuit_halt.json"),
            )
        )
        if halt_file.exists():
            parser.error(f"circuit halt exists: {halt_file}; reset through risk_ctl.py")
        stats_db = os.getenv("BOT_STATS_DB", "").strip()
        if not stats_db:
            parser.error("BOT_STATS_DB is required for LIVE mode")
        try:
            with sqlite3.connect(stats_db, timeout=5) as con:
                con.execute("SELECT 1 FROM trades LIMIT 1").fetchall()
            t0 = int(time.time() * 1000)
            server = _public_get("/api/v3/time")
            t1 = int(time.time() * 1000)
            assess_exchange_clock(
                server_time_ms=int(server["serverTime"]),
                request_started_ms=t0,
                response_finished_ms=t1,
                max_offset_ms=int(os.getenv("RISK_MAX_TIME_OFFSET_MS", "1000")),
                max_round_trip_ms=int(os.getenv("RISK_MAX_TIME_RTT_MS", "5000")),
            ).require_safe()
            pull_filters(args.symbol.upper())
            account = _signed_request("GET", "/api/v3/account")
            if account.get("canTrade") is not True:
                raise RuntimeError("Binance account/API key is not allowed to trade")
            _order_journal()
            # Reconcile every ordinary BUY/SELL intent before any new LIVE
            # action. This closes externally cancelled orders and definitive
            # Binance -2013 absences without manual SQLite edits.
            reconcile_nonterminal_orders(args.symbol.upper())
        except (OSError, sqlite3.Error, requests.RequestException, RuntimeError, KeyError, ValueError) as exc:
            parser.error(f"LIVE preflight failed: {exc}")
    attach_oco = bool(args.attach_oco_on_fill)

    symbol = args.symbol

    # OCO status is no longer hidden behind a question mark: before the first check,
    # explicitly show that protection is not confirmed. This distinguishes a
    # pending BUY from a verified OCO in logs and the dashboard.
    protection_state = "not_checked" if attach_oco else "disabled"

    def status_message(left: int) -> str:
        return (
            f"[status] {symbol} pid={os.getpid()} OCO:{protection_state} | "
            f"started:{datetime.fromtimestamp(started_at).strftime('%Y-%m-%d %H:%M:%S')} | "
            f"left:{int(left)}s | last: idle"
        )

    # --- per-symbol lock: a second process for the symbol exits immediately ---
    _lock = SymbolLock(symbol)
    if not _lock.acquire():
        return

    user_stream_mailbox = OrderEventMailbox()
    user_stream_observer: Optional[BinanceUserDataObserver] = None
    market_store: MarketSnapshotStore | None = None
    market_observer: BinanceMarketDataObserver | None = None
    try:
        ladder_prices = parse_comma_floats(args.ladder_prices)

        # --- Breakeven: keep OCO linked to the original BUY average price ---
        be_syms = {s.strip().upper() for s in args.breakeven_on_tp1_symbols.split(",") if s.strip()}
        BE_ENABLED = symbol.upper() in be_syms
        fee_pct = max(Decimal("0"), getenv_decimal("BOT_FEE_PCT", "0.00075"))
        BE_OFFSET = (
            args.breakeven_offset_pct
            if args.breakeven_offset_pct is not None
            else Decimal("2") * fee_pct
        )
        BE_CHECK_N = max(1, int(args.breakeven_check_interval))
        breakeven = BreakevenRuntime(
            enabled=BE_ENABLED,
            offset_pct=BE_OFFSET,
            check_interval=BE_CHECK_N,
        )
        be_state = BreakevenStateStore(bot_run_dir, dbg)

        if BE_ENABLED:
            log(f"[BE] {symbol} enabled | offset={BE_OFFSET:.4%} | check={BE_CHECK_N}s")
        else:
            dbg(f"[BE] {symbol} disabled")

        install_signal_handlers()
        pull_filters(symbol)
        user_stream_enabled = (
            LIVE_MODE
            and os.getenv("BOT_USER_STREAM_SHADOW", "1").lower()
            in ("1", "true", "yes")
        )
        if user_stream_enabled:
            if not API_KEY or not API_SECRET:
                log(
                    f"[USER-STREAM] {symbol} disabled: credentials unavailable; "
                    "REST polling remains authoritative"
                )
            else:
                user_stream_observer = BinanceUserDataObserver(
                    api_key=API_KEY,
                    api_secret=API_SECRET,
                    rest_base_url=BINANCE_API_BASE,
                    mailbox=user_stream_mailbox,
                    logger=log,
                    state_path=Path(bot_run_dir())
                    / f"user_stream_{symbol.upper()}.json",
                    timestamp_ms=TM._timestamp_ms,
                    state_persist_interval_sec=_compat_float(
                        os.getenv("BOT_USER_STREAM_STATE_WRITE_SEC", "5")
                    ),
                    idle_timeout_sec=_compat_float(
                        os.getenv("BOT_USER_STREAM_IDLE_TIMEOUT_SEC", "90")
                    ),
                )
                user_stream_observer.start()
        if args.fast_market_mode != "OFF":
            market_store = MarketSnapshotStore(symbol)
            market_observer = BinanceMarketDataObserver(
                market_store,
                testnet="testnet" in BINANCE_API_BASE.lower(),
                logger=log,
            )
            market_observer.start()
            log(
                f"[FAST-MARKET] {symbol} mode={args.fast_market_mode} "
                f"max_age={args.fast_market_max_age_ms}ms"
            )
        current_price = get_price(symbol)

        # Protection deduplication also runs here: direct worker startup must not
        # depend on whether the supervisor normalized the ladder.
        ladder_prices = dedup_ladder(symbol, ladder_prices, current_price)

        started_at = time.time()
        warmup = cleanup_warmup_sec()
        log(status_message(int(args.loop_minutes * 60)))

        # BUY size comes from the environment (per-order cap) when supplied by supervisor.
        cap = _cap_decimal(
            "BOT_CAP_PER_ORDER",
            os.getenv("BOT_CAP_PER_ORDER", "50"),
        )

        vwap_ratio: Optional[float] = None
        vwap_value: Optional[float] = None
        need_vwap = (
            args.buy_vwap_premium is not None or
            (args.buy_vwap_discount is not None and _compat_float(args.buy_vwap_discount) > 0) or
            (args.buy_vwap_discount_scale is not None and _compat_float(args.buy_vwap_discount_scale) != 1.0)
        )
        if need_vwap:
            try:
                vwap_value = get_vwap_cached(
                    symbol,
                    interval=args.buy_vwap_interval or "1m",
                    window=max(5, int(args.buy_vwap_window)),
                    ttl_sec=15,
                )
            except (
                requests.RequestException,
                RuntimeError,
                ValueError,
                ArithmeticError,
                OSError,
            ) as e:
                dbg(f"[VWAP] {symbol} calc err: {e}")
                vwap_value = None
            if vwap_value and vwap_value > 0:
                vwap_ratio = current_price / vwap_value

        # Average price and panic state jointly control BUY permission and the minimum
        # acceptable protective SELL price.
        safety_buy_block_reason: Optional[str] = None
        try:
            ema20, atr, prev_close = get_indicators_cached(symbol, args.panic_interval, ttl_sec=20)
            _clear_safety_control_failure("panic-indicators", symbol)
            raw_panic_active = panic_raw(
                current_price,
                ema20,
                atr,
                prev_close,
                _compat_float(args.panic_drop_pct),
                _compat_float(args.panic_k_atr),
            )
        except (
            requests.RequestException,
            RuntimeError,
            ValueError,
            ArithmeticError,
            OSError,
        ) as exc:
            ema20 = atr = prev_close = None
            raw_panic_active = True
            _record_safety_control_failure("panic-indicators", symbol, exc)
            safety_buy_block_reason = "panic-indicators-unavailable"
        try:
            avg_px = avg_entry(symbol, cache_ttl=args.avg_cache_ttl, lookback=args.avg_lookback)
        except (
            requests.RequestException,
            RuntimeError,
            ValueError,
            ArithmeticError,
            OSError,
            sqlite3.Error,
        ):
            avg_px = None
        panic_active, panic_block_reason = _panic_state_fail_closed(
            "panic-state",
            symbol,
            lambda: update_panic_state(
                symbol=symbol,
                now_px=current_price,
                ema20=ema20, atr=atr, prev_close=prev_close,
                avg_entry_px=avg_px,
                panic_drop_pct=_compat_float(args.panic_drop_pct),
                panic_k_atr=_compat_float(args.panic_k_atr),
                debounce_checks=int(args.panic_debounce_checks),
                cooldown_sec=int(args.panic_cooldown_sec),
            ),
        )
        if panic_block_reason is not None:
            safety_buy_block_reason = panic_block_reason

        trend_interval = args.buy_trend_interval or args.panic_interval
        if trend_interval == args.panic_interval:
            trend_ema = ema20
        else:
            try:
                trend_ema, _, _ = get_indicators_cached(symbol, trend_interval, ttl_sec=20)
            except (
                requests.RequestException,
                RuntimeError,
                ValueError,
                ArithmeticError,
                OSError,
            ):
                trend_ema = None

        bear_gap = 0.0
        bear_mode = False
        if trend_ema and trend_ema > 0 and args.buy_trend_ema_gap is not None:
            try:
                gap_thr = max(0.0, _compat_float(args.buy_trend_ema_gap))
            except (TypeError, ValueError, OverflowError):
                gap_thr = 0.0
            bear_gap = max(0.0, (trend_ema - current_price) / trend_ema)
            bear_mode = (bear_gap > 0.0) and (bear_gap >= gap_thr)
        if bear_mode:
            log(f"[BEAR] {symbol} price≈{fmt_price_sym(symbol, current_price)} EMA({trend_interval})≈{fmt_price_sym(symbol, trend_ema or 0)} gap≈{bear_gap:.4f}")

        if bear_mode and args.bear_buy_shift_pct > 0:
            ladder_prices = adjust_buy_ladder(symbol, ladder_prices, current_price, _compat_float(args.bear_buy_shift_pct))
            ladder_prices = dedup_ladder(symbol, ladder_prices, current_price)

        if bear_mode and args.bear_cap_scale is not None:
            scale = Decimal(str(clamp(_compat_float(args.bear_cap_scale), 0.0, 5.0)))
            if scale != Decimal("1"):
                cap *= scale
                log(f"[BEAR] {symbol} cap scale {scale:.3f} → {cap:.2f} USDT")

        if vwap_ratio is not None and args.buy_vwap_discount is not None:
            try:
                discount_thr = clamp(_compat_float(args.buy_vwap_discount), 0.0, 0.5)
            except (TypeError, ValueError, OverflowError):
                discount_thr = 0.0
            if discount_thr > 0 and vwap_ratio <= (1.0 - discount_thr):
                scale = Decimal(
                    str(clamp(_compat_float(args.buy_vwap_discount_scale), 0.1, 10.0))
                )
                if scale != Decimal("1"):
                    old_cap = cap
                    cap *= scale
                    log(
                        f"[VWAP] {symbol} discount ratio={vwap_ratio:.4f} <= 1-{discount_thr:.4f} → cap {old_cap:.2f}→{cap:.2f} x{scale:.2f}"
                    )

        try:
            clamped_cap, cap_limits = hard_buy_cap(symbol, cap)
        except ValueError as exc:
            clamped_cap = Decimal("0")
            cap_limits = {}
            log(f"[CAP-HARD-ERROR] {symbol} {exc}; BUY disabled")
        if clamped_cap != cap:
            rendered = ",".join(
                f"{name}={value}" for name, value in sorted(cap_limits.items())
            )
            log(
                f"[CAP-HARD] {symbol} proposed={cap} "
                f"final={clamped_cap} limits={rendered}"
            )
        cap = clamped_cap

        use_remainder_in_last = effective_remainder_policy(
            requested=bool(args.use_remainder_in_last),
            live_mode=LIVE_MODE,
        )
        if LIVE_MODE and args.use_remainder_in_last:
            log(
                f"[CAP-HARD] {symbol} --use-remainder-in-last ignored in LIVE"
            )

        # Run the gap control before any new BUY. A failed check is a safety
        # state, not an informational error; replacement workers may otherwise
        # place exposure while protection telemetry is unavailable.
        if LIVE_MODE and os.getenv("BOT_GAP_WATCHDOG", "1").lower() in ("1", "true", "yes"):
            gap_block_reason = _gap_watchdog_fail_closed(
                symbol,
                current_price,
                dependencies=_protection_dependencies(),
                gap_tolerance_pct=max(
                    0.0,
                    getenv_float("BOT_GAP_TOLERANCE_PCT", 0.001),
                ),
            )
            if gap_block_reason is not None:
                safety_buy_block_reason = gap_block_reason

        # The debounce controls escalation/flattening.  It must never create a
        # window in which a fresh LIVE executor submits BUY exposure between the
        # first and second confirmation of the same adverse signal.
        skip_buys_reason = _panic_buy_block_reason(
            safety_buy_block_reason,
            live_mode=LIVE_MODE,
            raw_signal=raw_panic_active,
            debounced_active=panic_active,
            skip_while_panic=args.skip_buy_while_panic,
        )
        panic_sell_floor_pct = args.panic_sell_floor_pct
        if skip_buys_reason is None and bear_mode and args.bear_skip_buys:
            skip_buys_reason = "bear-trend"
        elif skip_buys_reason is None and cap <= 0:
            skip_buys_reason = "cap<=0"
        elif (
            skip_buys_reason is None
            and vwap_ratio is not None
            and args.buy_vwap_premium is not None
        ):
            try:
                premium = max(
                    Decimal("0"),
                    exact_decimal(
                        args.buy_vwap_premium,
                        field="BUY VWAP premium",
                    ),
                )
                hysteresis = max(
                    Decimal("0"),
                    getenv_decimal("BUY_VWAP_HYSTERESIS_PCT", "0.0002"),
                )
                previous_vwap_block = _VWAP_PREMIUM_BLOCKED.get(
                    symbol.upper(), False
                )
                current_vwap_block = (
                    vwap_premium_blocked(
                        previously_blocked=previous_vwap_block,
                        price_to_vwap_ratio=str(vwap_ratio),
                        premium=premium,
                        hysteresis=hysteresis,
                    )
                    if premium > 0
                    else False
                )
                _VWAP_PREMIUM_BLOCKED[symbol.upper()] = current_vwap_block
            except (ArithmeticError, TypeError, ValueError):
                current_vwap_block = True
                premium = Decimal("0")
                hysteresis = Decimal("0")
                _VWAP_PREMIUM_BLOCKED[symbol.upper()] = True
            if current_vwap_block:
                skip_buys_reason = "buy-vwap-premium"
                if vwap_value:
                    log(
                        f"[VWAP] {symbol} now≈{fmt_price_sym(symbol, current_price)} vwap≈{fmt_price_sym(symbol, vwap_value)} "
                        f"ratio={vwap_ratio:.6f} premium={premium} "
                        f"hysteresis={hysteresis} blocked={current_vwap_block} "
                        "→ skip BUY"
                    )

        # Before new BUY orders, recover unfinished intents after restart. This makes
        # the same FILLED/PARTIAL BUY pass through OCO protection again.
        placed_ids: List[int] = (
            recover_pending_buy_order_ids(symbol)
            if LIVE_MODE and attach_oco
            else []
        )
        if skip_buys_reason:
            log(f"[SKIP-BUY] {symbol} reason={skip_buys_reason}; new BUY orders suppressed this cycle")
        else:
            try:
                new_ids = service_place_buys(
                    symbol,
                    ladder_prices,
                    cap,
                    min_order_usdt=args.min_order_usdt,
                    cap_floor_usdt=args.cap_floor_usdt,
                    target_buy_per_symbol=args.target_buy_per_symbol,
                    enforce_limit=args.enforce_target_buys,
                    use_remainder_in_last=use_remainder_in_last,
                    buy_limit_maker=args.buy_limit_maker,
                    live_mode=LIVE_MODE,
                    market_store=market_store,
                    market_policy=DecisionFreshnessPolicy(
                        max_age_ms=args.fast_market_max_age_ms,
                        max_spread_bps=args.fast_market_max_spread_bps,
                        max_price_move_bps=args.fast_market_max_move_bps,
                        minimum_net_edge_bps=(
                            args.fast_market_min_net_edge_bps
                        ),
                    ),
                    market_mode=args.fast_market_mode,
                    otoco_mode=args.otoco_mode,
                    stop_limit_offset_pct=args.stop_limit_offset_pct,
                    runtime=globals(),
                )
                placed_ids = list(dict.fromkeys([*placed_ids, *new_ids]))
            except (
                requests.RequestException,
                RuntimeError,
                ValueError,
                ArithmeticError,
            ) as e:
                log(f"[ERR] maybe_place_buys: {e}")
            try:
                _observe_buy_market(symbol, placed_ids, current_price)
            except (
                RuntimeError,
                ValueError,
                ArithmeticError,
                OSError,
                sqlite3.Error,
            ) as exc:
                _record_safety_control_failure(
                    "order-lifetime-observation", symbol, exc
                )

        # Sell free holdings separately only when they do not compete for the same
        # base balance as an OCO waiting for a new BUY to execute.
        if args.auto_oco_holdings and (not attach_oco or not placed_ids):
            if attach_oco and not placed_ids:
                dbg("[AUTO-OCO] no new BUYs this run → enabling auto_oco_holdings for free base")
            try:
                _ = place_sells_from_holdings(
                    symbol,
                    ladder_prices,
                    args.max_oco_per_symbol,
                    enforce_limit=getattr(args, "enforce_sell_limit", False),
                    avg_entry_px=avg_px,
                    panic_active=panic_active,
                    sell_limit_maker=args.sell_limit_maker,
                    panic_sell_floor_pct=panic_sell_floor_pct,
                    runtime=globals(),
                )
            except (
                requests.RequestException,
                RuntimeError,
                ValueError,
                ArithmeticError,
            ) as e:
                log(f"[ERR] maybe_place_sells: {e}")
        else:
            if attach_oco and placed_ids:
                dbg("[SKIP] auto_oco_holdings: skipped because attach_oco_on_fill is enabled and new BUYs exist")

        # One-time trade collection when statistics are enabled.
        try:
            sync_account_trades(symbol, runtime=globals())
        except (
            requests.RequestException,
            RuntimeError,
            ValueError,
            ArithmeticError,
            OSError,
            sqlite3.Error,
        ) as e:
            log(f"[STATS] poll error: {e}")

        # The runtime loop does not create new BUY orders. It observes existing orders,
        # confirms FILLED/PARTIAL states, and always creates protection.
        last_check = 0
        panic_cancel_applied = False

        def record_stream_events(stream_events) -> None:
            """Persist sanitized event latency outside the order mutation path."""
            journal = _order_journal()
            latency_path = os.getenv(
                "BOT_EXECUTION_LATENCY_LOG",
                str(
                    Path(__file__).resolve().parents[3]
                    / "logs"
                    / "execution_latency.ndjson"
                ),
            )
            if journal is None:
                return
            for event in stream_events:
                created_ms = journal.created_at_ms_for_exchange_order(
                    event.order_id
                )
                if created_ms is None:
                    continue
                try:
                    commission_quote = None
                    commission_status = "not_applicable"
                    if event.execution_type == "TRADE":
                        commission_amount = Decimal(event.commission_amount)
                        if commission_amount == 0:
                            commission_quote = Decimal("0")
                            commission_status = "exact"
                        else:
                            commission_quote, commission_status = (
                                _commission_quote_value(
                                    event.symbol,
                                    event.commission_asset,
                                    commission_amount,
                                    Decimal(event.last_price),
                                    event.transaction_time_ms,
                                )
                            )
                    append_execution_latency_sample(
                        latency_path,
                        event,
                        intent_created_at_ms=created_ms,
                        commission_quote=commission_quote,
                        commission_value_status=commission_status,
                    )
                except (
                    ArithmeticError,
                    OSError,
                    TypeError,
                    ValueError,
                ) as exc:
                    dbg(
                        "[USER-STREAM] execution latency sample "
                        f"unavailable={type(exc).__name__}"
                    )

        def reconcile_tracked_buys(
            stream_events,
            *,
            event_woken: bool,
        ) -> None:
            """Run authoritative protection immediately after a WS wakeup."""
            nonlocal placed_ids, protection_state
            trace = LatencyTrace(symbol, "fill-reconcile")
            if event_woken:
                trace.mark("fill_received")
            pending_before = list(placed_ids)
            terminal_unfilled: set[int] = set()
            placed_ids = protect_filled_buys(
                symbol,
                placed_ids,
                ladder_prices,
                config=ProtectionConfig(
                    stop_limit_offset_pct=args.stop_limit_offset_pct,
                    oco_fallback=args.oco_fallback,
                    sell_limit_maker=args.sell_limit_maker,
                    avg_cache_ttl=args.avg_cache_ttl,
                    avg_lookback=args.avg_lookback,
                    panic_sell_floor_pct=panic_sell_floor_pct,
                ),
                panic_active=panic_active,
                breakeven_enabled=breakeven.enabled,
                state_store=be_state,
                dependencies=_protection_dependencies(),
                terminal_unfilled_order_ids=terminal_unfilled,
            )
            if user_stream_observer is not None:
                user_stream_observer.record_rest_reconciliation(
                    event_woken=event_woken
                )
            protection_state = _protection_state_after_sweep(
                pending_before,
                placed_ids,
                terminal_unfilled,
            )
            if event_woken and protection_state == "confirmed":
                trace.mark("protection_active")
            if event_woken:
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

        for left in trading_wakeups(
            int(args.loop_minutes * 60),
            running=lambda: RUN,
            wait=lambda timeout: (
                user_stream_mailbox.wait_for(placed_ids, timeout)
                if user_stream_observer is not None and placed_ids
                else time.sleep(timeout)
            ),
        ):
            stream_events = (
                user_stream_mailbox.consume_for(placed_ids)
                if attach_oco and placed_ids
                else []
            )
            if stream_events:
                record_stream_events(stream_events)
                latest = stream_events[-1]
                log(
                    f"[USER-STREAM] {symbol} order={latest.order_id} "
                    f"event={latest.execution_type}/{latest.order_status}; "
                    "immediate authoritative REST reconciliation"
                )
                reconcile_tracked_buys(
                    stream_events,
                    event_woken=True,
                )
                last_check = 0

            if status_due(left, args.status_interval):
                log(status_message(left))

            # Periodically refresh indicators/panic state in the lightweight mode.
            previous_panic_active = panic_active
            try:
                ema20, atr, prev_close = get_indicators_cached(symbol, args.panic_interval, ttl_sec=20)
                avg_px = avg_entry(symbol, cache_ttl=args.avg_cache_ttl, lookback=args.avg_lookback)
                runtime_price = get_price(symbol)
                _observe_buy_market(symbol, placed_ids, runtime_price)
                panic_active, _ = _panic_state_fail_closed(
                    "panic-runtime",
                    symbol,
                    lambda: update_panic_state(
                        symbol=symbol,
                        now_px=runtime_price,
                        ema20=ema20, atr=atr, prev_close=prev_close,
                        avg_entry_px=avg_px,
                        panic_drop_pct=_compat_float(args.panic_drop_pct),
                        panic_k_atr=_compat_float(args.panic_k_atr),
                        debounce_checks=int(args.panic_debounce_checks),
                        cooldown_sec=int(args.panic_cooldown_sec),
                    ),
                )
            except (
                requests.RequestException,
                RuntimeError,
                ValueError,
                ArithmeticError,
                OSError,
                sqlite3.Error,
            ) as exc:
                panic_active = True
                _record_safety_control_failure("panic-runtime", symbol, exc)

            if not panic_active:
                panic_cancel_applied = False
            elif LIVE_MODE and not panic_cancel_applied and placed_ids:
                placed_ids = cancel_open_buys_for_panic(symbol, placed_ids)
                panic_cancel_applied = True
                if not placed_ids:
                    protection_state = "not_needed"

            if LIVE_MODE and os.getenv("BOT_GAP_WATCHDOG", "1").lower() in ("1", "true", "yes"):
                try:
                    gap_price = get_price(symbol)
                except (
                    requests.RequestException,
                    RuntimeError,
                    ValueError,
                    ArithmeticError,
                    OSError,
                ) as exc:
                    _record_safety_control_failure("gap-watchdog", symbol, exc)
                else:
                    _gap_watchdog_fail_closed(
                        symbol,
                        gap_price,
                        dependencies=_protection_dependencies(),
                        gap_tolerance_pct=max(
                            0.0,
                            getenv_float("BOT_GAP_TOLERANCE_PCT", 0.001),
                        ),
                    )

            # The runtime loop deliberately cannot submit BUY orders. Once a
            # confirmed PANIC recovery leaves no BUY to protect, return normally
            # so the supervisor starts a fresh worker that re-runs every LIVE
            # preflight, Risk, gap, CAP, VWAP and open-order gate before buying.
            if _panic_recovery_restart_required(
                live_mode=LIVE_MODE,
                was_active=previous_panic_active,
                is_active=panic_active,
                tracked_buy_order_ids=placed_ids,
            ):
                log(
                    f"[PANIC-RECOVERY] {symbol} no tracked BUY; "
                    "requesting fresh gated executor cycle"
                )
                return

            # A stream event was reconciled before indicators and other REST
            # analytics. Periodic REST remains authoritative when the stream is
            # quiet, disconnected, duplicated or out of order.
            if attach_oco and placed_ids and not stream_events:
                last_check += 1
                if reconciliation_due(
                    last_check,
                    args.check_fills_interval,
                    (),
                ):
                    last_check = 0
                    reconcile_tracked_buys(
                        (),
                        event_woken=False,
                    )

            # LIVE time-stop prevents a position from remaining stuck forever. Binance
            # does not provide this policy for an already filled BUY, so track position
            # age locally and close it with a MARKET order.
            max_hold_min = max(0.0, getenv_float("BOT_MAX_HOLDING_MINUTES", 0.0))
            if LIVE_MODE and max_hold_min > 0 and placed_ids:
                now_ms = int(time.time() * 1000)
                for oid in list(placed_ids):
                    held = get_order(symbol, oid)
                    if not held or str(held.get("status", "")).upper() != "FILLED":
                        continue
                    opened_ms = int(held.get("time") or held.get("transactTime") or now_ms)
                    if now_ms - opened_ms < max_hold_min * 60_000:
                        continue
                    qty_exp = Decimal(str(held.get("executedQty", 0) or 0))
                    # When the ledger knows lots, time-stop closes the oldest inventory
                    # first instead of an arbitrary aggregated quantity.
                    if STATS_CON is not None:
                        try:
                            lots = oldest_lots(STATS_CON, symbol)
                            lot_qty = sum((lot.qty for lot in lots), Decimal("0"))
                            if lot_qty > 0:
                                qty_exp = min(qty_exp, lot_qty)
                        except sqlite3.Error:
                            pass
                    if qty_exp > 0:
                        log(f"[TIME-STOP] {symbol} order={oid} age>{max_hold_min:g}m; flattening")
                        place_market_order(symbol, "SELL", qty_exp,
                                           ref_price=get_price_exact(symbol),
                                           filters=symbol_filters.get(symbol))
                    _trip_execution_halt("max holding time exceeded", symbol=symbol, order_id=oid)
                    placed_ids.remove(oid)

            # --- Breakeven OCO support after a partial TP fill ---
            if breakeven.due():
                maintain_breakeven(
                    symbol,
                    offset_pct=breakeven.offset_pct,
                    stop_limit_offset_pct=args.stop_limit_offset_pct,
                    state_store=be_state,
                    dependencies=_protection_dependencies(),
                )

        return
    finally:
        if _WS_TRADING_TRANSPORT is not None:
            _WS_TRADING_TRANSPORT.close()
        if market_observer is not None:
            market_observer.stop()
        if user_stream_observer is not None:
            user_stream_observer.stop()
        # Always release the lock.
        _lock.release()

if __name__ == "__main__":
    main()
