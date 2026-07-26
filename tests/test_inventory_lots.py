import sqlite3
from decimal import Decimal

import pytest

from ladder_dragon.execution.inventory_lots import (
    add_lot,
    consume_fifo,
    cost_basis_coverage,
    ensure_schema,
    oldest_lots,
    lot_for_order,
    sync_exchange_fill,
)
from ladder_dragon.execution.trade_accounting import UnpricedCommission


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


def test_fill_without_commission_quote_cannot_create_inventory_lot():
    con = sqlite3.connect(":memory:")
    ensure_schema(con)

    with pytest.raises(UnpricedCommission):
        sync_exchange_fill(
            con,
            {
                "symbol": "SOLUSDT",
                "side": "BUY",
                "price": "100",
                "qty": "1",
                "commission_asset": "BNB",
                "commission_amount": "0.001",
                "trade_id": "missing-fee-value",
                "order_id": "501",
            },
        )

    assert con.execute(
        "SELECT COUNT(*) FROM inventory_lots"
    ).fetchone()[0] == 0


def test_source_trade_id_makes_fill_lot_idempotent():
    con = sqlite3.connect(":memory:")
    first = add_lot(
        con, symbol="SOLUSDT", qty=Decimal("1"), price=Decimal("100"),
        source_order_id="10", source_trade_id="20",
    )
    repeated = add_lot(
        con, symbol="SOLUSDT", qty=Decimal("1"), price=Decimal("100"),
        source_order_id="10", source_trade_id="20",
    )
    assert repeated == first
    assert con.execute("SELECT COUNT(*) FROM inventory_lots").fetchone()[0] == 1


@pytest.mark.parametrize(
    ("quantity", "price", "order_id"),
    (
        (Decimal("1.1"), Decimal("100"), "10"),
        (Decimal("1"), Decimal("101"), "10"),
        (Decimal("1"), Decimal("100"), "11"),
    ),
)
def test_buy_trade_id_rejects_mismatched_payload(
    quantity, price, order_id
):
    con = sqlite3.connect(":memory:")
    add_lot(
        con,
        symbol="SOLUSDT",
        qty=Decimal("1"),
        price=Decimal("100"),
        source_order_id="10",
        source_trade_id="20",
    )

    with pytest.raises(
        ValueError, match="BUY source trade payload mismatch"
    ):
        add_lot(
            con,
            symbol="SOLUSDT",
            qty=quantity,
            price=price,
            source_order_id=order_id,
            source_trade_id="20",
        )

    lot = oldest_lots(con, "SOLUSDT")[0]
    assert lot.qty == Decimal("1")
    assert lot.price == Decimal("100")


def test_fill_lot_sync_accounts_for_quote_and_base_commissions():
    con = sqlite3.connect(":memory:")
    buy = {
        "symbol": "SOLUSDT", "side": "BUY", "price": Decimal("100"),
        "qty": Decimal("1"), "fee_quote": Decimal("0.1"),
        "commission_asset": "USDT", "commission_amount": Decimal("0.1"),
        "trade_id": 20, "order_id": 10, "ts": 1_700_000_000_000,
    }
    sync_exchange_fill(con, buy)
    sync_exchange_fill(con, buy)
    lot = oldest_lots(con, "SOLUSDT")[0]
    assert lot.qty == Decimal("1")
    assert lot.price == Decimal("100.1")
    sell = {
        "symbol": "SOLUSDT", "side": "SELL", "price": Decimal("110"),
        "qty": Decimal("0.5"), "fee_quote": Decimal("1.1"),
        "commission_asset": "SOL", "commission_amount": Decimal("0.01"),
        "trade_id": 21, "order_id": 11, "ts": 1_700_000_001_000,
    }
    sync_exchange_fill(con, sell)
    assert oldest_lots(con, "SOLUSDT")[0].qty == Decimal("0.49")


def test_sell_trade_id_makes_fifo_consumption_idempotent():
    con = sqlite3.connect(":memory:")
    add_lot(
        con,
        symbol="SOLUSDT",
        qty=Decimal("1"),
        price=Decimal("100"),
        source_order_id="10",
        source_trade_id="20",
    )
    sell = {
        "symbol": "SOLUSDT",
        "side": "SELL",
        "price": Decimal("110"),
        "qty": Decimal("0.4"),
        "fee_quote": Decimal("0.04"),
        "commission_asset": "USDT",
        "commission_amount": Decimal("0.04"),
        "trade_id": 21,
        "order_id": 11,
        "ts": 1_700_000_001_000,
    }

    first = sync_exchange_fill(con, sell)
    repeated = sync_exchange_fill(con, sell)

    assert sum(item.qty for item in first) == Decimal("0.4")
    assert repeated == []
    assert oldest_lots(con, "SOLUSDT")[0].qty == Decimal("0.6")
    assert con.execute(
        "SELECT COUNT(*) FROM inventory_lot_consumptions"
    ).fetchone()[0] == 1


@pytest.mark.parametrize(
    ("quantity", "price", "order_id"),
    (
        (Decimal("0.5"), Decimal("110"), 11),
        (Decimal("0.4"), Decimal("111"), 11),
        (Decimal("0.4"), Decimal("110"), 12),
    ),
)
def test_sell_trade_id_rejects_mismatch_without_consuming_again(
    quantity, price, order_id
):
    con = sqlite3.connect(":memory:")
    add_lot(
        con,
        symbol="SOLUSDT",
        qty=Decimal("1"),
        price=Decimal("100"),
        source_trade_id="20",
    )
    sell = {
        "symbol": "SOLUSDT",
        "side": "SELL",
        "price": Decimal("110"),
        "qty": Decimal("0.4"),
        "trade_id": 21,
        "order_id": 11,
        "ts": 1_700_000_001_000,
    }
    sync_exchange_fill(con, sell)

    with pytest.raises(
        ValueError, match="SELL source trade payload mismatch"
    ):
        sync_exchange_fill(
            con,
            {
                **sell,
                "qty": quantity,
                "price": price,
                "order_id": order_id,
            },
        )

    assert oldest_lots(con, "SOLUSDT")[0].qty == Decimal("0.6")


def test_fifo_shortage_is_read_only_before_failure():
    con = sqlite3.connect(":memory:")
    add_lot(
        con,
        symbol="SOLUSDT",
        qty=Decimal("0.4"),
        price=Decimal("100"),
        source_trade_id="20",
    )
    before = con.execute(
        "SELECT qty,status FROM inventory_lots ORDER BY lot_id"
    ).fetchall()

    with pytest.raises(ValueError, match="SELL exceeds FIFO"):
        consume_fifo(con, "SOLUSDT", Decimal("0.5"))
    con.commit()

    assert con.execute(
        "SELECT qty,status FROM inventory_lots ORDER BY lot_id"
    ).fetchall() == before


def test_fifo_savepoint_rolls_back_mid_update_failure():
    con = sqlite3.connect(":memory:")
    add_lot(
        con,
        symbol="SOLUSDT",
        qty=Decimal("0.4"),
        price=Decimal("100"),
        opened_at=10,
    )
    add_lot(
        con,
        symbol="SOLUSDT",
        qty=Decimal("0.4"),
        price=Decimal("90"),
        opened_at=20,
    )
    con.execute(
        """CREATE TRIGGER reject_second_fifo_update
        BEFORE UPDATE ON inventory_lots
        WHEN OLD.lot_id = 2
        BEGIN
            SELECT RAISE(ABORT, 'forced fifo update failure');
        END"""
    )

    with pytest.raises(sqlite3.IntegrityError):
        consume_fifo(con, "SOLUSDT", Decimal("0.6"))

    assert con.execute(
        "SELECT qty,status FROM inventory_lots ORDER BY lot_id"
    ).fetchall() == [("0.4", "OPEN"), ("0.4", "OPEN")]


def test_oldest_lots_excludes_non_positive_open_rows():
    con = sqlite3.connect(":memory:")
    ensure_schema(con)
    con.execute(
        "INSERT INTO inventory_lots("
        "symbol,qty,price,opened_at,updated_at,status"
        ") VALUES('SOLUSDT','0','100',1,1,'OPEN')"
    )
    con.execute(
        "INSERT INTO inventory_lots("
        "symbol,qty,price,opened_at,updated_at,status"
        ") VALUES('SOLUSDT','NaN','100',1,1,'OPEN')"
    )
    con.execute(
        "INSERT INTO inventory_lots("
        "symbol,qty,price,opened_at,updated_at,status"
        ") VALUES('SOLUSDT','-1','100',1,1,'OPEN')"
    )
    add_lot(
        con,
        symbol="SOLUSDT",
        qty=Decimal("1"),
        price=Decimal("90"),
        opened_at=2,
    )

    lots = oldest_lots(con, "SOLUSDT")
    consumed = consume_fifo(con, "SOLUSDT", Decimal("0.5"))

    assert [lot.qty for lot in lots] == [Decimal("1")]
    assert [lot.qty for lot in consumed] == [Decimal("0.5")]
    assert con.execute(
        "SELECT qty,status FROM inventory_lots WHERE lot_id=1"
    ).fetchone() == ("0", "OPEN")


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
