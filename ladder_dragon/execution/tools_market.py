#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: implement the tools market component of the execution layer.
"""Ladder Dragon tools market support."""

from __future__ import annotations
from decimal import Decimal, InvalidOperation
import os
import time
import hmac
import math
import hashlib
import threading
import requests
from typing import Dict, Tuple, List, Optional, Any
from urllib.parse import urlsplit
from urllib3.exceptions import HTTPError as UrllibHttpError

from ladder_dragon.execution.market_http_body import read_body, remaining_seconds
from ladder_dragon.execution.market_tickers import requested_prices

from ladder_dragon.execution.time_safety import (
    assess_exchange_clock,
    exchange_time_offset_ms,
)
from ladder_dragon.execution.exchange_math import (
    exact_symbol_filters,
    normalized_order_values,
    round_step,
)
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
INITIAL_PUBLIC_SESSION = requests.Session()
INITIAL_PUBLIC_SESSION.headers.update({"User-Agent": "tools_market/1.4"})
PREFLIGHT_CLOCK_SESSION = requests.Session()
PREFLIGHT_CLOCK_SESSION.headers.update({"User-Agent": "tools_market/1.4"})
PREFLIGHT_FILTERS_SESSION = requests.Session()
PREFLIGHT_FILTERS_SESSION.headers.update({"User-Agent": "tools_market/1.4"})

class BinanceHttpError(RuntimeError):
    """Carry bounded Binance error fields without retaining a signed URL."""

    def __init__(
        self,
        message: str | None = None,
        *,
        status: int | None = None,
        code: int | None = None,
        endpoint: str | None = None,
        retry_after_seconds: int | None = None,
    ) -> None:
        self.status = status
        self.code = code
        self.endpoint = endpoint
        self.retry_after_seconds = retry_after_seconds
        if status is None and code is None and endpoint is None:
            super().__init__(str(message or "Binance request failed"))
            return
        parts = [f"HTTP {status}" if status is not None else "Binance error"]
        if code is not None:
            parts.append(f"code={code}")
        if endpoint:
            parts.append(f"endpoint={endpoint}")
        if message:
            parts.append(str(message)[:240])
        super().__init__(" ".join(parts))

# ---- simple retries ----
_rate_limit_lock = threading.RLock()
_rate_limit_until = 0.0
_rate_limit_error: BinanceHttpError | None = None


def _retry_after_seconds(response: requests.Response) -> int:
    """Return a bounded exchange cooldown from Retry-After."""
    default = 120 if response.status_code == 418 else 1
    raw = getattr(response, "headers", {}).get("Retry-After")
    try:
        seconds = math.ceil(float(raw)) if raw is not None else default
    except (OverflowError, TypeError, ValueError):
        seconds = default
    return min(3 * 24 * 60 * 60, max(1, seconds))


def _raise_if_rate_limited() -> None:
    global _rate_limit_until, _rate_limit_error
    with _rate_limit_lock:
        if time.monotonic() >= _rate_limit_until:
            _rate_limit_until = 0.0
            _rate_limit_error = None
            return
        error = _rate_limit_error
    if error is not None:
        raise error


def _activate_rate_limit(response: requests.Response, url: str) -> BinanceHttpError:
    """Block local reads until Binance permits the next request."""
    global _rate_limit_until, _rate_limit_error
    retry_after = _retry_after_seconds(response)
    deadline = time.monotonic() + retry_after
    endpoint = urlsplit(url).path or "<unknown>"
    error = BinanceHttpError(
        status=int(response.status_code),
        endpoint=endpoint,
        retry_after_seconds=retry_after,
        message=f"requests blocked locally for {retry_after}s",
    )
    with _rate_limit_lock:
        if _rate_limit_error is not None and _rate_limit_until > deadline:
            return _rate_limit_error
        _rate_limit_until = deadline
        _rate_limit_error = error
    return error


def _do_request(
    method: str,
    url: str,
    *,
    session: requests.Session | None = None,
    **kw,
) -> requests.Response:
    request_timeout = kw.pop("timeout", TIMEOUT)
    if (isinstance(request_timeout, bool)
            or not isinstance(request_timeout, (int, float))
            or not math.isfinite(request_timeout * 3 + 1.5) or request_timeout <= 0):
        raise ValueError("request timeout must be finite and positive")
    if method.upper() not in {"GET", "HEAD"}:
        raise ValueError("market retry transport permits reads only")
    attempts = 3
    delay = 0.5
    # Preserve the existing retry allowance, but never renew the total budget.
    deadline = time.monotonic() + attempts * request_timeout + 1.5
    headers = dict(kw.pop("headers", {}) or {})
    headers["Accept-Encoding"] = "gzip, deflate"
    kw.update(stream=True, allow_redirects=False, headers=headers)
    for i in range(attempts):
        _raise_if_rate_limited()
        r = None
        try:
            budget = min(request_timeout, remaining_seconds(deadline))
            request_session = session if session is not None else SESSION
            r = request_session.request(method, url, timeout=budget, **kw)
            if r.status_code in (418, 429):
                raise _activate_rate_limit(r, url)
            r._content = read_body(r, deadline=deadline)
            r._content_consumed = True
            if 500 <= r.status_code < 600:
                if i == attempts - 1:
                    return r
            else:
                return r
        except (requests.RequestException, UrllibHttpError):
            if i == attempts - 1:
                raise requests.RequestException("market transport failed") from None
        finally:
            if r is not None:
                r.close()
        time.sleep(min(delay, remaining_seconds(deadline)))
        delay *= 2

def _raise_for_binance(resp: requests.Response):
    if resp.status_code == 200:
        return
    try:
        data = resp.json()
    except (requests.JSONDecodeError, TypeError, ValueError):
        data = {}
    if not isinstance(data, dict):
        data = {}
    raw_url = str(getattr(resp, "url", "") or "")
    endpoint = urlsplit(raw_url).path or "<unknown>"
    code = data.get("code")
    if resp.status_code in (401, 403) or data.get("code") in (-2014, -2015, -1022):
        notify_binance_auth_error(
            status=resp.status_code,
            code=code,
            endpoint=endpoint,
            message="exchange rejected request",
        )
    raise BinanceHttpError(
        status=int(resp.status_code),
        code=int(code) if isinstance(code, int) else None,
        endpoint=endpoint,
        message="exchange rejected request",
    )

# ---- time offset (server time skew) ----
_time_offset_ms: Optional[int] = None
_time_offset_ts: float = 0.0
_OFFSET_TTL = 60.0

def _refresh_time_offset(
    *,
    timeout: float | None = None,
    max_offset_ms: int | None = None,
    max_round_trip_ms: int | None = None,
    session: requests.Session | None = None,
):
    global _time_offset_ms, _time_offset_ts
    url = f"{BASE_URL}/api/v3/time"
    started = int(time.time() * 1000)
    request_kw = {"timeout": timeout} if timeout is not None else {}
    r = _do_request("GET", url, session=session, **request_kw)
    finished = int(time.time() * 1000)
    _raise_for_binance(r)
    srv = int(r.json()["serverTime"])
    if (max_offset_ms is None) != (max_round_trip_ms is None):
        raise ValueError("both clock safety limits are required")
    if max_offset_ms is not None and max_round_trip_ms is not None:
        check = assess_exchange_clock(
            server_time_ms=srv,
            request_started_ms=started,
            response_finished_ms=finished,
            max_offset_ms=max_offset_ms,
            max_round_trip_ms=max_round_trip_ms,
        )
        check.require_safe()
        _time_offset_ms = check.offset_ms
    else:
        _time_offset_ms = exchange_time_offset_ms(
            server_time_ms=srv,
            request_started_ms=started,
            response_finished_ms=finished,
        )
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
def _public_get(
    path: str,
    params: Dict | List[Tuple[str, str]] | None = None,
    *,
    timeout: float | None = None,
    session: requests.Session | None = None,
) -> Any:
    url = f"{BASE_URL}{path}"
    request_kw = {"timeout": timeout} if timeout is not None else {}
    if session is not None:
        request_kw["session"] = session
    r = _do_request("GET", url, params=params or {}, **request_kw)
    _raise_for_binance(r)
    return r.json()

def _signed_get(
    path: str,
    params: Dict | None = None,
    *,
    timeout: float | None = None,
) -> Any:
    if not API_KEY or not API_SECRET:
        raise BinanceHttpError("BINANCE_API_KEY/SECRET not set in environment")
    url = f"{BASE_URL}{path}"
    headers = {"X-MBX-APIKEY": API_KEY}
    for attempt in range(2):
        base_params = params.copy() if params else {}
        base_params["timestamp"] = str(_timestamp_ms())
        base_params["recvWindow"] = str(RECV_WINDOW)
        items: List[Tuple[str, str]] = [
            (key, str(value)) for key, value in base_params.items()
        ]
        sig = _sign_tuples(items, API_SECRET)
        items.append(("signature", sig))
        request_kw = {"timeout": timeout} if timeout is not None else {}
        r = _do_request("GET", url, params=items, headers=headers, **request_kw)
        try:
            payload = r.json()
        except (requests.JSONDecodeError, TypeError, ValueError):
            payload = None
        code = payload.get("code") if isinstance(payload, dict) else None
        if code == -1021 and attempt == 0:
            # A received -1021 is a definitive rejection, so one resync and
            # one newly signed retry cannot duplicate an exchange mutation.
            _refresh_time_offset()
            continue
        if code == -1021 and r.status_code == 200:
            raise BinanceHttpError(
                status=200,
                code=-1021,
                endpoint=path,
                message="clock resynchronization did not restore signed reads",
            )
        _raise_for_binance(r)
        return payload if payload is not None else r.json()
    raise BinanceHttpError(
        status=400,
        code=-1021,
        endpoint=path,
        message="clock resynchronization did not restore signed reads",
    )

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

def get_symbol_filters(
    symbol: str,
    *,
    session: requests.Session | None = None,
) -> Dict[str, object]:
    symbol = symbol.upper()
    now = time.time()
    if symbol in _exchange_cache and (now - _exchange_cache_ts.get(symbol, 0)) < _CACHE_TTL:
        return _exchange_cache[symbol]

    data = _public_get(
        "/api/v3/exchangeInfo", {"symbol": symbol}, session=session
    )
    symbols = data.get("symbols") or []
    if not symbols:
        raise BinanceHttpError(f"exchangeInfo: symbol '{symbol}' not found")
    info = symbols[0]

    tick_size_exact = "0"
    step_size_exact = "0"
    min_qty_exact = "0"
    min_notional_exact = "0"

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
    try:
        exact_symbol_filters(res)
    except ValueError as exc:
        raise BinanceHttpError(
            f"exchangeInfo: invalid required filters for '{symbol}': {exc}"
        ) from exc
    _exchange_cache[symbol] = res
    _exchange_cache_ts[symbol] = now
    return res

def get_ticker_prices_decimal(symbols) -> dict[str, Decimal]:
    """Read one bounded public response; retain only requested exact prices."""
    return requested_prices(_public_get("/api/v3/ticker/price"), symbols)


def get_ticker_price(symbol: str) -> float:
    """Return the legacy float view for compatibility callers."""
    return float(get_ticker_price_decimal(symbol))


def get_ticker_price_decimal(
    symbol: str,
    *,
    session: requests.Session | None = None,
) -> Decimal:
    """Parse the venue's exact price string without a float intermediate."""
    request_kw = {"session": session} if session is not None else {}
    data = _public_get(
        "/api/v3/ticker/price", {"symbol": symbol.upper()}, **request_kw
    )
    message = "ticker price must be a finite positive decimal string"
    try:
        raw = data["price"]
        if not isinstance(raw, str):
            raise ValueError(message)
        price = Decimal(raw)
    except (KeyError, TypeError, ValueError, InvalidOperation):
        # Do not include an untrusted response value in diagnostics.
        raise ValueError(message) from None
    if not price.is_finite() or price <= 0:
        raise ValueError(message)
    return price

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
