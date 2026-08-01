CREATE TABLE risk_sell_outcomes(
  trade_row_id INTEGER PRIMARY KEY,
  symbol TEXT NOT NULL,
  exchange_trade_id INTEGER,
  executed_at INTEGER NOT NULL,
  net_pnl_quote_text TEXT NOT NULL
);

CREATE INDEX risk_sell_outcomes_symbol_time
ON risk_sell_outcomes(symbol, executed_at DESC, trade_row_id DESC);

CREATE TABLE risk_sell_outcome_state(
  singleton INTEGER PRIMARY KEY CHECK(singleton=1),
  backfill_complete INTEGER NOT NULL DEFAULT 0 CHECK(backfill_complete IN (0,1)),
  updated_at INTEGER NOT NULL DEFAULT 0
);

INSERT INTO risk_sell_outcome_state(singleton, backfill_complete, updated_at)
VALUES(1, 0, 0);

CREATE TABLE risk_sell_streaks(
  scope TEXT PRIMARY KEY,
  consecutive_losses INTEGER NOT NULL CHECK(consecutive_losses >= 0),
  last_executed_at INTEGER NOT NULL DEFAULT 0,
  last_trade_row_id INTEGER NOT NULL DEFAULT 0
);
