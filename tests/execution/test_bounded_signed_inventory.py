from types import SimpleNamespace
import requests
import pytest

from ladder_dragon.execution.binance_transport import BinanceTransport
from ladder_dragon.execution.market_http_body import MarketResponseError


@pytest.mark.parametrize("body, limit, blocked", [(b"[]", 2, False), (b"[123]", 2, True)])
def test_signed_read_streams_and_closes_before_parsing(body, limit, blocked):
    chunks = iter([body, b""])
    response = requests.Response()
    response.status_code = 200
    response.raw = SimpleNamespace(read1=lambda *args, **kwargs: next(chunks))
    closed, calls = [], []
    response.close = lambda: closed.append(True)
    def request(*args, **kwargs):
        calls.append(kwargs)
        return response
    transport = BinanceTransport(SimpleNamespace(request=request), base_url=lambda: "https://example.invalid",
                                 api_key=lambda: "synthetic", api_secret=lambda: "synthetic",
                                 live=lambda: False, recv_window=lambda: 5000, logger=lambda _: None)
    if blocked:
        with pytest.raises(MarketResponseError):
            transport.signed_request("GET", "/api/v3/myTrades", maximum_response_bytes=limit)
    else:
        assert transport.signed_request("GET", "/api/v3/myTrades", maximum_response_bytes=limit) == []
    assert closed == [True]
    assert calls[0]["stream"] is True and calls[0]["allow_redirects"] is False
