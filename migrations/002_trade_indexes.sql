CREATE INDEX IF NOT EXISTS trades_idx ON trades(symbol, ts);
CREATE INDEX IF NOT EXISTS trades_monthly_cover
ON trades(symbol, ts, side, price, qty, fee_quote);
CREATE UNIQUE INDEX IF NOT EXISTS trades_sym_tradeid_uq
ON trades(symbol, trade_id) WHERE trade_id IS NOT NULL;
