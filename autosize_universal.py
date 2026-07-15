#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Ladder Dragon — универсальный исполнитель с автоматическим размером заявки

Скрипт-воркер: по списку цен создаёт/поддерживает лимитные заявки BUY,
и (опционально) распродаёт имеющиеся холдинги сеткой SELL/TP (auto-oco-holdings).

Особенности:
- Авто-расчёт размера заявки из доступного USDT (или базовой монеты)
- Поддержка шагов цены/количества по биржевым фильтрам (tickSize/stepSize/minQty/minNotional)
- Управление плотностью сетки и таймаутами TTL (near/far) — делается супервизором
- Простой статус-лог и мягкое завершение по SIGINT/SIGTERM

Патчи (2025-08-18):
- backoff+повторы на 418/429/5xx и коды 1003/-1003/-1015
- подпись приватных запросов (account/openOrders/order/myTrades)
- get_price(): фолбэки /ticker/bookTicker → /avgPrice
- защита «последнего SELL» (не превышать free после округлений/minNotional)
- аккуратный /myTrades со state в SQLite (если STATS_ENABLE=1 и задан BOT_STATS_DB)

Патчи (2025-08-21):
- Добавлены флаги --cap-floor-usdt и --min-order-usdt:
  • если свободных USDT меньше cap-floor — BUY не ставим вовсе (гейт на уровне воркера)
  • если нотационал заявки < min-order-usdt — пропускаем такой BUY
- Безопасное форматирование цены/количества согласно tickSize/stepSize (динамическая точность)

Патч (2025-08-24):
- --attach-oco-on-fill: после FILLED у BUY автоматически вешать OCO (TP/SL) SELL
- Стоп-лимит SELL выравнивается под нижнюю ступень лестницы; TP — под верхнюю ступень
- Защита от «Insufficient balance» при подвесе OCO (учитываем только свободный base)
- --stop-limit-offset-pct (учитывается при расчёте stopPrice), --check-fills-interval — период опроса статусов BUY
- Фолбэк: при ошибке OCO — одиночный TP, если --oco-fallback=prefer-tp1

Пояс-гарантии (дедуп лестницы в воркере, 2025-08-24):
- После парсинга --ladder-prices выполняется дедуп по тикам отдельно для BUY/SELL,
  чтобы исключить почти дублирующиеся уровни, если воркер запущен напрямую.

Патч (динамическое распределение CAP, 2025-08-24):
- В maybe_place_buys() CAP на заявку берётся как min(global_cap, остаток / оставшиеся_слоты)
  с динамическим пересчётом на каждом шаге.
- Для последнего слота возможность использовать «весь остаток» управляется флагом
  --use-remainder-in-last (по умолчанию ВЫКЛ). Если флаг не задан — распределение равномерное.

Патч (TP-floor, 2025-08-24):
- TP не ниже “пола” по прибыли: tp_floor_pct = max(MIN_PROFIT_OVER_AVГ, 2*BOT_FEE_PCT*1.05)
- Доп. потолок цели по ENV TP1_MAX (по умолчанию 0.040).
- Итоговый TP = min(max(верхняя ступень, fill*(1+tp_floor_pct)), fill*(1+TP1_MAX))

Патч (2025-08-25):
- Breakeven after TP1 (опционально, по символам): при частичном исполнении TP1 подтягиваем стоп в безубыток для остатка.
  Управляется флагами --breakeven-on-tp1-symbols / --breakeven-offset-pct / --breakeven-check-interval.
  По умолчанию выключено — текущая логика не меняется.

Патч (Средняя цена + Паника, 2025-08-25 поздно):
- Подсчёт средней цены текущей позиции из /myTrades (кэш ~30с).
- Запрет SELL/TP ниже средней входа, кроме режима «паника».
- Режим «паника»: триггеры на пролив (EMA20−k*ATR, или мгновенное падение от prev_close), дебаунс/кулдаун.
- Кэш индикаторов (EMA/ATR/prev_close) с TTL, чтобы не спамить /klines).

Патч (пер-символьный лок + PID в статусах, 2025-08-26):
- Эксклюзивный fcntl-лок /run/mybot/lock_{SYMBOL}.pid, чтобы не было двойных воркеров.
- PID добавлен в стартовый и периодический статус-логи.
"""
from __future__ import annotations

import os
import sys
import math
import time
import json
import hmac
import hashlib
import signal
import random
import sqlite3
import argparse
import re
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
import tools_market as TM
from order_identity import client_order_id
from order_recovery import OrderIntent, OrderJournal, TERMINAL_EXCHANGE_STATES
from exchange_math import round_step
from risk_manager import create_manual_halt
from time_safety import assess_exchange_clock
from trade_accounting import TradeExecution, UnpricedCommission, replay_average_cost
from product_version import product_label, user_agent

import requests
from urllib.parse import urlencode
# для пер-символьного лока
import fcntl  # Linux/Unix

RUN = True
LIVE_MODE = False
_ORDER_JOURNAL: Optional[OrderJournal] = None

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


def _order_journal() -> Optional[OrderJournal]:
    """Open the durable intent journal only when exchange mutations are enabled."""
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
    path = create_manual_halt(reason, metadata=metadata)
    log(f"[EXECUTION-HALT] {reason}; marker={path}")


def _http_error_code(exc: requests.HTTPError) -> Optional[int]:
    try:
        payload = exc.response.json()
        return int(payload.get("code")) if isinstance(payload, dict) else None
    except (AttributeError, TypeError, ValueError):
        return None

# ------------------- helpers: rounding & env -------------------

def _round(x: float, step: float, mode: str = "nearest") -> float:
    return float(round_step(x, step, mode))

def fmt(v, n=8):
    try:
        return f"{float(v):.{n}f}"
    except Exception:
        return str(v)

def clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))

def parse_comma_floats(s: str) -> List[float]:
    return [float(x.strip()) for x in s.split(",") if x.strip()]

def getenv_float(name, default):
    v = os.getenv(name)
    try:
        return float(v) if v is not None else default
    except Exception:
        return default

def getenv_int(name, default):
    v = os.getenv(name)
    try:
        return int(v) if v is not None else default
    except Exception:
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
    """
    Файловый лок на BOT_RUN_DIR/lock_{SYMBOL}.pid
    - эксклюзивная блокировка через fcntl.flock(LOCK_EX|LOCK_NB)
    - при успехе пишет PID в файл (для удобной диагностики)
    - при выходе — пытается удалить файл (лочение всё равно снимется на close())
    """
    def __init__(self, symbol: str):
        self.symbol = symbol
        self.path = os.path.join(bot_run_dir(), f"lock_{symbol}.pid")
        self.fd: Optional[int] = None

    def acquire(self) -> bool:
        os.makedirs(os.path.dirname(self.path) or bot_run_dir(), exist_ok=True)
        # открываем (создаём) файл и пытаемся поставить неблокирующий эксклюзивный лок
        self.fd = os.open(self.path, os.O_RDWR | os.O_CREAT, 0o644)
        try:
            fcntl.flock(self.fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            # уже залочено живым процессом
            try:
                with open(self.path, "r", encoding="utf-8") as f:
                    pid_txt = f.read().strip()
            except Exception:
                pid_txt = "?"
            log(f"[LOCK] {self.symbol} уже запущен (pid={pid_txt}). Выход.")
            return False

        # лок получен — запишем текущий PID для наглядности
        try:
            os.ftruncate(self.fd, 0)
            os.write(self.fd, f"{os.getpid()}\n".encode("utf-8"))
        except Exception:
            pass
        return True

    def release(self) -> None:
        # при закрытии дескриптора flock снимается автоматически;
        # файл можно попытаться удалить «для чистоты», но это не обязательно
        try:
            if self.fd is not None:
                os.close(self.fd)
                self.fd = None
                try:
                    os.unlink(self.path)
                except Exception:
                    pass
        except Exception:
            pass

# --- profit floor helpers ---

def _tp1_max_pct() -> float:
    # верхняя граница ближайшей цели (если 0 — без ограничителя)
    return max(0.0, getenv_float("TP1_MAX", 0.040))

def _fee_floor_pct() -> float:
    # нижний порог профита от двусторонней комиссии (с небольшим запасом)
    fee = max(0.0, getenv_float("BOT_FEE_PCT", 0.001))
    return fee * 2.0 * 1.05

def _profit_floor_pct() -> float:
    # совмещённый “пол”: не ниже MIN_PROFIT_OVER_AVГ и не ниже комиссии
    min_edge = max(0.0, getenv_float("MIN_PROFIT_OVER_AVG", 0.0))
    return max(min_edge, _fee_floor_pct())

# ------------------- HTTP / signed / backoff -------------------

def _ts_ms() -> int:
    return int(time.time() * 1000)

def _sign(qs: str) -> str:
    return hmac.new(API_SECRET.encode(), qs.encode(), hashlib.sha256).hexdigest()

def _request_with_backoff(method: str,
                          url: str,
                          *,
                          params: Dict[str, Any] | None = None,
                          data: Dict[str, Any] | None = None,
                          timeout: float = 15.0,
                          max_tries: int = 8) -> Any:
    tries = 0
    backoff = 0.5
    while True:
        tries += 1
        try:
            r = SESSION.request(method, url, params=params, data=data, timeout=timeout)
            code = None
            j = None
            try:
                j = r.json()
                if isinstance(j, dict):
                    code = j.get("code")
            except Exception:
                j = None

            if r.status_code >= 400:
                if r.status_code in (418, 429) or 500 <= r.status_code < 600 or code in (1003, -1003, -1015):
                    retry_after = r.headers.get("Retry-After")
                    if retry_after:
                        try:
                            backoff = max(backoff, float(retry_after))
                        except Exception:
                            pass
                    else:
                        backoff = min(backoff * 1.8, 20.0)
                    sleep_s = backoff + random.random() * 0.5
                    log(f"[BACKOFF] {r.status_code} code={code} → sleep {sleep_s:.2f}s URL={url}")
                    time.sleep(sleep_s)
                    if tries < max_tries:
                        continue
                r.raise_for_status()

            # 2xx но json с троттлинг-кодом
            if isinstance(j, dict) and j.get("code") in (1003, -1003, -1015):
                if tries >= max_tries:
                    raise requests.HTTPError(f"Binance throttle code {j.get('code')}: {j.get('msg')}")
                backoff = min(backoff * 1.8, 20.0)
                sleep_s = backoff + random.random() * 0.5
                log(f"[BACKOFF] json code={j.get('code')} → sleep {sleep_s:.2f}s URL={url}")
                time.sleep(sleep_s)
                continue

            try:
                return r.json()
            except ValueError:
                return r.text

        except requests.RequestException as e:
            if tries >= max_tries:
                raise
            backoff = min(backoff * 1.8, 20.0)
            sleep_s = backoff + random.random() * 0.5
            log(f"[RETRY] {e.__class__.__name__}: {e}; sleep {sleep_s:.2f}s URL={url}")
            time.sleep(sleep_s)

def _public_get(path: str, params: Dict[str, Any] | None = None, timeout: float = 15.0):
    url = BINANCE_API_BASE + path
    return _request_with_backoff("GET", url, params=params, timeout=timeout)

def _signed_request(method: str, path: str, params: Dict[str, Any] | None = None, timeout: float = 15.0):
    if method.upper() not in ("GET", "HEAD") and not LIVE_MODE:
        raise RuntimeError(f"DRY mode blocked mutating Binance request: {method.upper()} {path}")
    if not API_SECRET or not API_KEY:
        raise RuntimeError("API key/secret are required for signed endpoints.")
    p_base = dict(params or {})
    # позволим увеличить окно через ENV, дефолт побольше
    p_base.setdefault("recvWindow", getenv_int("RECV_WINDOW_MS", 15000))

    tries = 0
    backoff = 0.5
    while True:
        tries += 1
        # каждый раз новый timestamp + подпись
        p = dict(p_base)
        p["timestamp"] = _ts_ms()
        qs = urlencode(p, doseq=True)
        sig = _sign(qs)
        url = f"{BINANCE_API_BASE}{path}?{qs}&signature={sig}"

        try:
            r = SESSION.request(method, url, timeout=timeout)
            j = None
            code = None
            try:
                j = r.json()
                if isinstance(j, dict):
                    code = j.get("code")
            except Exception:
                j = None

            # http-ошибки: троттлинг/сервер/временные — с ретраем
            if r.status_code >= 400:
                if r.status_code in (418, 429) or 500 <= r.status_code < 600 or code in (1003, -1003, -1015, -1021):
                    retry_after = r.headers.get("Retry-After")
                    if retry_after:
                        try:
                            backoff = max(backoff, float(retry_after))
                        except Exception:
                            pass
                    else:
                        backoff = min(backoff * 1.8, 20.0)
                    sleep_s = backoff + random.random() * 0.5
                    log(f"[BACKOFF] {r.status_code} code={code} → sleep {sleep_s:.2f}s URL={path}")
                    time.sleep(sleep_s)
                    if tries < 8:
                        continue
                # не ретраибл — кинем исключение как есть
                r.raise_for_status()

            # 2xx, но тело с «мягким» кодом троттлинга или -1021
            if isinstance(j, dict) and j.get("code") in (1003, -1003, -1015, -1021):
                if tries >= 8:
                    raise requests.HTTPError(f"Binance code {j.get('code')}: {j.get('msg')}")
                backoff = min(backoff * 1.8, 20.0)
                sleep_s = backoff + random.random() * 0.5
                log(f"[BACKOFF] json code={j.get('code')} → sleep {sleep_s:.2f}s URL={path}")
                time.sleep(sleep_s)
                continue

            # успех
            try:
                return r.json()
            except ValueError:
                return r.text

        except requests.RequestException as e:
            if tries >= 8:
                raise
            backoff = min(backoff * 1.8, 20.0)
            sleep_s = backoff + random.random() * 0.5
            log(f"[RETRY] {e.__class__.__name__}: {e}; sleep {sleep_s:.2f}s URL={path}")
            time.sleep(sleep_s)

# ------------------- Indicators / averages / panic -------------------

# Кэш индикаторов, чтобы не спамить klines
_IND_CACHE: Dict[tuple[str, str], Dict[str, float]] = {}
_IND_TS: Dict[tuple[str, str], float] = {}

# Кэш VWAP (похожая логика, но отдельный TTL/ключи)
_VWAP_CACHE: Dict[tuple[str, str, int], Dict[str, float | None]] = {}
_VWAP_TS: Dict[tuple[str, str, int], float] = {}

def _get_klines(symbol: str, interval: str = "1m", limit: int = 120):
    # теперь пользуемся единым клиентом с нормализацией алиасов и фолбэком -1120→15m
    limit = max(20, min(1000, int(limit)))
    return TM.get_klines(symbol, interval, limit=limit)

def _ema(vals: List[float], period: int) -> float:
    if not vals:
        return 0.0
    period = max(1, int(period))
    k = 2.0 / (period + 1.0)
    e = vals[0]
    for v in vals[1:]:
        e = v * k + e * (1.0 - k)
    return e

def _atr_from_klines(kl: List[list], period: int = 14) -> float:
    if len(kl) < period + 2:
        return 0.0
    # берём закрытые свечи: исключим последнюю (возможна формирующаяся)
    highs = [float(x[2]) for x in kl[:-1]]
    lows  = [float(x[3]) for x in kl[:-1]]
    closes= [float(x[4]) for x in kl[:-1]]
    trs: List[float] = []
    prev_close = closes[0]
    for i in range(1, len(closes)):
        h = highs[i]
        l = lows[i]
        c_prev = closes[i-1]
        tr = max(h - l, abs(h - c_prev), abs(l - c_prev))
        trs.append(tr)
        prev_close = closes[i]
    if len(trs) < period:
        return 0.0
    return _ema(trs[-(period*3):], period)  # сглаживание ЭМА

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
    closes = [float(x[4]) for x in kl[:-1]]  # закрытые свечи
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
            high = float(bar[2])
            low = float(bar[3])
            close = float(bar[4])
            volume = float(bar[5])
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

# Средняя цена позиции из /myTrades (кэш)
_AVG_CACHE: Dict[str, Dict[str, float]] = {}

def avg_entry(symbol: str, cache_ttl: int = 30, lookback: int = 1000) -> Optional[float]:
    base, quote = get_symbol_assets(symbol)
    bals = get_balances()
    pos_free = float(bals.get(base, {}).get("free", 0.0))
    pos_locked = float(bals.get(base, {}).get("locked", 0.0))
    pos = pos_free + pos_locked
    if pos <= 0:
        return None

    ent = _AVG_CACHE.get(symbol)
    now_ts = time.time()
    if ent and (now_ts - ent.get("ts", 0)) < cache_ttl and ent.get("pos", 0.0) > 0:
        return float(ent.get("avg", 0.0))

    try:
        trades = _signed_request("GET", "/api/v3/myTrades", {"symbol": symbol, "limit": lookback}) or []
    except Exception:
        trades = []

    if not isinstance(trades, list) or not trades:
        return None

    # Сортируем по времени (возрастание)
    try:
        trades.sort(key=lambda t: int(t.get("time", 0)))
    except Exception:
        pass

    executions: List[TradeExecution] = []
    for t in trades:
        try:
            side = "BUY" if bool(t.get("isBuyer")) else "SELL"
            q = Decimal(str(t.get("qty") or "0"))
            p = Decimal(str(t.get("price") or "0"))
            fee = Decimal(str(t.get("commission") or "0"))
            c_asset = str(t.get("commissionAsset", "")).upper()
            fee_q, fee_status = _commission_quote_value(
                symbol, c_asset, fee, p, int(t.get("time") or 0)
            )
            executions.append(TradeExecution.create(
                symbol=symbol,
                side=side,
                price=p,
                gross_qty=q,
                commission_asset=c_asset,
                commission_amount=fee,
                commission_quote=fee_q,
                commission_value_status=fee_status,
            ))
        except (ArithmeticError, TypeError, ValueError):
            continue

    try:
        result = replay_average_cost(executions)
    except UnpricedCommission as exc:
        log(f"[AVG] {symbol} unavailable: {exc}")
        return None
    if result.qty <= 0:
        return None
    avg_px = result.avg_cost
    _AVG_CACHE[symbol] = {"ts": now_ts, "avg": float(avg_px), "pos": float(result.qty)}
    return float(avg_px)

# --- PANIC state ---

_panic: Dict[str, Dict[str, float | int | bool]] = {}

def panic_raw(now_px: float,
              ema20: float | None,
              atr: float | None,
              prev_close: float | None,
              panic_drop_pct: float,
              panic_k_atr: float) -> bool:
    cond1 = False
    cond2 = False
    if ema20 is not None and atr is not None and atr > 0:
        cond1 = now_px <= (ema20 - panic_k_atr * atr)
    if prev_close is not None and prev_close > 0:
        cond2 = (now_px / prev_close - 1.0) <= -abs(panic_drop_pct)
    return cond1 or cond2

def update_panic_state(symbol: str,
                       now_px: float,
                       ema20: float | None,
                       atr: float | None,
                       prev_close: float | None,
                       avg_entry_px: float | None,
                       panic_drop_pct: float = 0.02,
                       panic_k_atr: float = 2.0,
                       debounce_checks: int = 2,
                       cooldown_sec: int = 180) -> bool:
    s = _panic.get(symbol, {"on": False, "since": 0.0, "last_trig": 0.0, "hits": 0})
    now_ts = time.time()

    trig = panic_raw(now_px, ema20, atr, prev_close, panic_drop_pct, panic_k_atr)

    if trig:
        s["hits"] = int(s.get("hits", 0)) + 1
        s["last_trig"] = now_ts
        if (not s.get("on", False)) and s["hits"] >= debounce_checks:
            s["on"] = True
            s["since"] = now_ts
            log(f"[PANIC] {symbol} ON (now≈{fmt(now_px, 6)}, ema20≈{fmt(ema20 or 0, 6)}, ATR≈{fmt(atr or 0, 6)})")
    else:
        s["hits"] = 0

    if s.get("on", False):
        # Выйти из паники — после cooldown и при восстановлении к EMA-1*ATR или к средней
        recovered_ema = False
        recovered_avg = False
        if ema20 is not None and atr is not None and atr > 0:
            recovered_ema = now_px >= (ema20 - 1.0 * atr)
        if avg_entry_px is not None:
            recovered_avg = now_px >= avg_entry_px
        if (now_ts - float(s.get("since", 0.0)) >= cooldown_sec) and (recovered_ema or recovered_avg):
            s["on"] = False
            s["hits"] = 0
            log(f"[PANIC] {symbol} OFF (recover: ema_ok={recovered_ema}, avg_ok={recovered_avg})")

    _panic[symbol] = s  # persist
    return bool(s["on"])

# ------------------- Exchange info / filters -------------------

symbol_filters: Dict[str, Dict[str, float]] = {}
_symbol_assets_cache: Dict[str, Tuple[str, str]] = {}

def exchange_info(symbol: str):
    return _public_get("/api/v3/exchangeInfo", {"symbol": symbol})

def pull_filters(symbol: str) -> Dict[str, float]:
    global symbol_filters
    if symbol in symbol_filters:
        return symbol_filters[symbol]
    flt = {
        "tickSize": 0.01,
        "stepSize": 0.0001,
        "minQty": 0.0,
        "minNotional": 5.0,
    }
    j = exchange_info(symbol)
    try:
        for s in j["symbols"]:
            if s["symbol"] == symbol:
                for f in s["filters"]:
                    t = str(f.get("filterType", ""))

                    if t == "PRICE_FILTER":
                        flt["tickSize"] = float(f["tickSize"])

                    elif t == "LOT_SIZE":  # важный блок — MARKET_LOT_SIZE игнорируем для лимиток
                        flt["stepSize"] = float(f["stepSize"])
                        flt["minQty"]   = float(f["minQty"])

                    elif t in ("NOTIONAL", "MIN_NOTIONAL"):
                        flt["minNotional"] = float(f.get("minNotional", 5.0))
    except Exception:
        pass

    symbol_filters[symbol] = flt
    log(f"[FILTERS] {symbol} tickSize={flt['tickSize']:.8f} stepSize={flt['stepSize']:.8f} "
        f"minQty={flt['minQty']:.6f} minNotional={flt['minNotional']}")
    return flt

def _decimals_from_step(step: float) -> int:
    """
    Возвращает количество знаков после запятой для форматирования,
    исходя из шага (tick/step). Работает и для 1e-8 и для 0.01000000.
    """
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

def dedup_ladder(symbol: str, ladder_prices: List[float], now_price: float) -> List[float]:
    try:
        tick = float(symbol_filters[symbol]["tickSize"])
    except Exception:
        tick = 0.0
    if tick <= 0 or not ladder_prices:
        return ladder_prices

    seen: set[tuple[int, str]] = set()
    dedup: List[float] = []
    for raw_p in ladder_prices:
        try:
            pr = round_price(symbol, float(raw_p))
        except Exception:
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
    if shift_pct <= 0:
        return ladder_prices
    adj: List[float] = []
    shift = clamp(float(shift_pct), 0.0, 0.95)
    factor = 1.0 - shift
    for price in ladder_prices:
        if price < now_price:
            new_price = max(0.0, price * factor)
            adj.append(new_price)
        else:
            adj.append(price)
    return adj

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
    """
    /ticker/price → /ticker/bookTicker(mid) → /avgPrice
    """
    try:
        j = _public_get("/api/v3/ticker/price", {"symbol": symbol})
        if isinstance(j, dict) and "price" in j:
            return float(j["price"])
        # крайне редко приходит массив
        return float(j[0]["price"])
    except Exception as e1:
        log(f"[ERR] {symbol}: {e1} at /ticker/price, trying /ticker/bookTicker")
        try:
            j = _public_get("/api/v3/ticker/bookTicker", {"symbol": symbol})
            bid = float(j["bidPrice"]); ask = float(j["askPrice"])
            return (bid + ask) / 2.0 if ask > 0 else bid
        except Exception as e2:
            log(f"[ERR] {symbol}: {e2} at /ticker/bookTicker, trying /avgPrice")
            j = _public_get("/api/v3/avgPrice", {"symbol": symbol})
            return float(j["price"])

def get_balances() -> Dict[str, Dict[str, float]]:
    j = _signed_request("GET", "/api/v3/account")
    bals: Dict[str, Dict[str, float]] = {}
    for b in j.get("balances", []):
        asset = b.get("asset")
        free = float(b.get("free", 0))
        locked = float(b.get("locked", 0))
        bals[asset] = {"free": free, "locked": locked}
    return bals

def get_symbol_assets(symbol: str) -> Tuple[str, str]:
    """
    Надёжно определяем base/quote из /exchangeInfo, с кэшем.
    Фолбэк — прежняя эвристика, если биржа не ответит.
    """
    sym = symbol.upper()
    if sym in _symbol_assets_cache:
        return _symbol_assets_cache[sym]
    try:
        j = exchange_info(sym)
        if isinstance(j, dict) and "symbols" in j and j["symbols"]:
            s = j["symbols"][0]
            base = str(s.get("baseAsset", "")).upper()
            quote = str(s.get("quoteAsset", "")).upper()
            if base and quote:
                _symbol_assets_cache[sym] = (base, quote)
                return base, quote
    except Exception:
        pass
    # fallback — только если info не пришёл
    if sym.endswith("USDT"):
        return sym[:-4], "USDT"
    return sym[:-4], sym[-4:]

def list_open_orders(symbol: str) -> List[Dict[str, Any]]:
    try:
        return _signed_request("GET", "/api/v3/openOrders", {"symbol": symbol}) or []
    except Exception as e:
        log(f"[ERR] list_open_orders: {e}")
        return []

def cancel_order(symbol: str, oid: int):
    try:
        _signed_request("DELETE", "/api/v3/order", {"symbol": symbol, "orderId": oid})
        log(f"[CANCEL] {symbol} order {oid}")
    except Exception as e:
        log(f"[ERR] cancel_order: {e}")

def cancel_oco(symbol: str, order_list_id: int) -> None:
    try:
        _signed_request("DELETE", "/api/v3/orderList", {"symbol": symbol, "orderListId": int(order_list_id)})
        log(f"[CANCEL-OCO] {symbol} orderListId={order_list_id}")
    except Exception as e:
        log(f"[ERR] cancel_oco: {e}")

def get_order_by_client_id(symbol: str, client_id: str) -> Dict[str, Any] | None:
    try:
        return _signed_request(
            "GET",
            "/api/v3/order",
            {"symbol": symbol, "origClientOrderId": client_id},
        )
    except requests.HTTPError as exc:
        if _http_error_code(exc) == -2013:
            return None
        raise


def get_order_list_by_client_id(client_id: str) -> Dict[str, Any] | None:
    try:
        return _signed_request(
            "GET",
            "/api/v3/orderList",
            {"origClientOrderId": client_id},
        )
    except requests.HTTPError as exc:
        if _http_error_code(exc) in (-2013, -2011):
            return None
        raise


def verify_oco_legs(symbol: str, order_list: Dict[str, Any]) -> List[Dict[str, Any]]:
    refs = order_list.get("orders") or []
    if len(refs) != 2:
        raise RuntimeError("OCO verification did not return exactly two legs")
    legs: List[Dict[str, Any]] = []
    for ref in refs:
        if ref.get("orderId") is None:
            raise RuntimeError("OCO leg has no orderId")
        payload = _signed_request(
            "GET",
            "/api/v3/order",
            {"symbol": symbol, "orderId": int(ref["orderId"])},
        )
        if not isinstance(payload, dict):
            raise RuntimeError("OCO leg query returned an invalid payload")
        legs.append(payload)
    if any(str(leg.get("side") or "").upper() != "SELL" for leg in legs):
        raise RuntimeError("OCO contains a non-SELL leg")
    leg_types = {str(leg.get("type") or "").upper() for leg in legs}
    if not ({"LIMIT_MAKER", "LIMIT"} & leg_types) or not (
        {"STOP_LOSS_LIMIT", "STOP_LOSS"} & leg_types
    ):
        raise RuntimeError(f"OCO leg types are invalid: {sorted(leg_types)}")
    return legs


def _record_order_payload(payload: Dict[str, Any] | None) -> Optional[OrderIntent]:
    if not payload:
        return None
    journal = _order_journal()
    if journal is None:
        return None
    client_id = str(payload.get("clientOrderId") or payload.get("origClientOrderId") or "")
    intent = journal.get(client_id) if client_id else None
    if intent is None and payload.get("orderId") is not None:
        intent = journal.get_by_exchange_order_id(int(payload["orderId"]))
    if intent is None:
        return None
    return journal.record_exchange_order(intent.client_order_id, payload)


def recover_pending_buy_order_ids(symbol: str) -> List[int]:
    """Reconcile every unfinished BUY before allowing new placement after restart."""
    journal = _order_journal()
    if journal is None:
        return []
    recovered: List[int] = []
    for intent in journal.unresolved_buys(symbol):
        try:
            payload = get_order_by_client_id(symbol, intent.client_order_id)
        except requests.RequestException as exc:
            journal.mark_unknown(intent.client_order_id, exc)
            reason = f"cannot reconcile BUY {intent.client_order_id} after restart: {exc}"
            _trip_execution_halt(reason, symbol=symbol, client_order_id=intent.client_order_id)
            raise RuntimeError(reason) from exc
        if payload is None:
            if intent.state not in ("PREPARED", "UNKNOWN"):
                reason = (
                    f"exchange lost unresolved BUY {intent.client_order_id} "
                    f"recorded as {intent.state}"
                )
                _trip_execution_halt(reason, symbol=symbol, client_order_id=intent.client_order_id)
                raise RuntimeError(reason)
            log(f"[RECOVERY] {symbol} {intent.client_order_id} not found; safe to retry same ID")
            continue
        updated = journal.record_exchange_order(intent.client_order_id, payload)
        if updated.state in ("SUBMITTED", "PARTIALLY_FILLED", "FILLED", "PROTECTION_PENDING"):
            if updated.exchange_order_id is None:
                reason = f"reconciled BUY {intent.client_order_id} has no exchange orderId"
                _trip_execution_halt(reason, symbol=symbol, client_order_id=intent.client_order_id)
                raise RuntimeError(reason)
            recovered.append(updated.exchange_order_id)
            log(
                f"[RECOVERY] {symbol} client={intent.client_order_id} "
                f"order={updated.exchange_order_id} state={updated.state}"
            )
    return list(dict.fromkeys(recovered))


def recover_existing_protection(parent_client_order_id: str) -> bool:
    """Resolve a crash after protection POST but before the local ACK was persisted."""
    journal = _order_journal()
    if journal is None:
        return False
    protection = journal.protection_for_parent(parent_client_order_id)
    if protection is None:
        return False
    if protection.state == "PROTECTED":
        return True
    if protection.order_type == "OCO":
        payload = get_order_list_by_client_id(protection.client_order_id)
        if not isinstance(payload, dict) or payload.get("listStatusType") not in ("EXEC_STARTED", "ALL_DONE"):
            return False
        order_list_id = payload.get("orderListId")
        try:
            verify_oco_legs(protection.symbol, payload)
        except (requests.RequestException, RuntimeError):
            if order_list_id is not None:
                cancel_oco(protection.symbol, int(order_list_id))
            return False
        journal.mark_protected(
            parent_client_order_id=parent_client_order_id,
            protection_client_order_id=protection.client_order_id,
            order_list_id=int(order_list_id) if order_list_id is not None else None,
        )
        return True
    payload = get_order_by_client_id(protection.symbol, protection.client_order_id)
    if not isinstance(payload, dict):
        return False
    updated = journal.record_exchange_order(protection.client_order_id, payload)
    if updated.state in ("SUBMITTED", "PARTIALLY_FILLED", "FILLED"):
        journal.mark_protected(
            parent_client_order_id=parent_client_order_id,
            protection_client_order_id=protection.client_order_id,
            exchange_order_id=updated.exchange_order_id,
        )
        return True
    return False


def get_order(symbol: str, order_id: int) -> Dict[str, Any] | None:
    try:
        payload = _signed_request("GET", "/api/v3/order", {"symbol": symbol, "orderId": order_id})
        _record_order_payload(payload)
        return payload
    except Exception as e:
        log(f"[ERR] get_order: {e}")
        return None

def place_limit_order(side: str,
                      symbol: str,
                      qty: float,
                      price: float,
                      *,
                      maker: bool = False,
                      purpose: str = "ladder",
                      parent_client_order_id: Optional[str] = None) -> Dict[str, Any] | None:
    if not LIVE_MODE:
        log(f"[DRY] skip LIMIT {symbol} {side.upper()} {qty:.8f} @ {price:.8f}")
        return None
    # округлим к шагам
    pull_filters(symbol)
    price = round_price(symbol, price)
    qty = round_qty(symbol, qty)

    # уважим minQty/minNotional
    if qty < min_qty(symbol, 0):
        return None
    if qty * price < min_notional(symbol, price):
        need = min_notional(symbol, price) / price
        need = round_qty(symbol, max(need, min_qty(symbol, 0)))
        if need <= 0:
            return None
        qty = need

    qty_s = fmt_qty_sym(symbol, qty)
    price_s = fmt_price_sym(symbol, price)
    journal = _order_journal()
    active = journal.find_active(
        symbol=symbol,
        side=side,
        purpose=purpose,
        quantity=qty_s,
        price=price_s,
    ) if journal is not None else None
    if active is not None:
        try:
            existing = get_order_by_client_id(symbol, active.client_order_id)
        except requests.RequestException as exc:
            journal.mark_unknown(active.client_order_id, exc)
            raise
        if existing is not None:
            updated = journal.record_exchange_order(active.client_order_id, existing)
            if updated.state not in TERMINAL_EXCHANGE_STATES:
                log(
                    f"[IDEMPOTENT] reuse {symbol} {side} client={active.client_order_id} "
                    f"order={updated.exchange_order_id} state={updated.state}"
                )
                return existing
            active = None

    generated_id = client_order_id(symbol, side, purpose, price_s, qty_s)
    if journal is not None and journal.get(generated_id) is not None:
        generated_id = client_order_id(
            symbol,
            side,
            f"{purpose}-{time.time_ns()}",
            price_s,
            qty_s,
            bucket_seconds=1,
        )
    order_client_id = active.client_order_id if active is not None else generated_id
    if journal is not None:
        journal.prepare(
            client_order_id=order_client_id,
            symbol=symbol,
            side=side,
            purpose=purpose,
            order_type=("LIMIT_MAKER" if maker else "LIMIT"),
            quantity=qty_s,
            price=price_s,
            parent_client_order_id=parent_client_order_id,
        )

    params = {
        "symbol": symbol,
        "side": side,
        "type": ("LIMIT_MAKER" if maker else "LIMIT"),
        "quantity": qty_s,
        "price": price_s,
        "newOrderRespType": "RESULT",
        "newClientOrderId": order_client_id,
    }
    if not maker:
        params["timeInForce"] = "GTC"

    try:
        j = _signed_request("POST", "/api/v3/order", params)
        if isinstance(j, dict):
            j.setdefault("clientOrderId", order_client_id)
            if journal is not None:
                journal.record_exchange_order(order_client_id, j)
        oid = j.get("orderId")
        log(f"[PLACE] {symbol} {side} {qty_s} @ {price_s} client={order_client_id} order={oid}")
        return j
    except requests.RequestException as e:
        if journal is not None:
            journal.mark_unknown(order_client_id, e)
            try:
                reconciled = get_order_by_client_id(symbol, order_client_id)
            except requests.RequestException:
                reconciled = None
            if reconciled is not None:
                journal.record_exchange_order(order_client_id, reconciled)
                log(f"[IDEMPOTENT] recovered uncertain POST client={order_client_id}")
                return reconciled
            _trip_execution_halt(
                f"uncertain order submission has no exchange confirmation: {order_client_id}",
                symbol=symbol,
                side=side,
                client_order_id=order_client_id,
            )
        try:
            err = e.response.json()
            log(f"[ERR] place_limit_order: HTTP {e.response.status_code} {json.dumps(err)}")
        except Exception:
            log(f"[ERR] place_limit_order: {e}")
        raise

def place_oco_sell(symbol: str,
                   qty: float,
                   tp_limit_price: float,
                   sl_stop_price: float,
                   sl_limit_price: float,
                   *,
                   parent_client_order_id: Optional[str] = None) -> Dict[str, Any] | None:
    """
    Создаёт OCO SELL: LIMIT по tp_limit_price и STOP_LOSS_LIMIT по sl_stop_price/sl_limit_price.
    Все цены и qty должны быть уже округлены и проверены на minNotional.
    """
    if not LIVE_MODE:
        log(f"[DRY] skip OCO {symbol} SELL {qty:.8f}")
        return None
    pull_filters(symbol)
    q  = fmt_qty_sym(symbol, round_qty(symbol, qty))
    tp = fmt_price_sym(symbol, round_price(symbol, tp_limit_price))
    sp = fmt_price_sym(symbol, round_price(symbol, sl_stop_price))
    sl = fmt_price_sym(symbol, round_price(symbol, sl_limit_price))

    journal = _order_journal()
    purpose = f"oco:{parent_client_order_id[:12]}" if parent_client_order_id else "oco"
    active = journal.find_active(
        symbol=symbol,
        side="SELL",
        purpose=purpose,
        quantity=q,
        price=tp,
    ) if journal is not None else None
    list_client_id = (
        active.client_order_id
        if active is not None
        else client_order_id(symbol, "SELL", purpose, tp, q)
    )
    if active is not None:
        existing = get_order_list_by_client_id(list_client_id)
        if isinstance(existing, dict) and existing.get("listStatusType") in ("EXEC_STARTED", "ALL_DONE"):
            order_list_id = existing.get("orderListId")
            try:
                verify_oco_legs(symbol, existing)
            except (requests.RequestException, RuntimeError):
                if order_list_id is not None:
                    cancel_oco(symbol, int(order_list_id))
                raise
            if journal is not None:
                journal.record_order_list(list_client_id, existing)
                if parent_client_order_id:
                    journal.mark_protected(
                        parent_client_order_id=parent_client_order_id,
                        protection_client_order_id=list_client_id,
                        order_list_id=int(order_list_id) if order_list_id is not None else None,
                    )
            log(f"[IDEMPOTENT] reuse OCO {symbol} client={list_client_id} list={order_list_id}")
            return existing
    if active is None and journal is not None and journal.get(list_client_id) is not None:
        list_client_id = client_order_id(
            symbol,
            "SELL",
            f"{purpose}-{time.time_ns()}",
            tp,
            q,
            bucket_seconds=1,
        )
    if journal is not None:
        journal.prepare(
            client_order_id=list_client_id,
            symbol=symbol,
            side="SELL",
            purpose=purpose,
            order_type="OCO",
            quantity=q,
            price=tp,
            parent_client_order_id=parent_client_order_id,
            metadata={"stopPrice": sp, "stopLimitPrice": sl},
        )
        if parent_client_order_id:
            journal.mark_protection_pending(parent_client_order_id)

    params = {
        "symbol": symbol,
        "side": "SELL",
        "quantity": q,
        "aboveType": "LIMIT_MAKER",
        "abovePrice": tp,
        "belowType": "STOP_LOSS_LIMIT",
        "belowStopPrice": sp,
        "belowPrice": sl,
        "belowTimeInForce": "GTC",
        "newOrderRespType": "RESULT",
        "listClientOrderId": list_client_id,
        "aboveClientOrderId": client_order_id(symbol, "SELL", "otp", tp, q),
        "belowClientOrderId": client_order_id(symbol, "SELL", "osl", sp, q),
    }
    try:
        j = _signed_request("POST", "/api/v3/orderList/oco", params)
        order_list_id = j.get("orderListId") if isinstance(j, dict) else None
        if order_list_id is None:
            raise RuntimeError("OCO response has no orderListId")
        verified = _signed_request(
            "GET", "/api/v3/orderList", {"orderListId": int(order_list_id)}
        )
        if not isinstance(verified, dict) or verified.get("listStatusType") not in ("EXEC_STARTED", "ALL_DONE"):
            raise RuntimeError(f"OCO verification failed: {verified}")
        try:
            verify_oco_legs(symbol, verified)
        except (requests.RequestException, RuntimeError):
            try:
                _signed_request(
                    "DELETE",
                    "/api/v3/orderList",
                    {"symbol": symbol, "orderListId": int(order_list_id)},
                )
            except requests.RequestException:
                pass
            raise
        if isinstance(j, dict):
            j.setdefault("listClientOrderId", list_client_id)
        if journal is not None:
            journal.record_order_list(list_client_id, verified)
            if parent_client_order_id:
                journal.mark_protected(
                    parent_client_order_id=parent_client_order_id,
                    protection_client_order_id=list_client_id,
                    order_list_id=int(order_list_id),
                )
        log(f"[ATTACH-OCO] {symbol} SELL {q} | TP={tp} / SL stop={sp} limit={sl} verified")
        return j
    except (requests.RequestException, RuntimeError) as e:
        if journal is not None:
            journal.mark_unknown(list_client_id, e)
            try:
                reconciled = get_order_list_by_client_id(list_client_id)
            except requests.RequestException:
                reconciled = None
            if isinstance(reconciled, dict) and reconciled.get("listStatusType") in ("EXEC_STARTED", "ALL_DONE"):
                order_list_id = reconciled.get("orderListId")
                try:
                    verify_oco_legs(symbol, reconciled)
                except (requests.RequestException, RuntimeError) as verify_exc:
                    log(f"[ERR] recovered OCO leg verification failed: {verify_exc}")
                    return None
                journal.record_order_list(list_client_id, reconciled)
                if parent_client_order_id:
                    journal.mark_protected(
                        parent_client_order_id=parent_client_order_id,
                        protection_client_order_id=list_client_id,
                        order_list_id=int(order_list_id) if order_list_id is not None else None,
                    )
                log(f"[IDEMPOTENT] recovered uncertain OCO POST client={list_client_id}")
                return reconciled
        try:
            err = e.response.json()
            log(f"[ERR] place_oco_sell: HTTP {e.response.status_code} {json.dumps(err)}")
        except (AttributeError, ValueError):
            log(f"[ERR] place_oco_sell: {e}")
        return None

# ------------------- STATS (optional) -------------------

STATS_ENABLE = getenv_int("STATS_ENABLE", 0) == 1
STATS_DB = getenv_str("BOT_STATS_DB", "")

TOOLS_STATS = None
STATS_CON: Optional[sqlite3.Connection] = None
_COMMISSION_QUOTE_CACHE: Dict[Tuple[str, str, int], Decimal] = {}

def _stats_init_if_needed():
    global TOOLS_STATS, STATS_CON
    if not STATS_ENABLE or not STATS_DB:
        return
    if TOOLS_STATS is None:
        try:
            import tools_stats as TOOLS_STATS  # type: ignore
        except Exception as e:
            log(f"[STATS] import error: {e}")
            return
    if STATS_CON is None:
        try:
            os.makedirs(os.path.dirname(STATS_DB) or ".", exist_ok=True)
            STATS_CON = TOOLS_STATS.init_db(STATS_DB)
        except Exception as e:
            log(f"[STATS] open error: {e}")
            STATS_CON = None


def _commission_quote_value(
    symbol: str,
    commission_asset: str,
    commission_amount: Decimal,
    trade_price: Decimal,
    trade_time_ms: int,
) -> Tuple[Optional[Decimal], str]:
    """Value a Binance commission in the symbol quote asset at trade time."""
    base, quote = get_symbol_assets(symbol)
    asset = commission_asset.strip().upper()
    if commission_amount <= 0:
        return Decimal("0"), "none"
    if asset == quote.upper():
        return commission_amount, "exact"
    if asset == base.upper():
        return commission_amount * trade_price, "exact"

    minute_ms = int(trade_time_ms // 60_000 * 60_000)
    key = (asset, quote.upper(), minute_ms)
    cached = _COMMISSION_QUOTE_CACHE.get(key)
    if cached is not None:
        return commission_amount * cached, "converted"

    pairs = ((asset + quote.upper(), False), (quote.upper() + asset, True))
    for pair, inverse in pairs:
        try:
            candles = _public_get(
                "/api/v3/klines",
                {"symbol": pair, "interval": "1m", "startTime": minute_ms, "limit": 1},
            )
            if not isinstance(candles, list) or not candles:
                continue
            close = Decimal(str(candles[0][4]))
            if close <= 0:
                continue
            conversion = Decimal("1") / close if inverse else close
            _COMMISSION_QUOTE_CACHE[key] = conversion
            return commission_amount * conversion, "converted"
        except (ArithmeticError, IndexError, TypeError, ValueError, requests.RequestException):
            continue
    return None, "unpriced"

def _stats_poll_mytrades_once(symbol: str):
    if not (STATS_ENABLE and STATS_DB):
        return
    _stats_init_if_needed()
    if STATS_CON is None or TOOLS_STATS is None:
        return
    base, quote = get_symbol_assets(symbol)
    last_id = None
    try:
        last_id = TOOLS_STATS.get_last_trade_id(STATS_CON, symbol)
    except Exception as e:
        log(f"[STATS] get_last_trade_id error: {e}")

    # аккуратно тянем от last_id (если None — Binance вернёт последние)
    params = {"symbol": symbol, "limit": 1000}
    if last_id is not None:
        params["fromId"] = int(last_id) + 1

    try:
        trades = _signed_request("GET", "/api/v3/myTrades", params) or []
    except Exception as e:
        log(f"[STATS] myTrades error: {e}")
        return

    if not isinstance(trades, list) or not trades:
        return

    max_id = last_id or -1
    for t in trades:
        try:
            tid = int(t.get("id"))
            side = "BUY" if t.get("isBuyer") else "SELL"
            price = Decimal(str(t.get("price")))
            qty = Decimal(str(t.get("qty")))
            ts = int(t.get("time"))
            commission = Decimal(str(t.get("commission", "0") or "0"))
            c_asset = str(t.get("commissionAsset", "")).upper()
            fee_q, fee_status = _commission_quote_value(
                symbol, c_asset, commission, price, ts
            )
            # применим в БД
            try:
                TOOLS_STATS.apply_trade(
                    STATS_CON,
                    symbol,
                    side,
                    price,
                    qty,
                    fee_quote=fee_q or Decimal("0"),
                    ts=ts,
                    trade_id=tid,
                    gross_qty=qty,
                    commission_asset=c_asset,
                    commission_amount=commission,
                    commission_quote=fee_q,
                    commission_value_status=fee_status,
                )
            except sqlite3.OperationalError as dberr:
                if "locked" in str(dberr).lower():
                    log("[STATS] skip: database is locked")
                    break
                else:
                    log(f"[STATS] apply_trade error: {dberr}")
                    continue
            if fee_status == "unpriced":
                log(
                    f"[STATS] {symbol} trade_id={tid}: {c_asset or 'unknown'} "
                    "commission is unpriced; importer will retry before advancing"
                )
                break
            # обновим max id
            if tid > (max_id or -1):
                max_id = tid
        except Exception as e:
            log(f"[STATS] parse trade error: {e}")

    # сохраняем новый last_id
    if max_id is not None and max_id != (last_id or -1):
        try:
            TOOLS_STATS.set_last_trade_id(STATS_CON, symbol, int(max_id))
        except Exception as e:
            log(f"[STATS] set_last_trade_id error: {e}")

# ------------------- OCO price picker (ladder-aligned + TP-floor) -------------------

def _pick_ladder_aligned_oco_prices(symbol: str,
                                    ladder_prices: List[float],
                                    fill_price: float,
                                    stop_limit_offset_pct: float) -> tuple[float, float, float]:
    """
    Возвращает (tp_limit_price, sl_stop_price, sl_limit_price).

    - TP: не ниже “пола” (учёт комиссии/edge) и не выше cap (TP1_MAX), при этом
          не ниже ближайшей верхней ступени лестницы.
          TP = min(max(верхняя ступень, fill*(1+tp_floor_pct)), fill*(1+TP1_MAX))
    - SL limit: ближайшая нижняя ступень
    - SL stop: тик/offset выше SL limit (для SELL SL: stopPrice > stopLimitPrice)
    """
    pull_filters(symbol)
    tick = symbol_filters[symbol]["tickSize"]
    eps_mult = max(1.0, price_eps_mult())  # из ENV (PRICE_EPS_MULT)

    # Разделяем лестницу вокруг fill
    lower = [p for p in ladder_prices if p < fill_price]
    upper = [p for p in ladder_prices if p > fill_price]

    # Базовые fallback'и на случай отсутствия ступеней
    ladder_tp = upper[0] if upper else round_price(symbol, fill_price * 1.01)
    sl_limit = lower[-1] if lower else round_price(symbol, fill_price * 0.99)

    # Пол по прибыли и потолок
    floor_pct = _profit_floor_pct()
    cap_pct = _tp1_max_pct()

    floor_price = round_price(symbol, fill_price * (1.0 + max(0.0, floor_pct)))
    cap_price = round_price(symbol, fill_price * (1.0 + max(0.0, cap_pct))) if cap_pct > 0 else float("inf")

    # Итоговый TP: не ниже пола/лестницы, но ограничен cap
    tp_limit = max(ladder_tp, floor_price)
    if tp_limit > cap_price:
        tp_limit = cap_price

    # stopPrice — чуть выше, чем sl_limit (для SELL SL)
    sl_stop = sl_limit + max(tick * eps_mult, fill_price * max(0.0, float(stop_limit_offset_pct)))
    sl_stop = round_price(symbol, sl_stop)

    dbg("[TP-PICK] %s fill=%s ladder_tp=%s floor=%s cap=%s -> TP=%s; SLlim=%s, SLstop=%s" % (
        symbol,
        fmt_price_sym(symbol, fill_price),
        fmt_price_sym(symbol, ladder_tp),
        fmt_price_sym(symbol, floor_price),
        ("∞" if cap_price == float("inf") else fmt_price_sym(symbol, cap_price)),
        fmt_price_sym(symbol, tp_limit),
        fmt_price_sym(symbol, sl_limit),
        fmt_price_sym(symbol, sl_stop),
    ))

    return tp_limit, sl_stop, sl_limit

# ------------------- Core logic: BUY / SELL -------------------

def maybe_place_buys(symbol: str,
                     ladder_prices: List[float],
                     cap_per_order_usdt: float,
                     *,
                     min_order_usdt: Optional[float] = None,
                     cap_floor_usdt: Optional[float] = None,
                     target_buy_per_symbol: Optional[int] = None,
                     enforce_limit: bool = False,
                     use_remainder_in_last: bool = False,
                     buy_limit_maker: bool = False) -> List[int]:
    """
    Размещает BUY ниже текущей цены.

    Доп. гейты:
      - если free USDT < cap_floor_usdt → вообще не ставим BUY
      - если notional заявки < min-order-usdt → пропускаем уровень
      - если enforce_limit=True → не превышаем target_buy_per_symbol активных BUY ниже рынка
        и не дублируем уже стоящие цены (по округлению к tickSize/PRICE_ROUND_MODE).

    Динамическое распределение остатка:
      local_cap = min(cap_per_order_usdt, usdt_free / max(1, remaining_slots)).
      Если use_remainder_in_last=True, то для последнего уровня local_cap = usdt_free,
      иначе — равномерный cap до конца без «съедания» всей кассы.
    Возвращает список orderId успешно размещённых BUY.
    """
    base, quote = get_symbol_assets(symbol)
    bals = get_balances()
    reserve = max(0.0, getenv_float("RISK_RESERVE_USDT", 0.0))
    usdt_free = max(0.0, float(bals.get("USDT", {}).get("free", 0.0)) - reserve)

    # Гейт по порогу свободного USDT
    if cap_floor_usdt is not None and usdt_free < float(cap_floor_usdt):
        log(f"[CAP-FLOOR] free≈{usdt_free:.2f} < {float(cap_floor_usdt):.2f}; skip BUY this cycle")
        return []

    if usdt_free <= 0:
        return []

    pull_filters(symbol)
    placed_ids: List[int] = []
    now = get_price(symbol)

    # Подготовка лимита и анти-дубликатов
    allowed_new: Optional[int] = None
    existing_buy_prices: set[float] = set()
    if enforce_limit and (target_buy_per_symbol is not None):
        try:
            open_orders = list_open_orders(symbol) or []
        except Exception:
            open_orders = []
        for o in open_orders:
            try:
                if str(o.get("side", "")).upper() != "BUY":
                    continue
                pr = float(o.get("price") or 0.0)
                if pr <= 0 or pr >= now:
                    continue
                existing_buy_prices.add(round_price(symbol, pr))
            except Exception:
                pass
        existing_cnt = len(existing_buy_prices)
        allowed_new = max(0, int(target_buy_per_symbol) - existing_cnt)
        log(f"[TARGET-LIMIT] {symbol} existing_buy={existing_cnt} target={int(target_buy_per_symbol)} → allow_new={allowed_new}")
        if allowed_new <= 0:
            return []

    # Сформируем список КАНДИДАТОВ: ниже рынка, без дублей по цене, ограничим по allow_new
    candidates: List[float] = []
    for p in ladder_prices:
        if p <= 0 or p >= now:
            continue
        p_rounded = round_price(symbol, p)
        if p_rounded in existing_buy_prices:
            continue
        candidates.append(p)

    # Обрежем по разрешенному количеству новых
    if enforce_limit and allowed_new is not None and len(candidates) > allowed_new:
        candidates = candidates[:allowed_new]

    total_slots = len(candidates)
    if total_slots <= 0:
        now = get_price(symbol)
        log(f"[BUY-NONE] {symbol} нет уровней ниже рынка (now≈{fmt_price_sym(symbol, now)}). "
            f"Проверь --ladder-prices и режим reduce-only.")
        return []

    # Основной цикл по кандидатам
    for idx, p in enumerate(candidates, start=1):
        if not RUN:
            log(f"[STOP] {symbol} BUY placement interrupted before slot {idx}/{total_slots}")
            break
        if usdt_free <= 0:
            break
        # Цена заявки с учётом тиковой сетки
        pr = round_price(symbol, p)

        remaining_slots = max(1, total_slots - idx + 1)

        # Динамический CAP для текущего слота
        local_cap = min(cap_per_order_usdt, usdt_free / remaining_slots)
        # Для последнего уровня — использовать весь остаток ТОЛЬКО если явно разрешено
        if use_remainder_in_last and (idx == total_slots):
            local_cap = usdt_free

        dbg(f"[DYN-CAP] {symbol} slot {idx}/{total_slots} p≈{fmt_price_sym(symbol, p)} "
            f"local_cap≈{local_cap:.2f} free≈{usdt_free:.2f}")

        # Базовый размер от локального CAP (ВАЖНО: по округлённой цене pr)
        qty = local_cap / pr
        qty = round_qty(symbol, qty)
        if qty < min_qty(symbol, 0):
            qty = min_qty(symbol, 0)

        # Доводим до биржевого minNotional (вся математика по pr)
        if qty * pr < min_notional(symbol, pr):
            need = min_notional(symbol, pr) / pr
            need = round_qty(symbol, max(need, min_qty(symbol, 0)))

            # Не выходим за local_cap (кроме разрешённого последнего слота)
            cap_here = (usdt_free if (use_remainder_in_last and idx == total_slots) else local_cap)
            if need * pr <= cap_here:
                qty = need
            else:
                continue  # не набирается биржевой минимум — пропускаем уровень

        # пересчёт стоимости и финальные гейты (всё по pr)
        cost = qty * pr

        # Защитимся от перерасхода из-за округления
        if cost > usdt_free:
            qty = round_qty(symbol, max(0.0, usdt_free / pr))
            cost = qty * pr
            if qty <= 0:
                continue

        # Пользовательский минимум на заявку (если задан)
        if (min_order_usdt is not None) and (cost < float(min_order_usdt)):
            log(f"[MIN-ORDER] skip BUY {fmt_qty_sym(symbol, qty)} @ {fmt_price_sym(symbol, pr)} "
                f"(≈{cost:.2f} USDT < {float(min_order_usdt):.2f})")
            continue

        try:
            if not RUN:
                log(f"[STOP] {symbol} BUY placement interrupted before exchange POST")
                break
            maker_flag = (
                buy_limit_maker or
                os.getenv("BUY_LIMIT_MAKER", "").lower() in ("1", "true", "yes")
            )
            # ВАЖНО: ставим по округлённой цене pr
            j = place_limit_order("BUY", symbol, qty, pr, maker=maker_flag)
            if j:
                oid = int(j.get("orderId"))
                placed_ids.append(oid)
                # вычитаем из free по pr
                usdt_free = max(0.0, usdt_free - qty * pr)
                # антидубликат — храним уже округлённую цену
                existing_buy_prices.add(pr)
        except Exception:
            pass

    return placed_ids

def maybe_place_sells_from_holdings(
    symbol: str,
    ladder_prices: List[float],
    max_oco_per_symbol: Optional[int] = None,
    *,
    enforce_limit: bool = False,
    avg_entry_px: Optional[float] = None,
    panic_active: bool = False,
    sell_limit_maker: bool = False,
    panic_sell_floor_pct: Optional[float] = None,
) -> int:
    """
    Раскидывает свободный base-холдинг SELL-лимитками по верхним уровням.

    Если enforce_limit=True:
      - не дублируем цены SELL, уже стоящие в открытых ордерах (с округлением к tickSize/PRICE_ROUND_MODE)
      - общее число новых SELL не превысит max_oco_per_symbol с учётом уже стоящих SELL

    Защита: не ставить SELL ниже средней цены входа (avg_entry_px), если паника не активна.
    При панике можно ограничить скидку от средней через panic_sell_floor_pct.
    """
    base, quote = get_symbol_assets(symbol)
    bals = get_balances()
    base_free = float(bals.get(base, {}).get("free", 0.0))
    if base_free <= 0:
        dbg(f"[HOLD-SELL] {symbol} no free base (free={fmt_qty_sym(symbol, base_free)})")
        return 0

    pull_filters(symbol)

    now = get_price(symbol)
    upper_all = [p for p in ladder_prices if p > now]
    if not upper_all:
        dbg(f"[HOLD-SELL] {symbol} no upper ladder above market (now≈{fmt_price_sym(symbol, now)})")
        return 0

    # Соберём уже стоящие SELL (выше рынка) и посчитаем разрешённое число новых
    existing_sell_prices: set[float] = set()
    allowed_new: Optional[int] = None
    if enforce_limit and (max_oco_per_symbol is not None):
        try:
            oo = list_open_orders(symbol) or []
        except Exception:
            oo = []
        for o in oo:
            try:
                if str(o.get("side", "")).upper() != "SELL":
                    continue
                typ = str(o.get("type", "")).upper()
                if typ not in ("LIMIT", "LIMIT_MAKER", "STOP_LOSS_LIMIT", "TAKE_PROFIT_LIMIT"):
                    continue
                pr = float(o.get("price") or 0.0)
                if pr <= now or pr <= 0:
                    continue
                existing_sell_prices.add(round_price(symbol, pr))
            except Exception:
                pass
        existing_cnt = len(existing_sell_prices)
        allowed_new = max(0, int(max_oco_per_symbol) - existing_cnt)
        log(f"[SELL-LIMIT] {symbol} existing_sell={existing_cnt} max_oco={int(max_oco_per_symbol)} → allow_new={allowed_new}")
        if allowed_new <= 0:
            return 0

    # Уберём дубликаты цен и обрежем количество новых уровней (по существующим ордерам)
    upper: List[float] = []
    for p in upper_all:
        pr = round_price(symbol, p)
        if enforce_limit and pr in existing_sell_prices:
            continue
        upper.append(p)

    if enforce_limit and allowed_new is not None:
        upper = upper[:allowed_new]

    if (not enforce_limit) and (max_oco_per_symbol is not None) and len(upper) > max_oco_per_symbol:
        upper = upper[:max_oco_per_symbol]

    if not upper:
        dbg(f"[HOLD-SELL] {symbol} all candidate prices collide with existing SELLs")
        return 0

    # --- GUARD: цена SELL не ниже средней + минимальный edge (если нет паники) ---
    steps_up = sorted({round_price(symbol, x) for x in ladder_prices})
    upper_guarded: List[float] = []

    for idx, p in enumerate(upper):
        pp = p
        min_sell_price: Optional[float] = None
        if avg_entry_px is not None:
            if panic_active:
                if panic_sell_floor_pct is not None:
                    min_sell_price = avg_entry_px * (1.0 - max(0.0, float(panic_sell_floor_pct)))
            else:
                floor_pct = _profit_floor_pct()
                min_sell_price = avg_entry_px * (1.0 + max(0.0, floor_pct))

        thr = pp
        if (min_sell_price is not None) and (pp < min_sell_price):
            thr = max(pp, min_sell_price)

        if thr != pp:
            cand = [s for s in steps_up if s >= thr]
            if cand:
                bumped = cand[min(idx, len(cand) - 1)]
            else:
                bumped = round_price(symbol, thr)
            if min_sell_price is not None and bumped < min_sell_price:
                bumped = min_sell_price
            if round_price(symbol, pp) != round_price(symbol, bumped):
                dbg(
                    f"[GUARD] {symbol} bump SELL "
                    f"{fmt_price_sym(symbol, p)} → {fmt_price_sym(symbol, bumped)}"
                )
            pp = bumped

        if pp > now:
            upper_guarded.append(pp)

    if not upper_guarded:
        dbg(f"[HOLD-SELL] {symbol} empty after GUARD (all ≤ now)")
        return 0

    # Дедуп по тиковой сетке после GUARD: дубликаты проталкиваем на следующую свободную ступень вверх
    steps_up = sorted({round_price(symbol, x) for x in ladder_prices if x > now})

    fixed_levels: list[float] = []
    seen: set[float] = set()

    for p in upper_guarded:
        pr = round_price(symbol, p)

        if pr in seen:
            # ищем ближайшую ступень ≥ pr и толкаем дальше, пока не найдём свободную
            j = next((i for i, s in enumerate(steps_up) if s >= pr), len(steps_up))
            while j < len(steps_up) and steps_up[j] in seen:
                j += 1
            if j < len(steps_up):
                dbg(f"[GUARD] {symbol} push duplicate {fmt_price_sym(symbol, pr)} → {fmt_price_sym(symbol, steps_up[j])}")
                pr = steps_up[j]
            else:
                dbg(f"[GUARD] {symbol} drop duplicate {fmt_price_sym(symbol, pr)} — no free step above")
                continue

        if pr <= now or pr in seen:
            continue

        seen.add(pr)
        fixed_levels.append(pr)

    upper_guarded = fixed_levels

    # dust и распределение
    dust = min_qty(symbol, 0)
    qty_left = max(0.0, base_free - dust)
    if qty_left <= 0:
        dbg(f"[HOLD-SELL] {symbol} sellable≈{fmt_qty_sym(symbol, qty_left)} "
            f"(free={fmt_qty_sym(symbol, base_free)}, dust={fmt_qty_sym(symbol, dust)})")
        return 0

    n = len(upper_guarded)
    if n <= 0:
        dbg(f"[HOLD-SELL] {symbol} empty after GUARD/push (no unique levels above now)")
        return 0

    placed = 0
    share = qty_left / n

    for idx, p in enumerate(upper_guarded, start=1):
        if qty_left <= 0:
            break

        q = min(share, qty_left)

        # доводим до биржевого minNotional (но не превышая остаток)
        need = min_notional(symbol, p) / p
        need = round_qty(symbol, max(need, min_qty(symbol, 0)))
        if q < need:
            q = min(need, qty_left)

        q = round_qty(symbol, q)

        # последний уровень — отдать весь остаток (округлённый вниз)
        if idx == n:
            q = round_qty(symbol, qty_left)

        if q <= 0:
            continue
        if q > qty_left:
            q = round_qty(symbol, qty_left)
            if q <= 0:
                continue
        if q * p < min_notional(symbol, p):
            need_q = round_qty(symbol, max(min_notional(symbol, p) / p, min_qty(symbol, 0)))
            dbg(f"[HOLD-SELL] {symbol} skip: notional {q*p:.2f} < min {min_notional(symbol, p):.2f} "
                f"at {fmt_price_sym(symbol, p)} with q={fmt_qty_sym(symbol, q)} (need≥{fmt_qty_sym(symbol, need_q)})")
            continue

        try:
            maker_flag = (
                sell_limit_maker or
                os.getenv("SELL_LIMIT_MAKER", "").lower() in ("1", "true", "yes")
            )
            j = place_limit_order("SELL", symbol, q, p, maker=maker_flag)
            if j:
                oid = j.get("orderId")
                log(f"[HOLD-SELL] {symbol} placed {fmt_qty_sym(symbol, q)} @ {fmt_price_sym(symbol, p)} (order {oid})")
                qty_left = max(0.0, qty_left - q)
                placed += 1
        except Exception:
            # не уменьшаем qty_left при ошибке биржи
            pass

    return placed

# ------------------- CLI / main -------------------

def main():
    parser = argparse.ArgumentParser(description="Ladder Dragon symbol executor")
    parser.add_argument("--version", action="version", version=product_label("executor"))
    parser.add_argument("--symbol", required=True)
    parser.add_argument("--ladder-prices", required=True, help="comma-separated absolute prices")
    parser.add_argument("--max-oco-per-symbol", type=int, default=None)
    parser.add_argument("--tp1", type=float, default=0.08)
    parser.add_argument("--tp2", type=float, default=0.08)
    parser.add_argument("--sl", type=float, default=-0.01)
    parser.add_argument("--status-interval", type=int, default=5)
    parser.add_argument("--loop-minutes", type=int, default=5)
    parser.add_argument("--oco-fallback", type=str, default="prefer-tp1")
    parser.add_argument("--target-buy-per-symbol", type=int, default=10)
    parser.add_argument("--auto-oco-holdings", action="store_true")
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--enforce-target-buys", action="store_true")
    parser.add_argument("--enforce-sell-limit", action="store_true")

    # Новые флаги (гейты BUY)
    parser.add_argument("--cap-floor-usdt", type=float, default=None,
                        help="Если свободных USDT меньше порога — не ставить BUY вовсе")
    parser.add_argument("--min-order-usdt", type=float, default=None,
                        help="Не ставить BUY, если нотационал заявки меньше этого порога (USDT)")

    # Патч: автоподвес OCO после заливки BUY
    parser.add_argument("--attach-oco-on-fill", action="store_true",
                        help="После FILLED у BUY автоматически ставить OCO (TP/SL) SELL")
    parser.add_argument("--stop-limit-offset-pct", type=float, default=0.0015,
                        help="На сколько ниже stopPrice ставить stopLimitPrice (для SELL)")
    parser.add_argument("--check-fills-interval", type=int, default=5,
                        help="Период проверки статусов BUY (сек) для подвеса OCO")

    # Управление динамическим CAP
    parser.add_argument("--use-remainder-in-last", action="store_true",
                        help="Если включено — последний BUY использует весь оставшийся USDT; без флага распределение равномерное")

    # Новые флаги: Breakeven after TP1 (опционально, по символам)
    parser.add_argument("--breakeven-on-tp1-symbols", type=str, default="",
                        help="Включить BE-stop после частичного TP1 для перечисленных символов (через запятую)")
    parser.add_argument("--breakeven-offset-pct", type=float, default=None,
                        help="Сдвиг BE над средней покупкой; если не задано — возьмём 2*BOT_FEE_PCT")
    parser.add_argument("--breakeven-check-interval", type=int, default=5,
                        help="Как часто проверять OCO на частичный TP (в шагах 1-секундного цикла)")

    # Паника / индикаторы
    parser.add_argument("--panic-drop-pct", type=float, default=0.02,
                        help="Мгновенное падение от prev_close для включения паники (доля, 0.02 = -2%%)")
    parser.add_argument("--panic-k-atr",   type=float, default=2.0,
                        help="Порог EMA20 - k*ATR для включения паники")
    parser.add_argument("--panic-debounce-checks", type=int, default=2,
                        help="Сколько подряд проверок требуется для включения паники")
    parser.add_argument("--panic-cooldown-sec",    type=int, default=180,
                        help="Время удержания режима паники перед выходом")
    parser.add_argument("--panic-interval", type=str, default="1m",
                        help="Таймфрейм для индикаторов паники (например, 1m/5m)")
    parser.add_argument("--panic-sell-floor-pct", type=float, default=None,
                        help="В панике не продавать ниже средней цены * (1 - pct). Если не задано — без ограничения")
    parser.add_argument("--avg-lookback", type=int, default=1000,
                        help="Сколько последних трейдов учитывать в средней (по умолчанию 1000)")
    parser.add_argument("--avg-cache-ttl", type=int, default=30,
                        help="TTL кэша средней цены позиции, сек (по умолчанию 30)")
    parser.add_argument("--sell-limit-maker", action="store_true",
                        help="Ставить SELL из холдингов как LIMIT_MAKER (maker-only)")
    parser.add_argument("--buy-limit-maker", action="store_true",
                        help="Ставить BUY как LIMIT_MAKER (maker-only)")

    # Тренд/медвежьи фильтры
    parser.add_argument("--skip-buy-while-panic", action="store_true",
                        help="В режиме паники не ставить новые BUY заявки")
    parser.add_argument("--buy-trend-ema-gap", type=float, default=None,
                        help="Если цена ниже EMA на заданную долю — считаем рынок падающим и применяем bear-фильтры")
    parser.add_argument("--buy-trend-interval", type=str, default=None,
                        help="Интервал для EMA в тренд-фильтре (по умолчанию как panic-interval)")
    parser.add_argument("--bear-skip-buys", action="store_true",
                        help="При медвежьем сигнале (buy-trend-ema-gap) полностью пропускать новые BUY")
    parser.add_argument("--bear-cap-scale", type=float, default=1.0,
                        help="Множитель CAP на заявку при медвежьем сигнале (1.0 = без изменений)")
    parser.add_argument("--bear-buy-shift-pct", type=float, default=0.0,
                        help="При медвежьем сигнале смещать BUY уровни вниз на указанную долю (0.05 = -5%%)")
    parser.add_argument("--buy-vwap-premium", type=float, default=None,
                        help="Если цена выше VWAP на эту долю — пропустить BUY (например 0.003 = +0.3%%)")
    parser.add_argument("--buy-vwap-discount", type=float, default=None,
                        help="Если цена ниже VWAP на эту долю — усилить CAP")
    parser.add_argument("--buy-vwap-discount-scale", type=float, default=1.0,
                        help="Множитель CAP при скидке к VWAP (например 1.4 = +40%%)")
    parser.add_argument("--buy-vwap-interval", type=str, default="1m",
                        help="Интервал свечей для расчёта VWAP (по умолчанию 1m)")
    parser.add_argument("--buy-vwap-window", type=int, default=180,
                        help="Сколько закрытых свечей использовать при расчёте VWAP")

    args = parser.parse_args()
    log(f"[VERSION] {product_label('executor')}")
    global LIVE_MODE
    if args.live and os.getenv("BOT_LIVE_CONFIRMED", "") != "YES":
        parser.error("--live requires BOT_LIVE_CONFIRMED=YES")
    if not re.fullmatch(r"[A-Z0-9]{5,20}", args.symbol.strip().upper()):
        parser.error("--symbol must be a valid uppercase Binance symbol")
    if args.target_buy_per_symbol <= 0 or args.loop_minutes <= 0:
        parser.error("target and loop limits must be > 0")
    if args.cap_floor_usdt is not None and args.cap_floor_usdt < 0:
        parser.error("--cap-floor-usdt must be >= 0")
    if args.min_order_usdt is not None and args.min_order_usdt <= 0:
        parser.error("--min-order-usdt must be > 0")
    if not 0 <= args.stop_limit_offset_pct < 0.25:
        parser.error("--stop-limit-offset-pct must be in [0, 0.25)")
    LIVE_MODE = bool(args.live)
    if LIVE_MODE:
        # Risk budgeting in the supervisor assumes this is a hard maximum.
        args.enforce_target_buys = True

    if LIVE_MODE:
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
        except (OSError, sqlite3.Error, requests.RequestException, RuntimeError, KeyError, ValueError) as exc:
            parser.error(f"LIVE preflight failed: {exc}")
    attach_oco = bool(args.attach_oco_on_fill)

    symbol = args.symbol

    # --- пер-символьный лок: второй процесс того же символа сразу завершится ---
    _lock = SymbolLock(symbol)
    if not _lock.acquire():
        return  # тихий выход

    try:
        ladder_prices = parse_comma_floats(args.ladder_prices)

        # --- Breakeven config ---
        be_syms = {s.strip().upper() for s in args.breakeven_on_tp1_symbols.split(",") if s.strip()}
        BE_ENABLED = symbol.upper() in be_syms
        FEE_PCT = getenv_float("BOT_FEE_PCT", 0.00075)
        BE_OFFSET = args.breakeven_offset_pct if args.breakeven_offset_pct is not None else max(0.0, 2.0 * FEE_PCT)
        BE_CHECK_N = max(1, int(args.breakeven_check_interval))
        be_tick = 0

        if BE_ENABLED:
            log(f"[BE] {symbol} enabled | offset={BE_OFFSET:.4%} | check={BE_CHECK_N}s")
        else:
            dbg(f"[BE] {symbol} disabled")

        def _be_state_path(sym: str) -> str:
            return os.path.join(bot_run_dir(), f"oco_be_state_{sym}.json")

        def _be_state_load(sym: str) -> dict:
            try:
                p = _be_state_path(sym)
                if os.path.exists(p):
                    with open(p, "r", encoding="utf-8") as f:
                        return json.load(f) or {}
            except Exception as e:
                dbg(f"[BE] state load err: {e}")
            return {}

        def _be_state_save(sym: str, d: dict) -> None:
            try:
                p = _be_state_path(sym)
                os.makedirs(os.path.dirname(p) or bot_run_dir(), exist_ok=True)
                with open(p, "w", encoding="utf-8") as f:
                    json.dump(d, f)
            except Exception as e:
                dbg(f"[BE] state save err: {e}")

        install_signal_handlers()
        pull_filters(symbol)
        current_price = get_price(symbol)

        # ------------------- ДЕДУП ЛЕСТНИЦЫ (belt & suspenders) -------------------
        ladder_prices = dedup_ladder(symbol, ladder_prices, current_price)
        # -------------------------------------------------------------------------

        started_at = time.time()
        warmup = cleanup_warmup_sec()
        log(f"[status] {symbol} pid={os.getpid()} OCO:? | started:{datetime.fromtimestamp(started_at).strftime('%Y-%m-%d %H:%M:%S')} | left:{int(args.loop_minutes*60)}s | last: idle")

        # BUY — размер из окружения (кап на заявку), если передаёт супервизор
        cap = getenv_float("BOT_CAP_PER_ORDER", 50.0)

        vwap_ratio: Optional[float] = None
        vwap_value: Optional[float] = None
        need_vwap = (
            args.buy_vwap_premium is not None or
            (args.buy_vwap_discount is not None and float(args.buy_vwap_discount) > 0) or
            (args.buy_vwap_discount_scale is not None and float(args.buy_vwap_discount_scale) != 1.0)
        )
        if need_vwap:
            try:
                vwap_value = get_vwap_cached(
                    symbol,
                    interval=args.buy_vwap_interval or "1m",
                    window=max(5, int(args.buy_vwap_window)),
                    ttl_sec=15,
                )
            except Exception as e:
                dbg(f"[VWAP] {symbol} calc err: {e}")
                vwap_value = None
            if vwap_value and vwap_value > 0:
                vwap_ratio = current_price / vwap_value

        # Предварительная оценка средней и паники
        try:
            ema20, atr, prev_close = get_indicators_cached(symbol, args.panic_interval, ttl_sec=20)
        except Exception:
            ema20 = atr = prev_close = None
        try:
            avg_px = avg_entry(symbol, cache_ttl=args.avg_cache_ttl, lookback=args.avg_lookback)
        except Exception:
            avg_px = None
        try:
            panic_active = update_panic_state(
                symbol=symbol,
                now_px=current_price,
                ema20=ema20, atr=atr, prev_close=prev_close,
                avg_entry_px=avg_px,
                panic_drop_pct=float(args.panic_drop_pct),
                panic_k_atr=float(args.panic_k_atr),
                debounce_checks=int(args.panic_debounce_checks),
                cooldown_sec=int(args.panic_cooldown_sec),
            )
        except Exception:
            panic_active = False

        trend_interval = args.buy_trend_interval or args.panic_interval
        if trend_interval == args.panic_interval:
            trend_ema = ema20
        else:
            try:
                trend_ema, _, _ = get_indicators_cached(symbol, trend_interval, ttl_sec=20)
            except Exception:
                trend_ema = None

        bear_gap = 0.0
        bear_mode = False
        if trend_ema and trend_ema > 0 and args.buy_trend_ema_gap is not None:
            try:
                gap_thr = max(0.0, float(args.buy_trend_ema_gap))
            except Exception:
                gap_thr = 0.0
            bear_gap = max(0.0, (trend_ema - current_price) / trend_ema)
            bear_mode = (bear_gap > 0.0) and (bear_gap >= gap_thr)
        if bear_mode:
            log(f"[BEAR] {symbol} price≈{fmt_price_sym(symbol, current_price)} EMA({trend_interval})≈{fmt_price_sym(symbol, trend_ema or 0)} gap≈{bear_gap:.4f}")

        if bear_mode and args.bear_buy_shift_pct > 0:
            ladder_prices = adjust_buy_ladder(symbol, ladder_prices, current_price, float(args.bear_buy_shift_pct))
            ladder_prices = dedup_ladder(symbol, ladder_prices, current_price)

        if bear_mode and args.bear_cap_scale is not None:
            scale = clamp(float(args.bear_cap_scale), 0.0, 5.0)
            if scale != 1.0:
                cap *= scale
                log(f"[BEAR] {symbol} cap scale {scale:.3f} → {cap:.2f} USDT")

        if vwap_ratio is not None and args.buy_vwap_discount is not None:
            try:
                discount_thr = clamp(float(args.buy_vwap_discount), 0.0, 0.5)
            except Exception:
                discount_thr = 0.0
            if discount_thr > 0 and vwap_ratio <= (1.0 - discount_thr):
                scale = clamp(float(args.buy_vwap_discount_scale), 0.1, 10.0)
                if scale != 1.0:
                    old_cap = cap
                    cap *= scale
                    log(
                        f"[VWAP] {symbol} discount ratio={vwap_ratio:.4f} <= 1-{discount_thr:.4f} → cap {old_cap:.2f}→{cap:.2f} x{scale:.2f}"
                    )

        skip_buys_reason: Optional[str] = None
        panic_sell_floor_pct = args.panic_sell_floor_pct
        if panic_active and args.skip_buy_while_panic:
            skip_buys_reason = "panic"
        elif bear_mode and args.bear_skip_buys:
            skip_buys_reason = "bear-trend"
        elif cap <= 0:
            skip_buys_reason = "cap<=0"
        elif (skip_buys_reason is None and vwap_ratio is not None and args.buy_vwap_premium is not None):
            try:
                premium_thr = 1.0 + max(0.0, float(args.buy_vwap_premium))
            except Exception:
                premium_thr = 1.0
            if premium_thr > 1.0 and vwap_ratio > premium_thr:
                skip_buys_reason = "buy-vwap-premium"
                if vwap_value:
                    log(
                        f"[VWAP] {symbol} now≈{fmt_price_sym(symbol, current_price)} vwap≈{fmt_price_sym(symbol, vwap_value)} "
                        f"ratio={vwap_ratio:.4f} > {premium_thr:.4f} → skip BUY"
                    )

        # BUY ниже текущей
        placed_ids: List[int] = (
            recover_pending_buy_order_ids(symbol)
            if LIVE_MODE and attach_oco
            else []
        )
        if skip_buys_reason:
            log(f"[SKIP-BUY] {symbol} reason={skip_buys_reason}; new BUY orders suppressed this cycle")
        else:
            try:
                new_ids = maybe_place_buys(
                    symbol,
                    ladder_prices,
                    cap,
                    min_order_usdt=args.min_order_usdt,
                    cap_floor_usdt=args.cap_floor_usdt,
                    target_buy_per_symbol=args.target_buy_per_symbol,
                    enforce_limit=args.enforce_target_buys,
                    use_remainder_in_last=bool(args.use_remainder_in_last),
                    buy_limit_maker=args.buy_limit_maker,
                )
                placed_ids = list(dict.fromkeys([*placed_ids, *new_ids]))
            except Exception as e:
                log(f"[ERR] maybe_place_buys: {e}")

        # Если attach_oco_on_fill включён, но новых BUY в этом запуске нет — не блокируем auto_oco_holdings
        if args.auto_oco_holdings and (not attach_oco or not placed_ids):
            if attach_oco and not placed_ids:
                dbg("[AUTO-OCO] no new BUYs this run → enabling auto_oco_holdings for free base")
            try:
                _ = maybe_place_sells_from_holdings(
                    symbol,
                    ladder_prices,
                    args.max_oco_per_symbol,
                    enforce_limit=getattr(args, "enforce_sell_limit", False),
                    avg_entry_px=avg_px,
                    panic_active=panic_active,
                    sell_limit_maker=args.sell_limit_maker,
                    panic_sell_floor_pct=panic_sell_floor_pct,
                )
            except Exception as e:
                log(f"[ERR] maybe_place_sells: {e}")
        else:
            if attach_oco and placed_ids:
                dbg("[SKIP] auto_oco_holdings: skipped because attach_oco_on_fill is enabled and new BUYs exist")

        # единоразовый сбор трейдов (если включена статистика)
        try:
            _stats_poll_mytrades_once(symbol)
        except Exception as e:
            log(f"[STATS] poll error: {e}")

        # простой «живой» цикл статуса, пока слот активен + подвес OCO после FILLED BUY
        left = int(args.loop_minutes * 60)
        last_check = 0

        while RUN and left > 0:
            time.sleep(1)
            left -= 1

            if left % max(1, args.status_interval) == 0:
                log(f"[status] {symbol} pid={os.getpid()} OCO:? | started:{datetime.fromtimestamp(started_at).strftime('%Y-%m-%d %H:%M:%S')} | left:{left}s | last: idle")

            # периодически обновляем индикаторы/панику (лёгкий режим)
            try:
                ema20, atr, prev_close = get_indicators_cached(symbol, args.panic_interval, ttl_sec=20)
                avg_px = avg_entry(symbol, cache_ttl=args.avg_cache_ttl, lookback=args.avg_lookback)  # кэш управляется CLI
                panic_active = update_panic_state(
                    symbol=symbol,
                    now_px=get_price(symbol),
                    ema20=ema20, atr=atr, prev_close=prev_close,
                    avg_entry_px=avg_px,
                    panic_drop_pct=float(args.panic_drop_pct),
                    panic_k_atr=float(args.panic_k_atr),
                    debounce_checks=int(args.panic_debounce_checks),
                    cooldown_sec=int(args.panic_cooldown_sec),
                )
            except Exception:
                pass

            # подвес OCO после FILLED у новых BUY
            if attach_oco and placed_ids:
                last_check += 1
                if last_check >= max(1, args.check_fills_interval):
                    last_check = 0
                    for oid in list(placed_ids):  # идём по копии
                        o = get_order(symbol, oid)
                        if not o:
                            continue
                        st = str(o.get("status", "")).upper()
                        try:
                            executed_status = float(o.get("executedQty", "0") or 0.0)
                        except (TypeError, ValueError):
                            executed_status = 0.0
                        terminal_partial = st in TERMINAL_EXCHANGE_STATES and executed_status > 0
                        if st != "FILLED" and not terminal_partial:
                            continue

                        protected = False
                        journal = _order_journal()
                        buy_intent = journal.get_by_exchange_order_id(oid) if journal is not None else None
                        parent_client_id = buy_intent.client_order_id if buy_intent is not None else None
                        try:
                            # Persist the terminal BUY state before protection work.  This makes
                            # restart recovery deterministic even if the process is interrupted
                            # while creating the OCO.
                            if journal is not None and parent_client_id:
                                journal.record_exchange_order(parent_client_id, o)
                            if parent_client_id and recover_existing_protection(parent_client_id):
                                log(f"[RECOVERY] protection already exists for BUY order={oid}")
                                _stats_poll_mytrades_once(symbol)
                                placed_ids.remove(oid)
                                continue
                            executed = executed_status
                            if executed <= 0:
                                try:
                                    placed_ids.remove(oid)
                                except ValueError:
                                    pass
                                continue

                            cumm_q = float(o.get("cummulativeQuoteQty", "0") or 0.0)
                            avg_fill_price = (cumm_q / executed) if executed > 0 else float(o.get("price", "0") or 0.0)

                            # Лестнично-выравненные + floor/cap TP/SL
                            tp_lim, sl_stop, sl_lim = _pick_ladder_aligned_oco_prices(
                                symbol, ladder_prices, avg_fill_price, args.stop_limit_offset_pct
                            )

                            # GUARD: не продавать ниже средней (кроме паники)
                            try:
                                avg_px = avg_entry(symbol, cache_ttl=args.avg_cache_ttl, lookback=args.avg_lookback)
                            except Exception:
                                avg_px = None
                            if avg_px is not None:
                                min_guard_price: Optional[float] = None
                                if panic_active:
                                    if panic_sell_floor_pct is not None:
                                        min_guard_price = avg_px * (1.0 - max(0.0, float(panic_sell_floor_pct)))
                                else:
                                    min_guard_price = max(avg_px, avg_fill_price * (1.0 + _profit_floor_pct()))

                                if (min_guard_price is not None) and tp_lim < min_guard_price:
                                    guard_floor = round_price(symbol, min_guard_price)
                                    if guard_floor > tp_lim:
                                        dbg(
                                            f"[GUARD] {symbol} TP поднят: {fmt_price_sym(symbol, tp_lim)} → {fmt_price_sym(symbol, guard_floor)} "
                                            f"(avg={fmt_price_sym(symbol, avg_px)})"
                                        )
                                        tp_lim = guard_floor

                            # Не продавать больше свободного; уважать minNotional (и на SL-тележке тоже)
                            pull_filters(symbol)
                            base, _ = get_symbol_assets(symbol)
                            bals = get_balances()
                            base_free = float(bals.get(base, {}).get("free", 0.0))
                            dust = min_qty(symbol, 0)
                            sellable = max(0.0, base_free - dust)

                            q = min(executed, sellable)
                            q = round_qty(symbol, q)

                            # --- Проверка нотациона с подробным логом ДО place_oco_sell ---
                            tp_r = round_price(symbol, tp_lim)
                            sl_r = round_price(symbol, sl_lim)

                            min_tp = min_notional(symbol, tp_r)
                            min_sl = min_notional(symbol, sl_r)

                            tp_val = q * tp_r
                            sl_val = q * sl_r

                            if q <= 0 or tp_val < min_tp or sl_val < min_sl:
                                reason = (
                                    "cannot protect filled BUY: quantity/notional too small | "
                                    "symbol=%s order=%s q=%s sellable=%s dust=%s "
                                    "TPv=%.2f<minTP=%.2f SLv=%.2f<minSL=%.2f | tp=%s sl_lim=%s"
                                    % (
                                        symbol,
                                        oid,
                                        fmt_qty_sym(symbol, q),
                                        fmt_qty_sym(symbol, sellable),
                                        fmt_qty_sym(symbol, dust),
                                        tp_val, min_tp, sl_val, min_sl,
                                        fmt_price_sym(symbol, tp_r),
                                        fmt_price_sym(symbol, sl_r),
                                    )
                                )
                                _trip_execution_halt(
                                    reason,
                                    symbol=symbol,
                                    order_id=oid,
                                    client_order_id=parent_client_id,
                                )
                                continue
                            # -------------------------------------------------------------

                            res = place_oco_sell(
                                symbol,
                                q,
                                tp_r,
                                sl_stop,
                                sl_r,
                                parent_client_order_id=parent_client_id,
                            )
                            protected = bool(res)
                            if not res and args.oco_fallback == "prefer-tp1":
                                # guard на notional и «пыль» для одиночного TP
                                if q * tp_r < min_notional(symbol, tp_r):
                                    dbg(f"[FALLBACK-SKIP] {symbol} TP notional too small: {q*tp_r:.2f} < {min_notional(symbol, tp_r):.2f}")
                                    raise RuntimeError("single TP notional too small")
                                try:
                                    fallback = place_limit_order(
                                        "SELL",
                                        symbol,
                                        q,
                                        tp_r,
                                        maker=getattr(args, "sell_limit_maker", False),
                                        purpose="fallback_tp",
                                        parent_client_order_id=parent_client_id,
                                    )
                                    if fallback:
                                        protected = True
                                        if journal is not None and parent_client_id:
                                            fallback_client_id = str(fallback.get("clientOrderId") or "")
                                            if fallback_client_id:
                                                journal.mark_protected(
                                                    parent_client_order_id=parent_client_id,
                                                    protection_client_order_id=fallback_client_id,
                                                    exchange_order_id=(
                                                        int(fallback["orderId"])
                                                        if fallback.get("orderId") is not None
                                                        else None
                                                    ),
                                                )
                                        log(f"[FALLBACK] {symbol} single TP placed @ {fmt_price_sym(symbol, tp_r)}")
                                except Exception as ee:
                                    log(f"[FALLBACK-ERR] {symbol} -> {ee}")
                            # ---- BE-состояние: запомним связку OCO ↔ avg_fill_price ----
                            if res and BE_ENABLED:
                                try:
                                    olid = int(res.get("orderListId") or 0)
                                    if olid:
                                        stmap = _be_state_load(symbol)
                                        stmap[str(olid)] = {"fill_price": float(avg_fill_price), "tp_price": float(tp_r), "ts": time.time()}
                                        _be_state_save(symbol, stmap)
                                        dbg(f"[BE] state add: orderListId={olid} fill={fmt_price_sym(symbol, avg_fill_price)}")
                                except Exception as ee:
                                    dbg(f"[BE] state add err: {ee}")
                            if not protected:
                                reason = f"filled BUY {oid} has no confirmed OCO or fallback protection"
                                _trip_execution_halt(
                                    reason,
                                    symbol=symbol,
                                    order_id=oid,
                                    client_order_id=parent_client_id,
                                )
                        except Exception as e:
                            log(f"[ATTACH-OCO-ERR] {symbol} order {oid}: {e}")
                            _trip_execution_halt(
                                f"protection error for filled BUY {oid}: {e}",
                                symbol=symbol,
                                order_id=oid,
                                client_order_id=parent_client_id,
                            )

                        # BUY завершён только после подтверждённой защиты.
                        if protected:
                            # Refresh the local ledger immediately after protection is confirmed.
                            # The supervisor reconciles exchange balances against this inventory;
                            # waiting for the next worker restart creates a false mismatch window.
                            _stats_poll_mytrades_once(symbol)
                            try:
                                placed_ids.remove(oid)
                            except ValueError:
                                pass

            # --- Breakeven поддержка OCO после частичного TP ---
            if BE_ENABLED:
                be_tick += 1
                if be_tick >= BE_CHECK_N:
                    be_tick = 0
                    try:
                        opens = list_open_orders(symbol)  # SELL-ордера текущего символа
                        # сгруппируем по orderListId
                        groups: Dict[str, List[Dict[str, Any]]] = {}
                        for o in opens:
                            try:
                                if str(o.get("side", "")).upper() != "SELL":
                                    continue
                                olid = o.get("orderListId")
                                if not olid:
                                    continue
                                groups.setdefault(str(olid), []).append(o)
                            except Exception:
                                continue
                        if groups:
                            stmap = _be_state_load(symbol)
                        for olid, orders in groups.items():
                            # ищем пару: LIMIT (TP) и STOP_LOSS_LIMIT (SL)
                            lim = next((x for x in orders if "LIMIT" in str(x.get("type","")).upper() and "STOP" not in str(x.get("type","")).upper()), None)
                            sto = next((x for x in orders if "STOP_LOSS" in str(x.get("type","")).upper()), None)
                            if not lim or not sto:
                                continue
                            # частично исполненный TP?
                            try:
                                orig = float(lim.get("origQty","0") or 0.0)
                                execd = float(lim.get("executedQty","0") or 0.0)
                                remain = max(0.0, orig - execd)
                            except Exception:
                                continue
                            if execd <= 0.0 or remain <= 0.0:
                                continue  # TP не трогался или уже всё закрыто

                            # целевой BE-stop
                            fill_px = float(stmap.get(str(olid),{}).get("fill_price", 0.0))
                            if fill_px <= 0.0:
                                continue  # нет данных — не трогаем
                            be_stop = round_price(symbol, fill_px * (1.0 + BE_OFFSET))

                            current_stop = 0.0
                            try:
                                current_stop = float(sto.get("stopPrice","0") or 0.0)
                            except Exception:
                                current_stop = 0.0

                            if current_stop + 1e-12 >= be_stop:
                                continue  # уже не хуже BE

                            # цены для нового SL (stopLimit чуть ниже stop)
                            pull_filters(symbol)
                            tick = symbol_filters[symbol]["tickSize"]
                            eps = max(tick * max(1.0, price_eps_mult()), fill_px * max(0.0, float(args.stop_limit_offset_pct)))
                            # поднимем stop к ближайшему тиковому "вверх", limit — вниз; гарантируем строгий порядок
                            sl_stop = _round(be_stop, tick, "up")
                            sl_lim  = _round(sl_stop - eps, tick, "down")
                            if sl_stop <= sl_lim:
                                sl_stop = _round(sl_lim + tick, tick, "up")

                            # TP оставляем прежним
                            try:
                                tp_price = float(lim.get("price","0") or 0.0)
                            except Exception:
                                tp_price = 0.0
                            if tp_price <= 0.0:
                                continue

                            # уважаем minQty/minNotional (и для TP, и для SL)
                            pull_filters(symbol)
                            remain = round_qty(symbol, remain)
                            if remain < min_qty(symbol, 0):
                                dbg(f"[BE] skip dust remain={fmt_qty_sym(symbol, remain)}")
                                continue
                            # Проверка нотациона обеих ног
                            try:
                                min_tp_notional = min_notional(symbol, tp_price)
                            except Exception:
                                min_tp_notional = 0.0
                            try:
                                min_sl_notional = min_notional(symbol, sl_lim)
                            except Exception:
                                min_sl_notional = 0.0
                            tp_val = remain * tp_price
                            sl_val = remain * sl_lim
                            if tp_val < min_tp_notional:
                                dbg(f"[BE] skip TP notional too small: {tp_val:.2f} < {min_tp_notional:.2f}")
                                continue
                            if sl_val < min_sl_notional:
                                dbg(f"[BE] skip SL notional too small: {sl_val:.2f} < {min_sl_notional:.2f}")
                                continue

                            # Пересобираем OCO на остаток
                            try:
                                cancel_oco(symbol, int(olid))
                                time.sleep(0.25)
                            except Exception:
                                pass
                            res2 = place_oco_sell(symbol, remain, tp_price, sl_stop, sl_lim)
                            if res2:
                                try:
                                    new_olid = int(res2.get("orderListId") or 0)
                                except Exception:
                                    new_olid = 0
                                if new_olid:
                                    # переносим fill_price в новый orderListId
                                    stmap.pop(str(olid), None)
                                    stmap[str(new_olid)] = {"fill_price": float(fill_px), "tp_price": float(tp_price), "ts": time.time()}
                                    _be_state_save(symbol, stmap)
                                    log(f"[BE] {symbol} OCO re-arm -> BE stop={fmt_price_sym(symbol, sl_stop)} (orderListId={new_olid})")
                    except Exception as e:
                        dbg(f"[BE] loop err: {e}")

        return
    finally:
        # гарантированно снимем лок
        _lock.release()

if __name__ == "__main__":
    main()
