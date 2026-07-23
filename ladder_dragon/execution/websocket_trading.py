# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: submit supported Binance mutations over one authenticated WebSocket.
"""Persistent Binance Spot WebSocket API transport with unknown-ACK safety."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import stat
import threading
import time
import uuid
from pathlib import Path
from typing import Callable, Mapping
from urllib.parse import urlencode

import requests
from websocket import WebSocketException, WebSocketTimeoutException, create_connection

from ladder_dragon.execution.binance_transport import BinanceResponseError

WS_METHODS = {
    ("POST", "/api/v3/order"): "order.place",
    ("DELETE", "/api/v3/order"): "order.cancel",
    ("POST", "/api/v3/order/cancelReplace"): "order.cancelReplace",
    ("POST", "/api/v3/orderList/oco"): "orderList.place.oco",
    ("POST", "/api/v3/orderList/otoco"): "orderList.place.otoco",
}


class BinanceWebSocketUnknownOutcome(requests.ConnectionError):
    """The mutation may have reached Binance but its response was not received."""

    def __init__(self, *, method: str, path: str, cause_type: str) -> None:
        self.method = method
        self.path = path
        self.cause_type = cause_type
        super().__init__(
            f"Binance WebSocket outcome is unknown: {cause_type} "
            f"endpoint={path}"
        )


class BinanceWebSocketResponseError(BinanceResponseError):
    """A definitive Binance WebSocket API business response."""

    def __init__(self, *, status: int, code: object, message: str) -> None:
        response = requests.Response()
        response.status_code = int(status)
        super().__init__(
            status=int(status),
            code=code,
            message=message,
            endpoint="websocket-api",
            response=response,
        )


def websocket_api_url(*, testnet: bool) -> str:
    return (
        "wss://ws-api.testnet.binance.vision/ws-api/v3"
        if testnet
        else "wss://ws-api.binance.com:443/ws-api/v3"
    )


class RequestSigner:
    """Sign canonical WebSocket API parameters without logging key material."""

    def __init__(
        self,
        *,
        key_type: str,
        hmac_secret: Callable[[], str],
        ed25519_private_key_file: Callable[[], str],
    ) -> None:
        self.key_type = key_type.strip().upper()
        self._hmac_secret = hmac_secret
        self._ed25519_private_key_file = ed25519_private_key_file
        self._key_lock = threading.Lock()
        self._ed25519_cache: tuple[Path, int, object] | None = None

    def sign(self, params: Mapping[str, object]) -> str:
        payload = urlencode(sorted(params.items()), doseq=True).encode("ascii")
        if self.key_type == "HMAC":
            secret = self._hmac_secret()
            if not secret:
                raise RuntimeError("HMAC API secret is unavailable")
            return hmac.new(
                secret.encode("utf-8"),
                payload,
                hashlib.sha256,
            ).hexdigest()
        if self.key_type != "ED25519":
            raise ValueError("BINANCE_KEY_TYPE must be HMAC or ED25519")
        key_path = Path(self._ed25519_private_key_file())
        if not key_path.is_absolute():
            raise RuntimeError("Ed25519 private-key path must be absolute")
        key_stat = key_path.stat()
        mode = stat.S_IMODE(key_stat.st_mode)
        if mode & 0o077:
            raise PermissionError(
                "Ed25519 private-key file must not be group/world accessible"
            )
        with self._key_lock:
            cached = self._ed25519_cache
            if (
                cached is None
                or cached[0] != key_path
                or cached[1] != key_stat.st_mtime_ns
            ):
                from cryptography.hazmat.primitives import serialization

                private_key = serialization.load_pem_private_key(
                    key_path.read_bytes(),
                    password=None,
                )
                self._ed25519_cache = (
                    key_path,
                    key_stat.st_mtime_ns,
                    private_key,
                )
            else:
                private_key = cached[2]
        return base64.b64encode(private_key.sign(payload)).decode("ascii")


class BinanceWebSocketTradingTransport:
    """Serialize one in-flight mutation over a reused WebSocket connection."""

    def __init__(
        self,
        *,
        api_key: Callable[[], str],
        signer: RequestSigner,
        recv_window: Callable[[], int],
        live: Callable[[], bool],
        testnet: bool,
        connect: Callable[..., object] = create_connection,
        timestamp_ms: Callable[[], int] = lambda: int(time.time() * 1000),
    ) -> None:
        self._api_key = api_key
        self._signer = signer
        self._recv_window = recv_window
        self._live = live
        self._connect = connect
        self._timestamp_ms = timestamp_ms
        self._url = websocket_api_url(testnet=testnet)
        self._lock = threading.Lock()
        self._connection: object | None = None

    def close(self) -> None:
        with self._lock:
            connection, self._connection = self._connection, None
            if connection is not None:
                try:
                    connection.close()
                except (OSError, RuntimeError, WebSocketException):
                    pass

    def _connected(self, timeout: float) -> object:
        if self._connection is None:
            self._connection = self._connect(self._url, timeout=timeout)
        else:
            self._connection.settimeout(timeout)
        return self._connection

    def request(
        self,
        method: str,
        path: str,
        params: Mapping[str, object] | None = None,
        *,
        timeout: float = 15.0,
    ) -> object:
        method = method.upper()
        ws_method = WS_METHODS.get((method, path))
        if ws_method is None:
            raise ValueError(f"unsupported WebSocket trading endpoint: {method} {path}")
        if not self._live():
            raise RuntimeError(
                f"DRY mode blocked mutating Binance request: {method} {path}"
            )
        api_key = self._api_key()
        if not api_key:
            raise RuntimeError("Binance API key is unavailable")
        signed = dict(params or {})
        signed["apiKey"] = api_key
        signed.setdefault("recvWindow", int(self._recv_window()))
        signed["timestamp"] = int(self._timestamp_ms())
        signed["signature"] = self._signer.sign(signed)
        request_id = uuid.uuid4().hex
        frame = json.dumps(
            {"id": request_id, "method": ws_method, "params": signed},
            separators=(",", ":"),
            sort_keys=True,
        )
        with self._lock:
            try:
                connection = self._connected(timeout)
                connection.send(frame)
                while True:
                    raw = connection.recv()
                    payload = json.loads(raw)
                    if not isinstance(payload, dict):
                        raise ValueError("WebSocket response is not an object")
                    if payload.get("id") != request_id:
                        continue
                    status = int(payload.get("status") or 0)
                    if status >= 400 or payload.get("error") is not None:
                        error = payload.get("error")
                        error = error if isinstance(error, dict) else {}
                        raise BinanceWebSocketResponseError(
                            status=status or 500,
                            code=error.get("code"),
                            message=str(error.get("msg") or ""),
                        )
                    return payload.get("result")
            except BinanceWebSocketResponseError:
                raise
            except (
                OSError,
                RuntimeError,
                TypeError,
                ValueError,
                WebSocketException,
                WebSocketTimeoutException,
            ) as exc:
                connection, self._connection = self._connection, None
                if connection is not None:
                    try:
                        connection.close()
                    except (OSError, RuntimeError, WebSocketException):
                        pass
                raise BinanceWebSocketUnknownOutcome(
                    method=method,
                    path=path,
                    cause_type=type(exc).__name__,
                ) from exc


def build_websocket_trading_transport(
    *,
    api_key: Callable[[], str],
    api_secret: Callable[[], str],
    recv_window: Callable[[], int],
    live: Callable[[], bool],
    testnet: bool,
) -> BinanceWebSocketTradingTransport:
    """Build the transport from non-secret configuration references."""
    signer = RequestSigner(
        key_type=os.getenv("BINANCE_KEY_TYPE", "HMAC"),
        hmac_secret=api_secret,
        ed25519_private_key_file=lambda: os.getenv(
            "BINANCE_ED25519_PRIVATE_KEY_FILE",
            "",
        ),
    )
    return BinanceWebSocketTradingTransport(
        api_key=api_key,
        signer=signer,
        recv_window=recv_window,
        live=live,
        testnet=testnet,
    )
