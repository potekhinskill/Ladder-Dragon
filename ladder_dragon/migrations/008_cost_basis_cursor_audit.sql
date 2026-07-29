ALTER TABLE inventory_lot_imports
ADD COLUMN stats_trade_max_id INTEGER;

ALTER TABLE inventory_lot_imports
ADD COLUMN cursor_gap_start_trade_id INTEGER;

ALTER TABLE inventory_lot_imports
ADD COLUMN cursor_gap_end_trade_id INTEGER;
