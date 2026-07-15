#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ladder_pct_runner.py — адаптирован под исполнителя 1.8:
- Геометрическая сетка по модулю процентов (устойчивое geomspace)
- BUY округляем вниз, SELL вверх по tickSize
- Дедуп + порядок: BUY (ближние→дальние), затем SELL (ближние→дальние)

Фильтрация/ограничения:
  • --one-side buys|sells|both
  • --min-ticks-gap K        (K*tickSize между соседними уровнями)
  • --min-abs-gap-pct P      (минимальная относительная дистанция между соседями, %)
  • --min-buy-offset-pct X   (отступ: не ставить BUY ближе, чем X% ниже цены)
  • --min-sell-offset-pct Y  (отступ: не ставить SELL ближе, чем Y% выше цены)
  • --min-order-usdt V       (оценочный CAP для проверки против minNotional)
  • --strict-minnotional     (жёстко валидировать CAP ≥ minNotional, иначе выход с ошибкой)
  • --kill-if-empty          (завершить с ошибкой, если уровней не осталось)
  • --nudge-first-sell       (если первый SELL ≤ текущей цены, поджать его на +1*tick)
  • --nudge-first-buy        (если первый BUY ≥ текущей цены, поджать его на -1*tick)
"""

import os, sys, argparse, subprocess
from decimal import Decimal, getcontext
getcontext().prec = 28

from dotenv import load_dotenv
load_dotenv()

# общий модуль работы с Binance
import tools_market as TM


def die(msg, code=2):
    print("[ERR]", msg, file=sys.stderr); sys.exit(code)


def round_down_to_step(value: Decimal, step: Decimal) -> Decimal:
    if step is None or step <= 0: return value
    return (value // step) * step


def round_up_to_step(value: Decimal, step: Decimal) -> Decimal:
    if step is None or step <= 0: return value
    if (value % step) == 0: return value
    return ((value // step) + 1) * step


def fmt_decimal(d: Decimal) -> str:
    s = f"{d.normalize():f}"
    return s.rstrip('0').rstrip('.') if '.' in s else s


def calc_atr(symbol: str, interval: str = "1h", window: int = 14) -> float:
    """
    ATR по TM.get_klines() с авто-нормализацией интервала (алиасы типа '1hour', '8hours' и т.п.).
    """
    k = TM.get_klines(symbol, interval, limit=max(window + 2, 16))
    if not k or len(k) < 2:
        return 0.0
    highs = [float(x[2]) for x in k]
    lows  = [float(x[3]) for x in k]
    closes= [float(x[4]) for x in k]
    trs = []
    for i in range(1, len(k)):
        h,l,c_prev = highs[i], lows[i], closes[i-1]
        trs.append(max(h-l, abs(h-c_prev), abs(l-c_prev)))
    return sum(trs)/len(trs) if trs else 0.0


def parse_args():
    p = argparse.ArgumentParser()
    p.add_argument("--symbol", required=True)
    # Формат: -min%,-max%,[density]  (пример: -0.5,-20,20)
    p.add_argument("--ladder-pct", type=str, default="-0.5,-20,20")
    p.add_argument("--grid-density", type=int, default=20)  # запасной, если в ladder-pct нет density
    p.add_argument("--base-script", type=str, default="1.8_autosize_universal.py")
    p.add_argument("--kill-if-empty", action="store_true",
                   help="Завершить с ошибкой, если после фильтрации не осталось уровней.")

    # Управление стороной и расстояниями
    p.add_argument("--one-side", choices=("buys","sells","both"), default="both",
                   help="Оставить только покупки, только продажи или обе стороны.")
    p.add_argument("--min-ticks-gap", type=int, default=0,
                   help="Минимальная дистанция между соседними уровнями в тик-сайзах (0 = без ограничения).")
    p.add_argument("--min-abs-gap-pct", type=float, default=0.0,
                   help="Минимальная относительная дистанция между соседними уровнями, в % (0 = без ограничения).")
    p.add_argument("--min-buy-offset-pct", type=float, default=0.0,
                   help="Не ставить BUY ближе, чем X%% ниже текущей цены.")
    p.add_argument("--min-sell-offset-pct", type=float, default=0.0,
                   help="Не ставить SELL ближе, чем Y%% выше текущей цены.")
    p.add_argument("--nudge-first-sell", action="store_true",
                    help="Если первый SELL ≤ now, поджать на +1*tick.")
    p.add_argument("--nudge-first-buy", action="store_true",
                    help="Если первый BUY ≥ now, поджать на -1*tick.")

    # Валидация против minNotional
    p.add_argument("--min-order-usdt", type=float, default=None,
                   help="Оценочный CAP на ордер в USDT (для сравнения с minNotional).")
    p.add_argument("--strict-minnotional", action="store_true",
                   help="Если CAP < minNotional — завершить с ошибкой (не отдавать уровни).")

    # passthrough к исполнителю:
    p.add_argument("--live", action="store_true")
    p.add_argument("--only-new-fills", action="store_true")
    p.add_argument("--max-oco-per-symbol", type=int, default=4)
    p.add_argument("--tp1", type=float, default=0.08)
    p.add_argument("--tp2", type=float, default=0.08)
    p.add_argument("--sl",  type=float, default=-0.015)
    p.add_argument("--status-interval", type=int, default=1)
    p.add_argument("--loop-minutes", type=int, default=5)
    return p.parse_args()


def _filters_decimal(symbol: str) -> dict:
    """
    Берём фильтры из TM.get_symbol_filters() и конвертируем нужные поля в Decimal,
    чтобы вся математика ниже оставалась точной.
    """
    f = TM.get_symbol_filters(symbol)
    D = Decimal
    try:
        tick = D(str(f.get("tickSize") or "0.01"))
        if tick <= 0:
            die(f"Invalid tickSize for {symbol}: {tick}", code=6)
    except Exception as e:
        die(f"Bad filters for {symbol}: {e}", code=6)
    out = {
        "tickSize": D(str(f.get("tickSize", "0.01") or "0.01")),
        "stepSize": D(str(f.get("stepSize", "0") or "0")) if f.get("stepSize") else None,
        "minQty":   D(str(f.get("minQty", "0") or "0"))   if f.get("minQty")   else None,
        "minNotional": D(str(f.get("minNotional", "5") or "5")),
    }
    return out


def _now_price_decimal(symbol: str) -> Decimal:
    try:
        px = TM.get_ticker_price(symbol)
        return Decimal(str(px))
    except TM.BinanceHttpError as e:
        die(f"Failed to fetch ticker price: {e}")


def main():
    try:
        import numpy as np
    except Exception as e:
        die(f"NumPy is required: pip install numpy ({e})", code=5)
    args = parse_args()
    symbol = args.symbol.upper()

    # ladder-pct
    try:
        D_ = Decimal
        raw = [x.strip() for x in args.ladder_pct.split(",") if x.strip() != ""]
        if len(raw) not in (2,3): die("ladder-pct должен быть '-min%,-max%,[density]'. Пример: -0.5,-20,20")
        min_pct_in, max_pct_in = D_(raw[0]), D_(raw[1])
        density = int(raw[2]) if len(raw) == 3 else int(args.grid_density)
        density = max(2, min(density, 256))
        if not (min_pct_in < 0 and max_pct_in < 0 and abs(max_pct_in) >= abs(min_pct_in)):
            die("Ожидается: оба процента отрицательные и |max|>=|min| (например -0.5,-20)")
    except Exception:
        die("bad --ladder-pct format")

    now  = _now_price_decimal(symbol)
    flt  = _filters_decimal(symbol)
    tick = flt["tickSize"]

    # ATR-скейл (мягкий)
    atr_abs = calc_atr(symbol)
    atr_pct = (atr_abs / float(now)) if now > 0 else 0.0
    scale_factor = Decimal(str(1 + atr_pct * 0.5))  # 50% ATR к диапазону

    min_pct = (min_pct_in * scale_factor)  # отрицательные
    max_pct = (max_pct_in * scale_factor)

    # Геометрия по модулю
    start_mag = float(abs(min_pct))
    stop_mag  = float(abs(max_pct))
    if abs(start_mag - stop_mag) < 1e-12:
        mags = [start_mag] * density
    else:
        mags = np.geomspace(start_mag, stop_mag, num=density).tolist()

    buy_pcts  = [-Decimal(str(m)) for m in mags]   # вниз
    sell_pcts = [ Decimal(str(m)) for m in mags]   # вверх

    # Уровни
    buy_levels  = [now * (Decimal(1) + p/Decimal(100)) for p in buy_pcts]
    sell_levels = [now * (Decimal(1) + p/Decimal(100)) for p in sell_pcts]

    # Округление
    buy_q  = [round_down_to_step(lv, tick) for lv in buy_levels]
    sell_q = [round_up_to_step(lv,   tick) for lv in sell_levels]

    # Дедуп по строковому представлению (после округления)
    def uniq_keep(seq):
        seen, out = set(), []
        for x in seq:
            k = fmt_decimal(x)
            if k not in seen:
                seen.add(k); out.append(x)
        return out

    buy_q  = uniq_keep(buy_q)
    sell_q = uniq_keep(sell_q)

    # Отступы от цены
    mb = Decimal(str(max(0.0, args.min_buy_offset_pct)))
    ms = Decimal(str(max(0.0, args.min_sell_offset_pct)))
    if mb > 0:
        buy_threshold = now * (Decimal(1) - mb/Decimal(100))
        buy_q = [lv for lv in buy_q if lv <= buy_threshold]
    if ms > 0:
        sell_threshold = now * (Decimal(1) + ms/Decimal(100))
        sell_q = [lv for lv in sell_q if lv >= sell_threshold]

    # Порядок для воркера
    buy_q_sorted  = sorted(buy_q,  reverse=True)
    sell_q_sorted = sorted(sell_q, reverse=False)

    # Минимальная дистанция: тиковая
    def thin_ticks(seq, tick, min_ticks: int) -> list[Decimal]:
        if min_ticks <= 0 or tick <= 0 or len(seq) <= 1:
            return seq
        out, last = [], None
        gap = tick * Decimal(min_ticks)
        for x in seq:
            if last is None or abs(x - last) >= gap:
                out.append(x); last = x
        return out

    buy_q_sorted  = thin_ticks(buy_q_sorted,  tick, int(args.min_ticks_gap))
    sell_q_sorted = thin_ticks(sell_q_sorted, tick, int(args.min_ticks_gap))

    # Минимальная дистанция: абсолютная относительная (в %)
    def thin_abs_pct(seq, min_pct_gap: Decimal) -> list[Decimal]:
        if min_pct_gap <= 0 or len(seq) <= 1:
            return seq
        out, last = [], None
        for x in seq:
            if last is None:
                out.append(x); last = x
            else:
                rel = abs((x - last) / last) * Decimal(100)  # относит. зазор к предыдущему сохранённому
                if rel >= min_pct_gap:
                    out.append(x); last = x
        return out

    gap_pct = Decimal(str(max(0.0, args.min_abs_gap_pct)))
    buy_q_sorted  = thin_abs_pct(buy_q_sorted,  gap_pct)
    sell_q_sorted = thin_abs_pct(sell_q_sorted, gap_pct)

    # Валидация против minNotional
    eff_order_usdt = None
    if args.min_order_usdt and args.min_order_usdt > 0:
        eff_order_usdt = Decimal(str(args.min_order_usdt))
    else:
        cap_env = os.getenv("BOT_CAP_PER_ORDER")
        if cap_env:
            try: eff_order_usdt = Decimal(str(cap_env))
            except: eff_order_usdt = None

    if eff_order_usdt is not None and flt["minNotional"] is not None and flt["minNotional"] > 0:
        min_not = flt["minNotional"]
        if eff_order_usdt < min_not:
            msg = (f"effective order USDT ({fmt_decimal(eff_order_usdt)}) ниже minNotional "
                   f"({fmt_decimal(min_not)}).")
            if args.strict_minnotional:
                die(msg + " Прекращаю работу из-за --strict-minnotional.", code=3)
            else:
                print("[WARN]", msg, "Рассмотрите увеличение CAP.")

    # --- Автоподжим ближайшего уровня(ей), если включено ---
    def reflow_side(seq, ascending: bool) -> list[Decimal]:
        """Пересобрать сторону: сортировка, dedup, тиковый и процентный GAP — в исходном порядке."""
        seq_sorted = sorted(seq, reverse=not ascending)
        seq_sorted = thin_ticks(seq_sorted, tick, int(args.min_ticks_gap))
        seq_sorted = thin_abs_pct(seq_sorted, gap_pct)
        return seq_sorted

    # SELL nudge: после nudged учесть минимальный оффсет
    if args.nudge_first_sell and sell_q_sorted:
        if tick > 0 and sell_q_sorted[0] <= now:
            nudged = round_up_to_step(now + tick, tick)
            # соблюдение min-sell-offset-pct, если он задан
            if ms > 0:
                sell_threshold = now * (Decimal(1) + ms/Decimal(100))
                if nudged < sell_threshold:
                    nudged = round_up_to_step(sell_threshold, tick)
            if nudged > sell_q_sorted[0]:
                sell_q_sorted[0] = nudged
                sell_q_sorted = reflow_side(sell_q_sorted, ascending=True)

    # BUY nudge: после nudged учесть минимальный оффсет
    if args.nudge_first_buy and buy_q_sorted:
        if tick > 0 and buy_q_sorted[0] >= now:
            nudged = round_down_to_step(now - tick, tick)
            if mb > 0:
                buy_threshold = now * (Decimal(1) - mb/Decimal(100))
                if nudged > buy_threshold:  # для BUY нужно быть НЕ БЛИЖЕ, т.е. ≤ порога
                    nudged = round_down_to_step(buy_threshold, tick)
            if nudged < buy_q_sorted[0]:
                buy_q_sorted[0] = nudged
                buy_q_sorted = reflow_side(buy_q_sorted, ascending=False)

    # Применить --one-side
    if args.one_side == "buys":
        levels_all = buy_q_sorted
    elif args.one_side == "sells":
        levels_all = sell_q_sorted
    else:
        levels_all = buy_q_sorted + sell_q_sorted

    # Если после фильтров не осталось уровней — действуем согласно флагу
    if not levels_all:
        msg = f"[EMPTY] {symbol}: нет уровней после фильтрации."
        if args.kill_if_empty:
            die(msg + " Завершаю (--kill-if-empty).", code=4)
        else:
            print("[WARN]", msg, "Пропускаю запуск исполнителя для этого символа.")
            return 0  # мягкий выход без запуска

    levels_str = ",".join(fmt_decimal(lv) for lv in levels_all)

    print(f"[LADDER] {symbol} now≈{fmt_decimal(now)}  "
          f"pct_in={min_pct_in},{max_pct_in}  scaled={fmt_decimal(min_pct)},{fmt_decimal(max_pct)}  "
          f"ATR%={atr_pct:.4f}  counts(buy/sell)={len(buy_q_sorted)}/{len(sell_q_sorted)} total={len(levels_all)}  "
          f"one_side={args.one_side} gap={args.min_ticks_gap}t/{float(gap_pct):.3f}% "
          f"offsets(buy/sell)={float(mb):.3f}%/{float(ms):.3f}% "
          f"nudge(buy/sell)={'Y' if args.nudge_first_buy else 'N'}/{'Y' if args.nudge_first_sell else 'N'}")

    print(f"[FILTERS] tickSize={fmt_decimal(tick)} minNotional={fmt_decimal(flt['minNotional'])}"
          + (f" stepSize={fmt_decimal(flt['stepSize'])}" if flt['stepSize'] else ""))

    # Команда исполнителя
    cmd = ["python3", "-u", args.base_script, "--symbol", symbol, "--ladder-prices", levels_str]
    if args.live: cmd.append("--live")
    if args.only_new_fills: cmd.append("--only-new-fills")
    cmd += ["--max-oco-per-symbol", str(args.max_oco_per_symbol)]
    cmd += ["--tp1", str(args.tp1), "--tp2", str(args.tp2), "--sl", str(args.sl)]
    cmd += ["--status-interval", str(args.status_interval), "--loop-minutes", str(args.loop_minutes)]

    print("[LAUNCH]", " ".join(cmd))
    try:
        res = subprocess.run(cmd, check=False)
        sys.exit(res.returncode)
    except KeyboardInterrupt:
        print("\n[INTERRUPTED] Stopped by user."); sys.exit(130)


if __name__ == "__main__":
    main()
