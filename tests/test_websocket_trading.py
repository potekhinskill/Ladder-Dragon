import hashlib
import hmac
import json
from urllib.parse import urlencode

import pytest

from ladder_dragon.execution.websocket_trading import (
    BinanceWebSocketResponseError,
    BinanceWebSocketTradingTransport,
    BinanceWebSocketUnknownOutcome,
    RequestSigner,
)


class FakeConnection:
    def __init__(self, response=None, error=None):
        self.response = response
        self.error = error
        self.sent = []
        self.closed = False

    def settimeout(self, _timeout):
        return None

    def send(self, frame):
        self.sent.append(json.loads(frame))

    def recv(self):
        if self.error is not None:
            raise self.error
        payload = dict(self.response)
        payload["id"] = self.sent[-1]["id"]
        return json.dumps(payload)

    def close(self):
        self.closed = True


def make_transport(connection, *, live=True):
    return BinanceWebSocketTradingTransport(
        api_key=lambda: "public-key",
        signer=RequestSigner(
            key_type="HMAC",
            hmac_secret=lambda: "private-secret",
            ed25519_private_key_file=lambda: "",
        ),
        recv_window=lambda: 5000,
        live=lambda: live,
        testnet=True,
        connect=lambda *_args, **_kwargs: connection,
        timestamp_ms=lambda: 123456789,
    )


def test_hmac_signer_uses_canonical_sorted_parameters():
    signer = RequestSigner(
        key_type="HMAC",
        hmac_secret=lambda: "secret",
        ed25519_private_key_file=lambda: "",
    )
    params = {"timestamp": 2, "apiKey": "key", "symbol": "SOLUSDT"}
    expected = hmac.new(
        b"secret",
        urlencode(sorted(params.items())).encode("ascii"),
        hashlib.sha256,
    ).hexdigest()

    assert signer.sign(params) == expected


def test_ed25519_signer_requires_owner_only_key_file(tmp_path):
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import (
        Ed25519PrivateKey,
    )

    private_key = Ed25519PrivateKey.generate()
    key_path = tmp_path / "binance-ed25519.pem"
    key_path.write_bytes(
        private_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        )
    )
    key_path.chmod(0o600)
    signer = RequestSigner(
        key_type="ED25519",
        hmac_secret=lambda: "",
        ed25519_private_key_file=lambda: str(key_path),
    )

    assert signer.sign({"apiKey": "public", "timestamp": 1})

    key_path.chmod(0o640)
    with pytest.raises(PermissionError, match="group/world"):
        signer.sign({"apiKey": "public", "timestamp": 1})


def test_websocket_transport_reuses_connection_and_maps_order_method():
    connection = FakeConnection({"status": 200, "result": {"orderId": 7}})
    transport = make_transport(connection)

    assert transport.request(
        "POST",
        "/api/v3/order",
        {"symbol": "SOLUSDT", "side": "BUY"},
    ) == {"orderId": 7}
    assert transport.request(
        "POST",
        "/api/v3/order",
        {"symbol": "SOLUSDT", "side": "BUY"},
    ) == {"orderId": 7}
    assert connection.sent[0]["method"] == "order.place"
    assert len(connection.sent) == 2


def test_websocket_transport_never_retries_unknown_mutation():
    connection = FakeConnection(error=TimeoutError("secret-value"))
    transport = make_transport(connection)

    with pytest.raises(BinanceWebSocketUnknownOutcome) as exc:
        transport.request(
            "POST",
            "/api/v3/order",
            {"symbol": "SOLUSDT", "newClientOrderId": "safe-id"},
        )

    assert len(connection.sent) == 1
    assert "secret-value" not in str(exc.value)
    assert connection.closed is True


def test_websocket_transport_returns_definitive_business_error():
    connection = FakeConnection({
        "status": 400,
        "error": {"code": -1013, "msg": "invalid quantity"},
    })
    transport = make_transport(connection)

    with pytest.raises(BinanceWebSocketResponseError) as exc:
        transport.request("POST", "/api/v3/order", {"symbol": "SOLUSDT"})

    assert exc.value.code == -1013


def test_websocket_transport_blocks_dry_mutation_before_connect():
    transport = make_transport(FakeConnection(), live=False)

    with pytest.raises(RuntimeError, match="DRY mode blocked"):
        transport.request("DELETE", "/api/v3/order", {"symbol": "SOLUSDT"})
