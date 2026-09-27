# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: collect bounded sequential SOL history through a read-only adapter.
"""No CLI, credential discovery, accounting import, or production activation."""

import os
import time

import requests
from urllib3.exceptions import HTTPError

from ladder_dragon.execution.market_http_body import read_body
from ladder_dragon.strategy import history_archive as archive, history_pages as contract
from ladder_dragon.strategy.private_fill_capture import BASE, TIME, FILLS, _Session, _Client, credential_scope
from ladder_dragon.strategy.private_fill_export import check_keys


class HistorySession(_Session):
    def __init__(self):
        super().__init__(22)
        self.deadline = time.monotonic()+150
        self.started_ms = self.started_mono = self.response_deadline = 0

    def request(self, method, url, **kwargs):
        if method != 'GET' or url not in {BASE+TIME, BASE+FILLS}:
            raise ValueError('HISTORY_ENDPOINT_FORBIDDEN')
        self.started_ms = time.time_ns()//1000000
        self.started_mono = time.monotonic_ns()
        self.response_deadline = min(self.deadline, time.monotonic()+5)
        return super().request(method, url, **kwargs)


class HistoryClient(_Client):
    def _payload(self, response, *, endpoint):
        try:
            if response.status_code != 200:
                raise ValueError('HISTORY_HTTP_STATUS')
            limit = 1024 if endpoint == TIME else contract.MAX_BODY
            raw = read_body(response, deadline=self._session.response_deadline, max_bytes=limit)
            packet = dict(started_ms=self._session.started_ms, finished_ms=time.time_ns()//1000000,
                          elapsed_ms=(time.monotonic_ns()-self._session.started_mono)//1000000, body=raw)
            contract.interval(packet)
            value = contract.decode(raw, limit)
            if type(value) is dict and 'code' in value:
                raise ValueError('HISTORY_PROVIDER_ERROR')
            self.packet = packet
            return value
        finally:
            response.close()


def fetch(*, credentials, expected_scope):
    """In-memory source claims only; caller must impose the outer process deadline."""
    if (type(credentials) is not tuple or len(credentials) != 2
            or credential_scope(credentials[0]) != expected_scope
            or type(credentials[1]) is not str or not 1 <= len(credentials[1]) <= 256
            or not credentials[1].isascii() or not credentials[1].isalnum()):
        raise ValueError('HISTORY_CREDENTIAL_INVALID')
    with HistorySession() as session:
        client = HistoryClient(session=session, base_url=BASE, credentials=lambda: credentials,
                               auth_error=lambda **kwargs: None, offset_ttl_sec=900)
        client.refresh_clock()
        clocks = [client.packet]
        if contract.CUTOFF_MS > clocks[0]['started_ms']:
            raise ValueError('HISTORY_FUTURE_CUTOFF')
        pages = []
        cursor = previous_time = 0
        for _ in range(contract.MAX_PAGES):
            client.signed('GET', FILLS, {'symbol':contract.SYMBOL,'fromId':cursor,'limit':contract.PAGE_SIZE}, timeout=5)
            packet = dict(client.packet, from_id=cursor)
            result = contract.page(packet['body'],cursor,previous_time,packet['finished_ms'])
            pages.append(packet)
            cursor, previous_time = result['next_cursor'], result['last_time']
            if result['stop']:
                break
        client.refresh_clock()
        clocks.append(client.packet)
        contract.validate_capture(pages, clocks)
        return pages, clocks


def collect(root, *, credentials, binding, signing_key, encryption_key):
    """Internal child entry: validate keys before retrieval, preserve failed slots."""
    stage = 'preflight'
    directory = None
    try:
        check_keys(binding, signing_key, encryption_key)
        if type(credentials) is not tuple or len(credentials) != 2 or credential_scope(credentials[0]) != binding['scope_sha256']:
            raise ValueError
        directory = archive.reserve(root)
        stage = 'retrieval'
        pages, clocks = fetch(credentials=credentials, expected_scope=binding['scope_sha256'])
        stage = 'storage'
        token = archive.seal(pages, clocks, binding=binding, signing_key=signing_key, encryption_key=encryption_key)
        return archive.store(directory, token)
    except (OSError, ValueError, TypeError, KeyError, RecursionError, RuntimeError, requests.RequestException, HTTPError) as error:
        # Never return provider messages, signatures, account rows, or exception chains.
        cause = error.__cause__ if isinstance(error.__cause__, requests.RequestException) else error
        reason = ('TLS' if isinstance(cause, requests.exceptions.SSLError) else
                  'TIMEOUT' if isinstance(cause, requests.Timeout) else
                  'TRANSPORT' if isinstance(cause, (requests.RequestException, HTTPError)) else
                  'IO' if isinstance(cause, OSError) else 'VALIDATION')
        if type(error) is ValueError and error.args == ('HISTORY_HTTP_STATUS',):
            reason = 'HTTP_STATUS'
        return dict(status='BLOCKED', stage=stage, reason=reason,
                    history_complete=False, private_fills_authenticated=False, replay_allowed=False)
    finally:
        if directory is not None:
            os.close(directory)
