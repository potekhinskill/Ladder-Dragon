from decimal import Decimal

import pytest

from ladder_dragon.supervision import runtime


def test_supervisor_exact_price_uses_real_transport_adapter(monkeypatch):
    expected = Decimal("123456789.123456789")
    monkeypatch.setattr(runtime.TM, "_public_get", lambda *_a: {"price": str(expected)})

    def forbidden(_symbol):
        raise AssertionError("risk must not use the legacy float adapter")

    monkeypatch.setattr(runtime.TM, "get_ticker_price", forbidden)
    assert runtime.get_last_price_decimal("SOLUSDT") == expected


@pytest.mark.parametrize("payload", [
    {}, [], None, {"price": None}, {"price": 1.25}, {"price": True},
    {"price": "0"}, {"price": "-1"}, {"price": "NaN"},
    {"price": "Infinity"}, {"price": "synthetic-secret-marker"},
])
def test_invalid_transport_prices_fail_closed_without_payload_leak(
    monkeypatch, capsys, payload,
):
    monkeypatch.setattr(runtime.TM, "_public_get", lambda *_a: payload)
    with pytest.raises(ValueError) as error:
        runtime.get_last_price_decimal("SOLUSDT")
    assert str(error.value) == "ticker price must be a finite positive decimal string"
    assert error.value.__suppress_context__ or error.value.__context__ is None
    captured = capsys.readouterr()
    assert captured.out == captured.err == ""


def test_legacy_ticker_view_remains_float(monkeypatch):
    monkeypatch.setattr(runtime.TM, "_public_get", lambda *_a: {"price": "75.25"})
    value = runtime.TM.get_ticker_price("SOLUSDT")
    assert isinstance(value, float)
    assert value == 75.25


def test_initial_ticker_uses_public_only_session(monkeypatch):
    calls = []

    def ticker(symbol, *, session=None):
        calls.append((symbol, session))
        return Decimal("75.25")

    monkeypatch.setattr(runtime.TM, "get_ticker_price_decimal", ticker)

    assert runtime.get_initial_last_price_decimal("SOLUSDT") == Decimal("75.25")
    assert calls == [("SOLUSDT", runtime.TM.INITIAL_PUBLIC_SESSION)]
    assert runtime.TM.INITIAL_PUBLIC_SESSION is not runtime.TM.SESSION
    assert "X-MBX-APIKEY" not in runtime.TM.INITIAL_PUBLIC_SESSION.headers


def test_transport_failure_preserves_provider_classification(monkeypatch):
    failure = runtime.TM.BinanceHttpError(status=400, code=-1121, endpoint="/api/v3/ticker/price")

    def unavailable(*_args):
        raise failure

    monkeypatch.setattr(runtime.TM, "_public_get", unavailable)
    with pytest.raises(runtime.TM.BinanceHttpError) as error:
        runtime.get_last_price_decimal("SOLUSDT")
    assert error.value is failure
