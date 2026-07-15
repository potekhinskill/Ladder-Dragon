#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tools_stats.py — лёгкая БД статистики (SQLite) для учёта инвентаря и трейдов.

Функции:
- init_db(db_path)
- apply_trade(symbol, side, price, qty, fee_quote=0.0, ts=None, trade_id=None)
- get_inventory(symbol) -> (qty, avg_cost, realized_pnl)
- get_last_trade_id(symbol) / set_last_trade_id(symbol, last_id)
- monthly_summary(symbol, year, month) -> dict
- daily_summary(symbol, utc=True) -> dict

Хранение:
- table trades(symbol, side, price, qty, fee_quote, ts, trade_id)
- table inventory(symbol PRIMARY KEY, qty, avg_cost, realized_pnl, last_trade_id)

Доп. устойчивость к «database is locked»:
- Соединения открываются в режиме WAL + busy_timeout.
- Есть раздельные коннекторы: connect_ro() для чтения (mode=ro) и connect_rw() для записи.
- Все операции обёрнуты в retry с экспоненциальным backoff’ом.
"""

import sqlite3, os, time
from typing import Optional, Tuple, Dict, Iterable, Any

# ==========================
# Конфиг через переменные
# ==========================
DB_PATH = os.getenv("BOT_STATS_DB", "/home/bot/stats/bot_stats.db")
BUSY_TRIES  = int(os.getenv("STATS_BUSY_TRIES", "7"))      # повторы при lock’ах
BUSY_BASE_S = float(os.getenv("STATS_BUSY_BASE", "0.25"))  # базовая пауза backoff

SCHEMA = """
CREATE TABLE IF NOT EXISTS trades(
  id         INTEGER PRIMARY KEY AUTOINCREMENT,
  symbol     TEXT NOT NULL,
  side       TEXT CHECK(side IN ('BUY','SELL')) NOT NULL,
  price      REAL NOT NULL CHECK(price > 0.0),
  qty        REAL NOT NULL CHECK(qty > 0.0),
  fee_quote  REAL NOT NULL DEFAULT 0.0 CHECK(fee_quote >= 0.0),
  ts         INTEGER NOT NULL CHECK(ts > 0),
  trade_id   INTEGER
);
-- Базовый и покрывающий индексы под выборки по symbol+ts и отчётам
CREATE INDEX IF NOT EXISTS trades_idx ON trades(symbol, ts);
CREATE INDEX IF NOT EXISTS trades_monthly_cover
ON trades(symbol, ts, side, price, qty, fee_quote);
-- Уникальность trade_id в рамках символа (когда trade_id задан)
CREATE UNIQUE INDEX IF NOT EXISTS trades_sym_tradeid_uq
ON trades(symbol, trade_id) WHERE trade_id IS NOT NULL;

CREATE TABLE IF NOT EXISTS inventory(
  symbol        TEXT PRIMARY KEY,
  qty           REAL NOT NULL DEFAULT 0.0,
  avg_cost      REAL NOT NULL DEFAULT 0.0,
  realized_pnl  REAL NOT NULL DEFAULT 0.0,
  last_trade_id INTEGER
);
"""

# ==========================
# Вспомогательные функции
# ==========================

def _apply_pragmas(con: sqlite3.Connection, read_only: bool = False) -> None:
    cur = con.cursor()
    try:
        cur.execute("PRAGMA busy_timeout=7000;")
        cur.execute("PRAGMA synchronous=NORMAL;")
        if not read_only:
            cur.execute("PRAGMA journal_mode=WAL;")
            cur.execute("PRAGMA wal_autocheckpoint=2000;")
    except sqlite3.OperationalError:
        # В RO некоторые PRAGMA могут быть неразрешимы — мягко игнорируем
        pass
    finally:
        cur.close()

def connect_ro(db_path: str = DB_PATH) -> sqlite3.Connection:
    con = sqlite3.connect(
        f"file:{db_path}?mode=ro",
        uri=True,
        timeout=10.0,
        check_same_thread=False,
        isolation_level=None  # автокоммит
    )
    _apply_pragmas(con, read_only=True)
    return con

def connect_rw(db_path: str = DB_PATH) -> sqlite3.Connection:
    con = sqlite3.connect(
        db_path,
        timeout=15.0,
        check_same_thread=False,
        isolation_level=None  # автокоммит
    )
    _apply_pragmas(con, read_only=False)
    return con

def _retry_op(fn, *a, **kw):
    """
    Универсальная обёртка для ретраев на «database is locked».
    Возвращает результат fn(...) или пробрасывает исключение после BUSY_TRIES попыток.
    """
    tries = BUSY_TRIES
    delay = BUSY_BASE_S
    for i in range(tries):
        try:
            return fn(*a, **kw)
        except sqlite3.OperationalError as e:
            msg = str(e).lower()
            if ("locked" in msg or "busy" in msg) and i < tries - 1:
                time.sleep(delay)
                delay *= 2.0
                continue
            raise

def exec_with_retry(con: sqlite3.Connection, sql: str, params: Iterable[Any] = ()):
    cur = _retry_op(con.execute, sql, params)
    try:
        return cur.rowcount
    finally:
        cur.close()

def query_with_retry(con: sqlite3.Connection, sql: str, params: Iterable[Any] = ()) -> list:
    cur = _retry_op(con.execute, sql, params)
    rows = cur.fetchall()
    cur.close()
    return rows

# ==========================
# Инициализация БД
# ==========================

def init_db(db_path: str) -> sqlite3.Connection:
    """
    Инициализирует БД по пути db_path и возвращает RW-соединение.
    Включает WAL и нужные PRAGMA.
    """
    os.makedirs(os.path.dirname(db_path) or ".", exist_ok=True)
    con = connect_rw(db_path)
    con.executescript(SCHEMA)
    return con

# ==========================
# Пересчёт инвентаря
# ==========================

def _recalc_inventory(db: sqlite3.Connection, symbol: str):
    """
    Полный пересчёт инвентаря по символу «с нуля».
    Делается быстро даже для тысяч строк, зато логика простая/надёжная.
    """
    sym = symbol.upper()
    rows = query_with_retry(
        db,
        "SELECT side, price, qty, fee_quote FROM trades WHERE symbol=? ORDER BY ts ASC, id ASC",
        (sym,)
    )

    qty = 0.0
    avg_cost = 0.0
    realized = 0.0

    for side, price, q, fee_q in rows:
        if side == 'BUY':
            new_qty = qty + float(q)
            if new_qty <= 1e-12:
                qty, avg_cost = 0.0, 0.0
            else:
                # fee в котируемой валюте — прибавляем к стоимости входа
                avg_cost = (avg_cost * qty + float(price) * float(q) + float(fee_q)) / new_qty
                qty = new_qty
        else:  # SELL
            q = float(q)
            if q > qty + 1e-12:
                # логируем аномалию через уменьшение q (не уходим в отрицательный склад)
                q = max(0.0, qty)
            realized += (float(price) - avg_cost) * q - float(fee_q)
            qty -= q
            if qty <= 1e-12:
                qty, avg_cost = 0.0, 0.0

    exec_with_retry(db, """
        INSERT INTO inventory(symbol, qty, avg_cost, realized_pnl)
        VALUES(?,?,?,?)
        ON CONFLICT(symbol)
        DO UPDATE SET qty=excluded.qty,
                      avg_cost=excluded.avg_cost,
                      realized_pnl=excluded.realized_pnl
    """, (sym, qty, avg_cost, realized))

# ==========================
# Публичные функции
# ==========================

def apply_trade(con: sqlite3.Connection,
                symbol: str,
                side: str,
                price: float,
                qty: float,
                fee_quote: float = 0.0,
                ts: Optional[int] = None,
                trade_id: Optional[int] = None):
    """
    Добавляет исполненную сделку и пересчитывает инвентарь.
    ВАЖНО: вызывать только на закрытых (filled) сделках.
    """
    sym = symbol.upper()
    side = side.upper()
    ts = int(ts or time.time() * 1000)
    price = float(price)
    qty = float(qty)
    fee_quote = float(fee_quote)

    with con:  # короткая транзакция
        exec_with_retry(con, """
            INSERT INTO trades(symbol, side, price, qty, fee_quote, ts, trade_id)
            VALUES(?,?,?,?,?,?,?)
        """, (sym, side, price, qty, fee_quote, ts, trade_id))
        _recalc_inventory(con, sym)

def get_inventory(con: sqlite3.Connection, symbol: str) -> Tuple[float, float, float]:
    """
    Возвращает (qty, avg_cost, realized_pnl) для символа.
    Если записи нет — (0,0,0).
    """
    sym = symbol.upper()
    rows = query_with_retry(con, "SELECT qty, avg_cost, realized_pnl FROM inventory WHERE symbol=?", (sym,))
    if not rows:
        return (0.0, 0.0, 0.0)
    q, a, r = rows[0]
    return (float(q), float(a), float(r))

def get_last_trade_id(con: sqlite3.Connection, symbol: str) -> Optional[int]:
    sym = symbol.upper()
    rows = query_with_retry(con, "SELECT last_trade_id FROM inventory WHERE symbol=?", (sym,))
    if not rows:
        return None
    return rows[0][0]

def set_last_trade_id(con: sqlite3.Connection, symbol: str, last_id: int):
    sym = symbol.upper()
    with con:
        exec_with_retry(con, """
            INSERT INTO inventory(symbol, last_trade_id)
            VALUES(?,?)
            ON CONFLICT(symbol)
            DO UPDATE SET last_trade_id=excluded.last_trade_id
        """, (sym, int(last_id)))

def monthly_summary(con: sqlite3.Connection, symbol: str, year: int, month: int) -> Dict:
    import calendar
    import datetime as dt

    sym = symbol.upper()
    first = dt.datetime(year, month, 1)
    last_day = calendar.monthrange(year, month)[1]
    last = dt.datetime(year, month, last_day, 23, 59, 59, 999000)

    t1 = int(first.timestamp() * 1000)
    t2 = int(last.timestamp() * 1000)

    rows = query_with_retry(
        con,
        "SELECT side, price, qty, fee_quote FROM trades WHERE symbol=? AND ts BETWEEN ? AND ? ORDER BY ts ASC",
        (sym, t1, t2)
    )

    vol_buy = sum(float(q) for s, _, q, _ in rows if s == 'BUY')
    vol_sell = sum(float(q) for s, _, q, _ in rows if s == 'SELL')
    spent = sum(float(p) * float(q) + float(fee) for s, p, q, fee in rows if s == 'BUY')
    received = sum(float(p) * float(q) - float(fee) for s, p, q, fee in rows if s == 'SELL')

    # Приблизительный realized внутри месяца по FIFO (на срезе месяца)
    inv = 0.0
    avg = 0.0
    realized = 0.0
    for s, price, q, fee in rows:
        price = float(price); q = float(q); fee = float(fee)
        if s == 'BUY':
            new = inv + q
            avg = (avg * inv + price * q + fee) / max(new, 1e-12)
            inv = new
        else:
            q_eff = min(q, inv) if inv > 0 else 0.0
            realized += (price - avg) * q_eff - fee
            inv -= q_eff
            if inv <= 1e-12:
                inv = 0.0; avg = 0.0

    return {
        "buys_base": vol_buy,
        "sells_base": vol_sell,
        "spent_quote": spent,
        "received_quote": received,
        "realized_month": realized
    }

def daily_summary(con: sqlite3.Connection, symbol: str, utc: bool = True) -> Dict:
    """
    Суммирует сделки за текущие сутки (UTC по умолчанию).
    Возвращает приблизительный realized по FIFO внутри дня.
    """
    import datetime as dt

    sym = symbol.upper()
    now = dt.datetime.utcnow() if utc else dt.datetime.now()
    start = dt.datetime(now.year, now.month, now.day, 0, 0, 0)
    end = dt.datetime(now.year, now.month, now.day, 23, 59, 59, 999000)

    t1 = int(start.timestamp() * 1000)
    t2 = int(end.timestamp() * 1000)

    rows = query_with_retry(
        con,
        "SELECT side, price, qty, fee_quote FROM trades WHERE symbol=? AND ts BETWEEN ? AND ? ORDER BY ts ASC",
        (sym, t1, t2)
    )

    vol_buy = sum(float(q) for s, _, q, _ in rows if s == 'BUY')
    vol_sell = sum(float(q) for s, _, q, _ in rows if s == 'SELL')
    spent = sum(float(p) * float(q) + float(fee) for s, p, q, fee in rows if s == 'BUY')
    received = sum(float(p) * float(q) - float(fee) for s, p, q, fee in rows if s == 'SELL')

    # FIFO в пределах суток
    inv = 0.0
    avg = 0.0
    realized = 0.0
    for s, price, q, fee in rows:
        price = float(price); q = float(q); fee = float(fee)
        if s == 'BUY':
            new = inv + q
            avg = (avg * inv + price * q + fee) / max(new, 1e-12)
            inv = new
        else:
            q_eff = min(q, inv) if inv > 0 else 0.0
            realized += (price - avg) * q_eff - fee
            inv -= q_eff
            if inv <= 1e-12:
                inv = 0.0; avg = 0.0

    return {
        "buys_base": vol_buy,
        "sells_base": vol_sell,
        "spent_quote": spent,
        "received_quote": received,
        "realized_day": realized
    }
