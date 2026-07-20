ALTER TABLE inventory_lot_imports
ADD COLUMN prehistory_qty TEXT NOT NULL DEFAULT '0';

ALTER TABLE inventory_lot_imports
ADD COLUMN unmanaged_dust_qty TEXT NOT NULL DEFAULT '0';

ALTER TABLE inventory_lot_imports
ADD COLUMN history_reset_trade_id INTEGER NOT NULL DEFAULT 0;
