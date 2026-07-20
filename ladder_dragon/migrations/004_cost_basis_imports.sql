CREATE TABLE IF NOT EXISTS inventory_lot_imports(
  batch_id TEXT PRIMARY KEY,
  symbol TEXT NOT NULL,
  created_at INTEGER NOT NULL,
  plan_sha256 TEXT NOT NULL UNIQUE,
  history_sha256 TEXT NOT NULL,
  account_qty TEXT NOT NULL,
  reconstructed_qty TEXT NOT NULL,
  weighted_average TEXT NOT NULL,
  last_trade_id INTEGER NOT NULL,
  baseline_realized_pnl TEXT NOT NULL DEFAULT '0',
  status TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS inventory_lot_imports_symbol_status
ON inventory_lot_imports(symbol, status, created_at);
