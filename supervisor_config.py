"""CLI construction and strict validation for the trading supervisor."""

from __future__ import annotations

import argparse
import os
import re
from pathlib import Path
from typing import List

from product_version import product_label


def env_flag(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in ("1", "true", "t", "yes", "y", "on")


def build_supervisor_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description="Ladder Dragon trading supervisor")
    ap.add_argument("--version", action="version", version=product_label("supervisor"))
    ap.add_argument("--singleton", action="store_true", help="разрешить только один экземпляр (lock в /tmp)")
    ap.add_argument("--base-script", default="/home/bot/apps/binance_bot/autosize_universal.py")
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

    # LLM используется только как рекомендательный слой. Ключи принимаются
    # исключительно через окружение и никогда не попадают в argv/process list.
    ap.add_argument("--ai-advisor", action="store_true", default=env_flag("AI_ADVISOR_ENABLE", False),
                    help="Включить рекомендательный LLM-слой без доступа к ордерам")
    ap.add_argument("--no-ai-advisor", action="store_false", dest="ai_advisor")
    ap.add_argument("--ai-provider", choices=["openai", "deepseek", "compatible"],
                    default=os.getenv("AI_PROVIDER", "deepseek"))
    ap.add_argument("--ai-mode", choices=["DISABLED", "SHADOW", "APPLY"],
                    default=os.getenv("AI_MODE", "SHADOW").upper())
    ap.add_argument("--ai-model", default=os.getenv("AI_MODEL", ""))
    ap.add_argument("--ai-base-url", default=os.getenv("AI_BASE_URL", ""))
    ap.add_argument("--ai-timeout-sec", type=float, default=float(os.getenv("AI_TIMEOUT_SEC", "10")))
    ap.add_argument("--ai-cache-sec", type=int, default=int(os.getenv("AI_CACHE_SEC", "300")))
    ap.add_argument("--ai-min-confidence", type=float, default=float(os.getenv("AI_MIN_CONFIDENCE", "0.65")))
    ap.add_argument("--ai-width-scale-min", type=float, default=float(os.getenv("AI_WIDTH_SCALE_MIN", "0.75")))
    ap.add_argument("--ai-width-scale-max", type=float, default=float(os.getenv("AI_WIDTH_SCALE_MAX", "1.50")))
    ap.add_argument("--ai-cap-scale-min", type=float, default=float(os.getenv("AI_CAP_SCALE_MIN", "0.25")))
    ap.add_argument("--ai-cap-scale-max", type=float, default=float(os.getenv("AI_CAP_SCALE_MAX", "1.25")))
    ap.add_argument("--ai-usage-log", default=os.getenv("AI_USAGE_LOG", ".runtime/ai_usage.ndjson"))
    ap.add_argument("--ai-usage-log-max-bytes", type=int,
                    default=int(os.getenv("AI_USAGE_LOG_MAX_BYTES", "5242880")))
    ap.add_argument("--ai-decisions-db",
                    default=os.getenv("AI_DECISIONS_DB", ".runtime/ai_decisions.sqlite3"))
    ap.add_argument("--ai-daily-cost-limit-usd", type=float,
                    default=float(os.getenv("AI_DAILY_COST_LIMIT_USD", "0.05")))
    ap.add_argument("--ai-daily-token-limit", type=int,
                    default=int(os.getenv("AI_DAILY_TOKEN_LIMIT", "100000")))
    ap.add_argument("--ai-max-requests-per-day", type=int,
                    default=int(os.getenv("AI_MAX_REQUESTS_PER_DAY", "1000")))
    ap.add_argument("--ai-max-market-age-sec", type=float,
                    default=float(os.getenv("AI_MAX_MARKET_AGE_SEC", "30")))
    ap.add_argument("--ai-max-portfolio-age-sec", type=float,
                    default=float(os.getenv("AI_MAX_PORTFOLIO_AGE_SEC", "30")))
    ap.add_argument("--ai-max-spread-bps", type=float,
                    default=float(os.getenv("AI_MAX_SPREAD_BPS", "25")))
    ap.add_argument("--ai-high-volatility-pct", type=float,
                    default=float(os.getenv("AI_HIGH_VOLATILITY_PCT", "0.04")))
    ap.add_argument("--ai-min-trade-sells", type=int,
                    default=int(os.getenv("AI_MIN_TRADE_SELLS", "20")))
    ap.add_argument("--ai-min-accuracy-samples", type=int,
                    default=int(os.getenv("AI_MIN_ACCURACY_SAMPLES", "30")))
    ap.add_argument("--ai-min-accuracy", type=float,
                    default=float(os.getenv("AI_MIN_ACCURACY", "0.50")))

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

    return ap


def validate_supervisor_args(parser: argparse.ArgumentParser, args: argparse.Namespace) -> List[str]:
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
        "--ai-cache-sec": args.ai_cache_sec,
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
    if args.ai_timeout_sec <= 0:
        parser.error("--ai-timeout-sec must be > 0")
    if args.ai_usage_log_max_bytes <= 0:
        parser.error("--ai-usage-log-max-bytes must be > 0")
    if min(args.ai_daily_cost_limit_usd, args.ai_daily_token_limit, args.ai_max_requests_per_day) < 0:
        parser.error("AI daily budgets must be >= 0")
    if min(
        args.ai_max_market_age_sec,
        args.ai_max_portfolio_age_sec,
        args.ai_max_spread_bps,
        args.ai_high_volatility_pct,
    ) <= 0:
        parser.error("AI safety thresholds must be > 0")
    if min(args.ai_min_trade_sells, args.ai_min_accuracy_samples) < 0:
        parser.error("AI sample thresholds must be >= 0")
    if not 0 <= args.ai_min_accuracy <= 1:
        parser.error("--ai-min-accuracy must be in [0, 1]")
    if not 0 <= args.ai_min_confidence <= 1:
        parser.error("--ai-min-confidence must be in [0, 1]")
    if not 0 < args.ai_width_scale_min <= args.ai_width_scale_max <= 3:
        parser.error("AI width bounds must satisfy 0 < min <= max <= 3")
    if not 0 < args.ai_cap_scale_min <= args.ai_cap_scale_max <= 2:
        parser.error("AI CAP bounds must satisfy 0 < min <= max <= 2")
    if args.ai_advisor:
        if args.ai_base_url and not args.ai_base_url.startswith("https://"):
            parser.error("--ai-base-url must use https://")
        key_name = {
            "openai": "OPENAI_API_KEY",
            "deepseek": "DEEPSEEK_API_KEY",
            "compatible": "AI_API_KEY",
        }[args.ai_provider]
        if not os.getenv(key_name, ""):
            parser.error(f"--ai-advisor requires {key_name}")
        if args.ai_provider == "compatible" and (
            not args.ai_base_url or not args.ai_model
        ):
            parser.error(
                "compatible AI provider requires --ai-base-url and --ai-model"
            )

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
    if not Path(args.base_script).is_file():
        parser.error(f"--base-script does not exist: {args.base_script}")
    return symbols
