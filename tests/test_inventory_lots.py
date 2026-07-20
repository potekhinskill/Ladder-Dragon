import sqlite3
from decimal import Decimal

from ladder_dragon.execution.inventory_lots import (
    add_lot,
    consume_fifo,
    cost_basis_coverage,
    ensure_schema,
    oldest_lots,
    lot_for_order,
)


def test_fifo_lots_preserve_age_and_ladder_level():
    con = sqlite3.connect(":memory:")
    ensure_schema(con)
    add_lot(con, symbol="SOLUSDT", qty=Decimal("1"), price=Decimal("100"), ladder_level="L1", opened_at=10)
    add_lot(con, symbol="SOLUSDT", qty=Decimal("2"), price=Decimal("90"), ladder_level="L2", opened_at=20)
    consumed = consume_fifo(con, "SOLUSDT", Decimal("1.5"))
    assert consumed[0].ladder_level == "L1"
    assert consumed[1].qty == Decimal("0.5")
    assert oldest_lots(con, "SOLUSDT")[0].qty == Decimal("1.5")


def test_lot_can_be_recovered_by_exchange_order_id():
    con = sqlite3.connect(":memory:")
    add_lot(con, symbol="SOLUSDT", qty=Decimal("1"), price=Decimal("100"),
            source_order_id="501", opened_at=10)
    assert lot_for_order(con, "SOLUSDT", 501).lot_id == 1


def test_cost_basis_coverage_requires_price_provenance_and_quantity_match():
    con = sqlite3.connect(":memory:")
    add_lot(
        con, symbol="SOLUSDT", qty=Decimal("1"), price=Decimal("100"),
        source_order_id="501", opened_at=10,
    )
    covered = cost_basis_coverage(
        con, "SOLUSDT", Decimal("0.999"), tolerance_qty=Decimal("0.002")
    )
    assert covered.covered is True
    assert covered.covered_qty == Decimal("1")
    assert covered.average_price == Decimal("100")

    legacy = cost_basis_coverage(
        con, "SOLUSDT", Decimal("1.5"), tolerance_qty=Decimal("0.002")
    )
    assert legacy.covered is False
    assert legacy.uncovered_qty == Decimal("0.5")
    assert "legacy" in legacy.reason


def test_cost_basis_coverage_rejects_quantity_only_import():
    con = sqlite3.connect(":memory:")
    add_lot(
        con, symbol="ETHUSDT", qty=Decimal("1"), price=Decimal("100"),
        source_order_id="", opened_at=10,
    )
    result = cost_basis_coverage(con, "ETHUSDT", Decimal("1"))
    assert result.covered is False
    assert "provenance" in result.reason


def test_cost_basis_coverage_returns_weighted_fifo_average():
    con = sqlite3.connect(":memory:")
    add_lot(
        con, symbol="SOLUSDT", qty=Decimal("1"), price=Decimal("100"),
        source_order_id="501", opened_at=10,
    )
    add_lot(
        con, symbol="SOLUSDT", qty=Decimal("3"), price=Decimal("80"),
        source_order_id="502", opened_at=20,
    )
    result = cost_basis_coverage(con, "SOLUSDT", Decimal("4"))
    assert result.covered is True
    assert result.average_price == Decimal("85")
