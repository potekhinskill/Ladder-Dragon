# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: implement the binance transport component of the execution layer.
"""HTTP-транспорт Binance по принципу fail-closed для торговых компонентов.

Здесь сосредоточены подпись запросов, DRY/LIVE-гейт и повторные попытки.
Стратегия и управление ордерами не должны самостоятельно работать с HTTP.
"""

from __future__ import annotations

import hashlib
import hmac
import random
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
    ) -> None:
        self.status = int(status)
        self.code = code
        self.binance_message = str(message)[:300]
        self.endpoint = endpoint
        super().__init__(
            f"Binance HTTP {self.status} code={self.code}: "
            f"{self.binance_message or 'request rejected'} endpoint={endpoint}",
            response=response,
        )


class BinanceTransport:
    """Транспорт с подписью и поздним получением ключей и LIVE-состояния.

    Callbacks позволяют переключить venue или DRY/LIVE без пересоздания объекта.
    Модули стратегии и ордеров при этом не знают деталей HMAC-подписи.
    """

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
    ) -> None:
        self.session = session
        self._base_url = base_url
        self._api_key = api_key
        self._api_secret = api_secret
        self._live = live
        self._recv_window = recv_window
        self._logger = logger

    @staticmethod
    def _retryable(status: int, code: Any, *, include_clock: bool = False) -> bool:
        codes = (1003, -1003, -1015, -1021) if include_clock else (1003, -1003, -1015)
        return status in (418, 429) or 500 <= status < 600 or code in codes

    @staticmethod
    def _auth_error(status: int, code: Any) -> bool:
        return status in (401, 403) or code in (-2014, -2015, -1022)

    @staticmethod
    def _response_error(
        response: requests.Response,
        payload: Any,
        endpoint: str,
    ) -> BinanceResponseError:
        code = payload.get("code") if isinstance(payload, dict) else None
        message = payload.get("msg", "") if isinstance(payload, dict) else ""
        return BinanceResponseError(
            status=response.status_code,
            code=code,
            message=str(message),
            endpoint=endpoint,
            response=response,
        )

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
        # Retry only transient network/exchange failures. Binance business
        # errors must be returned to the caller immediately.
        tries = 0
        backoff = 0.5
        while True:
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
                    if self._auth_error(response.status_code, code):
                        notify_binance_auth_error(
                            status=response.status_code,
                            code=code,
                            endpoint=url,
                            message=(payload or {}).get("msg", "") if isinstance(payload, dict) else "",
                        )
                    if self._retryable(response.status_code, code):
                        if tries >= max_tries:
                            raise self._response_error(
                                response, payload, url.split("?", 1)[0]
                            )
                        backoff, delay = self._delay(backoff, response)
                        self._logger(
                            f"[BACKOFF] {response.status_code} code={code} "
                            f"→ sleep {delay:.2f}s endpoint={url.split('?', 1)[0]}"
                        )
                        time.sleep(delay)
                        continue
                    raise self._response_error(response, payload, url.split("?", 1)[0])

                if isinstance(payload, dict) and payload.get("code") in (1003, -1003, -1015):
                    if tries >= max_tries:
                        raise requests.HTTPError(
                            f"Binance throttle code {payload.get('code')}: {payload.get('msg')}"
                        )
                    backoff, delay = self._delay(backoff)
                    self._logger(
                        f"[BACKOFF] json code={payload.get('code')} "
                        f"→ sleep {delay:.2f}s URL={url}"
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
                        endpoint=url.split("?", 1)[0],
                        cause_type=exc.__class__.__name__,
                    ) from exc
                backoff, delay = self._delay(backoff)
                self._logger(
                    f"[RETRY] {exc.__class__.__name__}; "
                    f"sleep {delay:.2f}s endpoint={url.split('?', 1)[0]}"
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
    ) -> Any:
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
        tries = 0
        backoff = 0.5
        while True:
            tries += 1
            signed_params = dict(base_params)
            signed_params["timestamp"] = int(time.time() * 1000)
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
                    if self._auth_error(response.status_code, code):
                        notify_binance_auth_error(
                            status=response.status_code,
                            code=code,
                            endpoint=path,
                            message=(payload or {}).get("msg", "") if isinstance(payload, dict) else "",
                        )
                    if self._retryable(response.status_code, code, include_clock=True):
                        if tries >= 8:
                            raise self._response_error(response, payload, path)
                        backoff, delay = self._delay(backoff, response)
                        self._logger(
                            f"[BACKOFF] {response.status_code} code={code} "
                            f"→ sleep {delay:.2f}s URL={path}"
                        )
                        time.sleep(delay)
                        continue
                    raise self._response_error(response, payload, path)

                if isinstance(payload, dict) and payload.get("code") in (1003, -1003, -1015, -1021):
                    if tries >= 8:
                        raise requests.HTTPError(
                            f"Binance code {payload.get('code')}: {payload.get('msg')}"
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
            except requests.RequestException as exc:
                if tries >= 8:
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
