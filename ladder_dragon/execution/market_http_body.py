# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: bound market response bytes before financial JSON parsing.
"""Bound encoded and decoded bodies without trusting Content-Length."""

import time
import zlib

import requests


MAX_RESPONSE_BYTES = 8 * 1024 * 1024
CHUNK_BYTES = 8192


class MarketResponseError(RuntimeError):
    """Reject unsafe response framing without retaining provider content."""


def remaining_seconds(deadline: float) -> float:
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise requests.Timeout("market request budget exhausted")
    return remaining


def read_body(response: requests.Response, *, deadline: float) -> bytes:
    """Read raw chunks once, then decompress with an explicit output ceiling.

    The budget is checked between raw reads. Socket inactivity timeouts still
    bound blocking reads; DNS and OS scheduling are not hard-cancellable.
    """
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
        chunk = response.raw.read1(CHUNK_BYTES, decode_content=False)
        remaining_seconds(deadline)
        if not chunk:
            break
        encoded_size += len(chunk)
        if encoded_size > MAX_RESPONSE_BYTES:
            raise MarketResponseError("market response exceeds byte limit")
        try:
            decoded = (
                decoder.decompress(chunk, MAX_RESPONSE_BYTES - len(body) + 1)
                if decoder is not None else chunk
            )
        except zlib.error:
            raise MarketResponseError("invalid market response encoding") from None
        if len(body) + len(decoded) > MAX_RESPONSE_BYTES:
            raise MarketResponseError("market response exceeds byte limit")
        body.extend(decoded)
        if decoder is not None and decoder.unused_data:
            raise MarketResponseError("trailing compressed market response data")
    if decoder is not None and not decoder.eof:
        raise MarketResponseError("incomplete compressed market response")
    return bytes(body)
