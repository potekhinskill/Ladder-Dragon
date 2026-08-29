# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: bound historical-context GET reads without sharing the order transport.
"""Three allowed read endpoints, bounded decoded bytes, no mutation method."""

from __future__ import annotations

import hashlib
import hmac
import json
import re
import time
from urllib.parse import urlencode, urlsplit

import requests

from ladder_dragon.execution.time_safety import exchange_time_offset_ms

MAX_RESPONSE_BYTES = 64 * 1024
# Current depth archives contain Mainnet data. Testnet context cannot be mixed
# into that history until both contracts carry a separate venue identity.
HOSTS = {"api.binance.com", "api1.binance.com", "api2.binance.com", "api3.binance.com", "api4.binance.com"}


class HistoricalContextClient:
    """Use runtime credentials only for the symbol commission GET endpoint."""

    def __init__(self, *, base_url: str, credentials, session=None):
        parsed = urlsplit(base_url)
        if (parsed.scheme != "https" or parsed.hostname not in HOSTS or parsed.username or parsed.password
                or parsed.port not in (None, 443) or parsed.path not in ("", "/") or parsed.query or parsed.fragment):
            raise ValueError("context source host unsupported")
        self.base_url = f"https://{parsed.hostname}"
        self.credentials = credentials
        self.session = session or requests.Session()
        self.cooldown_until = 0.0
        self.offset_ms, self.clock_checked = None, 0.0

    def _get(self, endpoint: str, params: dict, headers=None) -> object:
        if endpoint not in {
            "/api/v3/time",
            "/api/v3/exchangeInfo",
            "/api/v3/klines",
            "/api/v3/account/commission",
        }:
            raise ValueError("context endpoint unsupported")
        if time.monotonic() < self.cooldown_until:
            raise RuntimeError("context source cooldown active")
        response = None
        try:
            response = self.session.get(self.base_url + endpoint, params=params, headers=headers or {},
                                        timeout=(5, 10), stream=True, allow_redirects=False)
            if response.status_code in (418, 429):
                try:
                    retry = int(response.headers.get("Retry-After", "120"))
                except (ValueError, TypeError):
                    retry = 120
                self.cooldown_until = time.monotonic() + min(259200, max(1, retry))
            if response.status_code != 200:
                raise RuntimeError("context source HTTP failure")
            body = bytearray()
            started = time.monotonic()
            for chunk in response.iter_content(chunk_size=8192):
                if len(body) + len(chunk) > MAX_RESPONSE_BYTES or time.monotonic() - started > 15:
                    raise ValueError("context source response limit reached")
                body.extend(chunk)
            payload = json.loads(body.decode("utf-8"))
            if not isinstance(payload, (dict, list)):
                raise ValueError("context source JSON container required")
            return payload
        except requests.RequestException:
            # Never retain a signed URL or provider text in diagnostics.
            raise RuntimeError("context source network failure") from None
        finally:
            if response is not None:
                response.close()

    def public_get(self, endpoint: str, params: dict) -> object:
        symbol = params.get("symbol")
        if not isinstance(symbol, str) or re.fullmatch(r"[A-Z0-9]{5,20}", symbol) is None:
            raise ValueError("context public symbol unsupported")
        if endpoint == "/api/v3/exchangeInfo" and set(params) == {"symbol"}:
            payload = self._get(endpoint, dict(params))
            if not isinstance(payload, dict):
                raise ValueError("context exchange information object required")
            return payload
        # PANIC observation uses one exact public request. It has no account or
        # order authority and remains subject to the shared decoded-byte limit.
        if (
            endpoint == "/api/v3/klines"
            and set(params) == {"symbol", "interval", "limit"}
            and params.get("interval") == "1m"
            and type(params.get("limit")) is int
            and params["limit"] == 120
        ):
            payload = self._get(endpoint, dict(params))
            if not isinstance(payload, list):
                raise ValueError("context kline array required")
            return payload
        raise ValueError("context public request unsupported")

    def signed_get(self, endpoint: str, params: dict) -> dict:
        if endpoint != "/api/v3/account/commission" or set(params) != {"symbol"}:
            raise ValueError("context signed request unsupported")
        key, secret = self.credentials()
        if not key or not secret:
            raise RuntimeError("context credentials unavailable")
        if self.offset_ms is None or time.monotonic() - self.clock_checked > 60:
            started = time.time_ns() // 1_000_000
            clock = self._get("/api/v3/time", {})
            finished = time.time_ns() // 1_000_000
            if not isinstance(clock, dict) or type(clock.get("serverTime")) is not int:
                raise ValueError("context exchange clock unavailable")
            self.offset_ms = exchange_time_offset_ms(
                server_time_ms=clock["serverTime"], request_started_ms=started, response_finished_ms=finished)
            self.clock_checked = time.monotonic()
        query = dict(params, timestamp=time.time_ns() // 1_000_000 + self.offset_ms, recvWindow=5000)
        query["signature"] = hmac.new(secret.encode(), urlencode(query).encode(), hashlib.sha256).hexdigest()
        payload = self._get(endpoint, query, {"X-MBX-APIKEY": key})
        if not isinstance(payload, dict):
            raise ValueError("context commission object required")
        return payload
