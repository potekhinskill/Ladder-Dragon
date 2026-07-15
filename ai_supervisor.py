#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
ai_supervisor.py — «Лестница Дракона» (SMART, high-profit grid 2025)

(докстринг без изменений, урезан здесь для краткости)
"""

import os
import sys
import time
import math
import hmac
import hashlib
import signal
import random
import argparse
import subprocess
import json
import re
import sqlite3
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from order_identity import client_order_id
from risk_manager import RiskDecision, RiskLimits, RiskManager, RiskSnapshot, load_daily_trade_metrics, money
from time_safety import assess_exchange_clock

try:
    import requests
except Exception:
    print("Please install requests: pip install requests", flush=True)
    raise

# >>> tools_market integration
try:
    import tools_market as TM  # важное: используем общее подписание и klines с фолбэком
except Exception as e:
    print(f"[FATAL] cannot import tools_market: {e}", flush=True)
    raise
# <<< tools_market integration

# =========================
# Константы и окружение
# =========================

BINANCE_API_BASE = (os.getenv("BINANCE_API_BASE") or os.getenv("BINANCE_BASE_URL") or "https://api.binance.com").rstrip("/")
API_KEY = os.getenv("BINANCE_API_KEY", "")
API_SECRET = os.getenv("BINANCE_API_SECRET", "")
USER_AGENT = os.getenv("USER_AGENT", "LadderDragon/1.8 (ai_supervisor)")

# Режим округления и тёплый старт для очистки
PRICE_ROUND_MODE = os.getenv("PRICE_ROUND_MODE", "nearest").lower()  # floor|ceil|nearest
CLEANUP_WARMUP_SEC = int(os.getenv("CLEANUP_WARMUP_SEC", "0") or 0)

SESSION = requests.Session()
if API_KEY:
    SESSION.headers.update({"X-MBX-APIKEY": API_KEY})
SESSION.headers.update({"User-Agent": USER_AGENT})

LOCK_FILE = "/tmp/ai_supervisor.lock"

LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
_CHILD_PROCS: Dict[str, subprocess.Popen] = {}
LIVE_MODE = False


def env_flag(name: str, default: bool = False) -> bool:
    v = os.getenv(name)
    if v is None:
        return default
    return str(v).strip().lower() in ("1", "true", "t", "yes", "y", "on")

def log(msg: str) -> None:
    print(msg, flush=True)

def dbg(msg: str) -> None:
    if LOG_LEVEL in ("DEBUG", "TRACE"):
        print(msg, flush=True)

# =========================
# Утилиты
# =========================

def clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))

def parse_pct_map(s: str) -> Dict[str, Tuple[float, float, float]]:
    out: Dict[str, Tuple[float, float, float]] = {}
    if not s:
        return out
    for part in s.split(";"):
        part = part.strip()
        if not part or "=" not in part:
            continue
        k, v = part.split("=", 1)
        vs = [x.strip() for x in v.split(",")]
        if len(vs) != 3:
            continue
        try:
            out[k.strip()] = (float(vs[0]), float(vs[1]), float(vs[2]))
        except Exception:
            pass
    return out

def parse_limit_map(s: str) -> Dict[str, float]:
    out: Dict[str, float] = {}
    if not s:
        return out
    for part in s.split(","):
        part = part.strip()
        if not part or ":" not in part:
            continue
        k, v = part.split(":", 1)
        try:
            out[k.strip()] = float(v.strip())
        except Exception:
            pass
    return out


def getenv_float(name: str, default: Optional[float] = None) -> Optional[float]:
    v = os.getenv(name)
    if v is None or v == "":
        return default
    try:
        return float(v)
    except Exception:
        return default


def resolve_vwap_value(symbol: str,
                       base: Optional[float],
                       mapping: Optional[Dict[str, float]],
                       env_name: str,
                       fallback: Optional[float] = None) -> Optional[float]:
    if mapping and symbol in mapping:
        return mapping[symbol]
    if base is not None:
        return base
    return getenv_float(env_name, fallback)


def resolve_vwap_params(symbol: str,
                        dir_mode: str,
                        atr_pct: float,
                        args: argparse.Namespace) -> tuple[Optional[float], Optional[float], Optional[float], Optional[str], Optional[int]]:
    premium_base = resolve_vwap_value(
        symbol,
        getattr(args, "child_buy_vwap_premium", None),
        getattr(args, "child_buy_vwap_premium_map", {}),
        "BUY_VWAP_PREMIUM",
    )
    discount_base = resolve_vwap_value(
        symbol,
        getattr(args, "child_buy_vwap_discount", None),
        getattr(args, "child_buy_vwap_discount_map", {}),
        "BUY_VWAP_DISCOUNT",
    )
    scale_base = resolve_vwap_value(
        symbol,
        getattr(args, "child_buy_vwap_discount_scale", None),
        getattr(args, "child_buy_vwap_discount_scale_map", {}),
        "BUY_VWAP_DISCOUNT_SCALE",
        fallback=1.0,
    )

    if scale_base is None:
        scale_base = 1.0

    premium_final = premium_base
    discount_final = discount_base
    scale_final = scale_base

    if args.child_buy_vwap_auto:
        mode = (dir_mode or "").upper()
        if premium_final is not None:
            mult = 1.0
            if mode == "UP":
                mult *= max(0.05, float(args.child_buy_vwap_premium_up_mult))
            elif mode == "DOWN":
                mult *= max(0.05, float(args.child_buy_vwap_premium_down_mult))
            if atr_pct and args.child_buy_vwap_premium_atr_coef:
                mult *= max(0.1, 1.0 - atr_pct * float(args.child_buy_vwap_premium_atr_coef))
            premium_final *= mult

        if scale_final is not None and atr_pct and args.child_buy_vwap_discount_scale_atr_coef:
            scale_final *= 1.0 + max(0.0, atr_pct) * float(args.child_buy_vwap_discount_scale_atr_coef)

    floor = max(0.0, float(args.child_buy_vwap_premium_floor))
    ceil = max(floor, float(args.child_buy_vwap_premium_ceil))
    if premium_final is not None:
        premium_final = max(floor, min(ceil, premium_final))

    scale_min = max(0.1, float(args.child_buy_vwap_discount_scale_min))
    scale_max = max(scale_min, float(args.child_buy_vwap_discount_scale_max))
    if scale_final is not None:
        scale_final = max(scale_min, min(scale_max, scale_final))
        if abs(scale_final - 1.0) < 1e-4:
            scale_final = None

    if discount_final is not None and discount_final <= 0:
        discount_final = None

    interval_final = getattr(args, "child_buy_vwap_interval", None) or os.getenv("BUY_VWAP_INTERVAL")
    if interval_final:
        interval_final = interval_final.strip() or None

    window_final: Optional[int]
    if getattr(args, "child_buy_vwap_window", None) is not None:
        window_final = int(args.child_buy_vwap_window)
    else:
        env_win = os.getenv("BUY_VWAP_WINDOW")
        if env_win:
            try:
                window_final = int(env_win)
            except Exception:
                window_final = None
        else:
            window_final = None

    return premium_final, discount_final, scale_final, interval_final, window_final


def _parse_vwap_line(key: str, value: str) -> Dict[str, float]:
    mapping: Dict[str, float] = {}
    if not value:
        return mapping
    for part in value.split(","):
        part = part.strip()
        if not part or ":" not in part:
            continue
        sym, val = part.split(":", 1)
        sym = sym.strip().upper()
        try:
            mapping[sym] = float(val)
        except Exception:
            continue
    return mapping


def parse_vwap_output(text: str) -> tuple[Dict[str, float], Dict[str, float], Dict[str, float]]:
    premium_map: Dict[str, float] = {}
    discount_map: Dict[str, float] = {}
    scale_map: Dict[str, float] = {}
    if not text:
        return premium_map, discount_map, scale_map
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key_up = key.strip().upper()
        value = value.strip()
        mapping = _parse_vwap_line(key, value)
        if key_up.endswith("DISCOUNT_SCALE_MAP"):
            if mapping:
                scale_map.update(mapping)
        elif key_up.endswith("PREMIUM_MAP"):
            if mapping:
                premium_map.update(mapping)
        elif key_up.endswith("DISCOUNT_MAP"):
            if mapping:
                discount_map.update(mapping)
    return premium_map, discount_map, scale_map

def symbol_assets(symbol: str) -> Tuple[str, str]:
    if symbol.endswith("USDT"):
        return symbol[:-4], "USDT"
    for q in ("BUSD", "USDC", "BTC", "ETH"):
        if symbol.endswith(q):
            return symbol[:-len(q)], q
    return symbol[:-3], symbol[-3:]

# =========================
# Устойчивый Backoff с джиттером
# =========================

def _request_with_backoff(method: str, url: str, *, params=None, data=None, headers=None,
                          timeout: float = 15.0, max_tries: int = 8) -> Any:
    tries = 0
    backoff = 0.75
    while True:
        tries += 1
        try:
            r = SESSION.request(method, url, params=params, data=data, headers=headers, timeout=timeout)

            body = None; code = None; msg = None
            try:
                body = r.json()
                if isinstance(body, dict):
                    code = body.get("code"); msg = body.get("msg")
            except Exception:
                body = None

            if 200 <= r.status_code < 300:
                return body if body is not None else r.text

            if r.status_code in (418, 429) or (500 <= r.status_code < 600) or code in (-1003, -1015, 1003):
                retry_after = r.headers.get("Retry-After")
                if retry_after:
                    try:
                        backoff = max(backoff, float(retry_after))
                    except Exception:
                        pass
                else:
                    backoff = min(backoff * 1.7, 20.0)
                sleep_s = backoff + random.random() * 0.5
                log(f"[BACKOFF] {r.status_code} / code={code} -> sleep {sleep_s:.2f}s URL={url}")
                time.sleep(sleep_s)
                if tries < max_tries:
                    continue
                raise requests.HTTPError(f"{r.status_code} (throttle) body={body}", response=r)

            if 400 <= r.status_code < 500:
                if code is not None or msg is not None:
                    log(f"[HTTP{r.status_code}] code={code} msg={msg}")
                else:
                    log(f"[HTTP{r.status_code}] {r.text[:300]}")
                raise requests.HTTPError(f"{r.status_code} client error body={body}", response=r)

            r.raise_for_status()

        except requests.HTTPError as e:
            resp = getattr(e, "response", None)
            sc = getattr(resp, "status_code", None)
            if sc is not None and (sc < 500) and sc not in (418, 429):
                raise
            if tries >= max_tries:
                raise
            backoff = min(backoff * 1.7, 20.0)
            sleep_s = backoff + random.random() * 0.5
            log(f"[BACKOFF] http error {e} -> sleep {sleep_s:.2f}s URL={url}")
            time.sleep(sleep_s)

        except requests.RequestException as e:
            if tries >= max_tries:
                raise
            backoff = min(backoff * 1.7, 20.0)
            sleep_s = backoff + random.random() * 0.5
            log(f"[BACKOFF] network error {e!r} -> sleep {sleep_s:.2f}s URL={url}")
            time.sleep(sleep_s)

# ================
# Подпись запросов
# ================

def _ts() -> int:
    return int(time.time() * 1000)

def _sign(qs: str) -> str:
    return hmac.new(API_SECRET.encode(), qs.encode(), hashlib.sha256).hexdigest()

# ---- tools_market-based HTTP helpers ----

def _public_get(path: str, params: Dict[str, Any] = None, timeout: int = 15) -> Any:
    return TM._public_get(path, params or {})

def _canonical_signed_request(method: str, path: str, params: Dict[str, Any] = None, timeout: int = 15) -> Any:
    if params is None:
        params = {}
    base_params = params.copy()
    base_params["timestamp"] = str(TM._timestamp_ms())
    base_params["recvWindow"] = str(getattr(TM, "RECV_WINDOW", 5000))

    items: List[Tuple[str, str]] = [(k, str(v)) for k, v in base_params.items()]
    sig = TM._sign_tuples(items, TM.API_SECRET)
    items.append(("signature", sig))

    headers = {"X-MBX-APIKEY": TM.API_KEY} if TM.API_KEY else {}
    url = f"{TM.BASE_URL}{path}"
    r = TM._do_request(method.upper(), url, params=items, headers=headers)
    TM._raise_for_binance(r)
    try:
        return r.json()
    except Exception:
        return r.text

# ===========================
# Доступ к аккаунту/рынкам
# ===========================

def get_server_time_offset_ms() -> int:
    try:
        t0 = int(time.time() * 1000)
        j = _public_get("/api/v3/time")
        srv = int(j.get("serverTime", t0))
        t1 = int(time.time() * 1000)
        rtt = (t1 - t0) // 2
        offset = srv - (t0 + rtt)
        log(f"[INFO] Server time offset: {offset} ms")
        return offset
    except Exception as e:
        log(f"[WARN] server time failed: {e}")
        return 0

def get_last_price(symbol: str) -> float:
    return float(TM.get_ticker_price(symbol))

def get_24h_volume_quote(symbol: str) -> float:
    j = _public_get("/api/v3/ticker/24hr", params={"symbol": symbol})
    return float(j.get("quoteVolume", 0.0))

def get_exchange_filters(symbol: str) -> Dict[str, float]:
    f = TM.get_symbol_filters(symbol)
    tick = float(f.get("tickSize", 0.0))
    step = float(f.get("stepSize", 0.0))
    minQty = float(f.get("minQty", 0.0))
    minNotional = float(f.get("minNotional", 0.0))
    log(f"[FILTERS] {symbol} tickSize={tick:.8f} stepSize={step:.8f} "
        f"minQty={minQty:.6f} minNotional={minNotional:.2f}")
    return {"tickSize": tick, "stepSize": step, "minQty": minQty, "minNotional": minNotional}

# --- кэш фильтров ---
_FILTERS_CACHE: Dict[str, Dict[str, float]] = {}

def get_exchange_filters_cached(symbol: str) -> Dict[str, float]:
    f = _FILTERS_CACHE.get(symbol)
    if f is None:
        f = get_exchange_filters(symbol)
        _FILTERS_CACHE[symbol] = f
    return f

def invalidate_exchange_filters_cache(symbol: Optional[str] = None) -> None:
    if symbol is None:
        _FILTERS_CACHE.clear()
    else:
        _FILTERS_CACHE.pop(symbol, None)

def get_balances() -> Dict[str, float]:
    j = TM._signed_get("/api/v3/account")
    out: Dict[str, float] = {}
    for b in j.get("balances", []):
        free = float(b.get("free", 0.0))
        locked = float(b.get("locked", 0.0))
        if free + locked > 0:
            out[b["asset"]] = free
    return out

def get_balances_full() -> Dict[str, Dict[str, float]]:
    j = TM._signed_get("/api/v3/account")
    out: Dict[str, Dict[str, float]] = {}
    for b in j.get("balances", []):
        free = float(b.get("free", 0.0))
        locked = float(b.get("locked", 0.0))
        if free + locked > 0:
            out[b["asset"]] = {"free": free, "locked": locked}
    return out

_AVG_CACHE: Dict[str, Dict[str, float]] = {}

def avg_entry_price(symbol: str, *, cache_ttl: int = 45, lookback: int = 1000) -> Optional[float]:
    now_ts = time.time()
    ent = _AVG_CACHE.get(symbol)
    if ent and (now_ts - ent.get("ts", 0.0)) < cache_ttl and ent.get("pos", 0.0) > 0:
        return float(ent.get("avg", 0.0))

    base, quote = symbol_assets(symbol)
    bals = get_balances_full()
    bal = bals.get(base, {"free": 0.0, "locked": 0.0})
    pos = float(bal.get("free", 0.0)) + float(bal.get("locked", 0.0))
    if pos <= 0:
        _AVG_CACHE[symbol] = {"ts": now_ts, "avg": 0.0, "pos": 0.0}
        return None

    try:
        trades = TM._signed_get("/api/v3/myTrades", {"symbol": symbol, "limit": lookback}) or []
    except Exception as e:
        dbg(f"[AVG] {symbol} myTrades error: {e}")
        return float(ent.get("avg", 0.0)) if ent and ent.get("pos", 0.0) > 0 else None

    if not isinstance(trades, list) or not trades:
        return None

    try:
        trades.sort(key=lambda t: int(t.get("time", 0)))
    except Exception:
        pass

    qty = 0.0
    cost = 0.0
    for t in trades:
        try:
            is_buy = bool(t.get("isBuyer"))
            q = float(t.get("qty") or 0.0)
            p = float(t.get("price") or 0.0)
            commission = float(t.get("commission") or 0.0)
            commission_asset = str(t.get("commissionAsset", "")).upper()
            fee_quote = 0.0
            if commission_asset == quote.upper():
                fee_quote = commission
            elif commission_asset == base.upper():
                fee_quote = commission * p
            if is_buy:
                qty += q
                cost += p * q + fee_quote
            else:
                sell = min(q, qty)
                if sell > 0 and qty > 0:
                    avg = cost / qty if qty > 0 else 0.0
                    cost -= avg * sell
                    qty -= sell
        except Exception:
            continue

    if qty <= 0:
        _AVG_CACHE[symbol] = {"ts": now_ts, "avg": 0.0, "pos": 0.0}
        return None

    avg_px = cost / qty
    _AVG_CACHE[symbol] = {"ts": now_ts, "avg": float(avg_px), "pos": float(qty)}
    return float(avg_px)

def list_open_orders(symbol: str) -> List[Dict[str, Any]]:
    try:
        return TM._signed_get("/api/v3/openOrders", {"symbol": symbol}) or []
    except Exception:
        return []

def cancel_order(symbol: str, order_id: int) -> bool:
    if not LIVE_MODE:
        log(f"[DRY] skip cancel {symbol} orderId={order_id}")
        return False
    try:
        _canonical_signed_request("DELETE", "/api/v3/order", {"symbol": symbol, "orderId": order_id})
        return True
    except Exception as e:
        log(f"[CANCEL] {symbol} orderId={order_id} -> {e}")
        return False


# --- ошибки фильтров (формат цены/количества) ---
def _is_filter_error(e: Exception) -> bool:
    try:
        resp = getattr(e, "response", None)
        if resp is None:
            return False
        j = resp.json()
        code = j.get("code")
        # -1013 BAD_ARGUMENTS / INVALID_PRICE_QTY, -1111 precision, -1102, -1106 — форматные
        return code in (-1013, -1111, -1102, -1106)
    except Exception:
        return False

# ======= NEW: точное форматирование qty/price под шаг =======

def _round_price(price: float, tick: float, mode: str) -> float:
    if tick <= 0:
        return float(f"{price:.8f}")
    x = price / tick
    if mode == "ceil":
        q = math.ceil(x) * tick
    elif mode == "nearest":
        q = math.floor(x + 0.5) * tick
    else:
        q = math.floor(x) * tick
    return float(f"{q:.8f}")

def _round_to_tick(price: float, tick: float) -> float:
    return _round_price(price, tick, PRICE_ROUND_MODE)

def _round_qty(qty: float, step: float) -> float:
    if step <= 0:
        return float(f"{qty:.12f}")
    x = math.floor(qty / step) * step
    return float(f"{x:.12f}")

def _decimals_from_step(x: float) -> int:
    s = f"{x:.12f}".rstrip('0')
    return len(s.split('.', 1)[1]) if '.' in s else 0

def _fmt_price_side_aware(price: float, tick: float, side: str) -> str:
    if tick is None or tick <= 0:
        tick = 1e-8
    mode = "floor" if side.upper() == "BUY" else "ceil"
    dec = _decimals_from_step(tick)
    p = _round_price(price, tick, mode)
    return f"{p:.{dec}f}"

def _fmt_qty(qty: float, step: float) -> str:
    if step is None or step <= 0:
        step = 1e-12
    dec = _decimals_from_step(step)
    q = _round_qty(qty, step)
    return f"{q:.{dec}f}"

def _fmt_price(price: float, tick: float) -> str:
    if tick is None or tick <= 0:
        tick = 1e-8
    dec = _decimals_from_step(tick)
    p = _round_to_tick(price, tick)
    return f"{p:.{dec}f}"

# ============================================================

def place_limit_order(symbol: str, side: str, quantity: float, price: float,
                      filters: Optional[Dict[str, float]] = None) -> Optional[Dict[str, Any]]:
    """
    Лимитки через централизованное округление/валидацию tools_market.round_qty_price().
    При фильтр-ошибке (-1013/-1111/-1102/-1106) один раз инвалидируем кэш фильтров и повторяем.
    """
    if not LIVE_MODE:
        log(f"[DRY] skip LIMIT {symbol} {side.upper()} {quantity:.8f} @ {price:.8f}")
        return None
    try:
        qty_s, price_s = TM.round_qty_price(
            symbol=symbol,
            qty=float(quantity),
            price=float(price),
            side=side.upper(),
        )

        params = {
            "symbol": symbol,
            "side": side.upper(),
            "type": "LIMIT",
            "timeInForce": "GTC",
            "quantity": qty_s,
            "price": price_s,
            "newOrderRespType": "ACK",
            "newClientOrderId": client_order_id(symbol, side, "limit", price_s, qty_s),
        }
        j = _canonical_signed_request("POST", "/api/v3/order", params)
        oid = j.get("orderId") if isinstance(j, dict) else None
        log(f"[PLACE] {symbol} {side.upper()} {qty_s} @ {price_s} (order {oid})")
        return j if isinstance(j, dict) else None

    except Exception as e:
        log(f"[PLACE-ERR] {symbol} {side.upper()} {quantity:.6f} @ {price:.4f} -> {e}")
        # попытка 1: инвалидация фильтров и один повтор
        if _is_filter_error(e):
            invalidate_exchange_filters_cache(symbol)
            try:
                # переокруглим через TM ещё раз — на случай изменившихся шагов
                qty_s, price_s = TM.round_qty_price(
                    symbol=symbol,
                    qty=float(quantity),
                    price=float(price),
                    side=side.upper(),
                )
                params = {
                    "symbol": symbol,
                    "side": side.upper(),
                    "type": "LIMIT",
                    "timeInForce": "GTC",
                    "quantity": qty_s,
                    "price": price_s,
                    "newOrderRespType": "ACK",
                    "newClientOrderId": client_order_id(symbol, side, "limit", price_s, qty_s),
                }
                j2 = _canonical_signed_request("POST", "/api/v3/order", params)
                oid2 = j2.get("orderId") if isinstance(j2, dict) else None
                log(f"[PLACE-RETRY] {symbol} {side.upper()} {qty_s} @ {price_s} (order {oid2})")
                return j2 if isinstance(j2, dict) else None
            except Exception as e2:
                log(f"[PLACE-RETRY-ERR] {symbol} -> {e2}")
        return None

def place_market_order(symbol: str, side: str, quantity: float,
                       ref_price: Optional[float] = None,
                       filters: Optional[Dict[str, float]] = None) -> Optional[Dict[str, Any]]:
    """
    Маркет-ордера унифицированы: round_qty_price() даёт корректный qty_s.
    При фильтр-ошибке инвалидируем кэш фильтров и повторяем один раз.
    """
    if not LIVE_MODE:
        log(f"[DRY] skip MARKET {symbol} {side.upper()} {quantity:.8f}")
        return None
    try:
        if ref_price is None:
            ref_price = get_last_price(symbol)

        qty_s, _ = TM.round_qty_price(
            symbol=symbol,
            qty=float(quantity),
            price=float(ref_price),  # нужна для minNotional
            side=side.upper(),
        )

        params = {
            "symbol": symbol,
            "side": side.upper(),
            "type": "MARKET",
            "quantity": qty_s,
            "newOrderRespType": "ACK",
            "newClientOrderId": client_order_id(symbol, side, "market", ref_price, qty_s, bucket_seconds=30),
        }
        j = _canonical_signed_request("POST", "/api/v3/order", params)
        oid = j.get("orderId") if isinstance(j, dict) else None
        log(f"[PLACE] {symbol} {side.upper()} {qty_s} @ MARKET (order {oid})")
        return j if isinstance(j, dict) else None

    except Exception as e:
        log(f"[PLACE-ERR] {symbol} {side.upper()} MARKET {quantity:.6f} -> {e}")
        if _is_filter_error(e):
            invalidate_exchange_filters_cache(symbol)
            try:
                if ref_price is None:
                    ref_price = get_last_price(symbol)
                qty_s, _ = TM.round_qty_price(
                    symbol=symbol,
                    qty=float(quantity),
                    price=float(ref_price),
                    side=side.upper(),
                )
                params = {
                    "symbol": symbol,
                    "side": side.upper(),
                    "type": "MARKET",
                    "quantity": qty_s,
                    "newOrderRespType": "ACK",
                    "newClientOrderId": client_order_id(symbol, side, "market", ref_price, qty_s, bucket_seconds=30),
                }
                j2 = _canonical_signed_request("POST", "/api/v3/order", params)
                oid2 = j2.get("orderId") if isinstance(j2, dict) else None
                log(f"[PLACE-RETRY] {symbol} {side.upper()} {qty_s} @ MARKET (order {oid2})")
                return j2 if isinstance(j2, dict) else None
            except Exception as e2:
                log(f"[PLACE-RETRY-ERR] {symbol} -> {e2}")
        return None

# ============================
# «Умная» очистка ордеров
# ============================

def startup_cleanup_orders(symbol: str,
                           now_price: float,
                           ladder_prices: List[float],
                           tick_size: float,
                           grace_sec: Optional[int]) -> Dict[str, int]:
    try:
        orders = list_open_orders(symbol)
    except Exception as e:
        log(f"[START-CLEANUP] {symbol} list_open_orders failed: {e}")
        return {"reviewed": 0, "canceled": 0}
    if not orders:
        return {"reviewed": 0, "canceled": 0}

    allowed = {_round_to_tick(p, tick_size) for p in ladder_prices}
    now_ms = int(time.time() * 1000)

    reviewed = canceled = 0
    for o in orders:
        try:
            reviewed += 1
            typ = (o.get("type") or "").upper()
            if typ not in ("LIMIT", "LIMIT_MAKER", "STOP_LOSS_LIMIT", "TAKE_PROFIT_LIMIT"):
                continue

            price = float(o.get("price") or 0.0)
            pr = _round_to_tick(price, tick_size)
            upd = int(o.get("updateTime") or o.get("time") or now_ms)
            age = max(0, (now_ms - upd)//1000)

            off = pr not in allowed
            old = (grace_sec is not None and age > int(grace_sec))
            offladder_grace = int(os.getenv("START_CLEANUP_OFFLADDER_GRACE_SEC", "0") or 0)

            do_cancel = False
            reason = None
            if old:
                do_cancel = True
                reason = f"age>{grace_sec}s"
            elif off:
                if offladder_grace == 0 or age > offladder_grace:
                    do_cancel = True
                    reason = "off-ladder"

            if do_cancel:
                if cancel_order(symbol, int(o.get("orderId"))):
                    canceled += 1
                    log(f"[START-CLEANUP] {symbol} canceled id={o.get('orderId')} price={pr} reason={reason}")
        except Exception as e:
            log(f"[START-CLEANUP] {symbol} skip: {e}")

    log(f"[START-CLEANUP-SUM] {symbol} reviewed={reviewed} canceled={canceled}")
    return {"reviewed": reviewed, "canceled": canceled}

def smart_cleanup_orders(symbol: str,
                         now_price: float,
                         ladder_prices: List[float],
                         tick_size: float,
                         near_ttl_sec: Optional[int],
                         far_ttl_sec: Optional[int],
                         cancel_offladder: bool = True) -> Dict[str, int]:
    try:
        orders = list_open_orders(symbol)
    except Exception as e:
        log(f"[CLEANUP] {symbol} list_open_orders failed: {e}")
        return {"reviewed": 0, "canceled": 0}
    if not orders:
        return {"reviewed": 0, "canceled": 0}

    now_ms = int(time.time() * 1000)
    near_lo = now_price * 0.90
    near_hi = now_price * 1.10
    allowed = {_round_to_tick(p, tick_size) for p in ladder_prices} if cancel_offladder else set()
    offladder_grace = int(os.getenv("CLEANUP_OFFLADDER_GRACE_SEC", "180") or 0)

    reviewed = canceled = 0
    for o in orders:
        try:
            reviewed += 1
            price = float(o.get("price") or 0.0)
            pr = _round_to_tick(price, tick_size)
            upd = int(o.get("updateTime") or o.get("time") or now_ms)
            age = max(0, (now_ms - upd)//1000)

            in_near = (near_lo <= price <= near_hi)
            ttl = (near_ttl_sec if in_near else far_ttl_sec)
            reason = None

            if ttl and age > ttl:
                reason = f"age>{ttl}s"
            elif cancel_offladder and pr not in allowed and age > offladder_grace:
                reason = "off-ladder"

            if reason:
                if cancel_order(symbol, int(o.get("orderId"))):
                    canceled += 1
                    log(f"[CLEANUP] {symbol} canceled {o.get('side')} {o.get('type')} id={o.get('orderId')} price={pr} age={age}s reason={reason}")
        except Exception as e:
            log(f"[CLEANUP] {symbol} skip: {e}")

    log(f"[CLEANUP-SUM] {symbol} reviewed={reviewed} canceled={canceled}")
    return {"reviewed": reviewed, "canceled": canceled}

# ===========================
# Планировщик «лестницы»
# ===========================

def build_ladder_pct(now_price: float,
                     low_pct: float,
                     down_pct: float,
                     up_pct: float,
                     density: int) -> List[float]:
    def pct_levels(p0, lo_pct, hi_pct, n):
        if n <= 0:
            return []
        lo = 1.0 + lo_pct/100.0
        hi = 1.0 + hi_pct/100.0
        if n == 1:
            ratios = [lo]
        else:
            step = (hi/lo) ** (1.0/(n-1))
            ratios = [lo * (step**i) for i in range(n)]
        return [ round(p0 * r, 8) for r in ratios ]

    buys  = pct_levels(now_price, low_pct, down_pct, density)
    sells = pct_levels(now_price, +abs(low_pct), up_pct, density)
    return buys + sells

def split_ladder(now_price: float, ladder: List[float]) -> Tuple[List[float], List[float]]:
    n = len(ladder)//2
    return ladder[:n], ladder[n:]

# ===========================
# Smart Rolling (краткий)
# ===========================

def smart_rolling(symbol: str,
                  now_price: float,
                  ladder: List[float],
                  args: argparse.Namespace) -> Dict[str, Any]:
    kept = 0
    try:
        open_orders = list_open_orders(symbol)
        kept = len(open_orders)
    except Exception:
        kept = 0
    return {"kept": kept, "cancel": {"ttl": 0, "atr": 0}}

# ===========================
# ATR и авто-адаптер порогов
# ===========================

def _klines(symbol: str, interval: str, limit: int = 30):
    return TM.get_klines(symbol, interval, limit=limit)

def _atr_pct(symbol: str, interval: str = '5m', length: int = 20) -> Tuple[float, float]:
    try:
        kl = _klines(symbol, interval, limit=length+2)
        if not kl or len(kl) < length+1:
            return 0.0, 0.0
        prev_close = float(kl[0][4])
        trs = []
        for row in kl[1:]:
            high = float(row[2]); low = float(row[3]); close = float(row[4])
            tr = max(high-low, abs(high - prev_close), abs(low - prev_close))
            trs.append(tr)
            prev_close = close
        atr = sum(trs[-length:]) / float(length)
        last_close = float(kl[-1][4])
        return atr, (atr / last_close if last_close > 0 else 0.0)
    except Exception as e:
        log(f"[ATR] failed: {e}")
        return 0.0, 0.0

# ===========================
# Детектор направления рынка (UP/DOWN/FLAT)
# ===========================

_DIR_STATE: Dict[str, Dict[str, Any]] = {}

def _ema_series(vals: List[float], length: int) -> List[float]:
    if length <= 1 or len(vals) == 0:
        return vals[:]
    k = 2.0 / (length + 1.0)
    out = []
    ema = sum(vals[:length]) / float(length) if len(vals) >= length else vals[0]
    out.extend([ema])
    for v in vals[1:]:
        ema = v * k + ema * (1.0 - k)
        out.append(ema)
    return out

def _adx_from_klines(kl, length: int = 14) -> float:
    if not kl or len(kl) < length + 2:
        return 0.0
    H = [float(r[2]) for r in kl]
    L = [float(r[3]) for r in kl]
    C = [float(r[4]) for r in kl]

    TR, PDM, NDM = [], [], []
    for i in range(1, len(kl)):
        up = H[i] - H[i-1]
        dn = L[i-1] - L[i]
        tr = max(H[i] - L[i], abs(H[i] - C[i-1]), abs(L[i] - C[i-1]))
        TR.append(tr)
        PDM.append(up if (up > dn and up > 0) else 0.0)
        NDM.append(dn if (dn > up and dn > 0) else 0.0)

    sTR  = sum(TR[:length])
    sPDM = sum(PDM[:length])
    sNDM = sum(NDM[:length])

    DIs = []
    eps = 1e-12
    for i in range(length, len(TR)):
        sTR  = sTR  - (sTR/length)  + TR[i]
        sPDM = sPDM - (sPDM/length) + PDM[i]
        sNDM = sNDM - (sNDM/length) + NDM[i]
        pDI = 100.0 * (sPDM / (sTR + eps))
        nDI = 100.0 * (sNDM / (sTR + eps))
        dx  = 100.0 * abs(pDI - nDI) / (pDI + nDI + eps)
        DIs.append(dx)

    if not DIs:
        return 0.0

    adx = sum(DIs[:length]) / float(length) if len(DIs) >= length else DIs[-1]
    for i in range(length, len(DIs)):
        adx = (adx * (length - 1) + DIs[i]) / float(length)
    return float(adx)

def _infer_market_mode(symbol: str, *, interval: str = "30m", ema_fast_len: int = 20,
                       ema_slow_len: int = 50, eps: float = 0.0005, slope_min: float = 0.0002,
                       adx_min: float = 16.0, hyst_bars: int = 5, confirm_bars: int = 3,
                       do_log: bool = True) -> Tuple[str, Dict[str, float]]:
    need = max(ema_slow_len + 5, 100)
    kl = _klines(symbol, interval, limit=need)
    if not kl or len(kl) < ema_slow_len + 2:
        return "FLAT", {"ema_fast": 0, "ema_slow": 0, "slope": 0, "adx": 0, "candidate": "FLAT"}

    closes = [float(r[4]) for r in kl]
    ema_fast = _ema_series(closes, ema_fast_len)
    ema_slow = _ema_series(closes, ema_slow_len)
    ef = float(ema_fast[-1]); es = float(ema_slow[-1])
    last_px = float(closes[-1])

    step_back = min(confirm_bars, len(ema_fast) - 1)
    slope = (ema_fast[-1] - ema_fast[-1 - step_back]) / max(step_back, 1) / max(last_px, 1e-12)
    adx = _adx_from_klines(kl, length=14)

    up_cond   = (ef > es * (1.0 + eps)) and (slope >=  slope_min) and (adx >= adx_min)
    down_cond = (ef < es * (1.0 - eps)) and (slope <= -slope_min) and (adx >= adx_min)
    cand = "UP" if up_cond else ("DOWN" if down_cond else "FLAT")

    st = _DIR_STATE.get(symbol, {"mode": "FLAT", "streak": 0, "last_cand": cand})
    mode = st["mode"]; streak = st["streak"]; last_cand = st["last_cand"]

    if cand == mode:
        streak = 0
    else:
        if cand == last_cand:
            streak += 1
        else:
            streak = 1
        if streak >= confirm_bars:
            mode = cand
            streak = 0
    _DIR_STATE[symbol] = {"mode": mode, "streak": streak, "last_cand": cand}

    if do_log:
        log(f"[DIR] {symbol} mode={mode} cand={cand} ema{ema_fast_len}={ef:.4f} ema{ema_slow_len}={es:.4f} slope={slope:.5f} adx={adx:.2f}")
    return mode, {"ema_fast": ef, "ema_slow": es, "slope": slope, "adx": adx, "candidate": cand}

# ===========================
# Позиционный страж
# ===========================

def _in_flatten_window(now_local: datetime, hhmm: str, t_minus_sec: int) -> bool:
    try:
        hh, mm = [int(x) for x in hhmm.split(":")]
    except Exception:
        return False
    target = now_local.replace(hour=hh, minute=mm, second=0, microsecond=0)
    if now_local > target:
        target = target + timedelta(days=1)
    return (target - now_local).total_seconds() <= max(0, int(t_minus_sec))

def _net_position_base(symbol: str) -> float:
    base, _ = symbol_assets(symbol)
    bals = get_balances_full()
    b = bals.get(base, {"free": 0.0, "locked": 0.0})
    return float(b.get("free", 0.0)) + float(b.get("locked", 0.0))

def _pos_limits(symbol: str, args: argparse.Namespace) -> Tuple[Optional[float], Optional[float]]:
    mb = args.pos_max_base_map.get(symbol) if args.pos_max_base_map else None
    mu = args.pos_max_usdt_map.get(symbol) if args.pos_max_usdt_map else None
    return mb, mu

def _prune_to_sells_only(now_price: float, ladder: List[float]) -> List[float]:
    _, sells = split_ladder(now_price, ladder)
    return sells

def _ensure_min_notional_qty(symbol: str, qty: float, price: float, step: float, min_qty: float, min_notional: float) -> Optional[float]:
    qty = _round_qty(qty, step)
    if qty <= 0:
        return None
    if qty < min_qty:
        qty = _round_qty(min_qty, step)
    if qty * price < min_notional:
        need = (min_notional / price) * 1.0001
        qty = _round_qty(max(qty, need), step)
        if qty * price < min_notional:
            return None
    return qty if qty > 0 else None

def position_guard_and_maybe_flatten(symbol: str, now_price: float, atr_abs: float,
                                     args: argparse.Namespace, filters: Dict[str, float]) -> str:
    if not args.pos_guard_enable and not args.flatten_enable:
        return "normal"

    max_base, max_usdt = _pos_limits(symbol, args)
    net_base = _net_position_base(symbol)
    net_usdt = net_base * now_price

    hard = False; warn = False
    warn_thr_base = warn_thr_usdt = None

    if max_base is not None:
        hard = hard or (abs(net_base) > max_base)
        warn_thr_base = float(args.pos_warn_pct) * max_base
        warn = warn or (abs(net_base) > warn_thr_base)
    if max_usdt is not None:
        hard = hard or (abs(net_usdt) > max_usdt)
        warn_thr_usdt = float(args.pos_warn_pct) * max_usdt
        warn = warn or (abs(net_usdt) > warn_thr_usdt)

    now_local = datetime.now()
    in_flat = args.flatten_enable and _in_flatten_window(now_local, args.flatten_at, args.flatten_t_minus_sec)

    if (in_flat and not hard
            and bool(getattr(args, "flatten_avoid_loss", 0))
            and not bool(getattr(args, "flatten_force", 0))):
        cache_ttl = int(getattr(args, "flatten_avg_cache_ttl", 45))
        lookback = int(getattr(args, "flatten_avg_lookback", 1000))
        edge_pct = max(0.0, float(getattr(args, "flatten_min_edge_pct", 0.0)))
        avg_px = avg_entry_price(symbol, cache_ttl=cache_ttl, lookback=lookback)
        if avg_px is not None:
            guard_price = avg_px * (1.0 + edge_pct)
            if now_price < guard_price:
                log(
                    f"[FLAT-GUARD] {symbol} skip flatten: avg≈{avg_px:.6f} guard≈{guard_price:.6f} now≈{now_price:.6f}"
                )
                in_flat = False

    if hard or in_flat:
        try:
            base, _ = symbol_assets(symbol)
            step = filters["stepSize"]; min_qty = filters["minQty"]; min_notional = filters["minNotional"]; tick = filters["tickSize"]

            target_base = 0.0 if (in_flat or args.pos_action_on_hard in ("flatten", "reduce_then_flatten")) \
                          else (warn_thr_base or 0.0) * (1 if net_base >= 0 else -1)
            need_total = max(0.0, abs(net_base - target_base))

            bals_full = get_balances_full()
            free_base = float(bals_full.get(base, {}).get("free", 0.0))
            sellable = max(0.0, free_base)

            if net_base <= 0:
                log(f"[POS] {symbol} net<=0 ({net_base:.6f}) -> nothing to flatten via SELL on spot")
                return "reduce_only" if warn else "normal"

            if sellable <= 0.0:
                log(f"[POS] {symbol} nothing free to sell (free={free_base:.6f}, locked may exist) -> reduce_only")
                return "reduce_only"

            left = min(need_total, sellable)
            if left <= 0.0:
                return "reduce_only" if warn else "normal"

            slice_cnt = max(1, int(args.flatten_slices))
            slice_pct = clamp(float(args.flatten_slice_pct), 0.05, 1.0)
            per_slice = max(left * slice_pct, left / slice_cnt)

            offset = clamp(float(args.flatten_limit_offset_atr), 0.0, 3.0)
            price = float(_fmt_price_side_aware(now_price + offset * atr_abs, tick, "SELL"))

            tries = 0
            while left > 0 and tries < slice_cnt:
                qty = min(left, per_slice)
                qty = _ensure_min_notional_qty(symbol, qty, price, step, min_qty, min_notional)
                if qty is None or qty <= 0:
                    break
                ok = place_limit_order(symbol, "SELL", qty, price, filters=filters)
                if not ok and args.flatten_market_failover:
                    qty_m = _ensure_min_notional_qty(symbol, qty, now_price, step, min_qty, min_notional)
                    if qty_m:
                        place_market_order(symbol, "SELL", qty_m, ref_price=now_price, filters=filters)
                left -= float(qty or 0)
                tries += 1

            return "flattening"
        except Exception as e:
            log(f"[FLAT-ERR] {symbol} -> {e}")
            return "reduce_only" if warn else "normal"

    if warn:
        log(f"[POS] {symbol} net≈{net_base:.6f} base / {net_usdt:.2f} USDT -> reduce-only (warn {args.pos_warn_pct*100:.1f}%)")
        return "reduce_only"

    return "normal"

# ===========================
# Запуск дочернего runner'а
# ===========================

def run_child(symbol: str, ladder: List[float], args: argparse.Namespace,
              extra_env: Optional[Dict[str, str]] = None,
              tp1: Optional[float] = None, tp2: Optional[float] = None) -> None:
    _child = _CHILD_PROCS.get(symbol)
    if _child is not None:
        if _child.poll() is None:
            return
        else:
            try:
                del _CHILD_PROCS[symbol]
            except KeyError:
                pass

    cli = [
        args.base_script,
        "--symbol", symbol,
        "--ladder-prices", ",".join(f"{p:.8f}" for p in ladder),
        "--max-oco-per-symbol", str(args.max_oco_per_symbol),
        "--tp1", f"{(tp1 if tp1 is not None else args.tp1):.6f}",
        "--tp2", f"{(tp2 if tp2 is not None else args.tp2):.6f}",
        "--sl",  f"{args.sl:.6f}",
        "--status-interval", str(args.status_interval),
        "--loop-minutes", str(args.child_loop_minutes),
        "--oco-fallback", args.oco_fallback,
        "--target-buy-per-symbol", str(args.target_buy_per_symbol),
    ]
    if getattr(args, "child_cap_floor_usdt", None) is not None:
        cli += ["--cap-floor-usdt", str(args.child_cap_floor_usdt)]
    if getattr(args, "child_min_order_usdt", None) is not None:
        cli += ["--min-order-usdt", str(args.child_min_order_usdt)]
    if args.oco_on_holdings:
        cli.append("--oco-on-holdings")
    if args.auto_oco_holdings:
        cli.append("--auto-oco-holdings")
    if args.live:
        cli.append("--live")
    if getattr(args, "enforce_target_buys", False):
        cli.append("--enforce-target-buys")
    if getattr(args, "enforce_sell_limit", False):
        cli.append("--enforce-sell-limit")
    if getattr(args, "attach_oco_on_fill", False):
        cli.append("--attach-oco-on-fill")
    if getattr(args, "check_fills_interval", None) is not None:
        cli += ["--check-fills-interval", str(args.check_fills_interval)]
    if getattr(args, "stop_limit_offset_pct", None) is not None:
        cli += ["--stop-limit-offset-pct", f"{args.stop_limit_offset_pct:.6f}"]

    if getattr(args, "child_skip_buy_while_panic", False):
        cli.append("--skip-buy-while-panic")
    if getattr(args, "child_buy_trend_ema_gap", None) is not None:
        cli += ["--buy-trend-ema-gap", f"{float(args.child_buy_trend_ema_gap):.6f}"]
    if getattr(args, "child_buy_trend_interval", None):
        cli += ["--buy-trend-interval", str(args.child_buy_trend_interval)]
    if getattr(args, "child_bear_skip_buys", False):
        cli.append("--bear-skip-buys")
    if getattr(args, "child_bear_cap_scale", None) is not None and float(args.child_bear_cap_scale) != 1.0:
        cli += ["--bear-cap-scale", f"{float(args.child_bear_cap_scale):.6f}"]
    if getattr(args, "child_bear_buy_shift_pct", 0.0):
        cli += ["--bear-buy-shift-pct", f"{float(args.child_bear_buy_shift_pct):.6f}"]
    if getattr(args, "child_panic_sell_floor_pct", None) is not None:
        cli += ["--panic-sell-floor-pct", f"{float(args.child_panic_sell_floor_pct):.6f}"]
    if getattr(args, "child_buy_vwap_premium", None) is not None:
        cli += ["--buy-vwap-premium", f"{float(args.child_buy_vwap_premium):.6f}"]
    if getattr(args, "child_buy_vwap_discount", None) is not None:
        cli += ["--buy-vwap-discount", f"{float(args.child_buy_vwap_discount):.6f}"]
    if getattr(args, "child_buy_vwap_discount_scale", None) is not None and float(args.child_buy_vwap_discount_scale) != 1.0:
        cli += ["--buy-vwap-discount-scale", f"{float(args.child_buy_vwap_discount_scale):.6f}"]
    if getattr(args, "child_buy_vwap_interval", None):
        cli += ["--buy-vwap-interval", str(args.child_buy_vwap_interval)]
    if getattr(args, "child_buy_vwap_window", None) is not None:
        cli += ["--buy-vwap-window", str(int(args.child_buy_vwap_window))]

    if getattr(args, "breakeven_on_tp1_symbols", None):
        if str(args.breakeven_on_tp1_symbols).strip():
            cli += ["--breakeven-on-tp1-symbols", str(args.breakeven_on_tp1_symbols).strip()]
    if getattr(args, "breakeven_offset_pct", None) is not None:
        cli += ["--breakeven-offset-pct", f"{float(args.breakeven_offset_pct):.6f}"]
    if getattr(args, "breakeven_check_interval", None) is not None:
        cli += ["--breakeven-check-interval", str(int(args.breakeven_check_interval))]

    py = sys.executable or "/usr/bin/python3"
    cmd = [py, "-u"] + cli
    log("[LAUNCH] " + " ".join(map(str, cmd)))
    try:
        env = os.environ.copy()
        if extra_env:
            env.update({k: str(v) for k, v in extra_env.items()})
        p = subprocess.Popen(cmd, stdout=sys.stdout, stderr=sys.stderr, env=env)
        _CHILD_PROCS[symbol] = p
    except Exception as e:
        log(f"[LAUNCH-ERR] {symbol} -> {e}")

# ===========================
# Авто-CAP на основе баланса
# ===========================

def auto_cap_if_needed(args: argparse.Namespace, n_syms: int) -> None:
    if not args.auto_cap:
        return
    try:
        bals = get_balances()
        reserve = max(0.0, float(os.getenv("RISK_RESERVE_USDT", "0") or 0.0))
        free = max(0.0, float(bals.get("USDT", 0.0)) - reserve)
        min_pool = float(args.cap_floor_usdt or 0.0)
        if free < max(10.0, min_pool):
            log(f"[AUTO-CAP] free≈{free:.2f} < threshold; skip CAP/BOT_CAP_PER_ORDER")
            return
        log(f"[BAL] USDT free≈{free:.2f}")
        if free <= 0:
            return
        pool = free * float(args.alloc_pct)
        denom = max(1, n_syms * max(1, args.target_buy_per_symbol))
        cap = pool / denom
        if args.cap_floor_usdt is not None:
            cap = max(cap, float(args.cap_floor_usdt))
        if args.cap_ceil_usdt is not None:
            cap = min(cap, float(args.cap_ceil_usdt))
        cap = max(5.0, cap)
        os.environ["BOT_CAP_PER_ORDER"] = f"{cap:.2f}"
        log(f"[AUTO-CAP] free≈{free:.2f} → BOT_CAP_PER_ORDER≈{cap:.2f} (n_syms={n_syms})")
    except Exception as e:
        log(f"[AUTO-CAP] failed: {e}")

# ===========================
# Логика на символ
# ===========================

_STARTUP_CLEAN_DONE: Dict[str, bool] = {}

def run_for_symbol(symbol: str, args: argparse.Namespace) -> None:
    # 1) Текущая цена + ATR
    now_p = get_last_price(symbol)
    log(f"[PLAN] {symbol} now≈{now_p:.4f}")

    atr_abs, atr_pct = _atr_pct(symbol, interval=(args.atr_interval if hasattr(args, 'atr_interval') else '5m'), length=20)

    # 2) Базовые TP/SL от ATR (если не заданы явно)
    tp1_calc = clamp(atr_pct * float(args.atr_mult_tp1), float(args.tp1_min), float(args.tp1_max))
    tp2_calc = clamp(atr_pct * float(args.atr_mult_tp2), float(args.tp1_min), float(args.tp1_max * 1.8))
    tp1_use = float(args.tp1) if args.tp1 is not None else tp1_calc
    tp2_use = float(args.tp2) if args.tp2 is not None else tp2_calc
    log(f"[ATR] {symbol} ATR={atr_abs:.4f} -> tp1={tp1_use:.4f}..{args.tp1_max:.4f} with mults tp1={args.atr_mult_tp1} tp2={args.atr_mult_tp2} sl={args.atr_mult_sl}")

    # 3) Режим направления (auto/forced)
    if args.dir_mode != "auto":
        dir_mode = args.dir_mode.upper()
        log(f"[DIR] {symbol} mode={dir_mode} (forced)")
    else:
        dir_mode, _diag = _infer_market_mode(
            symbol,
            interval=args.dir_interval,
            ema_fast_len=20,
            ema_slow_len=50,
            eps=float(args.dir_eps),
            slope_min=float(args.dir_slope_min),
            adx_min=float(args.dir_adx_min),
            hyst_bars=int(args.dir_hyst_bars),
            confirm_bars=int(args.dir_confirm_bars),
            do_log=bool(args.dir_log)
        )

    target_buys_use = int(args.target_buy_per_symbol)

    vwap_premium_final, vwap_discount_final, vwap_scale_final, vwap_interval_final, vwap_window_final = resolve_vwap_params(
        symbol,
        dir_mode,
        atr_pct or 0.0,
        args,
    )

    if args.child_buy_vwap_auto:
        dbg(
            f"[VWAP-AUTO] {symbol} dir={dir_mode} atr_pct={atr_pct:.4f} premium={vwap_premium_final if vwap_premium_final is not None else '∅'} "
            f"discount={vwap_discount_final if vwap_discount_final is not None else '∅'} scale={vwap_scale_final if vwap_scale_final is not None else '∅'}"
        )

    # 4) Фильтры биржи: берём один раз, используем для тик-округления и guard'а
    filters = get_exchange_filters_cached(symbol)
    tick = filters["tickSize"]

    # 5) Строим лестницу и делаем дедуп по тик-шагу и стороне
    low, down, up = args.ladder_pct
    if args.ladder_pct_map and symbol in args.ladder_pct_map:
        low, down, up = args.ladder_pct_map[symbol]
    ladder_all = build_ladder_pct(now_p, low, down, up, args.grid_density)

    dec = _decimals_from_step(tick)
    seen = set(); dedup = []
    for p in ladder_all:
        pr = _round_to_tick(p, tick)
        side = "B" if pr < now_p else "S"
        key = (f"{pr:.{dec}f}", side)
        if key in seen:
            continue
        seen.add(key)
        dedup.append(pr)
    ladder_all = dedup

    log(f"[PLAN] {symbol} ladder -> " + ", ".join(f"{p:.2f}" for p in ladder_all))

    # 6) Очистки: при старте и регулярная
    if not _STARTUP_CLEAN_DONE.get(symbol, False):
        startup_cleanup_orders(symbol, now_p, ladder_all, tick_size=tick, grace_sec=CLEANUP_WARMUP_SEC)
        _STARTUP_CLEAN_DONE[symbol] = True

    smart_cleanup_orders(
        symbol,
        now_price=now_p,
        ladder_prices=ladder_all,
        tick_size=tick,
        near_ttl_sec=args.near_ttl_sec,
        far_ttl_sec=args.far_ttl_sec,
        cancel_offladder=True
    )

    sr = smart_rolling(symbol, now_p, ladder_all, args)
    log(f"[SR-SUM] {symbol} kept={sr['kept']} cancel(ttl)={sr['cancel'].get('ttl',0)} cancel(atr)={sr['cancel'].get('atr',0)}")

    # 7) ATR-driven авто-адаптер (ENV override)
    extra_env = None
    if os.environ.get('AUTO_ADAPT_ENABLE', '0') in ('1', 'true', 'True', 'YES', 'yes'):
        base_dev_buy = float(os.environ.get('DEV_BUY_PCT', '0.004') or 0.004)
        base_min_profit = float(os.environ.get('MIN_PROFIT_OVER_AVG', '0.002') or 0.002)
        coef_dev = float(os.environ.get('ADAPT_DEV_BUY_COEF', '0.6') or 0.6)
        coef_min = float(os.environ.get('ADAPT_MIN_PROFIT_COEF', '0.6') or 0.6)
        floor_min = float(os.environ.get('ADAPT_MIN_FLOOR', '0.0025') or 0.0025)

        dev_buy_eff = max(base_dev_buy, coef_dev * atr_pct, floor_min)
        min_profit_eff = max(base_min_profit, coef_min * atr_pct, floor_min * 0.8)

        extra_env = {
            'DEV_BUY_PCT': f"{dev_buy_eff:.6f}",
            'MIN_PROFIT_OVER_AVG': f"{min_profit_eff:.6f}",
        }
        log(f"[ADAPT] {symbol} atr={atr_abs:.4f} atr/px={atr_pct*100:.3f}% -> DEV_BUY_PCT={dev_buy_eff:.4f} MIN_PROFIT_OVER_AVG={min_profit_eff:.4f}")
    if extra_env is None:
        extra_env = {}

    # 8) Мягкое применение режима к DEV_BUY_PCT и TP1
    cur_dev = float(extra_env.get('DEV_BUY_PCT') or os.environ.get('DEV_BUY_PCT', '0.004') or 0.004)
    before_dev = cur_dev
    before_tp1 = tp1_use

    if dir_mode == "UP":
        cur_dev = cur_dev * float(args.dir_up_dev_mult)
        tp1_use = max(float(args.tp1_min), tp1_use * float(args.dir_up_tp1_mult))
        target_buys_use = max(1, int(args.dir_up_target_buys))
    elif dir_mode == "DOWN":
        cur_dev = cur_dev * float(args.dir_down_dev_mult)
        tp1_use = min(float(args.tp1_max), tp1_use * float(args.dir_down_tp1_mult))
        target_buys_use = max(1, int(args.dir_down_target_buys))

    extra_env['DEV_BUY_PCT'] = f"{cur_dev:.6f}"
    log(f"[DIR-APPLY] {symbol} mode={dir_mode} DEV_BUY_PCT {before_dev:.4f}→{cur_dev:.4f}, TP1 {before_tp1:.4f}→{tp1_use:.4f}, target_buys={args.target_buy_per_symbol}→{target_buys_use}")

    # 9) Страж позиции / flatten — используем уже полученные filters (без повторных запросов)
    mode = position_guard_and_maybe_flatten(symbol, now_p, atr_abs, args, filters)
    log(f"[POS-MODE] {symbol} mode={mode}")

    ladder_for_child = ladder_all if mode not in ("reduce_only", "flattening") else _prune_to_sells_only(now_p, ladder_all)

    # 10) Запуск ребёнка с временной подменой target_buys
    orig_tb = int(args.target_buy_per_symbol)
    orig_vwap_premium = getattr(args, "child_buy_vwap_premium", None)
    orig_vwap_discount = getattr(args, "child_buy_vwap_discount", None)
    orig_vwap_scale = getattr(args, "child_buy_vwap_discount_scale", None)
    orig_vwap_interval = getattr(args, "child_buy_vwap_interval", None)
    orig_vwap_window = getattr(args, "child_buy_vwap_window", None)
    try:
        args.target_buy_per_symbol = int(target_buys_use)
        args.child_buy_vwap_premium = vwap_premium_final
        args.child_buy_vwap_discount = vwap_discount_final
        args.child_buy_vwap_discount_scale = vwap_scale_final
        args.child_buy_vwap_interval = vwap_interval_final
        args.child_buy_vwap_window = vwap_window_final
        run_child(symbol, ladder_for_child, args, extra_env=extra_env, tp1=tp1_use, tp2=tp2_use)
    finally:
        args.target_buy_per_symbol = orig_tb
        args.child_buy_vwap_premium = orig_vwap_premium
        args.child_buy_vwap_discount = orig_vwap_discount
        args.child_buy_vwap_discount_scale = orig_vwap_scale
        args.child_buy_vwap_interval = orig_vwap_interval
        args.child_buy_vwap_window = orig_vwap_window


def refresh_vwap_runtime_maps(args: argparse.Namespace,
                              symbols: List[str],
                              reason: str = "periodic") -> bool:
    if not symbols:
        return False

    script_dir = Path(__file__).resolve().parent
    sym_csv = ",".join(symbols)

    def _env(name: str, default: str) -> str:
        return os.getenv(name, default)

    base_cmd = [
        sys.executable or "/usr/bin/python3",
        str(script_dir / "gen_vwap_env.py"),
        "--symbols", sym_csv,
        "--interval", _env("BUY_VWAP_INTERVAL", "1m"),
        "--window", _env("BUY_VWAP_WINDOW", "240"),
        "--base-premium", _env("BUY_VWAP_PREMIUM", "0.0030"),
        "--base-discount", _env("BUY_VWAP_DISCOUNT", "0.0060"),
        "--base-scale", _env("BUY_VWAP_DISCOUNT_SCALE", "1.30"),
        "--premium-up-mult", _env("BUY_VWAP_PREMIUM_UP_MULT", "0.75"),
        "--premium-down-mult", _env("BUY_VWAP_PREMIUM_DOWN_MULT", "1.20"),
        "--premium-atr-coef", _env("BUY_VWAP_PREMIUM_ATR_COEF", "0.0"),
        "--premium-floor", _env("BUY_VWAP_PREMIUM_FLOOR", "0.0008"),
        "--premium-ceil", _env("BUY_VWAP_PREMIUM_CEIL", "0.0060"),
        "--scale-atr-coef", _env("BUY_VWAP_DISCOUNT_SCALE_ATR_COEF", "2.0"),
        "--scale-min", _env("BUY_VWAP_DISCOUNT_SCALE_MIN", "1.0"),
        "--scale-max", _env("BUY_VWAP_DISCOUNT_SCALE_MAX", "2.5"),
    ]

    env_vars = os.environ.copy()

    try:
        base_out = subprocess.check_output(base_cmd, text=True, env=env_vars)
    except subprocess.CalledProcessError as e:
        log(f"[VWAP-REFRESH] base generator failed ({reason}): {e}")
        return False
    except Exception as e:
        log(f"[VWAP-REFRESH] base error ({reason}): {e}")
        return False

    premium_map, discount_map, scale_map = parse_vwap_output(base_out)

    if getattr(args, "vwap_autotune_enable", False):
        auto_cmd = [
            sys.executable or "/usr/bin/python3",
            str(script_dir / "gen_vwap_autotune.py"),
            "--symbols", sym_csv,
            "--hours", str(getattr(args, "vwap_autotune_hours", 24)),
            "--pnl-threshold", str(getattr(args, "vwap_autotune_threshold", 25.0)),
            "--alpha", str(getattr(args, "vwap_autotune_alpha", 0.6)),
            "--state-file", getattr(args, "vwap_autotune_state", "/run/mybot/vwap_state.json"),
        ]
        try:
            auto_out = subprocess.check_output(auto_cmd, text=True, env=env_vars)
        except subprocess.CalledProcessError as e:
            log(f"[VWAP-REFRESH] autotune failed ({reason}): {e}")
        except Exception as e:
            log(f"[VWAP-REFRESH] autotune error ({reason}): {e}")
        else:
            p2, d2, s2 = parse_vwap_output(auto_out)
            if p2:
                premium_map.update(p2)
            if d2:
                discount_map.update(d2)
            if s2:
                scale_map.update(s2)

    if premium_map:
        args.child_buy_vwap_premium_map = premium_map
    if discount_map:
        args.child_buy_vwap_discount_map = discount_map
    if scale_map:
        args.child_buy_vwap_discount_scale_map = scale_map

    if premium_map or discount_map or scale_map:
        log(
            "[VWAP-REFRESH] maps updated (%s): premium=%s discount=%s scale=%s" % (
                reason,
                ",".join(f"{k}:{v:.6f}" for k, v in sorted(premium_map.items())) or "∅",
                ",".join(f"{k}:{v:.6f}" for k, v in sorted(discount_map.items())) or "∅",
                ",".join(f"{k}:{v:.6f}" for k, v in sorted(scale_map.items())) or "∅",
            )
        )
        return True

    log(f"[VWAP-REFRESH] no data received ({reason})")
    return False

# ===========================
# Аргументы CLI
# ===========================

def parse_ladder_pct_map(s: str) -> Dict[str, Tuple[float, float, float]]:
    return parse_pct_map(s)


def _validate_args(parser: argparse.ArgumentParser, args: argparse.Namespace) -> List[str]:
    symbols = [s.strip().upper() for s in args.symbols.split(",") if s.strip()]
    if not symbols:
        parser.error("--symbols must contain at least one symbol")
    if len(symbols) != len(set(symbols)):
        parser.error("--symbols contains duplicates")
    for symbol in symbols:
        if not re.fullmatch(r"[A-Z0-9]{5,20}", symbol):
            parser.error(f"invalid Binance symbol: {symbol!r}")

    positive_ints = {
        "--grid-density": args.grid_density,
        "--target-buy-per-symbol": args.target_buy_per_symbol,
        "--max-oco-per-symbol": args.max_oco_per_symbol,
        "--child-loop-minutes": args.child_loop_minutes,
        "--interval-seconds": args.interval_seconds,
        "--risk-check-sec": args.risk_check_sec,
        "--flatten-slices": args.flatten_slices,
    }
    for name, value in positive_ints.items():
        if value is None or int(value) <= 0:
            parser.error(f"{name} must be > 0")

    non_negative = {
        "--near-ttl-sec": args.near_ttl_sec,
        "--far-ttl-sec": args.far_ttl_sec,
        "--price-eps-mult": args.price_eps_mult,
        "--dir-eps": args.dir_eps,
        "--dir-slope-min": args.dir_slope_min,
        "--dir-adx-min": args.dir_adx_min,
        "--flatten-min-edge-pct": args.flatten_min_edge_pct,
        "--flatten-limit-offset-atr": args.flatten_limit_offset_atr,
        "--vwap-refresh-sec": args.vwap_refresh_sec,
        "--vwap-refresh-jitter-sec": args.vwap_refresh_jitter_sec,
    }
    for name, value in non_negative.items():
        if float(value) < 0:
            parser.error(f"{name} must be >= 0")
    if args.far_ttl_sec and args.near_ttl_sec and args.far_ttl_sec < args.near_ttl_sec:
        parser.error("--far-ttl-sec cannot be lower than --near-ttl-sec")

    positive_floats = {
        "--atr-mult-tp1": args.atr_mult_tp1,
        "--atr-mult-tp2": args.atr_mult_tp2,
        "--atr-mult-sl": args.atr_mult_sl,
        "--child-buy-vwap-window": args.child_buy_vwap_window,
        "--flatten-avg-cache-ttl": args.flatten_avg_cache_ttl,
        "--flatten-avg-lookback": args.flatten_avg_lookback,
    }
    for name, value in positive_floats.items():
        if value is not None and float(value) <= 0:
            parser.error(f"{name} must be > 0")

    if not 0 < args.alloc_pct <= 1:
        parser.error("--alloc-pct must be in (0, 1]")
    if not 0 < args.pos_warn_pct <= 1:
        parser.error("--pos-warn-pct must be in (0, 1]")
    if not 0 < args.flatten_slice_pct <= 1:
        parser.error("--flatten-slice-pct must be in (0, 1]")
    if not 0 <= args.stop_limit_offset_pct < 0.25:
        parser.error("--stop-limit-offset-pct must be in [0, 0.25)")
    if args.cap_floor_usdt is not None and args.cap_floor_usdt < 0:
        parser.error("--cap-floor-usdt must be >= 0")
    if args.cap_ceil_usdt is not None and args.cap_ceil_usdt <= 0:
        parser.error("--cap-ceil-usdt must be > 0")
    if (args.cap_floor_usdt is not None and args.cap_ceil_usdt is not None
            and args.cap_floor_usdt > args.cap_ceil_usdt):
        parser.error("--cap-floor-usdt cannot exceed --cap-ceil-usdt")
    if args.tp1_min <= 0 or args.tp1_max <= 0 or args.tp1_min > args.tp1_max:
        parser.error("TP1 bounds must be positive and --tp1-min <= --tp1-max")
    if args.sl_max <= 0 or args.sl_max >= 1:
        parser.error("--sl-max must be in (0, 1)")
    if args.child_buy_vwap_premium_floor < 0:
        parser.error("VWAP premium floor must be >= 0")
    if args.child_buy_vwap_premium_floor > args.child_buy_vwap_premium_ceil:
        parser.error("VWAP premium floor cannot exceed ceiling")
    if args.child_buy_vwap_discount_scale_min > args.child_buy_vwap_discount_scale_max:
        parser.error("VWAP discount scale min cannot exceed max")
    if not 0 <= args.child_bear_cap_scale <= 5:
        parser.error("--child-bear-cap-scale must be in [0, 5]")
    if not 0 <= args.child_bear_buy_shift_pct < 1:
        parser.error("--child-bear-buy-shift-pct must be in [0, 1)")
    if args.breakeven_offset_pct is not None and not 0 <= args.breakeven_offset_pct < 1:
        parser.error("--breakeven-offset-pct must be in [0, 1)")
    if args.sl is not None and args.sl >= 0:
        parser.error("--sl must be negative")
    if not re.fullmatch(r"(?:[01]\d|2[0-3]):[0-5]\d", args.flatten_at):
        parser.error("--flatten-at must use HH:MM (24-hour) format")
    if args.flatten_force and not args.flatten_enable:
        parser.error("--flatten-force requires --flatten-enable")

    try:
        values = [float(x.strip()) for x in args.ladder_pct.split(",")]
    except ValueError:
        parser.error("--ladder-pct must contain three numbers")
    if len(values) != 3:
        parser.error("--ladder-pct must contain exactly three numbers")
    if not values[0] < 0 or not values[1] < 0 or not values[2] > 0:
        parser.error("--ladder-pct expects negative low/down and positive up percentages")

    if args.live and os.getenv("BOT_LIVE_CONFIRMED", "") != "YES":
        parser.error("--live requires BOT_LIVE_CONFIRMED=YES")
    if args.live and not Path(args.base_script).is_file():
        parser.error(f"--base-script does not exist: {args.base_script}")
    return symbols


def _configure_venue(args: argparse.Namespace) -> None:
    """Select testnet/mainnet before any authenticated preflight request."""
    global BINANCE_API_BASE, API_KEY, API_SECRET
    if args.testnet:
        base = os.getenv("BINANCE_TESTNET_API_BASE", "https://testnet.binance.vision").rstrip("/")
        key = os.getenv("BINANCE_TESTNET_API_KEY", "")
        secret = os.getenv("BINANCE_TESTNET_API_SECRET", "")
        venue = "testnet"
    else:
        base = (os.getenv("BINANCE_API_BASE") or "https://api.binance.com").rstrip("/")
        key = os.getenv("BINANCE_API_KEY", "")
        secret = os.getenv("BINANCE_API_SECRET", "")
        venue = "mainnet"
    BINANCE_API_BASE, API_KEY, API_SECRET = base, key, secret
    TM.BASE_URL, TM.API_KEY, TM.API_SECRET = base, key, secret
    os.environ["BINANCE_API_BASE"] = base
    if key:
        os.environ["BINANCE_API_KEY"] = key
    if secret:
        os.environ["BINANCE_API_SECRET"] = secret
    SESSION.headers.pop("X-MBX-APIKEY", None)
    if key:
        SESSION.headers.update({"X-MBX-APIKEY": key})
    log(f"[VENUE] {venue} base={base} mode={'LIVE' if args.live else 'DRY'}")


def _preflight_live(args: argparse.Namespace, symbols: List[str], limits: RiskLimits) -> None:
    """Refuse LIVE before every required dependency has been proven usable."""
    if not args.live:
        return
    limits.validate()
    if limits.halt_file.exists():
        log(
            f"[PREFLIGHT] persistent halt detected at {limits.halt_file}; "
            "supervisor will only reconcile and cancel BUY until manual reset"
        )
    if not TM.API_KEY or not TM.API_SECRET:
        prefix = "BINANCE_TESTNET" if args.testnet else "BINANCE"
        raise RuntimeError(f"{prefix}_API_KEY/SECRET are required for LIVE mode")

    stats_db = os.getenv("BOT_STATS_DB", "").strip()
    if not stats_db:
        raise RuntimeError("BOT_STATS_DB is required for fail-closed LIVE mode")
    import tools_stats
    con = tools_stats.init_db(stats_db)
    try:
        con.execute("SELECT 1 FROM trades LIMIT 1").fetchall()
    finally:
        con.close()

    t0 = int(time.time() * 1000)
    server = _public_get("/api/v3/time")
    t1 = int(time.time() * 1000)
    clock = assess_exchange_clock(
        server_time_ms=int(server["serverTime"]),
        request_started_ms=t0,
        response_finished_ms=t1,
        max_offset_ms=int(os.getenv("RISK_MAX_TIME_OFFSET_MS", "1000")),
        max_round_trip_ms=int(os.getenv("RISK_MAX_TIME_RTT_MS", "5000")),
    )
    clock.require_safe()

    for symbol in symbols:
        filters = get_exchange_filters(symbol)
        required = ("tickSize", "stepSize", "minQty", "minNotional")
        invalid = [name for name in required if float(filters.get(name, 0)) <= 0]
        if invalid:
            raise RuntimeError(f"invalid exchange filters for {symbol}: {','.join(invalid)}")

    account = TM._signed_get("/api/v3/account")
    if account.get("canTrade") is not True:
        raise RuntimeError("Binance account/API key is not allowed to trade")

    cap = float(args.cap_ceil_usdt or os.getenv("BOT_CAP_PER_ORDER", "50"))
    theoretical = cap * args.target_buy_per_symbol * len(symbols)
    max_exposure = min(theoretical, float(limits.portfolio_cap_usdt))
    config = {
        "venue": "testnet" if args.testnet else "mainnet",
        "symbols": symbols,
        "target_buys_per_symbol": args.target_buy_per_symbol,
        "cap_per_order_usdt": cap,
        "max_new_buy_exposure_usdt": round(max_exposure, 2),
        "portfolio_cap_usdt": str(limits.portfolio_cap_usdt),
        "reserve_usdt": str(limits.reserve_usdt),
        "stats_db": stats_db,
    }
    log("[PREFLIGHT] PASS " + json.dumps(config, sort_keys=True))


def _stop_children(reason: str) -> None:
    for symbol, proc in list(_CHILD_PROCS.items()):
        if proc.poll() is None:
            log(f"[RISK] stop child {symbol} pid={proc.pid}: {reason}")
            proc.terminate()
        _CHILD_PROCS.pop(symbol, None)


def _cancel_open_buy_orders(orders: Optional[List[Dict[str, Any]]] = None) -> int:
    orders = orders if orders is not None else (TM._signed_get("/api/v3/openOrders") or [])
    canceled = 0
    for order in orders:
        if str(order.get("side", "")).upper() != "BUY":
            continue
        if cancel_order(str(order["symbol"]), int(order["orderId"])):
            canceled += 1
    log(f"[RISK] canceled open BUY orders={canceled}")
    return canceled


def _notify_risk(decision: RiskDecision) -> None:
    reason = "; ".join(decision.reasons) or "risk limit"
    log(f"[RISK-ALERT] halted={decision.halted} buy_blocked={decision.buy_blocked}: {reason}")
    webhook = os.getenv("BOT_ALERT_WEBHOOK_URL", "").strip()
    if webhook:
        try:
            requests.post(webhook, json={
                "event": "circuit_breaker" if decision.halted else "buy_blocked",
                "reason": reason,
            }, timeout=5).raise_for_status()
        except requests.RequestException as exc:
            log(f"[RISK-ALERT] webhook failed: {exc}")


def _build_risk_snapshot(
    symbols: List[str], limits: RiskLimits
) -> tuple[RiskSnapshot, List[Dict[str, Any]], Dict[str, float]]:
    balances = get_balances_full()
    prices = {symbol: get_last_price(symbol) for symbol in symbols}
    orders = TM._signed_get("/api/v3/openOrders") or []

    tracked_assets: Dict[str, Decimal] = {}
    equity = money(balances.get("USDT", {}).get("free", 0)) + money(balances.get("USDT", {}).get("locked", 0))
    holdings_exposure = Decimal("0")
    for symbol, price in prices.items():
        base, _ = symbol_assets(symbol)
        if base in tracked_assets:
            continue
        qty = money(balances.get(base, {}).get("free", 0)) + money(balances.get(base, {}).get("locked", 0))
        value = qty * money(price)
        tracked_assets[base] = value
        equity += value
        holdings_exposure += value

    if env_flag("RISK_RECONCILE_STRICT", True):
        tolerance = max(0.0, float(os.getenv("RISK_RECONCILE_TOLERANCE_PCT", "0.02") or 0.02))
        with sqlite3.connect(f"file:{os.environ['BOT_STATS_DB']}?mode=ro", uri=True, timeout=5) as con:
            inventory = {
                str(symbol).upper(): float(qty)
                for symbol, qty in con.execute("SELECT symbol, qty FROM inventory").fetchall()
            }
        mismatches = []
        for symbol in symbols:
            base, _ = symbol_assets(symbol)
            account_qty = float(balances.get(base, {}).get("free", 0)) + float(balances.get(base, {}).get("locked", 0))
            db_qty = inventory.get(symbol)
            if db_qty is None:
                if account_qty > 0:
                    mismatches.append(f"{symbol}: account={account_qty:.8f}, ledger=missing")
                continue
            allowed = max(1e-8, abs(account_qty) * tolerance)
            if abs(account_qty - db_qty) > allowed:
                mismatches.append(f"{symbol}: account={account_qty:.8f}, ledger={db_qty:.8f}")
        if mismatches:
            raise RuntimeError("position reconciliation failed: " + "; ".join(mismatches))

    open_buy = sum(
        money(order.get("price")) * money(order.get("origQty"))
        for order in orders
        if str(order.get("side", "")).upper() == "BUY"
        and str(order.get("symbol", "")).upper() in prices
    )
    exposure = holdings_exposure + open_buy
    correlated_symbols = {
        value.strip().upper()
        for value in os.getenv("RISK_CORRELATED_SYMBOLS", ",".join(symbols)).split(",")
        if value.strip()
    }
    correlated = sum(
        tracked_assets.get(symbol_assets(symbol)[0], Decimal("0"))
        for symbol in symbols if symbol in correlated_symbols
    ) + sum(
        money(order.get("price")) * money(order.get("origQty"))
        for order in orders
        if str(order.get("side", "")).upper() == "BUY"
        and str(order.get("symbol", "")).upper() in correlated_symbols
    )

    metrics = load_daily_trade_metrics(os.environ["BOT_STATS_DB"], symbols)
    snap = RiskSnapshot(
        equity_usdt=equity,
        exposure_usdt=exposure,
        free_usdt=money(balances.get("USDT", {}).get("free", 0)),
        open_order_count=len(orders),
        correlated_exposure_usdt=correlated,
        **metrics,
    )
    return snap, orders, prices

def main():
    ap = argparse.ArgumentParser(description="AI Supervisor for 1.8_autosize_universal.py")
    ap.add_argument("--singleton", action="store_true", help="разрешить только один экземпляр (lock в /tmp)")
    ap.add_argument("--base-script", default="/home/bot/apps/binance_bot/1.8_autosize_universal.py")
    ap.add_argument("--symbols", default="SOLUSDT,ETHUSDT", help="через запятую")
    ap.add_argument("--ladder-mode", default="pct", choices=["pct"], help="режим построения лестницы")
    ap.add_argument("--ladder-pct", default="-0.5,-20,20", help="low,down,up в процентах")
    ap.add_argument("--ladder-pct-map", default="", help="перекрытие по символам, формат: SYM=a,b,c;SYM2=a,b,c")
    ap.add_argument("--grid-density", type=int, default=20)
    ap.add_argument("--smart-rolling", action="store_true")
    ap.add_argument("--price-eps-mult", type=float, default=1.0)
    ap.add_argument("--near-ttl-sec", type=int, default=900)
    ap.add_argument("--far-ttl-sec", type=int, default=7200)
    ap.add_argument("--atr-interval", default="30m")
    ap.add_argument("--atr-kick", type=int, default=26)
    ap.add_argument("--child-cap-floor-usdt", type=float, default=None)
    ap.add_argument("--child-min-order-usdt", type=float, default=None)
    ap.add_argument("--child-skip-buy-while-panic", action="store_true",
                    help="Передавать дочернему воркеру флаг skip-buy-while-panic")
    ap.add_argument("--child-buy-trend-ema-gap", type=float, default=None,
                    help="Порог EMA gap для медвежьего режима в дочернем воркере")
    ap.add_argument("--child-buy-trend-interval", type=str, default=None,
                    help="Интервал EMA для тренд-фильтра в дочернем воркере")
    ap.add_argument("--child-bear-skip-buys", action="store_true",
                    help="Запретить дочернему воркере BUY при медвежьем сигнале")
    ap.add_argument("--child-bear-cap-scale", type=float, default=1.0,
                    help="Множитель CAP на заявку для дочернего воркера при медвежьем сигнале")
    ap.add_argument("--child-bear-buy-shift-pct", type=float, default=0.0,
                    help="Смещение BUY уровней вниз в дочернем воркере (доля)")
    ap.add_argument("--child-panic-sell-floor-pct", type=float, default=None,
                    help="Минимально допустимая скидка от средней при панике для дочернего воркера")
    ap.add_argument("--child-buy-vwap-premium", type=float, default=None,
                    help="Порог премии к VWAP, выше которого дочерний воркер пропустит BUY")
    ap.add_argument("--child-buy-vwap-discount", type=float, default=None,
                    help="Доля скидки к VWAP, при которой усиливается CAP у дочернего воркера")
    ap.add_argument("--child-buy-vwap-discount-scale", type=float, default=None,
                    help="Множитель CAP при скидке к VWAP (по умолчанию использовать логику воркера)")
    ap.add_argument("--child-buy-vwap-interval", type=str, default=None,
                    help="Интервал свечей для VWAP в дочернем воркере")
    ap.add_argument("--child-buy-vwap-window", type=int, default=None,
                    help="Размер окна (кол-во свечей) для VWAP в дочернем воркере")
    ap.add_argument("--child-buy-vwap-premium-map", type=str, default="",
                    help="Перечисление порогов премии к VWAP по символам (SYM:value)")
    ap.add_argument("--child-buy-vwap-discount-map", type=str, default="",
                    help="Перечисление скидок к VWAP по символам (SYM:value)")
    ap.add_argument("--child-buy-vwap-discount-scale-map", type=str, default="",
                    help="Перечисление множителей CAP при скидке по символам (SYM:value)")
    ap.add_argument("--child-buy-vwap-auto", action="store_true",
                    help="Автоматически подстраивать VWAP-параметры по режиму и ATR")
    ap.add_argument("--child-buy-vwap-premium-up-mult", type=float, default=0.75,
                    help="Множитель премии к VWAP в восходящем режиме")
    ap.add_argument("--child-buy-vwap-premium-down-mult", type=float, default=1.20,
                    help="Множитель премии к VWAP в нисходящем режиме")
    ap.add_argument("--child-buy-vwap-premium-atr-coef", type=float, default=0.0,
                    help="Коэффициент уменьшения премии по ATR (premium *= 1 - atr_pct*coef)")
    ap.add_argument("--child-buy-vwap-premium-floor", type=float, default=0.0005,
                    help="Нижний предел премии к VWAP")
    ap.add_argument("--child-buy-vwap-premium-ceil", type=float, default=0.02,
                    help="Верхний предел премии к VWAP")
    ap.add_argument("--child-buy-vwap-discount-scale-atr-coef", type=float, default=0.0,
                    help="Коэффициент увеличения CAP на скидке по ATR")
    ap.add_argument("--child-buy-vwap-discount-scale-min", type=float, default=1.0,
                    help="Минимальный множитель CAP при скидке к VWAP")
    ap.add_argument("--child-buy-vwap-discount-scale-max", type=float, default=3.0,
                    help="Максимальный множитель CAP при скидке к VWAP")

    ap.add_argument("--auto-cap", action="store_true")
    ap.add_argument("--alloc-pct", type=float, default=0.90)
    ap.add_argument("--target-buy-per-symbol", type=int, default=4)
    ap.add_argument("--cap-floor-usdt", type=float, default=None)
    ap.add_argument("--cap-ceil-usdt", type=float, default=None)

    ap.add_argument("--auto-oco-holdings", dest="auto_oco_holdings", action="store_true")
    ap.add_argument("--oco-on-holdings", action="store_true")
    ap.add_argument("--max-oco-per-symbol", type=int, default=12)
    ap.add_argument("--oco-fallback", choices=["none", "prefer-tp1"], default="prefer-tp1")
    ap.add_argument("--status-interval", type=int, default=1)
    ap.add_argument("--child-loop-minutes", type=int, default=5)
    ap.add_argument("--interval-seconds", type=int, default=60)
    ap.add_argument("--enforce-target-buys", action="store_true")
    ap.add_argument("--enforce-sell-limit", action="store_true")

    ap.add_argument("--atr-mult-tp1", type=float, default=2.8)
    ap.add_argument("--atr-mult-tp2", type=float, default=4.2)
    ap.add_argument("--atr-mult-sl", type=float, default=1.5)
    ap.add_argument("--tp1-min", type=float, default=0.003)
    ap.add_argument("--tp1-max", type=float, default=0.009)
    ap.add_argument("--sl-max", type=float, default=0.10)

    ap.add_argument("--tp1", type=float, default=None)
    ap.add_argument("--tp2", type=float, default=None)
    ap.add_argument("--sl",  type=float, default=-0.01035)

    ap.add_argument("--dir-mode", default=os.getenv("DIR_MODE", "auto"), choices=["auto", "up", "down", "flat"])
    ap.add_argument("--dir-interval", default=os.getenv("DIR_INTERVAL", "30m"))
    ap.add_argument("--dir-eps", type=float, default=float(os.getenv("DIR_EPS", "0.0005")))
    ap.add_argument("--dir-slope-min", type=float, default=float(os.getenv("DIR_SLOPE_MIN", "0.0002")))
    ap.add_argument("--dir-adx-min", type=float, default=float(os.getenv("DIR_ADX_MIN", "16.0")))
    ap.add_argument("--dir-hyst-bars", type=int, default=int(os.getenv("DIR_HYST_BARS", "5")))
    ap.add_argument("--dir-confirm-bars", type=int, default=int(os.getenv("DIR_CONFIRM_BARS", "3")))
    ap.add_argument("--dir-log", type=int, default=int(os.getenv("DIR_LOG", "1")))
    ap.add_argument("--dir-up-dev-mult", type=float, default=float(os.getenv("DIR_UP_DEV_MULT", "1.30")))
    ap.add_argument("--dir-up-tp1-mult", type=float, default=float(os.getenv("DIR_UP_TP1_MULT", "0.90")))
    ap.add_argument("--dir-up-target-buys", type=int, default=int(os.getenv("DIR_UP_TARGET_BUYS", "3")))
    ap.add_argument("--dir-down-dev-mult", type=float, default=float(os.getenv("DIR_DOWN_DEV_MULT", "0.80")))
    ap.add_argument("--dir-down-tp1-mult", type=float, default=float(os.getenv("DIR_DOWN_TP1_MULT", "1.15")))
    ap.add_argument("--dir-down-target-buys", type=int, default=int(os.getenv("DIR_DOWN_TARGET_BUYS", "2")))

    ap.add_argument("--pos-guard-enable", action="store_true")
    ap.add_argument("--pos-max-base-map", default="", help="SYM:base_qty,... напр. SOLUSDT:0.50,ETHUSDT:0.020")
    ap.add_argument("--pos-max-usdt-map", default="", help="SYM:usdt_equiv,... напр. SOLUSDT:500,ETHUSDT:600")
    ap.add_argument("--pos-warn-pct", type=float, default=0.60)
    ap.add_argument("--pos-action-on-warn", choices=["none", "block_increasing", "reduce_only"], default="reduce_only")
    ap.add_argument("--pos-action-on-hard", choices=["reduce_only", "flatten", "reduce_then_flatten"], default="reduce_then_flatten")

    ap.add_argument("--flatten-enable", action="store_true")
    ap.add_argument("--flatten-at", default="23:55")
    ap.add_argument("--flatten-t-minus-sec", type=int, default=900)
    ap.add_argument("--flatten-force", type=int, choices=[0, 1], default=0,
                    help="1 = разрешить flatten ниже средней после ручной проверки")
    ap.add_argument("--flatten-slices", type=int, default=3)
    ap.add_argument("--flatten-slice-pct", type=float, default=0.34)
    ap.add_argument("--flatten-limit-offset-atr", type=float, default=0.20)
    ap.add_argument("--flatten-market-failover", type=int, default=1)
    ap.add_argument("--flatten-avoid-loss", type=int, choices=[0, 1], default=1,
                    help="Если 1 — не форсировать flatten ниже средней цены (с учётом edge)")
    ap.add_argument("--flatten-min-edge-pct", type=float, default=0.0,
                    help="Минимальная надбавка к средней при flatten-guard (0 = просто средняя)")
    ap.add_argument("--flatten-avg-cache-ttl", type=int, default=45,
                    help="TTL кэша средней цены для flatten-guard")
    ap.add_argument("--flatten-avg-lookback", type=int, default=1200,
                    help="Сколько последних трейдов учитывать при расчёте средней для flatten-guard")

    ap.add_argument("--vwap-refresh-sec", type=int, default=int(os.getenv("VWAP_REFRESH_SEC", "600")),
                    help="Как часто обновлять VWAP-карты (0 = выключено)")
    ap.add_argument("--vwap-refresh-jitter-sec", type=int, default=int(os.getenv("VWAP_REFRESH_JITTER_SEC", "0")),
                    help="Случайный разброс к интервалу VWAP (для асинхронизации)" )
    ap.add_argument("--vwap-refresh-on-start", type=int, choices=[0, 1], default=int(os.getenv("VWAP_REFRESH_ON_START", "1")),
                    help="Пересчитывать VWAP перед первым запуском детей")
    ap.add_argument("--vwap-autotune-enable", action="store_true", default=env_flag("VWAP_AUTOTUNE", False),
                    help="Включить PnL-тюнер при обновлении VWAP-карт")
    ap.add_argument("--no-vwap-autotune", action="store_false", dest="vwap_autotune_enable")
    ap.add_argument("--vwap-autotune-hours", type=int, default=int(os.getenv("VWAP_AUTOTUNE_HOURS", "24")))
    ap.add_argument("--vwap-autotune-threshold", type=float, default=float(os.getenv("VWAP_AUTOTUNE_THRESHOLD", "25.0")))
    ap.add_argument("--vwap-autotune-alpha", type=float, default=float(os.getenv("VWAP_AUTOTUNE_ALPHA", "0.6")))
    ap.add_argument("--vwap-autotune-state", type=str, default=os.getenv("VWAP_AUTOTUNE_STATE", "/run/mybot/vwap_state.json"))

    ap.add_argument("--live", action="store_true")
    venue = ap.add_mutually_exclusive_group()
    venue.add_argument("--testnet", dest="testnet", action="store_true", default=True,
                       help="Binance Spot Testnet (по умолчанию)")
    venue.add_argument("--mainnet", dest="testnet", action="store_false",
                       help="Основной Binance Spot")
    ap.add_argument("--risk-check-sec", type=int, default=int(os.getenv("RISK_CHECK_SEC", "15")))
    ap.add_argument("--attach-oco-on-fill", action="store_true")
    ap.add_argument("--check-fills-interval", type=int, default=5)
    ap.add_argument("--stop-limit-offset-pct", type=float, default=0.0015)

    ap.add_argument("--breakeven-on-tp1-symbols", type=str, default="")
    ap.add_argument("--breakeven-offset-pct", type=float, default=None)
    ap.add_argument("--breakeven-check-interval", type=int, default=5)

    args = ap.parse_args()
    symbols = _validate_args(ap, args)
    _configure_venue(args)
    limits = RiskLimits.from_env()
    _preflight_live(args, symbols, limits)
    global LIVE_MODE
    LIVE_MODE = bool(args.live)
    risk_manager = RiskManager(limits) if args.live else None

    log(f"[SUP] symbols={symbols} ladder_mode={args.ladder_mode} ai_model=gpt-4o-mini")

    lp = [x.strip() for x in args.ladder_pct.split(",")]
    if len(lp) != 3:
        raise SystemExit("--ladder-pct ожидает три числа: low,down,up")
    args.ladder_pct = (float(lp[0]), float(lp[1]), float(lp[2]))
    args.ladder_pct_map = parse_ladder_pct_map(args.ladder_pct_map)

    args.pos_max_base_map = parse_limit_map(args.pos_max_base_map)
    args.pos_max_usdt_map = parse_limit_map(args.pos_max_usdt_map)
    args.child_buy_vwap_premium_map = parse_limit_map(getattr(args, "child_buy_vwap_premium_map", ""))
    args.child_buy_vwap_discount_map = parse_limit_map(getattr(args, "child_buy_vwap_discount_map", ""))
    args.child_buy_vwap_discount_scale_map = parse_limit_map(getattr(args, "child_buy_vwap_discount_scale_map", ""))

    if args.singleton:
        try:
            if os.path.exists(LOCK_FILE):
                with open(LOCK_FILE, "r") as f:
                    pid = int(f.read().strip() or "0")
                if pid and pid != os.getpid():
                    try:
                        os.kill(pid, signal.SIGTERM)
                        time.sleep(0.5)
                    except Exception:
                        pass
            with open(LOCK_FILE, "w") as f:
                f.write(str(os.getpid()))
        except Exception as e:
            log(f"[WARN] cannot create lock {LOCK_FILE}: {e}")

    get_server_time_offset_ms()
    auto_cap_if_needed(args, n_syms=len(symbols))
    configured_order_cap = money(args.cap_ceil_usdt or os.getenv("BOT_CAP_PER_ORDER", "50"))

    def _next_vwap_refresh() -> float:
        base = max(0, int(getattr(args, "vwap_refresh_sec", 0)))
        if base <= 0:
            return float("inf")
        delay = float(base)
        jitter = max(0, int(getattr(args, "vwap_refresh_jitter_sec", 0)))
        if jitter > 0:
            delay += random.uniform(-jitter, jitter)
        return time.time() + max(5.0, delay)

    next_vwap_refresh = float("inf")
    if getattr(args, "vwap_refresh_sec", 0) > 0:
        if getattr(args, "vwap_refresh_on_start", 1):
            try:
                if refresh_vwap_runtime_maps(args, symbols, reason="startup"):
                    next_vwap_refresh = _next_vwap_refresh()
                else:
                    next_vwap_refresh = _next_vwap_refresh()
            except Exception as e:
                log(f"[VWAP-REFRESH] startup error: {e}")
                next_vwap_refresh = _next_vwap_refresh()
        else:
            next_vwap_refresh = _next_vwap_refresh()

    next_risk_check = 0.0
    risk_buy_blocked = False
    last_risk_signature: tuple[bool, tuple[str, ...]] | None = None
    previous_prices: Dict[str, float] = {}
    consecutive_api_failures = 0

    try:
        while True:
            now_loop = time.time()
            if risk_manager is not None and now_loop >= next_risk_check:
                orders: List[Dict[str, Any]] = []
                try:
                    snapshot, orders, prices = _build_risk_snapshot(symbols, limits)
                    consecutive_api_failures = 0
                    shock_pct = float(os.getenv("RISK_SHOCK_PCT", "0.05") or 0.05)
                    shocks = []
                    for symbol, price in prices.items():
                        previous = previous_prices.get(symbol)
                        if previous and abs(price / previous - 1.0) >= shock_pct:
                            shocks.append(f"{symbol} moved {abs(price / previous - 1.0):.2%}")
                    previous_prices = prices
                    if shocks:
                        risk_manager.start_cooldown("; ".join(shocks))
                    decision = risk_manager.evaluate(snapshot)
                    if not decision.buy_blocked:
                        remaining = min(
                            limits.portfolio_cap_usdt - snapshot.exposure_usdt,
                            limits.daily_buy_cap_usdt - snapshot.daily_buy_usdt,
                            limits.correlated_cap_usdt - snapshot.correlated_exposure_usdt,
                            snapshot.free_usdt - limits.reserve_usdt,
                        )
                        slots = max(1, args.target_buy_per_symbol * len(symbols))
                        safe_cap = min(configured_order_cap, max(Decimal("0"), remaining) / slots)
                        min_order = money(args.child_min_order_usdt or 0)
                        if safe_cap <= 0 or (min_order > 0 and safe_cap < min_order):
                            decision = RiskDecision(
                                halted=False,
                                buy_blocked=True,
                                reasons=(f"remaining risk budget {remaining:.2f} USDT cannot fund a safe order",),
                            )
                        else:
                            os.environ["BOT_CAP_PER_ORDER"] = str(safe_cap)
                            dbg(f"[RISK] dynamic safe order cap={safe_cap:.2f} USDT")
                except Exception as exc:
                    consecutive_api_failures += 1
                    threshold = max(1, int(os.getenv("RISK_API_FAILURE_THRESHOLD", "3")))
                    reason = f"risk telemetry unavailable ({consecutive_api_failures}/{threshold}): {exc}"
                    if consecutive_api_failures >= threshold:
                        risk_manager.start_cooldown(reason)
                    decision = RiskDecision(halted=False, buy_blocked=True, reasons=(reason,))

                risk_buy_blocked = decision.buy_blocked
                if risk_buy_blocked:
                    reason = "; ".join(decision.reasons) or "risk limit"
                    _stop_children(reason)
                    try:
                        _cancel_open_buy_orders(orders or None)
                    except Exception as exc:
                        log(f"[RISK] cancel BUY failed: {exc}")
                signature = (decision.halted, decision.reasons)
                if signature != last_risk_signature and decision.buy_blocked:
                    _notify_risk(decision)
                last_risk_signature = signature
                next_risk_check = now_loop + max(1, int(args.risk_check_sec))

            if risk_buy_blocked:
                time.sleep(min(2.0, max(0.5, float(args.risk_check_sec) / 2.0)))
                continue

            if now_loop >= next_vwap_refresh:
                try:
                    refresh_vwap_runtime_maps(args, symbols, reason="periodic")
                except Exception as e:
                    log(f"[VWAP-REFRESH] periodic error: {e}")
                finally:
                    next_vwap_refresh = _next_vwap_refresh()

            for sym in symbols:
                try:
                    run_for_symbol(sym, args)
                except Exception as e:
                    log(f"[ERR] {sym}: {e}")
                time.sleep(0.2)
            time.sleep(0.5)
    finally:
        try:
            if os.path.exists(LOCK_FILE):
                os.remove(LOCK_FILE)
                log(f"[stop-all] lock удалён ({LOCK_FILE})")
        except Exception:
            pass

if __name__ == "__main__":
    main()
