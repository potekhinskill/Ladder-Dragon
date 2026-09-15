# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: measure capture-only DNS without global socket hooks.
"""Request-to-headers diagnostics; body and clock admission remain separate."""

from contextvars import ContextVar
import socket
import sys
import time

import requests
from urllib3.connection import HTTPSConnection
from urllib3.connectionpool import HTTPSConnectionPool
from urllib3.exceptions import ConnectTimeoutError, NameResolutionError, NewConnectionError
from urllib3.util.connection import allowed_gai_family
from urllib3.util import Timeout

from ladder_dragon.strategy.capture_dns import remaining, resolve_addresses


def measured_socket(connection, measurement):
    """Preserve address order, socket options, and source binding."""
    started = time.monotonic_ns()
    measurement['phase'] = 'dns'
    measurement['dns_calls'] += 1
    deadline = time.monotonic() + min(5, connection.timeout)
    try:
        addresses = resolve_addresses(connection._dns_host, connection.port,
                                      allowed_gai_family(), socket.SOCK_STREAM, deadline=deadline)
    finally:
        measurement['dns_ns'] += max(0, time.monotonic_ns() - started)
    measurement['phase'] = 'tcp'
    last_error = OSError('No resolved capture addresses')
    for family, kind, protocol, _, address in addresses:
        sock = None
        try:
            sock = socket.socket(family, kind, protocol)
            for option in connection.socket_options or ():
                sock.setsockopt(*option)
            sock.settimeout(remaining(deadline))
            if connection.source_address:
                sock.bind(connection.source_address)
            sock.connect(address)
            connection.timeout = remaining(deadline)
            sock.settimeout(connection.timeout)
            return sock
        except OSError as error:
            last_error = error
            if sock is not None:
                sock.close()
    raise last_error


class CaptureAdapter(requests.adapters.HTTPAdapter):
    """Own a pool and context; never mutate shared urllib3 or socket state."""

    def __init__(self, diagnostics):
        self.diagnostics = diagnostics
        self.measurement = ContextVar('capture_request', default=None)
        super().__init__(max_retries=0)
        context = self.measurement

        class Connection(HTTPSConnection):
            def _new_conn(self):
                current = context.get()
                if current is None:
                    return super()._new_conn()
                try:
                    sock = measured_socket(self, current)
                except socket.gaierror as error:
                    raise NameResolutionError(self.host, self, error) from error
                except socket.timeout as error:
                    raise ConnectTimeoutError(self, 'Capture connection timeout') from error
                except OSError as error:
                    raise NewConnectionError(self, 'Capture connection failed') from error
                current['phase'] = 'tls_headers'
                sys.audit('http.client.connect', self, self.host, self.port)
                return sock

        class Pool(HTTPSConnectionPool):
            ConnectionCls = Connection

        self.poolmanager.pool_classes_by_scheme = dict(self.poolmanager.pool_classes_by_scheme, https=Pool)

    def send(self, request, **kwargs):
        current = dict(dns_ns=0, dns_calls=0, phase='tls_headers', outcome='failed')
        token = self.measurement.set(current)
        started = time.monotonic_ns()
        stage = self.diagnostics.stage
        try:
            # urllib3 subtracts connection time, including DNS, from read time.
            budget = kwargs.get('timeout')
            if type(budget) not in (int, float) or not 0 < budget <= 5:
                raise requests.Timeout('Capture request budget required')
            kwargs['timeout'] = Timeout(total=budget, connect=budget, read=budget)
            response = super().send(request, **kwargs)
            current['outcome'] = 'headers_received'
            current['phase'] = 'headers'
            return response
        finally:
            elapsed = max(0, time.monotonic_ns() - started)
            current['request_headers_ns'] = elapsed
            current['non_dns_headers_ns'] = max(0, elapsed-current['dns_ns'])
            self.measurement.reset(token)
            self.diagnostics.record_network(stage, current)


def capture_session(diagnostics):
    session = requests.Session()
    session.trust_env = False
    session.mount('https://', CaptureAdapter(diagnostics))
    return session
