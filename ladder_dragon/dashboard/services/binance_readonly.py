# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: provide secret-safe read-only Binance access for the dashboard.
"""Secret-safe read-only Binance transport for the dashboard."""

from __future__ import annotations

import hashlib
import hmac
import json
import time
from collections.abc import Callable
from typing import Any

import requests

from ladder_dragon.execution.time_safety import exchange_time_offset_ms


MAX_RESPONSE_BYTES = 64 * 1024


class DashboardBinanceError(RuntimeError):
    """Report a bounded Binance failure without retaining a signed URL."""

    def __init__(self, *, endpoint: str, status: int | None, code: int | None) -> None:
        self.endpoint = endpoint
        self.status = status
        self.code = code
        parts = ["dashboard Binance read failed", f"endpoint={endpoint}"]
        if status is not None:
            parts.append(f"status={status}")
        if code is not None:
            parts.append(f"code={code}")
        super().__init__(" ".join(parts))


class ReadOnlyBinanceClient:
    """Use dedicated dashboard credentials for signed GET and HEAD requests."""

    def __init__(
        self,
        *,
        session: requests.Session,
        base_url: str,
        credentials: Callable[[], tuple[str, str]],
        auth_error: Callable[..., None],
        offset_ttl_sec: float = 60.0,
    ) -> None:
        self._session = session
        self._base_url = base_url.rstrip("/")
        self._credentials = credentials
        self._auth_error = auth_error
        self._offset_ttl_sec = offset_ttl_sec
        self._offset_ms: int | None = None
        self._offset_updated_at = 0.0

    @staticmethod
    def _payload(response: requests.Response, *, endpoint: str) -> Any:
        try:
            chunks = []
            size = 0
            for chunk in response.iter_content(chunk_size=8192):
                size += len(chunk)
                if size > MAX_RESPONSE_BYTES:
                    raise DashboardBinanceError(
                        endpoint=endpoint,
                        status=response.status_code,
                        code=None,
                    )
                chunks.append(chunk)
            return json.loads(b"".join(chunks).decode("utf-8"))
        except DashboardBinanceError:
            raise
        except (UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError):
            return None

    def refresh_clock(self, *, timeout: float = 10.0) -> None:
        """Refresh the exchange offset with midpoint latency compensation."""
        started = int(time.time() * 1000)
        try:
            response = self._session.get(
                f"{self._base_url}/api/v3/time", timeout=timeout, stream=True
            )
        except requests.RequestException as exc:
            raise DashboardBinanceError(
                endpoint="/api/v3/time", status=None, code=None
            ) from exc
        finished = int(time.time() * 1000)
        payload = self._payload(response, endpoint="/api/v3/time")
        if response.status_code >= 400 or not isinstance(payload, dict):
            raise DashboardBinanceError(
                endpoint="/api/v3/time",
                status=response.status_code,
                code=payload.get("code") if isinstance(payload, dict) else None,
            )
        try:
            server_time = int(payload["serverTime"])
        except (KeyError, TypeError, ValueError) as exc:
            raise DashboardBinanceError(
                endpoint="/api/v3/time", status=response.status_code, code=None
            ) from exc
        self._offset_ms = exchange_time_offset_ms(
            server_time_ms=server_time,
            request_started_ms=started,
            response_finished_ms=finished,
        )
        self._offset_updated_at = time.time()

    def timestamp_ms(self, *, timeout: float = 10.0) -> int:
        if (
            self._offset_ms is None
            or time.time() - self._offset_updated_at > self._offset_ttl_sec
        ):
            self.refresh_clock(timeout=timeout)
        return int(time.time() * 1000 + (self._offset_ms or 0))

    def signed(self, method: str, path: str, params=None, timeout: float = 10.0):
        normalized_method = method.upper()
        if normalized_method not in {"GET", "HEAD"}:
            raise RuntimeError("dashboard API credentials are read-only by design")
        key, secret = self._credentials()
        if not key or not secret:
            raise RuntimeError("No API creds")
        headers = {"X-MBX-APIKEY": key}
        for attempt in range(2):
            request_params = dict(params or {})
            request_params.setdefault("recvWindow", 5000)
            request_params["timestamp"] = self.timestamp_ms(timeout=timeout)
            query = requests.models.RequestEncodingMixin._encode_params(request_params)
            signature = hmac.new(
                secret.encode(), query.encode(), hashlib.sha256
            ).hexdigest()
            request_params["signature"] = signature
            try:
                response = self._session.request(
                    normalized_method,
                    f"{self._base_url}{path}",
                    params=request_params,
                    headers=headers,
                    timeout=timeout,
                    stream=True,
                )
            except requests.RequestException as exc:
                raise DashboardBinanceError(
                    endpoint=path, status=None, code=None
                ) from exc
            payload = self._payload(response, endpoint=path)
            code = payload.get("code") if isinstance(payload, dict) else None
            if code == -1021 and attempt == 0:
                self.refresh_clock(timeout=timeout)
                continue
            if response.status_code in {401, 403}:
                self._auth_error(
                    status=response.status_code,
                    code=code,
                    endpoint=path,
                    message=payload.get("msg", "") if isinstance(payload, dict) else "",
                )
            if response.status_code >= 400 or code == -1021 or payload is None:
                raise DashboardBinanceError(
                    endpoint=path, status=response.status_code, code=code
                )
            return payload
        raise DashboardBinanceError(endpoint=path, status=None, code=-1021)
