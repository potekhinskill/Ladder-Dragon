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
import signal
import sqlite3
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
from executor_config import build_executor_parser, validate_executor_args
from strategy_math import atr_from_klines as _atr_from_klines
from strategy_math import clamp, ema_value as _ema, panic_triggered as panic_raw
from strategy_math import shift_buy_levels
from binance_transport import BinanceTransport
from executor_market import get_balances as market_get_balances
from executor_market import get_price as market_get_price
from executor_market import get_symbol_assets as market_get_symbol_assets
from executor_recovery import RecoveryDependencies
from executor_recovery import cancel_oco as recovery_cancel_oco
from executor_recovery import cancel_order as recovery_cancel_order
from executor_recovery import get_order as recovery_get_order
from executor_recovery import get_order_by_client_id as recovery_get_order_by_client_id
from executor_recovery import get_order_list_by_client_id as recovery_get_order_list_by_client_id
from executor_recovery import list_open_orders as recovery_list_open_orders
from executor_recovery import record_order_payload as recovery_record_order_payload
from executor_recovery import recover_existing_protection as recovery_existing_protection
from executor_recovery import recover_pending_buy_order_ids as recovery_pending_buy_order_ids
from executor_recovery import verify_oco_legs as recovery_verify_oco_legs
from executor_stats import commission_quote_value, poll_mytrades_once

import requests
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


# ------------------- helpers: rounding & env -------------------

def _round(x: float, step: float, mode: str = "nearest") -> float:
    return float(round_step(x, step, mode))

def fmt(v, n=8):
    try:
        return f"{float(v):.{n}f}"
    except Exception:
        return str(v)

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
    return TRANSPORT.signed_request(method, path, params=params, timeout=timeout)

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

def get_balances() -> Dict[str, Dict[str, float]]:
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


def _recovery_dependencies() -> RecoveryDependencies:
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


def _stats_poll_mytrades_once(symbol: str):
    if not (STATS_ENABLE and STATS_DB):
        return
    _stats_init_if_needed()
    if STATS_CON is None or TOOLS_STATS is None:
        return
    poll_mytrades_once(
        symbol,
        connection=STATS_CON,
        stats=TOOLS_STATS,
        signed_request=_signed_request,
        commission_value=_commission_quote_value,
        logger=log,
    )

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
    parser = build_executor_parser()
    args = validate_executor_args(parser, parser.parse_args())
    log(f"[VERSION] {product_label('executor')}")
    global LIVE_MODE
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
