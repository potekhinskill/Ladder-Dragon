import sqlite3
from decimal import Decimal

from inventory_lots import add_lot, consume_fifo, ensure_schema, oldest_lots


def test_fifo_lots_preserve_age_and_ladder_level():
    con = sqlite3.connect(":memory:")
    ensure_schema(con)
    add_lot(con, symbol="SOLUSDT", qty=Decimal("1"), price=Decimal("100"), ladder_level="L1", opened_at=10)
    add_lot(con, symbol="SOLUSDT", qty=Decimal("2"), price=Decimal("90"), ladder_level="L2", opened_at=20)
    consumed = consume_fifo(con, "SOLUSDT", Decimal("1.5"))
    assert consumed[0].ladder_level == "L1"
    assert consumed[1].qty == Decimal("0.5")
    assert oldest_lots(con, "SOLUSDT")[0].qty == Decimal("1.5")
