#!/usr/bin/env python3
import os, sqlite3, sys

DB = os.getenv('BOT_STATS_DB', '/home/bot/apps/binance_bot/db/bot_stats.db')

DDL = [
    # покрывающий индекс под выборки по symbol+ts (месяц/сутки)
    "CREATE INDEX IF NOT EXISTS trades_monthly_cover "
    "ON trades(symbol, ts, side, price, qty, fee_quote);",

    # защита от дублей трейдов (trade_id уникален в рамках символа)
    "CREATE UNIQUE INDEX IF NOT EXISTS trades_sym_tradeid_uq "
    "ON trades(symbol, trade_id) WHERE trade_id IS NOT NULL;"
]

def table_exists(con: sqlite3.Connection, name: str) -> bool:
    cur = con.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?;", (name,))
    return cur.fetchone() is not None

def main() -> int:
    # Открываем соединение и ставим таймаут на локи
    with sqlite3.connect(DB, timeout=15.0) as con:
        con.execute("PRAGMA busy_timeout=7000;")
        # Если таблицы ещё нет — просто выходим «мягко»
        if not table_exists(con, 'trades'):
            print(f"[SKIP] no table 'trades' yet in {DB} — nothing to index")
            return 0

        cur = con.cursor()
        for sql in DDL:
            try:
                cur.execute(sql)
                idx_name = sql.split(' IF NOT EXISTS ')[-1].split()[0]
                print(f"[IDX] {idx_name} ok")
            except sqlite3.OperationalError as e:
                # Например, если схема неожиданно отличается
                print(f"[WARN] {e.__class__.__name__}: {e}", file=sys.stderr)

        # Обновим статистику оптимизатора
        cur.executescript("ANALYZE; PRAGMA optimize;")
        print("[OK] migrate_indexes done on", DB)
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
