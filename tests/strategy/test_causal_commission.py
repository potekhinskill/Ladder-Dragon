from decimal import Decimal, localcontext

import pytest

from ladder_dragon.strategy.prediction.causal_commission import value_bnb_commission
from ladder_dragon.execution.trade_accounting import commission_status_is_valued


def value(evidence_changes=None, **changes):
    evidence = dict(symbol="BNBUSDT", price="600.12", market_time_ms=1000,
                    available_at_ms=1100, source_sha256="a" * 64)
    evidence.update(evidence_changes or {})
    arguments = dict(symbol="SOLUSDT", commission_amount="0.0001",
                     fill_time_ms=1200, max_age_ms=1000, price_evidence=evidence)
    arguments.update(changes)
    return value_bnb_commission(**arguments)


def test_direct_reference_is_exact_but_not_accounting_attestation():
    result = value()
    assert result.quote_value == Decimal("0.060012")
    assert result.source_sha256 == "a" * 64
    assert not commission_status_is_valued(result.reason)


@pytest.mark.parametrize("change,reason", [
    ({"available_at_ms": 1200}, "PRICE_NOT_AVAILABLE_BEFORE_FILL"),
    ({"available_at_ms": 60000}, "PRICE_NOT_AVAILABLE_BEFORE_FILL"),
    ({"market_time_ms": 1201, "available_at_ms": 1201}, "PRICE_NOT_AVAILABLE_BEFORE_FILL"),
    ({"market_time_ms": 1101}, "PRICE_TIME_INVALID"),
    ({"market_time_ms": 0}, "PRICE_TIME_INVALID"),
    ({"available_at_ms": True}, "PRICE_TIME_INVALID"),
    ({"market_time_ms": 200}, "PRICE_STALE"),
    ({"symbol": "ETHUSDT"}, "PRICE_MARKET_MISMATCH"),
    ({"symbol": "USDTBNB"}, "PRICE_MARKET_MISMATCH"),
    ({"source_sha256": ""}, "PRICE_SOURCE_INVALID"),
    ({"price": "0"}, "PRICE_VALUE_INVALID"),
    ({"price": "NaN"}, "PRICE_VALUE_INVALID"),
    ({"price": 600.12}, "PRICE_VALUE_INVALID"),
    ({"price": "1e999999"}, "PRICE_VALUE_INVALID"),
    ({"price": "9" * 129}, "PRICE_VALUE_INVALID"),
])
def test_unusable_price_is_unknown_not_zero(change, reason):
    result = value(change)
    assert result.quote_value is None and result.reason == reason
    assert result.source_sha256 is None


@pytest.mark.parametrize("evidence", [None, {}, [], {"price": "600"}])
def test_missing_price_never_becomes_free_fee(evidence):
    assert value(price_evidence=evidence).quote_value is None
    assert value(price_evidence=evidence, commission_amount="0").quote_value is None


@pytest.mark.parametrize("changes", [dict(fill_time_ms=True), dict(max_age_ms=0),
    dict(commission_amount="-1"), dict(commission_amount="NaN"),
    dict(commission_amount=0.1), dict(symbol="solusdt"), dict(symbol="SOLBNB")])
def test_invalid_request_is_rejected(changes):
    with pytest.raises(ValueError):
        value(**changes)


def test_freshness_uses_market_time_not_recent_receipt():
    assert value({"market_time_ms": 201, "available_at_ms": 1199}).quote_value is not None
    assert value({"market_time_ms": 200, "available_at_ms": 1199}).quote_value is None


def test_precision_and_input_immutability():
    evidence = dict(symbol="BNBUSDT", price="600.123456789", market_time_ms=1000,
                    available_at_ms=1100, source_sha256="b" * 64)
    original = evidence.copy()
    with localcontext() as context:
        context.prec = 3
        result = value(price_evidence=evidence, commission_amount="0.000000000000000000001")
    assert result.quote_value == Decimal("0.000000000000000000600123456789")
    assert evidence == original
