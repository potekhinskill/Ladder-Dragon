-- Persist one normalized SELL fill per Binance symbol/trade ID so a process
-- restart before the myTrades cursor update cannot consume FIFO lots twice.
CREATE TABLE IF NOT EXISTS inventory_lot_consumptions(
  symbol TEXT NOT NULL,
  source_trade_id TEXT NOT NULL,
  source_order_id TEXT NOT NULL DEFAULT '',
  qty TEXT NOT NULL,
  price TEXT NOT NULL,
  executed_at INTEGER NOT NULL,
  recorded_at INTEGER NOT NULL,
  PRIMARY KEY(symbol, source_trade_id)
);

-- Existing valued SELL rows were already reflected in FIFO lots before this
-- journal existed. Seed their exact symbol/trade/quantity/price identity so a
-- later cursor rewind cannot apply them again. Order ID was not historically
-- stored in trades and may be enriched on a matching replay.
INSERT OR IGNORE INTO inventory_lot_consumptions(
  symbol, source_trade_id, source_order_id, qty, price, executed_at, recorded_at
)
SELECT UPPER(symbol), CAST(trade_id AS TEXT), '',
       net_qty, price_text, ts, CAST(strftime('%s','now') AS INTEGER)
FROM trades
WHERE side = 'SELL'
  AND trade_id IS NOT NULL
  AND net_qty IS NOT NULL AND net_qty != ''
  AND price_text IS NOT NULL AND price_text != ''
  AND COALESCE(commission_value_status, 'legacy') != 'unpriced';
