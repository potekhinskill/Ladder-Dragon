import json
import socket
from types import SimpleNamespace

import pytest
import requests
from urllib3.connection import HTTPSConnection
from urllib3.exceptions import ConnectTimeoutError, NameResolutionError, NewConnectionError

from ladder_dragon.strategy import bnb_capture_command as command
from ladder_dragon.strategy import capture_transport as transport
from ladder_dragon.strategy.capture_diagnostics import CaptureDiagnostics


class Socket:
    def __init__(self, failure=None):
        self.failure = failure
        self.closed = False
        self.options = []

    def setsockopt(self, *args): self.options.append(args)
    def settimeout(self, value): self.timeout = value
    def bind(self, value): self.source = value
    def connect(self, address):
        self.address = address
        if self.failure: raise self.failure
    def close(self): self.closed = True


def row(ip='192.0.2.1'):
    return (socket.AF_INET, socket.SOCK_STREAM, 6, '', (ip, 443))


def measurement():
    return dict(dns_ns=0, dns_calls=0, phase='tls_headers', outcome='failed')


def test_measures_actual_dns_and_preserves_socket_semantics(monkeypatch):
    seen = []
    def resolve(*args, **kwargs):
        seen.append(args)
        return [row(), row('192.0.2.2')]
    monkeypatch.setattr(transport, 'resolve_addresses', resolve)
    ticks = iter([100, 170])
    monkeypatch.setattr(transport.time, 'monotonic_ns', lambda: next(ticks))
    first, second = Socket(OSError('PRIVATE')), Socket()
    sockets = iter([first, second])
    monkeypatch.setattr(transport.socket, 'socket', lambda *args: next(sockets))
    conn = SimpleNamespace(_dns_host='data-api.binance.vision', port=443, timeout=5,
                           socket_options=[(6, 1, 1)], source_address=('127.0.0.1', 0))
    record = measurement()
    assert transport.measured_socket(conn, record) is second
    assert first.closed and not second.closed
    assert second.options == [(6, 1, 1)] and 0 < second.timeout <= 5
    assert second.source == ('127.0.0.1', 0) and second.address == ('192.0.2.2', 443)
    assert len(seen) == 1 and seen[0][0:2] == ('data-api.binance.vision', 443)
    assert record['dns_ns'] == 70 and record['dns_calls'] == 1 and record['phase'] == 'tcp'


@pytest.mark.parametrize('error,expected,phase', [
    (socket.gaierror('PRIVATE'), NameResolutionError, 'dns'),
    (socket.timeout('PRIVATE'), ConnectTimeoutError, 'tcp'),
    (OSError('PRIVATE'), NewConnectionError, 'tcp'),
])
def test_connection_failure_records_phase_and_closes_socket(monkeypatch, error, expected, phase):
    diag = CaptureDiagnostics()
    adapter = transport.CaptureAdapter(diag)
    cls = adapter.poolmanager.pool_classes_by_scheme['https'].ConnectionCls
    sock = Socket(error)
    def resolve(*args, **kwargs):
        if phase == 'dns': raise error
        return [row()]
    monkeypatch.setattr(transport, 'resolve_addresses', resolve)
    monkeypatch.setattr(transport.socket, 'socket', lambda *args: sock)
    current = measurement()
    token = adapter.measurement.set(current)
    try:
        with pytest.raises(expected): cls('data-api.binance.vision', timeout=5)._new_conn()
    finally:
        adapter.measurement.reset(token)
        adapter.close()
    assert current['dns_calls'] == 1 and current['phase'] == phase
    assert phase == 'dns' or sock.closed


@pytest.mark.parametrize('failure', [False, True])
def test_adapter_finally_records_disjoint_timings_without_payload(monkeypatch, failure):
    diag = CaptureDiagnostics(); diag.mark('clock_request')
    adapter = transport.CaptureAdapter(diag)
    ticks = iter([100, 110, 150, 200])
    monkeypatch.setattr(transport.time, 'monotonic_ns', lambda: next(ticks))
    monkeypatch.setattr(transport, 'resolve_addresses', lambda *args, **kwargs: [row()])
    monkeypatch.setattr(transport.socket, 'socket', lambda *args: Socket())
    def send(self, request, **kwargs):
        cls = self.poolmanager.pool_classes_by_scheme['https'].ConnectionCls
        cls('data-api.binance.vision', timeout=5)._new_conn().close()
        if failure: raise requests.exceptions.SSLError('PRIVATE_TOKEN_AND_URL')
        return requests.Response()
    monkeypatch.setattr(requests.adapters.HTTPAdapter, 'send', send)
    request = requests.Request('GET', 'https://data-api.binance.vision/api/v3/time').prepare()
    try:
        if failure:
            with pytest.raises(requests.exceptions.SSLError): adapter.send(request, timeout=5)
        else:
            adapter.send(request, timeout=5)
    finally:
        adapter.close()
    assert adapter.measurement.get() is None
    entry = diag.network[0]
    assert entry['dns_ns'] == 40 and entry['request_headers_ns'] == 100
    assert entry['non_dns_headers_ns'] == 60 and entry['stage'] == 'clock_request'
    assert entry['outcome'] == ('failed' if failure else 'headers_received')
    assert 'PRIVATE' not in json.dumps(diag.failure(RuntimeError('PRIVATE')))


def test_reused_connection_has_zero_dns_calls_and_fresh_request_state(monkeypatch):
    diag = CaptureDiagnostics(); diag.mark('market_request')
    adapter = transport.CaptureAdapter(diag)
    monkeypatch.setattr(requests.adapters.HTTPAdapter, 'send', lambda *args, **kwargs: requests.Response())
    for _ in range(2): adapter.send(None, timeout=5)
    adapter.close()
    assert len(diag.network) == 2 and diag.network[0] is not diag.network[1]
    assert all(entry['dns_calls'] == 0 and entry['dns_ns'] == 0 for entry in diag.network)


def test_adapter_pool_is_private_and_preserves_tls_implementation():
    resolver = socket.getaddrinfo
    with requests.Session() as normal, transport.capture_session(CaptureDiagnostics()) as capture:
        normal_adapter = normal.get_adapter('https://')
        capture_adapter = capture.get_adapter('https://')
        cls = capture_adapter.poolmanager.pool_classes_by_scheme['https'].ConnectionCls
        assert normal_adapter.poolmanager.pool_classes_by_scheme['https'].ConnectionCls is HTTPSConnection
        assert cls.connect is HTTPSConnection.connect
        assert socket.getaddrinfo is resolver
        assert capture_adapter.max_retries.total == 0
        assert capture.verify is True and capture.auth is None and capture.trust_env is False


def test_network_report_has_fixed_fields_and_bounded_retention():
    diag = CaptureDiagnostics()
    for _ in range(105):
        diag.record_network('PRIVATE', dict(dns_ns='PRIVATE', dns_calls=True,
            phase='PRIVATE', outcome='PRIVATE', request_headers_ns=-1, non_dns_headers_ns=2**64,
            secret='PRIVATE'))
    assert len(diag.network) == 100
    assert 'PRIVATE' not in json.dumps(diag.failure(ValueError('PRIVATE')))
    assert diag.network[0]['dns_calls'] is None
    assert not CaptureDiagnostics().network


def test_success_cli_diagnostics_do_not_modify_manifest(monkeypatch, capsys):
    manifest = dict(status='DIAGNOSTIC_ONLY', replay_allowed=False)
    def collect(*args, **kwargs):
        kwargs['diagnostics'].record_network('market_request', measurement())
        return manifest
    monkeypatch.setattr(command, 'collect', collect)
    monkeypatch.setattr('sys.argv', ['record', '--external-mount', '/unused'])
    assert command.main() == 0
    assert json.loads(capsys.readouterr().out)['network']
    assert 'network' not in manifest
