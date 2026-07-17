#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# Copyright (c) 2026 IURII Potekhin / Ladder Dragon. All rights reserved.
# Назначение файла и опасные границы логики должны оставаться понятными при сопровождении.
"""
pnl_reporter.py — отчёт по реализованному PnL (FIFO) для спот-сделок на Binance.

Что делает:
- Тянет сделки по /api/v3/myTrades для заданных символов и периода.
- Умеет длинные периоды: режет запросы на окна ≤ 24 часов (требование Binance).
- Пагинация внутри окна по времени (cursor = last_time+1).
- Считает реализованный PnL (в котируемой валюте) по FIFO с учётом комиссий (quote/base/третья).
- Пишет TXT-сводку в reports/ с ИТОГО за период по всем символам.

Улучшения: добавлен net PnL (после комиссий), win rate, avg_sell_notional в summary_txt.

Пример:
  python3 -u pnl_reporter.py --symbols SOLUSDT,ETHUSDT --days 7
"""

import os, time, hmac, hashlib, argparse
from typing import List, Dict, Tuple, Any
import requests
from dotenv import load_dotenv

load_dotenv()
BINANCE = (os.getenv("BINANCE_BASE_URL") or os.getenv("BINANCE_API_BASE") or "https://api.binance.com").rstrip("/")
API_KEY = os.getenv("BINANCE_API_KEY","")
API_SECRET = os.getenv("BINANCE_API_SECRET","")

REPORTS_DIR = "reports"
QUOTES = ("USDT","USDC","FDUSD","BUSD","TUSD","DAI","USDE","USDD","EUR","BTC","BNB","ETH")

def split_symbol(symbol: str) -> Tuple[str, str]:
    for q in QUOTES:
        if symbol.endswith(q):
            return symbol[:-len(q)], q
    # fallback
    return symbol[:-4], symbol[-4:]

def signed_get(path: str, params: Dict) -> Any:
    url = BINANCE + path
    params = dict(params)
    params["timestamp"] = int(time.time()*1000)
    params.setdefault("recvWindow", 5000)
    from requests import PreparedRequest
    pr = requests.PreparedRequest()
    pr.prepare_url(url, params)
    qs = requests.utils.urlparse(pr.url).query
    sig = hmac.new(API_SECRET.encode(), qs.encode(), hashlib.sha256).hexdigest()
    params["signature"] = sig
    r = requests.get(url, params=params, headers={"X-MBX-APIKEY": API_KEY}, timeout=15)
    if r.status_code >= 400:
        raise RuntimeError(f"HTTP {r.status_code}: {r.text}")
    return r.json()

def fetch_trades(symbol: str, start_ts: int, end_ts: int) -> List[Dict]:
    """
    Безопасная выборка: окна ≤24h, внутри окна страничимся по time:
    сдвигаем startTime = last_time + 1 пока не вычерпаем окно.
    """
    out: List[Dict] = []
    step = 24*60*60*1000
    cur = start_ts
    while cur < end_ts:
        ts_to = min(end_ts, cur + step)
        cursor = cur
        while True:
            batch = signed_get("/api/v3/myTrades", {
                "symbol": symbol,
                "startTime": cursor,
                "endTime": ts_to,
                "limit": 1000
            })
            if not batch:
                break
            out.extend(batch)
            if len(batch) < 1000:
                break
            last_time = batch[-1]["time"]
            cursor = int(last_time) + 1
        cur = ts_to
    return out

def fifo_pnl(trades: List[Dict]) -> Tuple[float, float, Dict]:
    """
    Реализованный PnL (GROSS) в котируемой валюте (quote).
    Комиссии:
      - fee в quote -> НЕ трогаем price/income, просто копим в fees_quote (GROSS→NET в summary)
      - fee в base  -> уменьшаем лот (BUY) или списываем сверх qty (SELL), стоимость считаем в quote
      - fee в третьем активе -> агрегируем отдельно (оценка=0.0)
    """
    lots: List[Tuple[float, float]] = []  # (qty_base, price_quote_per_base)
    realized_gross = 0.0
    fees_quote = 0.0
    third_asset_fees = 0.0
    wins = 0
    sell_trades = 0
    notional_sold = 0.0

    for t in trades:
        is_buy = bool(t["isBuyer"])
        qty = float(t["qty"])
        price = float(t["price"])
        quote_qty = float(t["quoteQty"])
        fee = float(t["commission"])
        fee_asset = t["commissionAsset"]
        symbol = t["symbol"]
        base, quote = split_symbol(symbol)

        if is_buy:
            eff_qty = qty
            if fee_asset == base:
                # комиссия списана базовой монетой: реально получено меньше base
                eff_qty = max(qty - fee, 0.0)
                fees_quote += fee * price   # оценка комиссии в котируемой
            elif fee_asset == quote:
                # комиссия списана котируемой: учитываем отдельно
                fees_quote += fee
            else:
                third_asset_fees += fee

            if eff_qty > 0:
                lots.append((eff_qty, price))

        else:
            sell_trades += 1
            income_gross = quote_qty  # GROSS доход
            cost = 0.0
            remain = qty

            if fee_asset == quote:
                fees_quote += fee
            elif fee_asset == base:
                # ВАЖНО: не уменьшаем remain — продали весь qty!
                fees_quote += fee * price  # учёт комиссии в котируемой
            else:
                third_asset_fees += fee

            notional_sold += quote_qty

            while remain > 1e-12 and lots:
                q, p = lots[0]
                take = min(remain, q)
                cost += take * p
                q -= take
                remain -= take
                if q <= 1e-12:
                    lots.pop(0)
                else:
                    lots[0] = (q, p)

            trade_pnl_gross = income_gross - cost
            realized_gross += trade_pnl_gross
            if trade_pnl_gross > 0:
                wins += 1

    stats = {
        "wins": wins,
        "trades": sell_trades,
        "avg_sell_notional": (notional_sold / sell_trades) if sell_trades else 0.0,
        "open_lots_qty": sum(q for q, _ in lots),
        "open_lots_cost": sum(q * p for q, p in lots),
        "third_asset_fees_units": third_asset_fees,
    }
    return realized_gross, fees_quote, stats

def ensure_reports_dir():
    os.makedirs(REPORTS_DIR, exist_ok=True)

def parse_args():
    p = argparse.ArgumentParser()
    p.add_argument("--symbols", type=str, required=True)
    p.add_argument("--days", type=int, default=7)
    return p.parse_args()

def main():
    args = parse_args()
    ensure_reports_dir()
    symbols = [s.strip().upper() for s in args.symbols.split(",") if s.strip()]
    end = int(time.time()*1000)
    start = end - args.days*24*60*60*1000

    summary_txt = os.path.join(REPORTS_DIR, f"summary_{args.days}d.txt")
    lines = [f"Summary for last {args.days} days", ""]

    # Переменные для построчного отчёта
    quotes_used = set()

    # Агрегаты по каждому квоуту
    # totals_by_quote[quote] = {"gross": float, "net": float}
    totals_by_quote: Dict[str, Dict[str, float]] = {}

    for sym in symbols:
        print(f"[FETCH] {sym} trades...")
        trades = fetch_trades(sym, start, end)
        trades = sorted(trades, key=lambda x: x["time"])
        pnl_gross, fees_quote, stats = fifo_pnl(trades)

        base, quote = split_symbol(sym)
        quotes_used.add(quote)

        # Копим агрегаты по квоуту
        agg = totals_by_quote.setdefault(quote, {"gross": 0.0, "net": 0.0})
        agg["gross"] += pnl_gross
        agg["net"]   += (pnl_gross - fees_quote)

        # Построчный отчёт по символу
        if stats["trades"] == 0:
            lines.append(f"{sym}: no trades in period; pnl=0.000000 fees={fees_quote:.6f} net={-fees_quote:.6f}")
        else:
            lines.append(
                f"{sym}: pnl={pnl_gross:.6f} fees={fees_quote:.6f} net={pnl_gross-fees_quote:.6f} "
                f"wins={stats['wins']}/{stats['trades']} "
                f"avg_sell_notional={stats['avg_sell_notional']:.2f}"
            )

    lines.append("")

    # Предупреждение о смешанных котируемых
    if len(quotes_used) > 1:
        lines.append(
            f"WARNING: mixed quotes detected: {', '.join(sorted(quotes_used))}. "
            f"Cross-quote totals are not directly comparable."
        )
        lines.append("")

    # Выгрузка итогов по каждому квоуту — отдельными блоками
    # Стабильный порядок: отсортируем квоуты
    for quote in sorted(totals_by_quote):
        gross = totals_by_quote[quote]["gross"]
        net   = totals_by_quote[quote]["net"]
        lines.append(f"[{quote}] TOTAL pnl={gross:.6f}")
        lines.append(f"[{quote}] NET   pnl={net:.6f}")
        lines.append("")

    # Если хочешь ещё общий сводный блок (без экономического смысла при смешанных квоутах) — можно убрать
    if len(totals_by_quote) == 1:
        # единственный квоут — общий блок эквивалентен
        only_quote = next(iter(totals_by_quote))
        gross = totals_by_quote[only_quote]["gross"]
        net   = totals_by_quote[only_quote]["net"]
        lines.append(f"TOTAL pnl={gross:.6f}")
        lines.append(f"NET   pnl={net:.6f}")

    with open(summary_txt, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print(f"[REPORT] Saved: {summary_txt}")

    # Консольный вывод: если квоутов несколько — показываем по каждому
    if len(totals_by_quote) == 1:
        only_quote = next(iter(totals_by_quote))
        gross = totals_by_quote[only_quote]["gross"]
        net   = totals_by_quote[only_quote]["net"]
        print(f"[DONE] Realized PnL total (gross, {only_quote}): {gross:.8f}")
        print(f"[DONE] Net PnL ({only_quote}): {net:.8f}")
    else:
        for quote in sorted(totals_by_quote):
            gross = totals_by_quote[quote]["gross"]
            net   = totals_by_quote[quote]["net"]
            print(f"[DONE] [{quote}] gross={gross:.8f} net={net:.8f}")

    print("[DONE] Reports written to:", REPORTS_DIR)

if __name__ == "__main__":
    main()
