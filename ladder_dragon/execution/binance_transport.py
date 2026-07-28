# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: implement the binance transport component of the execution layer.
"""Ladder Dragon binance transport support."""

from __future__ import annotations

import hashlib
import hmac
import math
import random
import threading
import time
from typing import Any, Callable, Mapping
from urllib.parse import urlencode

import requests
from ladder_dragon.execution.telegram_alerts import notify_binance_auth_error


class BinanceNetworkError(requests.ConnectionError):
    """Exhausted network retries without retaining a possibly signed URL."""

    def __init__(self, *, endpoint: str, cause_type: str) -> None:
        self.endpoint = endpoint
        self.cause_type = cause_type
        super().__init__(
            f"Binance network failure after retries: "
            f"{cause_type} endpoint={endpoint}"
        )


class BinanceResponseError(requests.HTTPError):
    """Definitive HTTP response from Binance without exposing a signed URL."""

    def __init__(
        self,
        *,
        status: int,
        code: Any,
        message: str,
        endpoint: str,
        response: requests.Response,
        retry_after_seconds: int | None = None,
    ) -> None:
        self.status = int(status)
        self.code = code
        self.binance_message = str(message)[:300]
        self.endpoint = endpoint
        self.retry_after_seconds = retry_after_seconds
        super().__init__(
            f"Binance HTTP {self.status} code={self.code}: "
            f"{self.binance_message or 'request rejected'} endpoint={endpoint}",
            response=response,
        )


class BinanceTransport:
    """Represent BinanceTransport."""

    def __init__(
        self,
        session: requests.Session,
        *,
        base_url: Callable[[], str],
        api_key: Callable[[], str],
        api_secret: Callable[[], str],
        live: Callable[[], bool],
        recv_window: Callable[[], int],
        logger: Callable[[str], None],
        timestamp_ms: Callable[[], int] | None = None,
    ) -> None:
        self.session = session
        self._base_url = base_url
        self._api_key = api_key
        self._api_secret = api_secret
        self._live = live
        self._recv_window = recv_window
        self._logger = logger
        self._timestamp_source = timestamp_ms or (lambda: int(time.time() * 1000))
        self._clock_offset_ms = 0
        self._state_lock = threading.RLock()
        self._request_cooldown_until = 0.0
        self._request_cooldown_error: BinanceResponseError | None = None

    @staticmethod
    def _retryable(status: int, code: Any) -> bool:
        return 500 <= status < 600 or code in (1003, -1003, -1015)

    @staticmethod
    def _auth_error(status: int, code: Any) -> bool:
        return status in (401, 403) or code in (-2014, -2015, -1022)

    @staticmethod
    def _response_error(
        response: requests.Response,
        payload: Any,
        endpoint: str,
        *,
        retry_after_seconds: int | None = None,
    ) -> BinanceResponseError:
        code = payload.get("code") if isinstance(payload, dict) else None
        message = payload.get("msg", "") if isinstance(payload, dict) else ""
        return BinanceResponseError(
            status=response.status_code,
            code=code,
            message=str(message),
            endpoint=endpoint,
            response=response,
            retry_after_seconds=retry_after_seconds,
        )

    @staticmethod
    def _retry_after_seconds(
        response: requests.Response,
        *,
        default: int,
    ) -> int:
        raw = response.headers.get("Retry-After")
        try:
            seconds = math.ceil(float(raw)) if raw is not None else default
        except (OverflowError, TypeError, ValueError):
            seconds = default
        return min(3 * 24 * 60 * 60, max(1, seconds))

    def _activate_rate_limit(
        self,
        response: requests.Response,
        payload: Any,
        endpoint: str,
    ) -> BinanceResponseError:
        is_ban = response.status_code == 418
        retry_after = self._retry_after_seconds(
            response,
            default=120 if is_ban else 1,
        )
        error = self._response_error(
            response,
            payload,
            endpoint,
            retry_after_seconds=retry_after,
        )
        with self._state_lock:
            self._request_cooldown_until = time.monotonic() + retry_after
            self._request_cooldown_error = error
        self._logger(
            f"[{'IP-BAN' if is_ban else 'RATE-LIMIT'}] "
            f"HTTP {response.status_code}; requests blocked locally for "
            f"{retry_after}s endpoint={endpoint}"
        )
        return error

    def _raise_if_rate_limited(self) -> None:
        with self._state_lock:
            if time.monotonic() >= self._request_cooldown_until:
                self._request_cooldown_until = 0.0
                self._request_cooldown_error = None
                return
            error = self._request_cooldown_error
        if error is not None:
            raise error

    def _timestamp_ms(self) -> int:
        with self._state_lock:
            offset = self._clock_offset_ms
        return int(self._timestamp_source()) + offset

    def _resync_clock(self, *, timeout: float) -> None:
        """Refresh the signed-request clock after a definitive -1021 rejection."""
        endpoint = "/api/v3/time"
        started = int(self._timestamp_source())
        try:
            response = self.session.request(
                "GET",
                self._base_url() + endpoint,
                timeout=min(float(timeout), 5.0),
            )
            payload = response.json()
            if response.status_code != 200 or not isinstance(payload, dict):
                raise ValueError("invalid server-time response")
            server_time = int(payload["serverTime"])
            finished = int(self._timestamp_source())
        except (KeyError, TypeError, ValueError, requests.RequestException) as exc:
            raise BinanceNetworkError(
                endpoint=endpoint,
                cause_type=exc.__class__.__name__,
            ) from exc
        midpoint = started + max(0, finished - started) // 2
        offset = server_time - midpoint
        with self._state_lock:
            self._clock_offset_ms = offset
        self._logger(f"[CLOCK-SYNC] offset_ms={offset} endpoint={endpoint}")

    def _delay(self, backoff: float, response: requests.Response | None = None) -> tuple[float, float]:
        retry_after = response.headers.get("Retry-After") if response is not None else None
        if retry_after:
            try:
                backoff = max(backoff, float(retry_after))
            except ValueError:
                backoff = min(backoff * 1.8, 20.0)
        else:
            backoff = min(backoff * 1.8, 20.0)
        return backoff, backoff + random.random() * 0.5

    def request_with_backoff(
        self,
        method: str,
        url: str,
        *,
        params: Mapping[str, Any] | None = None,
        data: Mapping[str, Any] | None = None,
        timeout: float = 15.0,
        max_tries: int = 8,
    ) -> Any:
        """Retry bounded read failures while never replaying mutations blindly."""
        # Retry only transient network/exchange failures. Binance business
        # errors must be returned to the caller immediately.
        endpoint = url.split("?", 1)[0]
        tries = 0
        backoff = 0.5
        while True:
            self._raise_if_rate_limited()
            tries += 1
            try:
                response = self.session.request(
                    method, url, params=params, data=data, timeout=timeout
                )
                try:
                    payload = response.json()
                except ValueError:
                    payload = None
                code = payload.get("code") if isinstance(payload, dict) else None

                if response.status_code >= 400:
                    if response.status_code in (418, 429):
                        raise self._activate_rate_limit(response, payload, endpoint)
                    if self._auth_error(response.status_code, code):
                        notify_binance_auth_error(
                            status=response.status_code,
                            code=code,
                            endpoint=endpoint,
                            message=(payload or {}).get("msg", "") if isinstance(payload, dict) else "",
                        )
                    if self._retryable(response.status_code, code):
                        if tries >= max_tries:
                            raise self._response_error(
                                response, payload, endpoint
                            )
                        backoff, delay = self._delay(backoff, response)
                        self._logger(
                            f"[BACKOFF] {response.status_code} code={code} "
                            f"→ sleep {delay:.2f}s endpoint={endpoint}"
                        )
                        time.sleep(delay)
                        continue
                    raise self._response_error(response, payload, endpoint)

                if isinstance(payload, dict) and payload.get("code") in (1003, -1003, -1015):
                    if tries >= max_tries:
                        raise BinanceResponseError(
                            status=response.status_code,
                            code=payload.get("code"),
                            message=str(payload.get("msg", "")),
                            endpoint=endpoint,
                            response=response,
                        )
                    backoff, delay = self._delay(backoff)
                    self._logger(
                        f"[BACKOFF] json code={payload.get('code')} "
                        f"→ sleep {delay:.2f}s endpoint={endpoint}"
                    )
                    time.sleep(delay)
                    continue
                return payload if payload is not None else response.text
            except BinanceResponseError:
                # A received HTTP response is definitive. Retrying a business
                # rejection can spam Binance and must not be treated as lost ACK.
                raise
            except requests.RequestException as exc:
                if tries >= max_tries:
                    raise BinanceNetworkError(
                        endpoint=endpoint,
                        cause_type=exc.__class__.__name__,
                    ) from exc
                backoff, delay = self._delay(backoff)
                self._logger(
                    f"[RETRY] {exc.__class__.__name__}; "
                    f"sleep {delay:.2f}s endpoint={endpoint}"
                )
                time.sleep(delay)

    def public_get(
        self,
        path: str,
        params: Mapping[str, Any] | None = None,
        timeout: float = 15.0,
    ) -> Any:
        return self.request_with_backoff(
            "GET", self._base_url() + path, params=params, timeout=timeout
        )

    def signed_request(
        self,
        method: str,
        path: str,
        params: Mapping[str, Any] | None = None,
        timeout: float = 15.0,
        max_tries: int | None = None,
    ) -> Any:
        """Sign one request and surface ambiguous mutations for reconciliation."""
        method = method.upper()
        # Main safety boundary: DRY may read private data, but every request
        # that changes exchange state is blocked before transport.
        if method not in ("GET", "HEAD") and not self._live():
            raise RuntimeError(f"DRY mode blocked mutating Binance request: {method} {path}")
        api_key = self._api_key()
        api_secret = self._api_secret()
        if not api_secret or not api_key:
            raise RuntimeError("API key/secret are required for signed endpoints.")

        base_params = dict(params or {})
        base_params.setdefault("recvWindow", self._recv_window())
        read_only = method in ("GET", "HEAD")
        # Mutations get one network attempt. Only the caller owns the durable
        # intent and can reconcile an unknown outcome without duplicating it.
        allowed_tries = (
            max(1, int(max_tries))
            if max_tries is not None and read_only
            else (3 if read_only else 1)
        )
        tries = 0
        backoff = 0.5
        clock_resynced = False
        while True:
            self._raise_if_rate_limited()
            tries += 1
            signed_params = dict(base_params)
            signed_params["timestamp"] = self._timestamp_ms()
            query = urlencode(signed_params, doseq=True)
            signature = hmac.new(
                api_secret.encode(), query.encode(), hashlib.sha256
            ).hexdigest()
            url = f"{self._base_url()}{path}?{query}&signature={signature}"
            try:
                response = self.session.request(
                    method,
                    url,
                    headers={"X-MBX-APIKEY": api_key},
                    timeout=timeout,
                )
                try:
                    payload = response.json()
                except ValueError:
                    payload = None
                code = payload.get("code") if isinstance(payload, dict) else None

                if response.status_code >= 400:
                    if response.status_code in (418, 429):
                        raise self._activate_rate_limit(response, payload, path)
                    if self._auth_error(response.status_code, code):
                        notify_binance_auth_error(
                            status=response.status_code,
                            code=code,
                            endpoint=path,
                            message=(payload or {}).get("msg", "") if isinstance(payload, dict) else "",
                        )
                    if code == -1021 and not clock_resynced:
                        self._resync_clock(timeout=timeout)
                        clock_resynced = True
                        continue
                    if not read_only and 500 <= response.status_code < 600:
                        raise BinanceNetworkError(
                            endpoint=path,
                            cause_type=f"HTTP{response.status_code}",
                        )
                    if self._retryable(response.status_code, code):
                        if tries >= allowed_tries:
                            raise self._response_error(response, payload, path)
                        backoff, delay = self._delay(backoff, response)
                        self._logger(
                            f"[BACKOFF] {response.status_code} code={code} "
                            f"→ sleep {delay:.2f}s URL={path}"
                        )
                        time.sleep(delay)
                        continue
                    raise self._response_error(response, payload, path)

                if isinstance(payload, dict) and payload.get("code") == -1021:
                    if not clock_resynced:
                        self._resync_clock(timeout=timeout)
                        clock_resynced = True
                        continue
                    raise BinanceResponseError(
                        status=response.status_code,
                        code=payload.get("code"),
                        message=str(payload.get("msg", "")),
                        endpoint=path,
                        response=response,
                    )
                if isinstance(payload, dict) and payload.get("code") in (
                    1003,
                    -1003,
                    -1015,
                ):
                    if tries >= allowed_tries:
                        raise BinanceResponseError(
                            status=response.status_code,
                            code=payload.get("code"),
                            message=str(payload.get("msg", "")),
                            endpoint=path,
                            response=response,
                        )
                    backoff, delay = self._delay(backoff)
                    self._logger(
                        f"[BACKOFF] json code={payload.get('code')} "
                        f"→ sleep {delay:.2f}s URL={path}"
                    )
                    time.sleep(delay)
                    continue
                return payload if payload is not None else response.text
            except BinanceResponseError:
                # The exchange answered. Do not retry or classify this as an
                # uncertain submission; callers can safely mark it rejected.
                raise
            except BinanceNetworkError:
                raise
            except requests.RequestException as exc:
                if not read_only or tries >= allowed_tries:
                    raise BinanceNetworkError(
                        endpoint=path,
                        cause_type=exc.__class__.__name__,
                    ) from exc
                backoff, delay = self._delay(backoff)
                self._logger(
                    f"[RETRY] {exc.__class__.__name__}; "
                    f"sleep {delay:.2f}s endpoint={path}"
                )
                time.sleep(delay)
