from decimal import Decimal as D, localcontext

import pytest

from ladder_dragon.execution.order_recovery import OrderJournal
from ladder_dragon.execution.journal.buy_inventory import SETTLEMENT_KEY, acquired_quantity
from ladder_dragon.execution.protection_quantity import verify_quantities
from tests.support.exchange_evidence import exit_order


def seeded(tmp_path):
    journal = OrderJournal(tmp_path / "orders.sqlite3", venue="mainnet")
    journal.prepare(client_order_id="buy", symbol="SOLUSDT", side="BUY", purpose="ladder",
                    order_type="LIMIT", quantity="1", price="100")
    order = dict(symbol="SOLUSDT", side="BUY", orderId=110, origQty="1", executedQty="1",
                 cummulativeQuoteQty="100", status="FILLED")
    fills = [dict(symbol="SOLUSDT", orderId=110, id=1, isBuyer=True, qty="1", price="100",
                  quoteQty="100", commission="0.001", commissionAsset="SOL")]
    journal.record_exchange_order("buy", order)
    journal.record_buy_settlement("buy", order, fills)
    return journal, order, fills


def protect(journal, qty="0.999"):
    journal.prepare(client_order_id="oco", symbol="SOLUSDT", side="SELL", purpose="oco",
                    order_type="OCO", quantity=qty, price="102", parent_client_order_id="buy")
    legs = [dict(orderId=121, clientOrderId="TP-A", type="LIMIT_MAKER"),
            dict(orderId=122, clientOrderId="SL-A", type="STOP_LOSS_LIMIT")]
    journal.mark_verified_protected(parent_client_order_id="buy", protection_client_order_id="oco",
                                    legs=legs, order_list_id=120)
    return [dict(leg, origQty=qty, executedQty="0", status="NEW") for leg in legs]


def test_net_evidence_survives_restart_and_final_writer(tmp_path):
    journal, order, fills = seeded(tmp_path)
    journal.record_buy_settlement("buy", order, fills)
    restored = OrderJournal(journal.path, venue="mainnet")
    assert acquired_quantity(restored.get("buy")) == D("0.999")
    legs = protect(restored)
    verify_quantities(restored, "buy", restored.get("oco"), legs)
    restored.mark_exact_lifecycle_closed(protection_client_order_id="oco", exit_order_id=121,
                                         exit_reason="TP", exit_order=exit_order(qty="0.999"))
    assert restored.get("buy").state == "CLOSED"


def test_generic_metadata_cannot_supply_settlement(tmp_path):
    journal, _, _ = seeded(tmp_path)
    with pytest.raises(ValueError):
        journal.update_metadata("buy", {SETTLEMENT_KEY: {}})
    assert acquired_quantity(journal.get("buy")) == D("0.999")


def test_settlement_is_immutable_and_invalid_retry_is_atomic(tmp_path):
    journal, order, fills = seeded(tmp_path)
    with pytest.raises(RuntimeError, match="immutable"):
        journal.record_buy_settlement("buy", order, [dict(fills[0], commission="0.002")])
    with pytest.raises(ValueError):
        journal.record_buy_settlement("buy", order, [])
    assert acquired_quantity(journal.get("buy")) == D("0.999")


def test_gross_sell_cannot_close_net_inventory(tmp_path):
    journal, _, _ = seeded(tmp_path)
    legs = protect(journal, "1")
    with pytest.raises(RuntimeError):
        verify_quantities(journal, "buy", journal.get("oco"), legs)
    with pytest.raises(RuntimeError):
        journal.mark_exact_lifecycle_closed(protection_client_order_id="oco", exit_order_id=121,
                                             exit_reason="TP", exit_order=exit_order(qty="1"))
    assert journal.get("buy").state != "CLOSED"


def test_changed_durable_execution_invalidates_net_evidence(tmp_path):
    journal, order, _ = seeded(tmp_path)
    journal.record_exchange_order("buy", dict(order, executedQty="0.9", cummulativeQuoteQty="90"))
    with pytest.raises(RuntimeError):
        acquired_quantity(journal.get("buy"))


def test_small_fee_survives_coverage_and_final_writer(tmp_path):
    journal, order, fills = seeded(tmp_path)
    # Use a separate journal: already verified evidence cannot be replaced.
    journal = OrderJournal(tmp_path / "tiny.sqlite3", venue="mainnet")
    journal.prepare(client_order_id="buy", symbol="SOLUSDT", side="BUY", purpose="ladder",
                    order_type="LIMIT", quantity="1", price="100")
    journal.record_exchange_order("buy", order)
    fills[0]["commission"] = "0.000000000000000000000000000001"
    journal.record_buy_settlement("buy", order, fills)
    net = "0.999999999999999999999999999999"
    legs = protect(journal, net)
    with localcontext() as context:
        context.prec = 4
        verify_quantities(journal, "buy", journal.get("oco"), legs)
        journal.mark_exact_lifecycle_closed(protection_client_order_id="oco", exit_order_id=121,
                                             exit_reason="TP", exit_order=exit_order(qty=net))
    assert journal.get("buy").state == "CLOSED"


def test_capacity_failure_preserves_protected_evidence(tmp_path, monkeypatch):
    from ladder_dragon.execution.journal import buy_inventory
    journal, order, fills = seeded(tmp_path)
    protect(journal)
    monkeypatch.setattr(buy_inventory, "MAXIMUM_SETTLEMENT_BYTES", 1)
    with pytest.raises(RuntimeError, match="capacity"):
        journal.record_buy_settlement("buy", order, fills)
    assert journal.get("buy").state == "PROTECTED"
    assert journal.get("buy").metadata[SETTLEMENT_KEY]["fills"] == fills
