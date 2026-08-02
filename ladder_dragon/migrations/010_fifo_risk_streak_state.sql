CREATE TABLE risk_fifo_lots(
  lot_id INTEGER PRIMARY KEY AUTOINCREMENT,
  source_trade_row_id INTEGER,
  symbol TEXT NOT NULL,
  exchange_trade_id INTEGER,
  opened_at INTEGER NOT NULL,
  remaining_qty_text TEXT NOT NULL,
  unit_cost_quote_text TEXT NOT NULL
);

CREATE INDEX risk_fifo_lots_symbol_time
ON risk_fifo_lots(symbol, opened_at, lot_id);

CREATE TABLE risk_fifo_incomplete_symbols(
  symbol TEXT PRIMARY KEY,
  reason TEXT NOT NULL,
  updated_at INTEGER NOT NULL
);

CREATE TABLE risk_fifo_symbol_state(
  symbol TEXT PRIMARY KEY,
  last_trade_at INTEGER NOT NULL DEFAULT 0,
  last_trade_row_id INTEGER NOT NULL DEFAULT 0
);

ALTER TABLE risk_sell_outcome_state
ADD COLUMN last_trade_at INTEGER NOT NULL DEFAULT 0;

ALTER TABLE risk_sell_outcome_state
ADD COLUMN last_trade_row_id INTEGER NOT NULL DEFAULT 0;

ALTER TABLE risk_sell_outcome_state
ADD COLUMN open_fifo_lot_count INTEGER NOT NULL DEFAULT 0;

UPDATE risk_sell_outcome_state
SET backfill_complete=0,last_trade_at=0,last_trade_row_id=0,
    open_fifo_lot_count=0;
