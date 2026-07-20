#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: implement the tools market component of the execution layer.
"""Ladder Dragon tools market support."""

from __future__ import annotations
import os
import time
import hmac
import math
import hashlib
import requests
from typing import Dict, Tuple, List, Optional, Any
from ladder_dragon.execution.exchange_math import normalized_order_values, round_step
from ladder_dragon.execution.telegram_alerts import notify_binance_auth_error

# --- optional .env ---
from pathlib import Path

try:
    from dotenv import load_dotenv, find_dotenv
except ModuleNotFoundError:
    # python-dotenv is optional; skip loading when it is not installed.
    pass
else:
    # 1) First try .env next to this file.
    env_path = (Path(__file__).resolve().parents[2] / ".env")
    if env_path.exists():
        load_dotenv(dotenv_path=env_path, override=False)
    else:
        # 2) Otherwise search upward from the current working directory for manual runs.
        found = find_dotenv(usecwd=True)
        if found:
            load_dotenv(found, override=False)

BASE_URL = (os.getenv("BINANCE_BASE_URL") or os.getenv("BINANCE_API_BASE") or "https://api.binance.com").rstrip("/")
API_KEY = os.getenv("BINANCE_API_KEY", "")
API_SECRET = os.getenv("BINANCE_API_SECRET", "")
RECV_WINDOW = int(os.getenv("BINANCE_RECV_WINDOW", "5000"))
TIMEOUT = int(os.getenv("BINANCE_TIMEOUT", "10"))

SESSION = requests.Session()
SESSION.headers.update({"User-Agent": "tools_market/1.4"})

class BinanceHttpError(RuntimeError):
    pass

# ---- simple retries ----
def _do_request(method: str, url: str, **kw) -> requests.Response:
    attempts = 3
    delay = 0.5
    for i in range(attempts):
        try:
            r = SESSION.request(method, url, timeout=TIMEOUT, **kw)
            if r.status_code in (418, 429) or 500 <= r.status_code < 600:
                if i == attempts - 1:
                    return r
                time.sleep(delay)
                delay *= 2
                continue
            return r
        except requests.RequestException:
            if i == attempts - 1:
                raise
            time.sleep(delay)
            delay *= 2

def _raise_for_binance(resp: requests.Response):
    if resp.status_code == 200:
        return
    try:
        data = resp.json()
    except (requests.JSONDecodeError, TypeError, ValueError):
        data = {"msg": resp.text}
    if not isinstance(data, dict):
        data = {"msg": str(data)}
    if resp.status_code in (401, 403) or data.get("code") in (-2014, -2015, -1022):
        notify_binance_auth_error(
            status=resp.status_code,
            code=data.get("code"),
            endpoint=resp.url,
            message=data.get("msg", ""),
        )
    raise BinanceHttpError(f"HTTP {resp.status_code}: {data}")

# ---- time offset (server time skew) ----
_time_offset_ms: Optional[int] = None
_time_offset_ts: float = 0.0
_OFFSET_TTL = 60.0

def _refresh_time_offset():
    global _time_offset_ms, _time_offset_ts
    url = f"{BASE_URL}/api/v3/time"
    r = _do_request("GET", url)
    _raise_for_binance(r)
    srv = int(r.json()["serverTime"])
    now = int(time.time() * 1000)
    _time_offset_ms = srv - now
    _time_offset_ts = time.time()

def _timestamp_ms() -> int:
    global _time_offset_ms, _time_offset_ts
    if _time_offset_ms is None or (time.time() - _time_offset_ts) > _OFFSET_TTL:
        # Signed mutations must not guess the exchange clock after a failed
        # time read. Propagating the operational failure keeps the caller
        # fail-closed and avoids ambiguous submissions outside recvWindow.
        _refresh_time_offset()
    return int(time.time() * 1000 + (_time_offset_ms or 0))

# ---- signing: keep a stable parameter order ----
def _sign_tuples(params: List[Tuple[str, str]], secret: str) -> str:
    query = "&".join(f"{k}={v}" for k, v in params)
    return hmac.new(secret.encode("utf-8"), query.encode("utf-8"), hashlib.sha256).hexdigest()

# ---- public/private requests ----
def _public_get(path: str, params: Dict | List[Tuple[str, str]] | None = None) -> Any:
    url = f"{BASE_URL}{path}"
    r = _do_request("GET", url, params=params or {})
    _raise_for_binance(r)
    return r.json()

def _signed_get(path: str, params: Dict | None = None) -> Any:
    if not API_KEY or not API_SECRET:
        raise BinanceHttpError("BINANCE_API_KEY/SECRET not set in environment")
    url = f"{BASE_URL}{path}"
    base_params = params.copy() if params else {}
    base_params["timestamp"] = str(_timestamp_ms())
    base_params["recvWindow"] = str(RECV_WINDOW)

    items: List[Tuple[str, str]] = [(k, str(v)) for k, v in base_params.items()]
    sig = _sign_tuples(items, API_SECRET)
    items.append(("signature", sig))

    headers = {"X-MBX-APIKEY": API_KEY}
    r = _do_request("GET", url, params=items, headers=headers)
    _raise_for_binance(r)
    return r.json()

# ---- kline interval normalization ----
VALID_INTERVALS: set[str] = {
    "1m","3m","5m","15m","30m",
    "1h","2h","4h","6h","8h","12h",
    "1d","3d","1w","1M",
}
_INTERVAL_ALIASES: Dict[str, str] = {
    # English aliases.
    "1min": "1m", "3min": "3m", "5min": "5m", "15min": "15m", "30min": "30m",
    "1hour": "1h", "2hour": "2h", "4hour": "4h", "6hour": "6h", "12hour": "12h",
    "1day": "1d", "3day": "3d", "1week": "1w", "1month": "1M",
    # Preserve legacy localized inputs without mixing localized text into source documentation.
    "1\u043c\u0438\u043d": "1m", "3\u043c\u0438\u043d": "3m", "5\u043c\u0438\u043d": "5m",
    "15\u043c\u0438\u043d": "15m", "30\u043c\u0438\u043d": "30m",
    "1\u0447\u0430\u0441": "1h", "2\u0447\u0430\u0441": "2h", "4\u0447\u0430\u0441": "4h",
    "6\u0447\u0430\u0441": "6h", "12\u0447\u0430\u0441": "12h",
    "1\u0434": "1d", "3\u0434": "3d", "1\u043d": "1w", "1\u043c\u0435\u0441": "1M",
    # Common Russian aliases kept for backward compatibility.
}

# --- additional aliases ---
_INTERVAL_ALIASES.update({
    "8hour": "8h", "8hours": "8h", "8\u0447\u0430\u0441": "8h",
    "8\u0447\u0430\u0441\u043e\u0432": "8h", "8\u0447": "8h",
    "2hours": "2h", "4hours": "4h", "6hours": "6h", "12hours": "12h",
    "2\u0447": "2h", "4\u0447": "4h", "6\u0447": "6h", "12\u0447": "12h",
    # Some callers add an s suffix; whitespace is already handled.
})

def norm_interval(interval: str | None, default: str = "15m") -> str:
    """Handle norm interval."""
    s = (interval or "").strip().replace(" ", "")
    if not s:
        return default

    # 1) Month: exact '1M' or a word alias -> '1M'.
    s_low = s.lower()
    if s == "1M" or s_low in {
        "1month", "1mon", "1mo", "1\u043c\u0435\u0441", "1\u043c\u0435\u0441\u044f\u0446"
    }:
        return "1M"

    # 2) Other aliases and minute/hour/day/week variants.
    s_norm = _INTERVAL_ALIASES.get(s_low, s_low)

    # 3) Final validity check.
    return s_norm if s_norm in VALID_INTERVALS else default

# ---- kline API with interval fallback ----
def get_klines(symbol: str,
               interval: str,
               *,
               limit: int = 500,
               startTime: Optional[int] = None,
               endTime: Optional[int] = None,
               fallback_default: str = "15m") -> List[List[Any]]:
    """Return klines."""
    symbol = symbol.upper()
    interval = norm_interval(interval, default=fallback_default)

    params: List[Tuple[str, str]] = [
        ("symbol", symbol),
        ("interval", interval),
        ("limit", str(limit)),
    ]
    if startTime is not None:
        params.append(("startTime", str(int(startTime))))
    if endTime is not None:
        params.append(("endTime", str(int(endTime))))

    url = f"{BASE_URL}/api/v3/klines"

    # First request.
    r = _do_request("GET", url, params=params)
    if r.status_code == 200:
        try:
            return r.json()  # type: ignore[return-value]
        except (requests.JSONDecodeError, TypeError, ValueError) as e:
            raise BinanceHttpError(f"Failed to parse klines JSON: {e}")

    # Error handling.
    try:
        err = r.json()
    except (requests.JSONDecodeError, TypeError, ValueError):
        err = {"msg": r.text}

    # Fallback for an invalid interval.
    if r.status_code == 400 and isinstance(err, dict) and err.get("code") == -1120:
        fb = norm_interval(fallback_default, default="15m")
        if fb != interval:
            print(f"[KLINES] invalid interval '{interval}', retry with '{fb}'", flush=True)
            params = [(k, v if k != "interval" else fb) for (k, v) in params]
            r2 = _do_request("GET", url, params=params)
            _raise_for_binance(r2)
            try:
                return r2.json()  # type: ignore[return-value]
            except (requests.JSONDecodeError, TypeError, ValueError) as e:
                raise BinanceHttpError(f"Failed to parse klines JSON after fallback: {e}")

    # If reached, re-raise the original exception.
    _raise_for_binance(r)
    return []

# ---- exchangeInfo cache ----
_exchange_cache: Dict[str, Dict[str, object]] = {}
_exchange_cache_ts: Dict[str, float] = {}  # TTL
_CACHE_TTL = 300

def get_symbol_filters(symbol: str) -> Dict[str, object]:
    symbol = symbol.upper()
    now = time.time()
    if symbol in _exchange_cache and (now - _exchange_cache_ts.get(symbol, 0)) < _CACHE_TTL:
        return _exchange_cache[symbol]

    data = _public_get("/api/v3/exchangeInfo", {"symbol": symbol})
    symbols = data.get("symbols") or []
    if not symbols:
        raise BinanceHttpError(f"exchangeInfo: symbol '{symbol}' not found")
    info = symbols[0]

    tick_size_exact = "0"
    step_size_exact = "0"
    min_qty_exact = "0"
    min_notional_exact = "5"

    # Additional fields used by the supervisor and validators.
    price_precision = int(info.get("pricePrecision", 0))
    qty_precision   = int(info.get("quantityPrecision", 0))

    # Some markets use MARKET_LOT_SIZE for market orders.
    market_step_size_exact = "0"
    market_min_qty_exact = "0"

    for f in info.get("filters", []):
        ftype = f.get("filterType")
        if ftype == "PRICE_FILTER":
            tick_size_exact = str(f.get("tickSize", "0") or "0")
        elif ftype == "LOT_SIZE":
            step_size_exact = str(f.get("stepSize", "0") or "0")
            min_qty_exact = str(f.get("minQty", "0") or "0")
        elif ftype == "MARKET_LOT_SIZE":
            market_step_size_exact = str(f.get("stepSize", "0") or "0")
            market_min_qty_exact = str(f.get("minQty", "0") or "0")
        elif ftype in ("MIN_NOTIONAL", "NOTIONAL"):
            mn = f.get("minNotional")
            if mn is not None:
                min_notional_exact = str(mn)

    res = {
        # Compatibility floats are retained for indicator-only callers. Every
        # order-normalization path consumes the exact strings below.
        "tickSize": float(tick_size_exact),
        "stepSize": float(step_size_exact),
        "minQty": float(min_qty_exact),
        "minNotional": float(min_notional_exact),
        "tickSizeExact": tick_size_exact,
        "stepSizeExact": step_size_exact,
        "minQtyExact": min_qty_exact,
        "minNotionalExact": min_notional_exact,
        "pricePrecision": price_precision,
        "quantityPrecision": qty_precision,
        "marketStepSize": float(market_step_size_exact),
        "marketMinQty": float(market_min_qty_exact),
        "marketStepSizeExact": market_step_size_exact,
        "marketMinQtyExact": market_min_qty_exact,
    }
    _exchange_cache[symbol] = res
    _exchange_cache_ts[symbol] = now
    return res

def get_ticker_price(symbol: str) -> float:
    data = _public_get("/api/v3/ticker/price", {"symbol": symbol.upper()})
    return float(data["price"])

def get_free_and_balance_usdt() -> Tuple[float, float]:
    data = _signed_get("/api/v3/account")
    free = 0.0
    locked = 0.0
    for a in data.get("balances", []):
        if a.get("asset") == "USDT":
            free = float(a.get("free", 0))
            locked = float(a.get("locked", 0))
            break
    return free, free + locked

# ---- filter-aware qty/price normalization ----
def _decimals_from_float_step(step: float) -> int:
    s = f"{step:.16f}".rstrip("0").rstrip(".")
    if "." in s:
        return len(s.split(".", 1)[1])
    return 0

def _round_by_step(value: float, step: float, mode: str = "floor") -> float:
    return float(round_step(value, step, mode))

def round_qty_price(symbol: str, qty: object, price: object, side: str = "BUY") -> Tuple[str, str]:
    """Handle round qty price."""
    side = (side or "BUY").upper()
    f = get_symbol_filters(symbol)
    try:
        return normalized_order_values(
            qty,
            price,
            step=f.get("stepSizeExact", f.get("stepSize", 0)),
            tick=f.get("tickSizeExact", f.get("tickSize", 0)),
            min_qty=f.get("minQtyExact", f.get("minQty", 0)),
            min_notional=f.get("minNotionalExact", f.get("minNotional", 0)),
            side=side,
        )
    except ValueError as exc:
        raise BinanceHttpError(str(exc)) from exc
