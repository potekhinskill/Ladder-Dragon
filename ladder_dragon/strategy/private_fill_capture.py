# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: retain bounded GET response bytes under one pinned credential scope.
"""Read-only source collector; no enrollment, accounting, or replay authority.

The scope identifies a selected API credential, not an independently verified
account UID. Activation still requires reviewed dashboard-key provenance.
"""
import hashlib
import json
import os
import time

import requests
from urllib3.exceptions import HTTPError

from ladder_dragon.dashboard.services.binance_readonly import ReadOnlyBinanceClient
from ladder_dragon.execution.exchange_evidence import valid_exchange_name
from ladder_dragon.execution.market_http_body import read_body
from ladder_dragon.execution.order_fill_evidence import complete_fills, terminal_order
from ladder_dragon.execution.time_safety import assess_exchange_clock
from ladder_dragon.strategy.bnb_capture import external_store, pairs
from ladder_dragon.strategy import private_fill_export

BASE = 'https://api.binance.com'
TIME = '/api/v3/time'
ORDER = '/api/v3/order'
FILLS = '/api/v3/myTrades'
FAILURE_STAGES = frozenset(('preflight', 'clock', 'order', 'fills', 'validation', 'storage'))
FAILURE_REASONS = frozenset(('VALIDATION', 'CLOCK_INVALID', 'HTTP_STATUS', 'PROVIDER_ERROR',
                           'TIMEOUT', 'TLS', 'TRANSPORT', 'BODY', 'BUDGET', 'IO'))


class CaptureFailure(ValueError):
    """Fixed failure text plus bounded stage metadata, never provider details."""
    def __init__(self, stage, reason='VALIDATION', http_status=None):
        super().__init__('PRIVATE_CAPTURE_FAILED_CLOSED')
        self.stage = stage if type(stage) is str and stage in FAILURE_STAGES else 'unknown'
        self.reason = reason if type(reason) is str and reason in FAILURE_REASONS else 'UNKNOWN'
        self.http_status = http_status if type(http_status) is int and 100 <= http_status <= 599 else None


def failure_report(error):
    """Return only revalidated diagnostic fields, never exception payloads."""
    safe = (CaptureFailure(error.stage, error.reason, error.http_status)
            if type(error) is CaptureFailure else CaptureFailure('unknown', 'UNKNOWN'))
    return dict(status='BLOCKED', stage=safe.stage, reason=safe.reason,
                http_status=safe.http_status if safe.reason == 'HTTP_STATUS' else None,
                private_fills_authenticated=False, replay_allowed=False)


def credential_scope(api_key):
    """Only a fingerprint crosses into evidence; never the credential itself."""
    if type(api_key) is not str or not 1 <= len(api_key) <= 256 or not api_key.isascii() or not api_key.isalnum():
        raise ValueError('PRIVATE_CAPTURE_CREDENTIAL_INVALID')
    return hashlib.sha256(b'LadderDragon:mainnet-readonly-credential:v1\x00'+api_key.encode()).hexdigest()


class _Session(requests.Session):
    def __init__(self, maximum):
        super().__init__()
        self.trust_env = False
        self.headers.clear()
        self.deadline = time.monotonic()+30
        self.calls = 0
        self.maximum = maximum
        self.mount('https://', requests.adapters.HTTPAdapter(max_retries=0))

    def request(self, method, url, **kwargs):
        if method != 'GET' or url not in {BASE+TIME, BASE+ORDER, BASE+FILLS}:
            raise ValueError('PRIVATE_CAPTURE_ENDPOINT_FORBIDDEN')
        left = self.deadline-time.monotonic()
        if self.calls >= self.maximum or left <= 0:
            raise ValueError('PRIVATE_CAPTURE_BUDGET')
        self.calls += 1
        self.cookies.clear()
        kwargs.update(stream=True, allow_redirects=False, timeout=min(5, left), verify=True, proxies={})
        return super().request(method, url, **kwargs)


class _Client(ReadOnlyBinanceClient):
    def _payload(self, response, *, endpoint):
        # Error responses never trigger inherited timestamp retries or enter evidence.
        self.raw = None
        try:
            if response.status_code != 200:
                stage = {TIME:'clock',ORDER:'order',FILLS:'fills'}.get(endpoint,'unknown')
                raise CaptureFailure(stage, 'HTTP_STATUS', response.status_code)
            raw = read_body(response, deadline=min(self._session.deadline,time.monotonic()+5),
                            max_bytes=1024 if endpoint == TIME else 65536)
            value = json.loads(raw, object_pairs_hook=pairs)
            if isinstance(value, dict) and 'code' in value:
                raise ValueError('PRIVATE_CAPTURE_PROVIDER_ERROR')
            self.raw = raw
            return value
        finally:
            response.close()

    def refresh_clock(self, *, timeout=5):
        started = time.time_ns()//1000000
        monotonic = time.monotonic_ns()
        response = self._session.get(BASE+TIME, timeout=timeout, stream=True)
        payload = self._payload(response, endpoint=TIME)
        finished = time.time_ns()//1000000
        elapsed = (time.monotonic_ns()-monotonic)//1000000
        if (type(payload) is not dict or set(payload) != {'serverTime'}
                or type(payload['serverTime']) is not int or payload['serverTime'] <= 0
                or abs((finished-started)-elapsed) > 2):
            raise ValueError('PRIVATE_CAPTURE_CLOCK_INVALID')
        clock = assess_exchange_clock(server_time_ms=payload['serverTime'], request_started_ms=started,
                                      response_finished_ms=finished)
        if not clock.safe:
            raise ValueError('PRIVATE_CAPTURE_CLOCK_INVALID')
        self._offset_ms = clock.offset_ms
        self._offset_updated_at = time.time()


def fetch(orders, *, credentials, expected_scope):
    """Fetch each complete order once with frozen credentials and no retries.

    An external process deadline remains necessary for OS-level DNS stalls.
    Returned private packets must go directly to the encrypted export boundary.
    """
    stage = 'preflight'
    try:
        if type(credentials) is not tuple or len(credentials) != 2:
            raise ValueError
        api_key, secret = credentials
        if (credential_scope(api_key) != expected_scope or type(secret) is not str
                or not 1 <= len(secret) <= 256 or not secret.isascii() or not secret.isalnum()):
            raise ValueError
        if type(orders) is not list or not 1 <= len(orders) <= 8:
            raise ValueError
        selected = []
        for item in orders:
            if (type(item) is not tuple or len(item) != 2 or not valid_exchange_name(item[0])
                    or type(item[1]) is not int or not 0 <= item[1] < 2**63 or item in selected):
                raise ValueError
            selected.append(item)
        packets = []
        with _Session(1+2*len(selected)) as session:
            client = _Client(session=session, base_url=BASE, credentials=lambda: credentials,
                             auth_error=lambda **kwargs: None, offset_ttl_sec=60)
            stage = 'clock'
            client.refresh_clock()
            for symbol, order_id in selected:
                started = time.time_ns()//1000000
                monotonic = time.monotonic_ns()
                stage = 'order'
                order = client.signed('GET', ORDER, {'symbol':symbol,'orderId':order_id}, timeout=5)
                order_raw = client.raw
                terminal_order(order, symbol, order_id)
                stage = 'fills'
                fills = client.signed('GET', FILLS, {'symbol':symbol,'orderId':order_id,'limit':1000}, timeout=5)
                fills_raw = client.raw
                stage = 'validation'
                finished = time.time_ns()//1000000
                if (time.monotonic() >= session.deadline or finished < started
                        or abs((finished-started)-(time.monotonic_ns()-monotonic)//1000000) > 2):
                    raise ValueError
                indexed = complete_fills(order, fills, symbol, order_id)
                if any(row['time'] > finished for row in indexed.values()):
                    raise ValueError
                packets.append(dict(symbol=symbol,order_id=order_id,scope_sha256=expected_scope,
                    started_ms=started,finished_ms=finished,order_body=order_raw,fills_body=fills_raw))
        return packets
    except CaptureFailure:
        raise
    except (OSError, ValueError, TypeError, KeyError, RecursionError, RuntimeError, requests.RequestException, HTTPError) as error:
        # Inspect only known types and whole fixed tokens, never provider text.
        reason = 'VALIDATION'
        transport = error.__cause__ if isinstance(error.__cause__, requests.RequestException) else error
        if isinstance(transport, requests.exceptions.SSLError): reason = 'TLS'
        elif isinstance(transport, requests.Timeout): reason = 'TIMEOUT'
        elif isinstance(transport, (requests.RequestException, HTTPError)): reason = 'TRANSPORT'
        elif isinstance(error, OSError): reason = 'IO'
        elif type(error) is ValueError and len(error.args) == 1 and type(error.args[0]) is str:
            reason = {'PRIVATE_CAPTURE_CLOCK_INVALID':'CLOCK_INVALID',
                      'PRIVATE_CAPTURE_PROVIDER_ERROR':'PROVIDER_ERROR',
                      'PRIVATE_CAPTURE_BUDGET':'BUDGET'}.get(error.args[0], reason)
        raise CaptureFailure(stage, reason) from None


def collect_and_export(root, orders, *, credentials, binding, signing_key, encryption_key):
    """No writes until complete retrieval; never overwrite an earlier export."""
    stage = 'preflight'
    try:
        private_fill_export._bindings(binding)
        private_fill_export.check_keys(binding, signing_key, encryption_key)
        mount = external_store(root)
        if os.path.lexists(mount/'private-fill-export'):
            raise ValueError
        packets = fetch(orders, credentials=credentials, expected_scope=binding['scope_sha256'])
        stage = 'storage'
        return private_fill_export.export(mount, packets, binding=binding,
            signing_key=signing_key, encryption_key=encryption_key)
    except CaptureFailure:
        raise
    except (OSError, ValueError, TypeError, KeyError, RecursionError):
        raise CaptureFailure(stage) from None
