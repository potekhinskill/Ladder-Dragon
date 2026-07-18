# Copyright (c) 2026 IURII Potekhin / Ladder Dragon. All rights reserved.
# Назначение файла и опасные границы логики должны оставаться понятными при сопровождении.
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
        # Повторяем только временные сетевые/биржевые сбои. Бизнес-ошибки
        # Binance должны сразу дойти до вызывающего кода.
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
                        backoff, delay = self._delay(backoff, response)
                        self._logger(
                            f"[BACKOFF] {response.status_code} code={code} "
                            f"→ sleep {delay:.2f}s URL={url}"
                        )
                        time.sleep(delay)
                        if tries < max_tries:
                            continue
                    response.raise_for_status()

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
            except requests.RequestException as exc:
                if tries >= max_tries:
                    raise
                backoff, delay = self._delay(backoff)
                self._logger(
                    f"[RETRY] {exc.__class__.__name__}: {exc}; "
                    f"sleep {delay:.2f}s URL={url}"
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
        # Главная граница безопасности: в DRY разрешено читать приватные данные,
        # но любой запрос, меняющий состояние биржи, блокируется до сети.
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
                        backoff, delay = self._delay(backoff, response)
                        self._logger(
                            f"[BACKOFF] {response.status_code} code={code} "
                            f"→ sleep {delay:.2f}s URL={path}"
                        )
                        time.sleep(delay)
                        if tries < 8:
                            continue
                    response.raise_for_status()

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
            except requests.RequestException as exc:
                if tries >= 8:
                    raise
                backoff, delay = self._delay(backoff)
                self._logger(
                    f"[RETRY] {exc.__class__.__name__}: {exc}; "
                    f"sleep {delay:.2f}s URL={path}"
                )
                time.sleep(delay)
