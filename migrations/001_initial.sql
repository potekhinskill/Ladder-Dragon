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

CREATE TABLE IF NOT EXISTS inventory(
  symbol        TEXT PRIMARY KEY,
  qty           REAL NOT NULL DEFAULT 0.0,
  avg_cost      REAL NOT NULL DEFAULT 0.0,
  realized_pnl  REAL NOT NULL DEFAULT 0.0,
  last_trade_id INTEGER
);
