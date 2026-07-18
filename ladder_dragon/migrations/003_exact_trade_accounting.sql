ALTER TABLE trades ADD COLUMN price_text TEXT;
ALTER TABLE trades ADD COLUMN gross_qty TEXT;
ALTER TABLE trades ADD COLUMN net_qty TEXT;
ALTER TABLE trades ADD COLUMN commission_asset TEXT NOT NULL DEFAULT '';
ALTER TABLE trades ADD COLUMN commission_amount TEXT;
ALTER TABLE trades ADD COLUMN commission_quote TEXT;
ALTER TABLE trades ADD COLUMN commission_value_status TEXT NOT NULL DEFAULT 'legacy';

UPDATE trades
SET price_text = COALESCE(price_text, printf('%.17g', price)),
    gross_qty = COALESCE(gross_qty, printf('%.17g', qty)),
    net_qty = COALESCE(net_qty, printf('%.17g', qty)),
    commission_amount = COALESCE(commission_amount, '0'),
    commission_quote = COALESCE(commission_quote, printf('%.17g', fee_quote)),
    commission_value_status = COALESCE(NULLIF(commission_value_status, ''), 'legacy');

ALTER TABLE inventory ADD COLUMN qty_text TEXT;
ALTER TABLE inventory ADD COLUMN avg_cost_text TEXT;
ALTER TABLE inventory ADD COLUMN realized_pnl_text TEXT;

UPDATE inventory
SET qty_text = COALESCE(qty_text, printf('%.17g', qty)),
    avg_cost_text = COALESCE(avg_cost_text, printf('%.17g', avg_cost)),
    realized_pnl_text = COALESCE(realized_pnl_text, printf('%.17g', realized_pnl));

CREATE INDEX IF NOT EXISTS trades_accounting_cover
ON trades(symbol, ts, side, price_text, gross_qty, net_qty);
