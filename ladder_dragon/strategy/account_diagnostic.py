# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: bound a separately authorized account diagnostic without fill authority.
"""No CLI or production wiring. DNS requires an external process deadline."""

from decimal import InvalidOperation
import time

import requests
from urllib3.exceptions import HTTPError

from ladder_dragon.execution.market_http_body import read_body
from ladder_dragon.strategy.account_binding import (
    MAX_ACCOUNT_BYTES, MAX_PERMISSION_BYTES, _object, validate_account_claims,
)
from ladder_dragon.strategy.account_enrollment import load_enrollment
from ladder_dragon.strategy.private_fill_capture import BASE, TIME, _Client, credential_scope


ACCOUNT = '/api/v3/account'
PERMISSIONS = '/sapi/v1/account/apiRestrictions'


class _DiagnosticSession(requests.Session):
    def __init__(self):
        super().__init__()
        self.trust_env = False
        self.headers.clear()
        self.deadline = time.monotonic() + 30
        self.calls = 0
        self.mount('https://', requests.adapters.HTTPAdapter(max_retries=0))

    def request(self, method, url, **kwargs):
        left = self.deadline - time.monotonic()
        if (method != 'GET' or url not in {BASE+TIME, BASE+ACCOUNT, BASE+PERMISSIONS}
                or self.calls >= 3 or left <= 0):
            raise ValueError('ACCOUNT_DIAGNOSTIC_BUDGET')
        self.calls += 1
        self.cookies.clear()
        kwargs.update(stream=True, allow_redirects=False, timeout=min(5, left),
                      verify=True, proxies={})
        return super().request(method, url, **kwargs)


class _DiagnosticClient(_Client):
    def _payload(self, response, *, endpoint):
        self.raw = None
        try:
            if response.status_code != 200:
                raise ValueError('ACCOUNT_DIAGNOSTIC_HTTP')
            maximum = {TIME: 1024, ACCOUNT: MAX_ACCOUNT_BYTES,
                       PERMISSIONS: MAX_PERMISSION_BYTES}[endpoint]
            raw = read_body(response, deadline=min(self._session.deadline, time.monotonic()+5),
                            max_bytes=maximum)
            value = _object(raw, maximum)
            if 'code' in value:
                raise ValueError('ACCOUNT_DIAGNOSTIC_PROVIDER')
            self.raw = raw
            return value
        finally:
            response.close()


def diagnose_account(*, enrollment_path, expected_reference, credentials):
    """Compare a protected operator claim with three bounded GET responses.

    Never persist responses or return identities, balances, or source bodies.
    Success proves only this diagnostic comparison, not historical provenance.
    Run only with separate live authority and an enforced outer process limit.
    """
    stage = 'enrollment'
    try:
        record = load_enrollment(enrollment_path, expected_reference=expected_reference)
        stage = 'credential'
        if type(credentials) is not tuple or len(credentials) != 2:
            raise ValueError
        key, secret = credentials
        if (credential_scope(key) != record['credential_scope'] or type(secret) is not str
                or not 1 <= len(secret) <= 256 or not secret.isascii() or not secret.isalnum()):
            raise ValueError
        with _DiagnosticSession() as session:
            started_wall = time.time_ns() // 1000000
            started_mono = time.monotonic_ns() // 1000000
            client = _DiagnosticClient(session=session, base_url=BASE,
                credentials=lambda: credentials, auth_error=lambda **kwargs: None, offset_ttl_sec=60)
            stage = 'clock'
            client.refresh_clock()
            stage = 'account'
            client.signed('GET', ACCOUNT, timeout=5)
            account_body = client.raw
            stage = 'permissions'
            client.signed('GET', PERMISSIONS, timeout=5)
            stage = 'validation'
            wall_elapsed = time.time_ns() // 1000000 - started_wall
            mono_elapsed = time.monotonic_ns() // 1000000 - started_mono
            if (time.monotonic() >= session.deadline or wall_elapsed < 0
                    or abs(wall_elapsed - mono_elapsed) > 2):
                raise ValueError
            result = validate_account_claims(expected_uid=record['uid'],
                expected_scope=record['credential_scope'], account_scope=credential_scope(key),
                permission_scope=credential_scope(key), account_body=account_body,
                permission_body=client.raw)
            result['stage'] = stage
            if result['status'] == 'CLAIMS_MATCH_ONLY':
                result['status'] = 'DIAGNOSTIC_MATCH_ONLY'
            return result
    except (OSError, ValueError, TypeError, KeyError, RecursionError, OverflowError,
            InvalidOperation, RuntimeError, requests.RequestException, HTTPError):
        return dict(status='BLOCKED', stage=stage, reason='ACCOUNT_DIAGNOSTIC_FAILED',
                    account_authenticated=False, private_fills_authenticated=False, replay_allowed=False)
