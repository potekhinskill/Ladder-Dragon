#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tools_market.py — утилиты для Binance Spot API (исправленная версия, 2025-08-24)

Новое в этой ревизии:
- Нормализация интервалов свечей для /api/v3/klines (alias: "15min", "15 мин" → "15m")
- Авто-фолбэк при ошибке Binance `code=-1120 (Invalid interval)` на безопасный "15m" с единичным ретраем
- Лёгкий лог фолбэка, чтобы было видно причину в журналах
- Возвращаем ещё и minQty из exchangeInfo, чтобы супервизор мог брать ВСЕ фильтры из одного места
  (tickSize, stepSize, minQty, minNotional) и не вызывать /exchangeInfo повторно.

Содержимое модуля:
- Корректная подпись: один и тот же порядок параметров при подписании и отправке (список кортежей) — избегаем -1022
- Защита от рассинхронизации времени: кешируем offset от /api/v3/time
- Ретраи на запросы
- Кэш exchangeInfo для фильтров (TTL)
- Функция round_qty_price(symbol, qty, price, side="BUY") — ОКРУГЛЯЕТ и ФОРМАТИРУЕТ qty/price под шаги.
- Функция get_klines(symbol, interval, ...) — с нормализацией и фолбэком интервала
"""

from __future__ import annotations
import os
import time
import hmac
import math
import hashlib
import requests
from typing import Dict, Tuple, List, Optional, Any

# --- .env (опционально) ---
from pathlib import Path

try:
    from dotenv import load_dotenv, find_dotenv
except ModuleNotFoundError:
    # python-dotenv не установлен — просто пропускаем
    pass
else:
    # 1) сначала пробуем .env рядом с текущим файлом
    env_path = (Path(__file__).resolve().parent / ".env")
    if env_path.exists():
        load_dotenv(dotenv_path=env_path, override=False)
    else:
        # 2) иначе ищем вверх от текущей рабочей директории (на случай запуска вручную)
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

# ---- простые ретраи ----
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
    except Exception:
        data = {"msg": resp.text}
    raise BinanceHttpError(f"HTTP {resp.status_code}: {data}")

# ---- time offset (server time skew) ----
_time_offset_ms: Optional[int] = None
_time_offset_ts: float = 0.0
_OFFSET_TTL = 60.0  # секунд

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
        try:
            _refresh_time_offset()
        except Exception:
            _time_offset_ms = 0
            _time_offset_ts = time.time()
    return int(time.time() * 1000 + (_time_offset_ms or 0))

# ---- подпись: гарантируем один и тот же порядок ----
def _sign_tuples(params: List[Tuple[str, str]], secret: str) -> str:
    query = "&".join(f"{k}={v}" for k, v in params)
    return hmac.new(secret.encode("utf-8"), query.encode("utf-8"), hashlib.sha256).hexdigest()

# ---- публичные/приватные запросы ----
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

# ---- нормализация интервалов для klines ----
VALID_INTERVALS: set[str] = {
    "1m","3m","5m","15m","30m",
    "1h","2h","4h","6h","8h","12h",
    "1d","3d","1w","1M",
}
_INTERVAL_ALIASES: Dict[str, str] = {
    # английские варианты
    "1min": "1m", "3min": "3m", "5min": "5m", "15min": "15m", "30min": "30m",
    "1hour": "1h", "2hour": "2h", "4hour": "4h", "6hour": "6h", "12hour": "12h",
    "1day": "1d", "3day": "3d", "1week": "1w", "1month": "1M",
    # русские (частые) варианты
    "1мин": "1m", "3мин": "3m", "5мин": "5m", "15мин": "15m", "30мин": "30m",
    "1час": "1h", "2час": "2h", "4час": "4h", "6час": "6h", "12час": "12h",
    "1д": "1d", "3д": "3d", "1н": "1w", "1мес": "1M",
}

# --- ДОБАВЬ в алиасы ---
_INTERVAL_ALIASES.update({
    "8hour": "8h", "8hours": "8h", "8час": "8h", "8часов": "8h", "8ч": "8h",
    "2hours": "2h", "4hours": "4h", "6hours": "6h", "12hours": "12h",
    "2ч": "2h", "4ч": "4h", "6ч": "6h", "12ч": "12h",
    # иногда пишут с суффиксом s / без пробелов уже учтено
})

def norm_interval(interval: str | None, default: str = "15m") -> str:
    """
    Нормализует интервал для /api/v3/klines.
    Особый случай: '1M' (месяц) должен остаться с заглавной M, в то время как '1m' — минуты.
    Признаём алиасы типа '1month', '1mon', '1mo', '1мес', '1месяц' как '1M'.
    """
    s = (interval or "").strip().replace(" ", "")
    if not s:
        return default

    # 1) Месяц: точный '1M' или словесные алиасы → '1M'
    s_low = s.lower()
    if s == "1M" or s_low in {"1month", "1mon", "1mo", "1мес", "1месяц"}:
        return "1M"

    # 2) Остальные алиасы/варианты (минуты/часы/дни/недели)
    s_norm = _INTERVAL_ALIASES.get(s_low, s_low)

    # 3) Финальная проверка на допустимость
    return s_norm if s_norm in VALID_INTERVALS else default

# ---- kline API с фолбэком интервала ----
def get_klines(symbol: str,
               interval: str,
               *,
               limit: int = 500,
               startTime: Optional[int] = None,
               endTime: Optional[int] = None,
               fallback_default: str = "15m") -> List[List[Any]]:
    """
    Возвращает список свечей (как на /api/v3/klines), с нормализацией интервала и фолбэком.
    При `code=-1120 (Invalid interval)` один раз ретраим с fallback_default (по умолчанию '15m').

    Параметры startTime/endTime — миллисекунды epoch.
    """
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

    # первый запрос
    r = _do_request("GET", url, params=params)
    if r.status_code == 200:
        try:
            return r.json()  # type: ignore[return-value]
        except Exception as e:
            raise BinanceHttpError(f"Failed to parse klines JSON: {e}")

    # обработка ошибок
    try:
        err = r.json()
    except Exception:
        err = {"msg": r.text}

    # фолбэк при неверном интервале
    if r.status_code == 400 and isinstance(err, dict) and err.get("code") == -1120:
        fb = norm_interval(fallback_default, default="15m")
        if fb != interval:
            print(f"[KLINES] invalid interval '{interval}', retry with '{fb}'", flush=True)
            params = [(k, v if k != "interval" else fb) for (k, v) in params]
            r2 = _do_request("GET", url, params=params)
            _raise_for_binance(r2)
            try:
                return r2.json()  # type: ignore[return-value]
            except Exception as e:
                raise BinanceHttpError(f"Failed to parse klines JSON after fallback: {e}")

    # если сюда дошли — поднимаем исключение как есть
    _raise_for_binance(r)  # поднимет BinanceHttpError
    return []  # недостижимо

# ---- кэш exchangeInfo ----
_exchange_cache: Dict[str, Dict[str, float | int]] = {}
_exchange_cache_ts: Dict[str, float] = {}  # TTL
_CACHE_TTL = 300  # 5 мин

def get_symbol_filters(symbol: str) -> Dict[str, float | int]:
    symbol = symbol.upper()
    now = time.time()
    if symbol in _exchange_cache and (now - _exchange_cache_ts.get(symbol, 0)) < _CACHE_TTL:
        return _exchange_cache[symbol]

    data = _public_get("/api/v3/exchangeInfo", {"symbol": symbol})
    symbols = data.get("symbols") or []
    if not symbols:
        raise BinanceHttpError(f"exchangeInfo: symbol '{symbol}' not found")
    info = symbols[0]

    tick_size = 0.0
    step_size = 0.0
    min_qty   = 0.0
    min_notional = 5.0

    # новые поля (полезны супервизору/валидаторам)
    price_precision = int(info.get("pricePrecision", 0))
    qty_precision   = int(info.get("quantityPrecision", 0))

    # некоторые рынки используют MARKET_LOT_SIZE для маркет-ордеров
    market_step_size = 0.0
    market_min_qty   = 0.0

    for f in info.get("filters", []):
        ftype = f.get("filterType")
        if ftype == "PRICE_FILTER":
            tick_size = float(f.get("tickSize", "0") or 0)
        elif ftype == "LOT_SIZE":
            step_size = float(f.get("stepSize", "0") or 0)
            min_qty   = float(f.get("minQty", "0") or 0)
        elif ftype == "MARKET_LOT_SIZE":
            market_step_size = float(f.get("stepSize", "0") or 0)
            market_min_qty   = float(f.get("minQty", "0") or 0)
        elif ftype in ("MIN_NOTIONAL", "NOTIONAL"):
            mn = f.get("minNotional")
            if mn is not None:
                min_notional = float(mn)

    res = {
        "tickSize": tick_size,
        "stepSize": step_size,
        "minQty": min_qty,
        "minNotional": min_notional,
        "pricePrecision": price_precision,
        "quantityPrecision": qty_precision,
        "marketStepSize": market_step_size,
        "marketMinQty": market_min_qty,
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

# ---- округление qty/price под фильтры ----
def _decimals_from_float_step(step: float) -> int:
    s = f"{step:.16f}".rstrip("0").rstrip(".")
    if "." in s:
        return len(s.split(".", 1)[1])
    return 0

def _round_by_step(value: float, step: float, mode: str = "floor") -> float:
    if step <= 0:
        return value
    q = value / step
    if mode == "floor":
        q = math.floor(q)
    elif mode == "ceil":
        q = math.ceil(q)
    else:
        q = round(q)
    return q * step

def round_qty_price(symbol: str, qty: float, price: float, side: str = "BUY") -> Tuple[str, str]:
    """
    Возвращает (qty_s, price_s) — округлённые и отформатированные строки
    под фильтры биржи. Для BUY — price вниз, для SELL — price вверх.
    qty всегда вниз (безопасно для остатков/stepSize).
    Также гарантирует minNotional/minQty. Бросает исключение, если после округлений qty/price невалидны.
    """
    side = (side or "BUY").upper()
    f = get_symbol_filters(symbol)
    step = float(f.get("stepSize", 0.0) or 0.0)
    tick = float(f.get("tickSize", 0.0) or 0.0)
    min_notional = float(f.get("minNotional", 0.0) or 0.0)

    # qty всегда вниз по шагу
    qty = _round_by_step(qty, step, mode="floor")

    # price: BUY вниз, SELL вверх по тикам
    price_mode = "floor" if side == "BUY" else "ceil"
    price = _round_by_step(price, tick, mode=price_mode)

    # Гарантия minNotional: если не проходит — поднимем qty до ближайшего шага
    if min_notional > 0 and price > 0:
        notional = qty * price
        if notional < min_notional:
            need = min_notional / price
            k = math.ceil(need / step) if step > 0 else 1
            qty = max(qty, k * step if step > 0 else need)

    # Гарантия minQty: дотягиваем до минимального шага, не меньше minQty
    min_qty = float(f.get("minQty", 0.0) or 0.0)
    if min_qty > 0 and qty < min_qty:
        k = math.ceil(min_qty / step) if step > 0 else 1
        qty = max(qty, k * step if step > 0 else min_qty)

    # Гард от нулевых/отрицательных после всех корректировок
    if qty <= 0 or price <= 0:
        raise BinanceHttpError(f"Invalid rounded qty/price: qty={qty}, price={price}")

    # Форматируем под точность шага/тика
    q_dec = _decimals_from_float_step(step)
    p_dec = _decimals_from_float_step(tick)
    return f"{qty:.{q_dec}f}", f"{price:.{p_dec}f}"
