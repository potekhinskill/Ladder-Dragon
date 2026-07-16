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
import time
import signal
import sqlite3
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
import tools_market as TM
from order_recovery import OrderIntent, OrderJournal
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
from executor_orders import OrderDependencies
from executor_orders import place_limit_order as orders_place_limit_order
from executor_orders import place_oco_sell as orders_place_oco_sell
from executor_planning import buy_candidates, existing_prices, guarded_sell_levels
from executor_planning import plan_buy_order, plan_sell_order
from executor_protection import (
    BreakevenRuntime,
    BreakevenStateStore,
    ProtectionConfig,
    ProtectionDependencies,
    maintain_breakeven,
    protect_filled_buys,
)
from executor_runtime import status_due, trading_seconds
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
from inventory_lots import add_lot, consume_fifo, ensure_schema as ensure_lots_schema, oldest_lots

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
    """Открыть постоянный intent-журнал только при разрешённых мутациях."""
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
    """Остановить дальнейшее исполнение при неподтверждённом состоянии ордера."""
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

def _execution_cost_floor_pct() -> float:
    """Минимальная gross-цель после комиссии и неблагоприятного исполнения."""
    fee = max(0.0, getenv_float("BOT_FEE_PCT", 0.001))
    spread = max(0.0, getenv_float("BOT_SPREAD_PCT", getenv_float("RISK_SPREAD_PCT", 0.0)))
    slippage = max(0.0, getenv_float("BOT_SLIPPAGE_PCT", getenv_float("RISK_SLIPPAGE_PCT", 0.0)))
    latency = max(0.0, getenv_float("BOT_LATENCY_COST_PCT", 0.0))
    stop_cost = max(0.0, getenv_float("BOT_STOP_EXECUTION_COST_PCT", 0.0))
    partial = max(0.0, getenv_float("BOT_PARTIAL_FILL_COST_PCT", 0.0))
    min_edge = max(0.0, getenv_float("BOT_MIN_NET_EDGE_PCT", getenv_float("MIN_NET_EDGE_PCT", 0.0)))
    return 2.0 * fee + spread + 2.0 * slippage + latency + stop_cost + partial + min_edge

def _profit_floor_pct() -> float:
    # совмещённый “пол”: не ниже MIN_PROFIT_OVER_AVГ и не ниже комиссии
    min_edge = max(0.0, getenv_float("MIN_PROFIT_OVER_AVG", 0.0))
    return max(min_edge, _fee_floor_pct(), _execution_cost_floor_pct())

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
    # Фасад связывает чистый recovery-модуль с transport, journal и halt
    # текущего процесса, не раскрывая ему глобальные переменные напрямую.
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


def _order_dependencies() -> OrderDependencies:
    # Ордерный модуль получает функции поздно: актуальный LIVE_MODE проверяется
    # в момент POST, а не фиксируется при импорте исполнителя.
    return OrderDependencies(
        live=lambda: LIVE_MODE,
        logger=log,
        pull_filters=pull_filters,
        round_price=round_price,
        round_qty=round_qty,
        min_qty=min_qty,
        min_notional=min_notional,
        format_price=fmt_price_sym,
        format_qty=fmt_qty_sym,
        journal=_order_journal,
        signed_request=_signed_request,
        get_order_by_client_id=get_order_by_client_id,
        get_order_list_by_client_id=get_order_list_by_client_id,
        verify_oco_legs=verify_oco_legs,
        cancel_oco=cancel_oco,
        halt=_trip_execution_halt,
    )


def _protection_dependencies() -> ProtectionDependencies:
    # Сопровождение позиции получает те же late-bound границы, что orders и
    # recovery: фактические HTTP, journal и halt остаются у исполнителя.
    return ProtectionDependencies(
        logger=log,
        debugger=dbg,
        journal=_order_journal,
        get_order=get_order,
        recover_existing_protection=recover_existing_protection,
        poll_trades=_stats_poll_mytrades_once,
        pick_oco_prices=_pick_ladder_aligned_oco_prices,
        average_entry=lambda symbol, ttl, lookback: avg_entry(
            symbol, cache_ttl=ttl, lookback=lookback
        ),
        profit_floor_pct=_profit_floor_pct,
        pull_filters=pull_filters,
        get_symbol_assets=get_symbol_assets,
        get_balances=get_balances,
        round_price=round_price,
        round_quantity=round_qty,
        min_quantity=min_qty,
        min_notional=min_notional,
        format_price=fmt_price_sym,
        format_quantity=fmt_qty_sym,
        halt=_trip_execution_halt,
        place_oco_sell=place_oco_sell,
        place_limit_order=place_limit_order,
        list_open_orders=list_open_orders,
        tick_size=lambda symbol: symbol_filters[symbol]["tickSize"],
        price_eps_mult=price_eps_mult,
        round_step=_round,
        cancel_oco=cancel_oco,
        place_market_order=place_market_order,
    )


def place_limit_order(side: str,
                      symbol: str,
                      qty: float,
                      price: float,
                      *,
                      maker: bool = False,
                      purpose: str = "ladder",
                      parent_client_order_id: Optional[str] = None) -> Dict[str, Any] | None:
    return orders_place_limit_order(
        side,
        symbol,
        qty,
        price,
        dependencies=_order_dependencies(),
        maker=maker,
        purpose=purpose,
        parent_client_order_id=parent_client_order_id,
    )

def place_oco_sell(symbol: str,
                   qty: float,
                   tp_limit_price: float,
                   sl_stop_price: float,
                   sl_limit_price: float,
                   *,
                   parent_client_order_id: Optional[str] = None) -> Dict[str, Any] | None:
    return orders_place_oco_sell(
        symbol,
        qty,
        tp_limit_price,
        sl_stop_price,
        sl_limit_price,
        dependencies=_order_dependencies(),
        parent_client_order_id=parent_client_order_id,
    )

# ------------------- STATS (optional) -------------------

STATS_ENABLE = getenv_int("STATS_ENABLE", 0) == 1
STATS_DB = getenv_str("BOT_STATS_DB", "")

TOOLS_STATS = None
STATS_CON: Optional[sqlite3.Connection] = None
_COMMISSION_QUOTE_CACHE: Dict[Tuple[str, str, int], Decimal] = {}

def _stats_init_if_needed():
    """Лениво открыть статистику, чтобы DRY/help не зависели от рабочей БД."""
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
    def on_fill(fill: dict) -> None:
        """Синхронизировать фактический fill с FIFO-партиями и AI журналом."""
        try:
            ensure_lots_schema(STATS_CON)
            if fill["side"] == "BUY":
                add_lot(STATS_CON, symbol=symbol, qty=Decimal(str(fill["qty"])),
                        price=Decimal(str(fill["price"])),
                        source_order_id=str(fill["trade_id"]), opened_at=int(fill["ts"] / 1000))
            else:
                consume_fifo(STATS_CON, symbol, Decimal(str(fill["qty"])))
            STATS_CON.commit()
        except (sqlite3.Error, ValueError, ArithmeticError) as exc:
            log(f"[LOTS] {symbol} fill sync failed: {exc}")
        # AI DB подключается мягко: отсутствие AI не должно блокировать торговый ledger.
        try:
            ai_db = os.getenv("AI_DECISIONS_DB", "").strip()
            if ai_db:
                from ai_context import AdvisorDecisionStore
                store = AdvisorDecisionStore(ai_db)
                decision_id = os.getenv("BOT_AI_DECISION_ID", "").strip() or store.latest_decision_id(symbol)
                if decision_id:
                    store.record_fill(decision_id, symbol=symbol, side=fill["side"],
                                      price=float(fill["price"]), qty=float(fill["qty"]),
                                      fee_quote=float(fill["fee_quote"]), ts=int(fill["ts"] / 1000))
        except (sqlite3.Error, ValueError, OSError) as exc:
            dbg(f"[AI-FILL] {symbol} sync skipped: {exc}")

    poll_mytrades_once(
        symbol,
        connection=STATS_CON,
        stats=TOOLS_STATS,
        signed_request=_signed_request,
        commission_value=_commission_quote_value,
        logger=log,
        on_fill=on_fill,
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
    # Сигнал остановки проверяется до любых сетевых запросов: после SIGTERM
    # функция не должна даже читать баланс или список открытых заявок.
    if not RUN:
        log(f"[STOP] {symbol} BUY placement skipped before exchange reads")
        return []
    get_symbol_assets(symbol)
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
        existing_buy_prices = existing_prices(
            open_orders,
            side="BUY",
            now_price=now,
            round_price=lambda value: round_price(symbol, value),
        )
        existing_cnt = len(existing_buy_prices)
        allowed_new = max(0, int(target_buy_per_symbol) - existing_cnt)
        log(f"[TARGET-LIMIT] {symbol} existing_buy={existing_cnt} target={int(target_buy_per_symbol)} → allow_new={allowed_new}")
        if allowed_new <= 0:
            return []

    candidates = buy_candidates(
        ladder_prices,
        now_price=now,
        occupied_prices=existing_buy_prices,
        round_price=lambda value: round_price(symbol, value),
        limit=allowed_new if enforce_limit else None,
    )

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
        remaining_slots = max(1, total_slots - idx + 1)
        local_cap = min(cap_per_order_usdt, usdt_free / remaining_slots)
        if use_remainder_in_last and (idx == total_slots):
            local_cap = usdt_free

        dbg(f"[DYN-CAP] {symbol} slot {idx}/{total_slots} p≈{fmt_price_sym(symbol, p)} "
            f"local_cap≈{local_cap:.2f} free≈{usdt_free:.2f}")
        pr = round_price(symbol, p)
        planned = plan_buy_order(
            p,
            free_quote=usdt_free,
            cap_per_order=cap_per_order_usdt,
            remaining_slots=remaining_slots,
            use_all_remaining=use_remainder_in_last and idx == total_slots,
            min_order_notional=None,
            min_quantity=min_qty(symbol, 0),
            min_notional=min_notional(symbol, pr),
            round_price=lambda value: round_price(symbol, value),
            round_quantity=lambda value: round_qty(symbol, value),
        )
        if planned is None:
            continue
        pr, qty, cost = planned.price, planned.quantity, planned.notional
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
                usdt_free = max(0.0, usdt_free - planned.notional)
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
    base, _ = get_symbol_assets(symbol)
    bals = get_balances()
    base_free = float(bals.get(base, {}).get("free", 0.0))
    if base_free <= 0:
        dbg(f"[HOLD-SELL] {symbol} no free base (free={fmt_qty_sym(symbol, base_free)})")
        return 0

    pull_filters(symbol)

    now = get_price(symbol)
    if not any(p > now for p in ladder_prices):
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
        existing_sell_prices = existing_prices(
            oo,
            side="SELL",
            now_price=now,
            round_price=lambda value: round_price(symbol, value),
        )
        existing_cnt = len(existing_sell_prices)
        allowed_new = max(0, int(max_oco_per_symbol) - existing_cnt)
        log(f"[SELL-LIMIT] {symbol} existing_sell={existing_cnt} max_oco={int(max_oco_per_symbol)} → allow_new={allowed_new}")
        if allowed_new <= 0:
            return 0

    limit = allowed_new if enforce_limit else max_oco_per_symbol
    upper_guarded = guarded_sell_levels(
        ladder_prices,
        now_price=now,
        occupied_prices=existing_sell_prices if enforce_limit else set(),
        round_price=lambda value: round_price(symbol, value),
        limit=limit,
        average_entry=avg_entry_px,
        panic_active=panic_active,
        panic_floor_pct=panic_sell_floor_pct,
        profit_floor_pct=_profit_floor_pct(),
    )
    if not upper_guarded:
        dbg(f"[HOLD-SELL] {symbol} empty after limits/GUARD")
        return 0

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

        minimum_notional = min_notional(symbol, p)
        planned = plan_sell_order(
            p,
            quantity_left=qty_left,
            share=share,
            is_last=idx == n,
            min_quantity=min_qty(symbol, 0),
            min_notional=minimum_notional,
            round_quantity=lambda value: round_qty(symbol, value),
        )
        if planned is None:
            need_q = round_qty(symbol, max(min_notional(symbol, p) / p, min_qty(symbol, 0)))
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
                qty_left = max(0.0, qty_left - planned.quantity)
                placed += 1
        except Exception:
            # не уменьшаем qty_left при ошибке биржи
            pass

    return placed

# ------------------- CLI / main -------------------

def main():
    """Один торговый сеанс символа: preflight, план, размещение и защита."""
    parser = build_executor_parser()
    args = validate_executor_args(parser, parser.parse_args())
    log(f"[VERSION] {product_label('executor')}")
    global LIVE_MODE
    LIVE_MODE = bool(args.live)
    if LIVE_MODE:
        # Расчёт риска в супервизоре считает target-buy жёстким максимумом.
        # Поэтому LIVE всегда включает контроль уже существующих BUY.
        args.enforce_target_buys = True

    if LIVE_MODE:
        # Повторный preflight нужен даже после проверки супервизора: воркер
        # может быть запущен отдельно или спустя время после исходной проверки.
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

        # --- Breakeven: постоянная связь OCO со средней ценой исходного BUY ---
        be_syms = {s.strip().upper() for s in args.breakeven_on_tp1_symbols.split(",") if s.strip()}
        BE_ENABLED = symbol.upper() in be_syms
        FEE_PCT = getenv_float("BOT_FEE_PCT", 0.00075)
        BE_OFFSET = args.breakeven_offset_pct if args.breakeven_offset_pct is not None else max(0.0, 2.0 * FEE_PCT)
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
        current_price = get_price(symbol)

        # Защитный дедуп выполняется и здесь: прямой запуск воркера не должен
        # зависеть от того, нормализовал ли лестницу супервизор.
        ladder_prices = dedup_ladder(symbol, ladder_prices, current_price)

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

        # Средняя цена и panic-state влияют одновременно на разрешение BUY
        # и на минимально допустимую цену защитного SELL.
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

        # Перед новыми BUY восстанавливаем незавершённые intent после рестарта.
        # Так один и тот же FILLED/PARTIAL BUY снова попадёт под контроль OCO.
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

        # Свободные holdings продаём отдельно только когда они не конкурируют
        # за один base-баланс с OCO, ожидающим исполнения нового BUY.
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

        # Runtime-цикл не создаёт новые BUY. Он наблюдает уже поставленные,
        # подтверждает FILLED/PARTIAL и обязательно создаёт защиту.
        last_check = 0

        for left in trading_seconds(
            int(args.loop_minutes * 60),
            running=lambda: RUN,
        ):
            if status_due(left, args.status_interval):
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

            # FILLED BUY удаляется из placed_ids только после подтверждённого
            # OCO либо резервного TP. Любая неопределённость создаёт halt.
            if attach_oco and placed_ids:
                last_check += 1
                if last_check >= max(1, args.check_fills_interval):
                    last_check = 0
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
                    )

            # LIVE time-stop: защита от бесконечно зависшей позиции. Binance
            # не предоставляет такой политики для уже исполненного BUY, поэтому
            # контролируем возраст позиции локально и закрываем её MARKET.
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
                    qty_exp = float(held.get("executedQty", 0) or 0)
                    # Если ledger знает партии, time-stop закрывает сначала
                    # самый старый inventory, а не случайную агрегированную qty.
                    if STATS_CON is not None:
                        try:
                            lots = oldest_lots(STATS_CON, symbol)
                            lot_qty = sum((lot.qty for lot in lots), Decimal("0"))
                            if lot_qty > 0:
                                qty_exp = min(qty_exp, float(lot_qty))
                        except sqlite3.Error:
                            pass
                    if qty_exp > 0:
                        log(f"[TIME-STOP] {symbol} order={oid} age>{max_hold_min:g}m; flattening")
                        place_market_order(symbol, "SELL", qty_exp,
                                           ref_price=get_price(symbol),
                                           filters=symbol_filters.get(symbol))
                    _trip_execution_halt("max holding time exceeded", symbol=symbol, order_id=oid)
                    placed_ids.remove(oid)

            # --- Breakeven поддержка OCO после частичного TP ---
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
        # гарантированно снимем лок
        _lock.release()

if __name__ == "__main__":
    main()
