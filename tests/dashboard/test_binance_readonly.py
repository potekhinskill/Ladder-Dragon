"""Read-only dashboard transport tests."""

import pytest
import json

from ladder_dragon.dashboard.services.binance_readonly import (
    DashboardBinanceError,
    ReadOnlyBinanceClient,
)
from tests.support.module_loaders import load_dashboard


class Response:
    def __init__(self, status_code, payload):
        self.status_code = status_code
        self._payload = payload

    def json(self):
        return self._payload

    def iter_content(self, chunk_size=8192):
        yield json.dumps(self._payload).encode("utf-8")


class Session:
    def __init__(self, signed_responses, time_response):
        self.signed_responses = iter(signed_responses)
        self.time_response = time_response
        self.signed_params = []
        self.time_reads = 0

    def get(self, url, **kwargs):
        self.time_reads += 1
        return self.time_response

    def request(self, method, url, **kwargs):
        self.signed_params.append(dict(kwargs["params"]))
        return next(self.signed_responses)


def _client(session):
    client = ReadOnlyBinanceClient(
        session=session,
        base_url="https://api.binance.test",
        credentials=lambda: ("read-only-key", "secret-value"),
        auth_error=lambda **kwargs: None,
    )
    client._offset_ms = 0
    client._offset_updated_at = 1_000.0
    return client


def test_signed_read_resynchronizes_once_after_timestamp_rejection(monkeypatch):
    from ladder_dragon.dashboard.services import binance_readonly

    session = Session(
        [Response(400, {"code": -1021}), Response(200, {"balances": []})],
        Response(200, {"serverTime": 1_005_000}),
    )
    client = _client(session)
    monkeypatch.setattr(binance_readonly.time, "time", lambda: 1_000.0)

    payload = client.signed("GET", "/api/v3/account")

    assert payload == {"balances": []}
    assert session.time_reads == 1
    assert [row["timestamp"] for row in session.signed_params] == [
        1_000_000,
        1_005_000,
    ]


def test_repeated_timestamp_rejection_is_fail_closed_and_secret_safe(monkeypatch):
    from ladder_dragon.dashboard.services import binance_readonly

    session = Session(
        [Response(400, {"code": -1021}), Response(400, {"code": -1021})],
        Response(200, {"serverTime": 1_005_000}),
    )
    client = _client(session)
    monkeypatch.setattr(binance_readonly.time, "time", lambda: 1_000.0)

    with pytest.raises(DashboardBinanceError) as caught:
        client.signed("GET", "/api/v3/account")

    message = str(caught.value)
    assert "code=-1021" in message
    assert "secret-value" not in message
    assert "signature" not in message
    assert session.time_reads == 1


def test_readonly_client_rejects_mutations_before_network_access():
    session = Session([], Response(200, {"serverTime": 1_000_000}))
    client = _client(session)

    with pytest.raises(RuntimeError, match="read-only"):
        client.signed("POST", "/api/v3/order")

    assert session.signed_params == []


def test_historical_price_requires_the_requested_minute(monkeypatch):
    module = load_dashboard(monkeypatch)
    requested = 1_000_001
    requested_minute = 960_000
    monkeypatch.setattr(
        module,
        "_pub_get",
        lambda path, params=None: [[requested_minute + 60_000, "75.0"]],
    )

    with pytest.raises(RuntimeError, match="timestamp does not match"):
        module.price_at("SOLUSDT", requested)


def test_equity_change_is_unavailable_without_historical_price(monkeypatch):
    module = load_dashboard(monkeypatch)
    monkeypatch.setattr(module, "account_balances_now", lambda: {"USDT": 10.0})
    monkeypatch.setattr(
        module,
        "price_at",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            RuntimeError("historical price is unavailable")
        ),
    )

    result = module.equity_pnl_usdt(1_000, [], 0.001, ["SOLUSDT"])

    assert result["equity_pnl_usdt"] is None
    assert result["equity_then_usdt"] is None
    assert result["method"] == "unavailable-historical-price"
