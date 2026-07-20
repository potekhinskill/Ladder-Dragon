-- Keep exact text accounting fields authoritative while legacy REAL columns
-- remain available to older installations until the next major release.

UPDATE trades
SET price_text = COALESCE(NULLIF(price_text, ''), printf('%.17g', price)),
    gross_qty = COALESCE(NULLIF(gross_qty, ''), printf('%.17g', qty)),
    net_qty = COALESCE(NULLIF(net_qty, ''), printf('%.17g', qty)),
    commission_amount = COALESCE(NULLIF(commission_amount, ''), '0'),
    commission_quote = CASE
        WHEN commission_value_status = 'unpriced' THEN commission_quote
        ELSE COALESCE(NULLIF(commission_quote, ''), printf('%.17g', fee_quote))
    END;

UPDATE inventory
SET qty_text = COALESCE(NULLIF(qty_text, ''), printf('%.17g', qty)),
    avg_cost_text = COALESCE(NULLIF(avg_cost_text, ''), printf('%.17g', avg_cost)),
    realized_pnl_text = COALESCE(
        NULLIF(realized_pnl_text, ''), printf('%.17g', realized_pnl)
    );

CREATE TRIGGER IF NOT EXISTS trades_exact_after_insert
AFTER INSERT ON trades
WHEN NEW.price_text IS NULL OR NEW.price_text = ''
  OR NEW.gross_qty IS NULL OR NEW.gross_qty = ''
  OR NEW.net_qty IS NULL OR NEW.net_qty = ''
BEGIN
  UPDATE trades
  SET price_text = COALESCE(NULLIF(NEW.price_text, ''), printf('%.17g', NEW.price)),
      gross_qty = COALESCE(NULLIF(NEW.gross_qty, ''), printf('%.17g', NEW.qty)),
      net_qty = COALESCE(NULLIF(NEW.net_qty, ''), printf('%.17g', NEW.qty))
  WHERE id = NEW.id;
END;

CREATE TRIGGER IF NOT EXISTS inventory_exact_after_insert
AFTER INSERT ON inventory
WHEN NEW.qty_text IS NULL OR NEW.qty_text = ''
  OR NEW.avg_cost_text IS NULL OR NEW.avg_cost_text = ''
  OR NEW.realized_pnl_text IS NULL OR NEW.realized_pnl_text = ''
BEGIN
  UPDATE inventory
  SET qty_text = COALESCE(NULLIF(NEW.qty_text, ''), printf('%.17g', NEW.qty)),
      avg_cost_text = COALESCE(
          NULLIF(NEW.avg_cost_text, ''), printf('%.17g', NEW.avg_cost)
      ),
      realized_pnl_text = COALESCE(
          NULLIF(NEW.realized_pnl_text, ''), printf('%.17g', NEW.realized_pnl)
      )
  WHERE symbol = NEW.symbol;
END;

CREATE TRIGGER IF NOT EXISTS inventory_exact_after_legacy_update
AFTER UPDATE OF qty, avg_cost, realized_pnl ON inventory
WHEN (NEW.qty != OLD.qty AND NEW.qty_text IS OLD.qty_text)
  OR (NEW.avg_cost != OLD.avg_cost AND NEW.avg_cost_text IS OLD.avg_cost_text)
  OR (
      NEW.realized_pnl != OLD.realized_pnl
      AND NEW.realized_pnl_text IS OLD.realized_pnl_text
  )
BEGIN
  UPDATE inventory
  SET qty_text = CASE
          WHEN NEW.qty != OLD.qty AND NEW.qty_text IS OLD.qty_text
          THEN printf('%.17g', NEW.qty) ELSE NEW.qty_text END,
      avg_cost_text = CASE
          WHEN NEW.avg_cost != OLD.avg_cost AND NEW.avg_cost_text IS OLD.avg_cost_text
          THEN printf('%.17g', NEW.avg_cost) ELSE NEW.avg_cost_text END,
      realized_pnl_text = CASE
          WHEN NEW.realized_pnl != OLD.realized_pnl
               AND NEW.realized_pnl_text IS OLD.realized_pnl_text
          THEN printf('%.17g', NEW.realized_pnl) ELSE NEW.realized_pnl_text END
  WHERE symbol = NEW.symbol;
END;

CREATE VIEW IF NOT EXISTS trades_exact AS
SELECT id, symbol, side,
       COALESCE(NULLIF(price_text, ''), CAST(price AS TEXT)) AS price_text,
       COALESCE(NULLIF(gross_qty, ''), CAST(qty AS TEXT)) AS gross_qty_text,
       COALESCE(NULLIF(net_qty, ''), CAST(qty AS TEXT)) AS net_qty_text,
       COALESCE(commission_asset, '') AS commission_asset,
       COALESCE(NULLIF(commission_amount, ''), '0') AS commission_amount_text,
       CASE WHEN commission_value_status = 'unpriced' THEN NULL
            ELSE COALESCE(NULLIF(commission_quote, ''), CAST(fee_quote AS TEXT))
       END AS commission_quote_text,
       COALESCE(NULLIF(commission_value_status, ''), 'legacy')
         AS commission_value_status,
       ts, trade_id
FROM trades;

CREATE VIEW IF NOT EXISTS inventory_exact AS
SELECT symbol,
       COALESCE(NULLIF(qty_text, ''), CAST(qty AS TEXT)) AS qty_text,
       COALESCE(NULLIF(avg_cost_text, ''), CAST(avg_cost AS TEXT)) AS avg_cost_text,
       COALESCE(NULLIF(realized_pnl_text, ''), CAST(realized_pnl AS TEXT))
         AS realized_pnl_text,
       last_trade_id
FROM inventory;
