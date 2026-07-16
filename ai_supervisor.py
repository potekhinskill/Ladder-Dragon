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
import signal
import random
import argparse
import subprocess
import json
import sqlite3
from dataclasses import asdict
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Tuple

from ai_advisor import (
    AIAdvisor,
    AdvisorConfig,
    MarketContext,
    limit_cap_by_recommendation,
)
from ai_context import (
    AdvisorDecisionStore,
    build_market_features,
    build_portfolio_features,
    load_trade_features,
)
from ai_policy import (
    PolicyConfig,
    UsageBudget,
    apply_safety_policy,
    read_usage_today,
    usage_budget_allows,
)
from ai_statistical import context_vector
from order_identity import client_order_id
from risk_manager import RiskDecision, RiskLimits, RiskManager, RiskSnapshot, load_daily_trade_metrics, money
from time_safety import assess_exchange_clock
from venue_config import apply_testnet_paths
from product_version import product_label, user_agent
from strategy_math import adx_from_klines as _adx_from_klines
from strategy_math import clamp, ema_series as _ema_series
from strategy_math import geometric_ladder as build_ladder_pct
from strategy_math import split_ladder
from supervisor_config import build_supervisor_parser, validate_supervisor_args

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
USER_AGENT = os.getenv("USER_AGENT", user_agent("supervisor"))

# Режим округления и тёплый старт для очистки
PRICE_ROUND_MODE = os.getenv("PRICE_ROUND_MODE", "nearest").lower()  # floor|ceil|nearest
CLEANUP_WARMUP_SEC = int(os.getenv("CLEANUP_WARMUP_SEC", "900") or 900)

SESSION = requests.Session()
if API_KEY:
    SESSION.headers.update({"X-MBX-APIKEY": API_KEY})
SESSION.headers.update({"User-Agent": USER_AGENT})

LOCK_FILE = "/tmp/ai_supervisor.lock"

LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
_CHILD_PROCS: Dict[str, subprocess.Popen] = {}
_CHILD_STARTED_AT: Dict[str, float] = {}
_CHILD_RESTART_AFTER: Dict[str, float] = {}
_CHILD_FAILURES: Dict[str, int] = {}
LIVE_MODE = False
_AI_ADVISOR: Optional[AIAdvisor] = None
_AI_DECISIONS: Optional[AdvisorDecisionStore] = None
_AI_POLICY: Optional[PolicyConfig] = None


def env_flag(name: str, default: bool = False) -> bool:
    v = os.getenv(name)
    if v is None:
        return default
    return str(v).strip().lower() in ("1", "true", "t", "yes", "y", "on")


def _build_ai_advisor(args: argparse.Namespace) -> Optional[AIAdvisor]:
    """Создать изолированный LLM-клиент без каких-либо торговых методов."""
    if not args.ai_advisor or args.ai_mode == "DISABLED":
        return None

    defaults = {
        "openai": (
            "https://api.openai.com/v1",
            "gpt-5-mini",
            "OPENAI_API_KEY",
        ),
        "deepseek": (
            "https://api.deepseek.com",
            "deepseek-v4-flash",
            "DEEPSEEK_API_KEY",
        ),
        "compatible": (
            args.ai_base_url,
            args.ai_model,
            "AI_API_KEY",
        ),
    }
    default_url, default_model, key_name = defaults[args.ai_provider]
    config = AdvisorConfig(
        enabled=True,
        provider=args.ai_provider,
        model=(args.ai_model or default_model).strip(),
        base_url=(args.ai_base_url or default_url).strip().rstrip("/"),
        api_key=os.environ[key_name],
        timeout_sec=float(args.ai_timeout_sec),
        cache_sec=int(args.ai_cache_sec),
        min_confidence=float(args.ai_min_confidence),
        width_scale_min=float(args.ai_width_scale_min),
        width_scale_max=float(args.ai_width_scale_max),
        cap_scale_min=float(args.ai_cap_scale_min),
        cap_scale_max=float(args.ai_cap_scale_max),
        usage_log_path=args.ai_usage_log,
        usage_log_max_bytes=int(args.ai_usage_log_max_bytes),
        input_cache_hit_usd_per_mtok=getenv_float(
            "AI_INPUT_CACHE_HIT_USD_PER_MTOK"
        ),
        input_cache_miss_usd_per_mtok=getenv_float(
            "AI_INPUT_CACHE_MISS_USD_PER_MTOK"
        ),
        output_usd_per_mtok=getenv_float("AI_OUTPUT_USD_PER_MTOK"),
    )
    budget = UsageBudget(
        max_requests=int(args.ai_max_requests_per_day),
        max_tokens=int(args.ai_daily_token_limit),
        max_cost_usd=Decimal(str(args.ai_daily_cost_limit_usd)),
    )

    def budget_checker() -> tuple[bool, str]:
        return usage_budget_allows(
            read_usage_today(args.ai_usage_log),
            budget,
        )

    def record_low_confidence(
        context: MarketContext,
        recommendation,
        confidence_accepted: bool,
    ) -> None:
        if confidence_accepted or _AI_DECISIONS is None:
            return
        _AI_DECISIONS.record(
            symbol=context.symbol,
            price=context.price,
            deterministic_mode=context.deterministic_mode,
            recommended_mode=recommendation.mode,
            width_scale=recommendation.ladder_width_scale,
            cap_scale=recommendation.cap_scale,
            confidence=recommendation.confidence,
            applied=False,
            policy_status="LOW_CONFIDENCE",
            policy_reasons="confidence_below_threshold",
        )

    return AIAdvisor(
        config,
        session=requests.Session(),
        logger=log,
        decision_recorder=record_low_confidence,
        budget_checker=budget_checker,
    )


def log(msg: str) -> None:
    print(msg, flush=True)

def dbg(msg: str) -> None:
    if LOG_LEVEL in ("DEBUG", "TRACE"):
        print(msg, flush=True)

# =========================
# Утилиты
# =========================

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

# ================
# Подпись запросов
# ================

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

    stats_db = os.getenv("BOT_STATS_DB", "").strip()
    if stats_db:
        try:
            with sqlite3.connect(f"file:{stats_db}?mode=ro", uri=True, timeout=3) as con:
                columns = {str(row[1]) for row in con.execute("PRAGMA table_info(inventory)")}
                qty_expr = (
                    "COALESCE(NULLIF(qty_text, ''), CAST(qty AS TEXT))"
                    if "qty_text" in columns else "CAST(qty AS TEXT)"
                )
                avg_expr = (
                    "COALESCE(NULLIF(avg_cost_text, ''), CAST(avg_cost AS TEXT))"
                    if "avg_cost_text" in columns else "CAST(avg_cost AS TEXT)"
                )
                row = con.execute(
                    f"SELECT {qty_expr}, {avg_expr} FROM inventory WHERE symbol=?",
                    (symbol.upper(),),
                ).fetchone()
            if row and Decimal(str(row[0])) > 0 and Decimal(str(row[1])) > 0:
                avg_px = float(Decimal(str(row[1])))
                _AVG_CACHE[symbol] = {"ts": now_ts, "avg": avg_px, "pos": float(row[0])}
                return avg_px
        except (OSError, sqlite3.Error, ArithmeticError, ValueError):
            pass

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
            if is_buy:
                net_q = q - commission if commission_asset == base.upper() else q
                cash_fee = commission if commission_asset == quote.upper() else 0.0
                qty += max(0.0, net_q)
                cost += p * q + cash_fee
            else:
                inventory_out = q + commission if commission_asset == base.upper() else q
                sell = min(inventory_out, qty)
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
            offladder_grace = int(
                os.getenv(
                    "START_CLEANUP_OFFLADDER_GRACE_SEC",
                    str(grace_sec if grace_sec is not None else 900),
                )
                or 0
            )

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
    offladder_grace = int(
        os.getenv("CLEANUP_OFFLADDER_GRACE_SEC", str(CLEANUP_WARMUP_SEC)) or 0
    )

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

def _schedule_child_restart(
    symbol: str,
    return_code: int,
    runtime_sec: float,
    *,
    now: Optional[float] = None,
) -> float:
    """Рассчитать backoff для нестабильного дочернего исполнителя."""
    now = time.time() if now is None else now
    stable_sec = max(1, int(os.getenv("BOT_CHILD_STABLE_SEC", "30")))
    if return_code != 0 and runtime_sec < stable_sec:
        failures = _CHILD_FAILURES.get(symbol, 0) + 1
        _CHILD_FAILURES[symbol] = failures
        base = max(1, int(os.getenv("BOT_CHILD_RESTART_BASE_SEC", "2")))
        maximum = max(base, int(os.getenv("BOT_CHILD_RESTART_MAX_SEC", "60")))
        delay = float(min(maximum, base * (2 ** min(failures - 1, 10))))
    else:
        _CHILD_FAILURES[symbol] = 0
        delay = 0.0
    _CHILD_RESTART_AFTER[symbol] = now + delay
    return delay

def run_child(symbol: str, ladder: List[float], args: argparse.Namespace,
              extra_env: Optional[Dict[str, str]] = None,
              tp1: Optional[float] = None, tp2: Optional[float] = None) -> None:
    """Запустить не более одного исполнителя на символ и учесть его прошлый exit."""
    # Сначала обслуживаем уже известный процесс. Живой не дублируем, а быстро
    # упавший переводим на экспоненциальную задержку перезапуска.
    now = time.time()
    _child = _CHILD_PROCS.get(symbol)
    if _child is not None:
        if _child.poll() is None:
            return
        return_code = _child.wait(timeout=0)
        runtime = max(0.0, now - _CHILD_STARTED_AT.pop(symbol, now))
        _CHILD_PROCS.pop(symbol, None)
        delay = _schedule_child_restart(symbol, return_code, runtime, now=now)
        if delay > 0:
            log(
                f"[CHILD-BACKOFF] {symbol} exit={return_code} runtime={runtime:.1f}s "
                f"failures={_CHILD_FAILURES[symbol]} retry_in={delay:.1f}s"
            )
            return

    restart_after = _CHILD_RESTART_AFTER.get(symbol, 0.0)
    if now < restart_after:
        return

    # Супервизор передаёт воркеру уже вычисленный торговый план. Сам воркер
    # повторно проверит CLI, LIVE-гейт, фильтры и лок конкретного символа.
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
    if args.live or getattr(args, "enforce_target_buys", False):
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
        _CHILD_STARTED_AT[symbol] = now
    except Exception as e:
        delay = _schedule_child_restart(symbol, 1, 0.0, now=now)
        log(f"[LAUNCH-ERR] {symbol} -> {e}")
        log(f"[CHILD-BACKOFF] {symbol} retry_in={delay:.1f}s")

# ===========================
# Авто-CAP на основе баланса
# ===========================

def auto_cap_if_needed(args: argparse.Namespace, n_syms: int) -> None:
    """Распределить доступный после резерва USDT между символами и BUY-слотами."""
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


def _build_ai_market_context(
    symbol: str,
    *,
    price: float,
    atr_pct: float,
    deterministic_mode: str,
    diag: Mapping[str, Any],
    ladder: tuple[float, float, float],
    target_buys: int,
) -> MarketContext:
    """Собрать ограниченные агрегаты без сырых сделок, баланса и ордер-ID."""
    low, down, up = ladder
    base: Dict[str, Any] = {
        "symbol": symbol,
        "price": float(price),
        "atr_pct": float(atr_pct),
        "deterministic_mode": deterministic_mode,
        "candidate_mode": str(diag.get("candidate", deterministic_mode)),
        "ema_gap_pct": (
            (float(diag.get("ema_fast", 0)) - float(diag.get("ema_slow", 0)))
            / max(float(price), 1e-12)
        ),
        "ema_slope": float(diag.get("slope", 0)),
        "adx": float(diag.get("adx", 0)),
        "ladder_low_pct": float(low),
        "ladder_down_pct": float(down),
        "ladder_up_pct": float(up),
        "target_buys": int(target_buys),
        "risk_safe_cap_usdt": float(
            os.getenv("BOT_CAP_PER_ORDER", "0") or 0
        ),
    }
    if _AI_DECISIONS is not None:
        try:
            def horizon_price(sym: str, target_ms: int) -> float:
                candles = TM.get_klines(
                    sym, "1m", limit=1, startTime=target_ms
                )
                if not candles:
                    raise ValueError("missing horizon candle")
                return float(candles[0][1])

            def horizon_candles(
                sym: str, start_ms: int, end_ms: int
            ) -> List[List[Any]]:
                return TM.get_klines(
                    sym,
                    "1m",
                    limit=min(1000, max(1, (end_ms - start_ms) // 60_000 + 1)),
                    startTime=start_ms,
                    endTime=end_ms,
                )

            _AI_DECISIONS.settle(
                symbol,
                price,
                price_lookup=horizon_price,
                candles_lookup=horizon_candles,
            )
        except sqlite3.Error as exc:
            dbg(f"[AI-DECISION] settle failed: {exc}")
    if _AI_ADVISOR is None or not _AI_ADVISOR.refresh_due(symbol):
        return MarketContext(**base)

    extra: Dict[str, Any] = {}
    trade_features = load_trade_features(
        os.getenv("BOT_STATS_DB", ""),
        symbol,
        price,
    )
    extra.update(asdict(trade_features))
    market_features = build_market_features(
        symbol,
        get_klines=TM.get_klines,
        public_get=TM._public_get,
    )
    extra.update(asdict(market_features))
    try:
        portfolio_features = build_portfolio_features(
            symbol,
            open_orders=list_open_orders(symbol),
            balances=get_balances_full(),
            portfolio_cap_usdt=float(
                os.getenv("RISK_PORTFOLIO_CAP_USDT", "0") or 0
            ),
            reserve_usdt=float(os.getenv("RISK_RESERVE_USDT", "0") or 0),
        )
        extra.update(asdict(portfolio_features))
    except Exception as exc:
        dbg(f"[AI-CONTEXT] portfolio aggregate unavailable: {exc}")
    if _AI_DECISIONS is not None:
        try:
            extra.update(asdict(_AI_DECISIONS.performance(symbol)))
        except sqlite3.Error as exc:
            dbg(f"[AI-DECISION] performance failed: {exc}")
    return MarketContext(**base, **extra)


def run_for_symbol(symbol: str, args: argparse.Namespace) -> None:
    """Построить план одного символа и передать его дочернему исполнителю."""
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
        _diag = {
            "ema_fast": 0.0,
            "ema_slow": 0.0,
            "slope": 0.0,
            "adx": 0.0,
            "candidate": dir_mode,
        }
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

    # Сначала формируется полностью детерминированная база. LLM получает только
    # агрегированные индикаторы и не видит API-ключи, балансы или методы ордеров.
    low, down, up = args.ladder_pct
    if args.ladder_pct_map and symbol in args.ladder_pct_map:
        low, down, up = args.ladder_pct_map[symbol]
    ai_width_scale = 1.0
    ai_cap_scale = 1.0
    ai_pause_buys = False
    if _AI_ADVISOR is not None:
        ai_context = _build_ai_market_context(
            symbol,
            price=now_p,
            atr_pct=float(atr_pct or 0),
            deterministic_mode=dir_mode,
            diag=_diag,
            ladder=(float(low), float(down), float(up)),
            target_buys=target_buys_use,
        )
        recommendation = _AI_ADVISOR.recommend(
            ai_context
        )
        if recommendation is not None:
            statistical = (
                _AI_DECISIONS.statistical_prediction(
                    ai_context,
                    min_samples=int(args.ai_min_accuracy_samples) * 2,
                )
                if _AI_DECISIONS is not None
                else {"available": False}
            )
            statistical_mode = (
                str(statistical["mode"])
                if statistical.get("available") else None
            )
            policy = apply_safety_policy(
                ai_context,
                recommendation,
                _AI_POLICY or PolicyConfig(mode="SHADOW"),
                benchmark_mode=statistical_mode,
            )
            if _AI_DECISIONS is not None:
                try:
                    _AI_DECISIONS.record(
                        symbol=symbol,
                        price=now_p,
                        deterministic_mode=dir_mode,
                        recommended_mode=policy.recommendation.mode,
                        width_scale=policy.recommendation.ladder_width_scale,
                        cap_scale=policy.recommendation.cap_scale,
                        confidence=policy.recommendation.confidence,
                        applied=policy.apply,
                        policy_status=policy.status,
                        policy_reasons=",".join(policy.reasons),
                        benchmark_mode=policy.benchmark_mode,
                        feature_json=json.dumps(context_vector(ai_context)),
                    )
                except sqlite3.Error as exc:
                    dbg(f"[AI-DECISION] record failed: {exc}")
            if policy.apply:
                if args.dir_mode == "auto":
                    dir_mode = policy.recommendation.mode
                ai_width_scale = policy.recommendation.ladder_width_scale
                ai_cap_scale = policy.recommendation.cap_scale
                ai_pause_buys = policy.pause_buys
            log(
                f"[AI-ADVISOR] {symbol} provider={recommendation.provider} "
                f"model={recommendation.model} status={policy.status} "
                f"confidence={recommendation.confidence:.2f} "
                f"mode={policy.recommendation.mode} benchmark={policy.benchmark_mode} "
                f"stat_samples={statistical.get('samples', 0)} "
                f"width×{policy.recommendation.ladder_width_scale:.2f} "
                f"cap×{policy.recommendation.cap_scale:.2f} "
                f"guards={','.join(policy.reasons) or 'none'} "
                f"reason={recommendation.rationale}"
            )

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
    low *= ai_width_scale
    down *= ai_width_scale
    up *= ai_width_scale
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

    # AI может только уменьшить уже безопасный CAP. Даже если модель вернула
    # коэффициент > 1, верхней границей остаётся расчёт Risk Manager.
    risk_safe_cap = float(os.getenv("BOT_CAP_PER_ORDER", "0") or 0)
    if risk_safe_cap > 0:
        advised_cap = limit_cap_by_recommendation(risk_safe_cap, ai_cap_scale)
        extra_env["BOT_CAP_PER_ORDER"] = f"{advised_cap:.8f}"

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

    ladder_for_child = (
        ladder_all
        if mode not in ("reduce_only", "flattening") and not ai_pause_buys
        else _prune_to_sells_only(now_p, ladder_all)
    )
    if ai_pause_buys:
        log(f"[AI-POLICY] {symbol} PAUSE_BUYS: child receives SELL levels only")

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


def _configure_venue(args: argparse.Namespace) -> None:
    """Выбрать testnet/mainnet до первого аутентифицированного запроса."""
    global BINANCE_API_BASE, API_KEY, API_SECRET
    if args.testnet:
        base = os.getenv("BINANCE_TESTNET_API_BASE", "https://testnet.binance.vision").rstrip("/")
        key = os.getenv("BINANCE_TESTNET_API_KEY", "")
        secret = os.getenv("BINANCE_TESTNET_API_SECRET", "")
        apply_testnet_paths()
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
    """Показать экспозицию и отказать в LIVE, пока не доказана готовность систем."""
    limits.validate()
    stats_db = os.getenv("BOT_STATS_DB", "").strip()
    cap = float(args.cap_ceil_usdt or os.getenv("BOT_CAP_PER_ORDER", "50"))
    theoretical = cap * args.target_buy_per_symbol * len(symbols)
    max_exposure = min(
        theoretical,
        float(limits.portfolio_cap_usdt),
        float(limits.daily_buy_cap_usdt),
        float(limits.correlated_cap_usdt),
    )
    config = {
        "mode": "LIVE" if args.live else "DRY",
        "venue": "testnet" if args.testnet else "mainnet",
        "symbols": symbols,
        "target_buys_per_symbol": args.target_buy_per_symbol,
        "cap_per_order_usdt": cap,
        "max_new_buy_exposure_usdt": round(max_exposure, 2),
        "portfolio_cap_usdt": str(limits.portfolio_cap_usdt),
        "daily_buy_cap_usdt": str(limits.daily_buy_cap_usdt),
        "correlated_cap_usdt": str(limits.correlated_cap_usdt),
        "reserve_usdt": str(limits.reserve_usdt),
        "stats_db": stats_db or None,
    }
    log("[CONFIG] " + json.dumps(config, sort_keys=True))
    # DRY тоже печатает итоговую конфигурацию, но не требует торговых ключей.
    if not args.live:
        return
    if limits.halt_file.exists():
        log(
            f"[PREFLIGHT] persistent halt detected at {limits.halt_file}; "
            "supervisor will only reconcile and cancel BUY until manual reset"
        )
    if not TM.API_KEY or not TM.API_SECRET:
        prefix = "BINANCE_TESTNET" if args.testnet else "BINANCE"
        raise RuntimeError(f"{prefix}_API_KEY/SECRET are required for LIVE mode")

    if not stats_db:
        raise RuntimeError("BOT_STATS_DB is required for fail-closed LIVE mode")
    import tools_stats
    con = tools_stats.init_db(stats_db)
    try:
        con.execute("SELECT 1 FROM trades LIMIT 1").fetchall()
    finally:
        con.close()

    # Проверяем не только offset часов, но и RTT: при медленной сети оценка
    # серверного времени недостаточно надёжна для подписанных ордеров.
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

    log("[PREFLIGHT] PASS " + json.dumps(config, sort_keys=True))


def _stop_children(reason: str) -> None:
    """Остановить всех воркеров с terminate → wait → kill fallback."""
    for symbol, proc in list(_CHILD_PROCS.items()):
        try:
            if proc.poll() is None:
                log(f"[RISK] stop child {symbol} pid={proc.pid}: {reason}")
                proc.terminate()
                try:
                    proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    log(f"[RISK] kill unresponsive child {symbol} pid={proc.pid}")
                    proc.kill()
                    proc.wait(timeout=2)
            else:
                proc.wait(timeout=0)
        except (OSError, subprocess.SubprocessError) as exc:
            log(f"[RISK] child cleanup failed {symbol} pid={proc.pid}: {exc}")
        finally:
            _CHILD_PROCS.pop(symbol, None)
            _CHILD_STARTED_AT.pop(symbol, None)
            _CHILD_RESTART_AFTER.pop(symbol, None)
            _CHILD_FAILURES.pop(symbol, None)


def _cancel_open_buy_orders(orders: Optional[List[Dict[str, Any]]] = None) -> int:
    """Отменить только BUY; защитные SELL/OCO должны продолжать работать."""
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
    """Зафиксировать точную причину risk-решения и опционально вызвать webhook."""
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
    """Собрать согласованный снимок account, ledger, ордеров и дневных метрик."""
    balances = get_balances_full()
    prices = {symbol: get_last_price(symbol) for symbol in symbols}
    orders = TM._signed_get("/api/v3/openOrders") or []

    # Строгая сверка не позволяет строить risk snapshot на расходящихся данных
    # Binance account и локального inventory ledger.
    if env_flag("RISK_RECONCILE_STRICT", True):
        tolerance = max(0.0, float(os.getenv("RISK_RECONCILE_TOLERANCE_PCT", "0.02") or 0.02))
        grace_sec = max(0.0, float(os.getenv("RISK_RECONCILE_GRACE_SEC", "5") or 5))
        retry_sec = max(0.05, float(os.getenv("RISK_RECONCILE_RETRY_SEC", "0.25") or 0.25))
        dust_steps = max(0.0, float(os.getenv("RISK_RECONCILE_DUST_STEPS", "1") or 1))
        deadline = time.monotonic() + grace_sec
        waited = False
        while True:
            with sqlite3.connect(f"file:{os.environ['BOT_STATS_DB']}?mode=ro", uri=True, timeout=5) as con:
                inventory_columns = {
                    str(row[1]) for row in con.execute("PRAGMA table_info(inventory)")
                }
                qty_expression = (
                    "COALESCE(NULLIF(qty_text, ''), CAST(qty AS TEXT))"
                    if "qty_text" in inventory_columns
                    else "CAST(qty AS TEXT)"
                )
                inventory = {
                    str(symbol).upper(): float(qty)
                    for symbol, qty in con.execute(
                        f"SELECT symbol, {qty_expression} FROM inventory"
                    ).fetchall()
                }
            mismatches = []
            for symbol in symbols:
                base, _ = symbol_assets(symbol)
                account_qty = float(balances.get(base, {}).get("free", 0)) + float(balances.get(base, {}).get("locked", 0))
                db_qty = inventory.get(symbol)
                step_size = max(0.0, float(get_exchange_filters_cached(symbol).get("stepSize", 0.0)))
                allowed = max(1e-8, abs(account_qty) * tolerance, step_size * dust_steps)
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
            # Пока ledger догонял account, воркер мог создать OCO. Перечитываем
            # ордера, чтобы exposure и их количество относились к одному моменту.
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
    """Главный orchestration loop: preflight → risk gate → планы → воркеры."""
    ap = build_supervisor_parser()
    args = ap.parse_args()
    log(f"[VERSION] {product_label('supervisor')}")
    symbols = validate_supervisor_args(ap, args)
    _configure_venue(args)
    global _AI_ADVISOR, _AI_DECISIONS, _AI_POLICY
    decisions_db = (
        os.getenv("AI_TESTNET_DECISIONS_DB", "").strip()
        if args.testnet else args.ai_decisions_db
    ) or args.ai_decisions_db
    _AI_DECISIONS = (
        AdvisorDecisionStore(decisions_db)
        if args.ai_advisor else None
    )
    _AI_POLICY = PolicyConfig(
        mode=args.ai_mode if args.ai_advisor else "DISABLED",
        max_market_age_sec=float(args.ai_max_market_age_sec),
        max_portfolio_age_sec=float(args.ai_max_portfolio_age_sec),
        max_spread_bps=float(args.ai_max_spread_bps),
        high_volatility_pct=float(args.ai_high_volatility_pct),
        max_consecutive_losses=int(
            os.getenv("RISK_MAX_CONSECUTIVE_LOSSES", "3") or 3
        ),
        min_trade_sells=int(args.ai_min_trade_sells),
        min_accuracy_samples=int(args.ai_min_accuracy_samples),
        min_ai_accuracy=float(args.ai_min_accuracy),
    )
    _AI_ADVISOR = _build_ai_advisor(args)
    limits = RiskLimits.from_env()
    _preflight_live(args, symbols, limits)
    global LIVE_MODE
    LIVE_MODE = bool(args.live)
    # В DRY circuit breaker не меняет постоянное состояние. LIVE использует
    # fail-closed менеджер и не запускает воркеры без свежего risk snapshot.
    risk_manager = RiskManager(limits) if args.live else None

    ai_label = (
        f"{args.ai_mode}:{_AI_ADVISOR.config.provider}/{_AI_ADVISOR.config.model}"
        if _AI_ADVISOR is not None else "disabled"
    )
    log(
        f"[SUP] symbols={symbols} ladder_mode={args.ladder_mode} "
        f"ai_advisor={ai_label}"
    )

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
                # Проверка риска выполняется раньше планирования символов. При любом
                # запрете останавливаем воркеры и отменяем только новые BUY.
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
                        # CAP дополнительно сужается по минимальному оставшемуся
                        # бюджету: portfolio, daily BUY, correlation и reserve.
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
                    # Недоступная telemetry не считается безопасным состоянием:
                    # новые BUY блокируются, после серии ошибок включается cooldown.
                    consecutive_api_failures += 1
                    threshold = max(1, int(os.getenv("RISK_API_FAILURE_THRESHOLD", "3")))
                    reason = f"risk telemetry unavailable ({consecutive_api_failures}/{threshold}): {exc}"
                    if consecutive_api_failures >= threshold:
                        risk_manager.start_cooldown(reason)
                    decision = RiskDecision(halted=False, buy_blocked=True, reasons=(reason,))

                was_buy_blocked = risk_buy_blocked
                risk_buy_blocked = decision.buy_blocked
                if risk_buy_blocked:
                    reason = "; ".join(decision.reasons) or "risk limit"
                    if risk_manager is not None and not decision.halted and not was_buy_blocked:
                        risk_manager.start_cooldown(reason)
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
                # Во время блока супервизор только переоценивает риск; торговые
                # планы не строятся до явного безопасного решения.
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
    except KeyboardInterrupt:
        log("[SUP] shutdown requested")
    finally:
        _stop_children("supervisor shutdown")
        try:
            if os.path.exists(LOCK_FILE):
                os.remove(LOCK_FILE)
                log(f"[stop-all] lock удалён ({LOCK_FILE})")
        except Exception:
            pass

if __name__ == "__main__":
    main()
