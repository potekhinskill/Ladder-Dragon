from copy import deepcopy
from decimal import Decimal
import hashlib
import json

import pytest

from ladder_dragon.execution.order_recovery import OrderJournal
from ladder_dragon.strategy.prediction.commission_evidence import value_settled_bnb_fill


def encoded(value):
    return json.dumps(value, separators=(",", ":")).encode()


@pytest.fixture
def evidence(tmp_path):
    journal = OrderJournal(tmp_path / "orders.sqlite3", venue="mainnet")
    journal.prepare(client_order_id="buy", symbol="SOLUSDT", side="BUY", purpose="ladder",
                    order_type="LIMIT", quantity="1", price="100")
    order = dict(symbol="SOLUSDT", side="BUY", orderId=42, origQty="1", executedQty="1",
                 cummulativeQuoteQty="100", status="FILLED")
    fills = [dict(symbol="SOLUSDT", orderId=42, id=n, isBuyer=True, qty="0.5", price="100",
                  quoteQty="50", commission="0.0001", commissionAsset="BNB", time=2000+n)
             for n in (1, 2)]
    journal.record_exchange_order("buy", order)
    journal.record_buy_settlement("buy", order, fills)
    price = dict(e="aggTrade", s="BNBUSDT", a=77, p="600", T=1700, E=1800,
                 _received_at_ms=1900, _source="binance-public-websocket")
    return journal, fills, price


def run(evidence, *, fills=None, price=None, **changes):
    journal, original_fills, original_price = evidence
    fill_bytes = encoded(original_fills if fills is None else fills)
    price_bytes = encoded(original_price if price is None else price)
    args = dict(parent=journal.get("buy"), trade_id=1, fills_bytes=fill_bytes,
                fills_sha256=hashlib.sha256(fill_bytes).hexdigest(), price_event_bytes=price_bytes,
                price_event_sha256=hashlib.sha256(price_bytes).hexdigest(), max_age_ms=1000)
    args.update(changes)
    return value_settled_bnb_fill(**args)


def test_binding_survives_restart_without_journal_mutation(evidence):
    journal, fills, price = evidence
    before = journal.get("buy")
    result = run(evidence, parent=OrderJournal(journal.path, venue="mainnet").get("buy"))
    assert result.valuation.quote_value == Decimal("0.0600")
    assert (result.order_id, result.trade_id, result.fill_time_ms) == (42, 1, 2001)
    assert result.fill_source_sha256 == hashlib.sha256(encoded(fills)).hexdigest()
    assert journal.get("buy") == before
    assert run(evidence, fills=list(reversed(fills))).valuation == result.valuation


@pytest.mark.parametrize("field,value", [("symbol", "ETHUSDT"), ("orderId", 99),
    ("id", 99), ("commission", "0.0002"), ("commissionAsset", "SOL"),
    ("isBuyer", False), ("time", None), ("time", True), ("qty", "0.4")])
def test_changed_fill_rejected_even_with_recomputed_hash(evidence, field, value):
    fills = deepcopy(evidence[1])
    fills[0][field] = value
    with pytest.raises((ValueError, RuntimeError)):
        run(evidence, fills=fills)


@pytest.mark.parametrize("kind", ["missing", "duplicate", "unknown", "bool"])
def test_complete_unique_fill_set_and_exact_selection_required(evidence, kind):
    fills = evidence[1]
    changes = dict(fills=fills[:1]) if kind == "missing" else (
        dict(fills=[fills[0], fills[0]]) if kind == "duplicate" else dict(trade_id=True if kind == "bool" else 88))
    with pytest.raises((ValueError, RuntimeError)):
        run(evidence, **changes)


@pytest.mark.parametrize("field", ["fills_sha256", "price_event_sha256"])
def test_pin_mismatch_rejected(evidence, field):
    with pytest.raises(ValueError, match="pinned hash"):
        run(evidence, **{field: "0" * 64})


def test_changed_durable_execution_rejected(evidence):
    journal = evidence[0]
    from ladder_dragon.execution.journal.buy_inventory import SETTLEMENT_KEY
    order = journal.get("buy").metadata[SETTLEMENT_KEY]["order"]
    journal.record_exchange_order("buy", dict(order, executedQty="0.9", cummulativeQuoteQty="90"))
    with pytest.raises(RuntimeError):
        run(evidence)


def test_legacy_parent_cannot_infer_settlement(evidence):
    from dataclasses import replace
    with pytest.raises(RuntimeError):
        run(evidence, parent=replace(evidence[0].get("buy"), metadata={}))


def test_timestamp_change_requires_new_external_pin(evidence):
    fills = deepcopy(evidence[1])
    fills[0]["time"] += 1
    with pytest.raises(ValueError, match="pinned hash"):
        run(evidence, fills=fills, fills_sha256=hashlib.sha256(encoded(evidence[1])).hexdigest())


@pytest.mark.parametrize("update,reason", [
    ({"_received_at_ms": 2001}, "PRICE_NOT_AVAILABLE_BEFORE_FILL"),
    ({"_received_at_ms": 3000}, "PRICE_NOT_AVAILABLE_BEFORE_FILL"),
    ({"T": 1001}, "PRICE_STALE"),
    ({"s": "ETHUSDT"}, "PRICE_MARKET_MISMATCH"),
    ({"p": "0"}, "PRICE_VALUE_INVALID"),
])
def test_recorded_price_reuses_causal_fail_closed_contract(evidence, update, reason):
    result = run(evidence, price=dict(evidence[2], **update))
    assert result.valuation.quote_value is None and result.valuation.reason == reason


@pytest.mark.parametrize("update", [{"e": "kline"}, {"_source": "other"},
    {"E": 2000}, {"T": 1801}, {"a": True}])
def test_unsupported_or_inconsistent_record_rejected(evidence, update):
    with pytest.raises(ValueError):
        run(evidence, price=dict(evidence[2], **update))


@pytest.mark.parametrize("body", [b'{"p":"1","p":"2"}', b'{"secret":"PRIVATE_TEST_MARKER",',
                                     b"[" * 2000, b" " * 16385])
def test_bounded_parser_and_safe_diagnostics(evidence, body):
    with pytest.raises(ValueError) as error:
        run(evidence, price_event_bytes=body, price_event_sha256=hashlib.sha256(body).hexdigest())
    assert "PRIVATE_TEST_MARKER" not in str(error.value)
