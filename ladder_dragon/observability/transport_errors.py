# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: classify transport failures without retaining private provider data.
"""Bounded transport diagnostics, independent of request and response ownership."""

import socket
from urllib.parse import urlsplit

import requests
from urllib3 import exceptions as urllib_errors


TRANSPORT_ERRORS = (requests.RequestException, urllib_errors.HTTPError)


def transport_cause(error: BaseException) -> str | None:
    """Inspect at most 16 exception nodes without serializing provider data."""
    pending, seen = [error], set()
    for _ in range(16):
        if not pending:
            break
        item = pending.pop(0)
        if not isinstance(item, BaseException) or id(item) in seen:
            continue
        seen.add(id(item))
        if isinstance(item, (socket.gaierror, urllib_errors.NameResolutionError)):
            return "dns"
        if isinstance(item, ConnectionRefusedError):
            return "refused"
        if isinstance(item, ConnectionResetError):
            return "reset"
        if isinstance(item, (requests.exceptions.SSLError, urllib_errors.SSLError)):
            return "tls"
        if isinstance(item, (requests.ConnectTimeout, urllib_errors.ConnectTimeoutError)) and not isinstance(item, urllib_errors.NewConnectionError):
            return "connect_timeout"
        if isinstance(item, (requests.ReadTimeout, urllib_errors.ReadTimeoutError)):
            return "read_timeout"
        pending.extend(child for child in (
            item.__cause__, item.__context__, getattr(item, "reason", None),
            *item.args[:4],
        ) if isinstance(child, BaseException))
    return None

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
    cause = transport_cause(error)
    detail = f" cause={cause}" if cause else ""
    return requests.RequestException(
        f"market transport failed reason={reason} endpoint={endpoint} "
        f"stage={stage} attempts={attempts}{detail} elapsed_ms={max(0, round(elapsed * 1000))}"
    )
