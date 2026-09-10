# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: bound market response bytes before financial JSON parsing.
"""Bound encoded and decoded bodies without trusting Content-Length."""

import time
import zlib
from urllib.parse import urlsplit

import requests
from urllib3 import exceptions as urllib_errors


MAX_RESPONSE_BYTES = 8 * 1024 * 1024
CHUNK_BYTES = 8192

# Only fixed provider paths can enter diagnostics; unknown paths may contain secrets.
_DIAGNOSTIC_PATHS = frozenset({
    "/api/v3/time", "/api/v3/exchangeInfo", "/api/v3/ticker/price",
    "/api/v3/klines", "/api/v3/depth", "/api/v3/aggTrades",
    "/api/v3/account", "/api/v3/myTrades", "/api/v3/openOrders",
    "/api/v3/order", "/api/v3/orderList", "/api/v3/openOrderList",
})


def transport_error(error: BaseException, url: str, attempts: int,
                    elapsed: float, body_started: bool) -> requests.RequestException:
    """Return bounded diagnostics without retaining provider exceptions or responses."""
    if isinstance(error, (requests.exceptions.SSLError, urllib_errors.SSLError)):
        reason = "tls"
    elif isinstance(error, (requests.Timeout, urllib_errors.TimeoutError)):
        reason = "timeout"
    elif body_started:
        reason = "body_read"
    elif isinstance(error, (requests.ConnectionError, urllib_errors.NewConnectionError)):
        reason = "connection"
    else:
        reason = "transport"
    try:
        path = urlsplit(url).path
    except ValueError:
        path = "unknown"
    endpoint = path if path in _DIAGNOSTIC_PATHS else "unknown"
    stage = "body" if body_started else "headers"
    return requests.RequestException(
        f"market transport failed reason={reason} endpoint={endpoint} "
        f"stage={stage} attempts={attempts} elapsed_ms={max(0, round(elapsed * 1000))}"
    )


class MarketResponseError(RuntimeError):
    """Reject unsafe response framing without retaining provider content."""


def remaining_seconds(deadline: float) -> float:
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise requests.Timeout("market request budget exhausted")
    return remaining


def read_body(response: requests.Response, *, deadline: float, max_bytes: int | None = None) -> bytes:
    """Read raw chunks once, then decompress with an explicit output ceiling.

    The budget is checked between raw reads. Socket inactivity timeouts still
    bound blocking reads; DNS and OS scheduling are not hard-cancellable.
    """
    limit = MAX_RESPONSE_BYTES if max_bytes is None else min(MAX_RESPONSE_BYTES, max_bytes)
    if limit <= 0:
        raise MarketResponseError("invalid response byte limit")
    encoding = response.headers.get("Content-Encoding", "identity").strip().lower()
    if encoding not in {"identity", "gzip", "deflate"}:
        raise MarketResponseError("unsupported market response encoding")
    decoder = (
        zlib.decompressobj(31 if encoding == "gzip" else zlib.MAX_WBITS)
        if encoding != "identity" else None
    )
    body = bytearray()
    encoded_size = 0
    while True:
        remaining_seconds(deadline)
        # read1 returns available wire data without waiting to fill a chunk.
        chunk = response.raw.read1(min(CHUNK_BYTES, limit + 1), decode_content=False)
        remaining_seconds(deadline)
        if not chunk:
            break
        encoded_size += len(chunk)
        if encoded_size > limit:
            raise MarketResponseError("market response exceeds byte limit")
        try:
            decoded = (
                decoder.decompress(chunk, limit - len(body) + 1)
                if decoder is not None else chunk
            )
        except zlib.error:
            raise MarketResponseError("invalid market response encoding") from None
        if len(body) + len(decoded) > limit:
            raise MarketResponseError("market response exceeds byte limit")
        body.extend(decoded)
        if decoder is not None and decoder.unused_data:
            raise MarketResponseError("trailing compressed market response data")
    if decoder is not None and not decoder.eof:
        raise MarketResponseError("incomplete compressed market response")
    return bytes(body)
