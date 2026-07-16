"""Построение и строгая валидация CLI символьного исполнителя.

Все ошибки конфигурации должны завершать процесс до чтения баланса и тем более
до торговых запросов. Поэтому parser и проверки отделены от runtime-цикла.
"""

from __future__ import annotations

import argparse
import os
import re

from product_version import product_label


def build_executor_parser() -> argparse.ArgumentParser:
    """Создать единственный канонический parser исполнителя."""
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
    parser.add_argument("--oco-fallback", type=str, choices=("halt", "prefer-tp1"), default="halt")
    parser.add_argument("--max-holding-minutes", type=int, default=0,
                        help="LIVE time-stop; 0 disables the additional guard")
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

    return parser
def validate_executor_args(
    parser: argparse.ArgumentParser,
    args: argparse.Namespace,
) -> argparse.Namespace:
    """Нормализовать аргументы и fail-fast отклонить опасные сочетания."""
    # Одного --live недостаточно: оператор обязан явно подтвердить включение
    # мутаций через окружение конкретного процесса.
    if args.live and os.getenv("BOT_LIVE_CONFIRMED", "") != "YES":
        parser.error("--live requires BOT_LIVE_CONFIRMED=YES")
    if args.live and args.oco_fallback == "prefer-tp1":
        parser.error("--oco-fallback=prefer-tp1 запрещён в LIVE: позиция останется без стопа")
    if args.max_holding_minutes < 0:
        parser.error("--max-holding-minutes must be >= 0")
    args.symbol = args.symbol.strip().upper()
    if not re.fullmatch(r"[A-Z0-9]{5,20}", args.symbol):
        parser.error("--symbol must be a valid uppercase Binance symbol")
    if args.target_buy_per_symbol <= 0 or args.loop_minutes <= 0:
        parser.error("target and loop limits must be > 0")
    if args.cap_floor_usdt is not None and args.cap_floor_usdt < 0:
        parser.error("--cap-floor-usdt must be >= 0")
    if args.min_order_usdt is not None and args.min_order_usdt <= 0:
        parser.error("--min-order-usdt must be > 0")
    if not 0 <= args.stop_limit_offset_pct < 0.25:
        parser.error("--stop-limit-offset-pct must be in [0, 0.25)")
    return args
