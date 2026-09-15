import json
import socket
import subprocess
import time
from types import SimpleNamespace

import pytest
import requests

from ladder_dragon.strategy import capture_dns as dns, capture_transport as transport
from ladder_dragon.strategy.capture_diagnostics import CaptureDiagnostics


def resolve():
    return dns.resolve_addresses('data-api.binance.vision', 443, socket.AF_INET,
                                 socket.SOCK_STREAM, deadline=time.monotonic()+2)


@pytest.mark.parametrize('parent_options', ['use-vc timeout:99', 'attempts:99', ''])
def test_resolver_subprocess_has_no_parent_environment_or_inherited_descriptors(monkeypatch, parent_options):
    monkeypatch.setenv('PRIVATE_TEST_SECRET', 'must-not-cross')
    monkeypatch.setenv('RES_OPTIONS', parent_options)
    seen = []
    def run(args, **kwargs):
        seen.append((args, kwargs))
        return SimpleNamespace(returncode=0, stdout=json.dumps([
            [int(socket.AF_INET), 1, 6, '', ['192.0.2.1', 443]],
        ]).encode())
    monkeypatch.setattr(dns.subprocess, 'run', run)
    assert resolve()[0][-1] == ('192.0.2.1', 443)
    args, options = seen[0]
    assert args[1:4] == ['-I', '-S', '-c']
    assert options['env'] == {'RES_OPTIONS': 'use-vc'} and options['close_fds'] is True
    import os
    assert os.environ['RES_OPTIONS'] == parent_options
    assert options['stdin'] == options['stderr'] == subprocess.DEVNULL
    assert 0 < options['timeout'] <= 2
    assert 'must-not-cross' not in repr(seen)


def test_real_stalled_resolver_is_killed_and_reaped(monkeypatch):
    monkeypatch.setattr(dns, '_RESOLVER', 'import time; time.sleep(60)')
    children = []
    original = subprocess.Popen
    def popen(*args, **kwargs):
        child = original(*args, **kwargs)
        children.append(child)
        return child
    monkeypatch.setattr(subprocess, 'Popen', popen)
    started = time.monotonic()
    with pytest.raises(socket.timeout, match='DNS deadline'):
        dns.resolve_addresses('data-api.binance.vision', 443, socket.AF_INET,
                              socket.SOCK_STREAM, deadline=started+0.15)
    assert time.monotonic()-started < 3
    assert len(children) == 1 and children[0].poll() is not None


def test_real_child_uses_protocol_without_parent_secret(monkeypatch):
    monkeypatch.setenv('PRIVATE_TEST_SECRET', 'must-not-cross')
    monkeypatch.setenv('RES_OPTIONS', 'attempts:99')
    prefix = "import os, socket; assert 'PRIVATE_TEST_SECRET' not in os.environ; "
    prefix += "assert os.environ['RES_OPTIONS']=='use-vc'; "
    prefix += "socket.getaddrinfo=lambda *a: [(socket.AF_INET, socket.SOCK_STREAM, 6, '', ('192.0.2.1',443))]\n"
    monkeypatch.setattr(dns, '_RESOLVER', prefix+dns._RESOLVER)
    assert resolve()[0][-1] == ('192.0.2.1', 443)


def test_tcp_resolver_failure_does_not_start_another_process(monkeypatch):
    calls = []
    def run(*args, **kwargs):
        calls.append(kwargs['env'])
        return SimpleNamespace(returncode=2, stdout=b'')
    monkeypatch.setattr(dns.subprocess, 'run', run)
    with pytest.raises(socket.gaierror): resolve()
    assert calls == [{'RES_OPTIONS': 'use-vc'}]


def test_real_requests_path_reports_dns_timeout_without_tcp(monkeypatch):
    def stall(*args, **kwargs):
        raise socket.timeout('PRIVATE')
    monkeypatch.setattr(transport, 'resolve_addresses', stall)
    diag = CaptureDiagnostics(); diag.mark('clock_request')
    with transport.capture_session(diag) as session:
        with pytest.raises(requests.ConnectTimeout) as failure:
            session.get('https://data-api.binance.vision/api/v3/time', timeout=1,
                        stream=True, allow_redirects=False)
    report = diag.failure(failure.value)
    assert report['reason'] == 'TIMEOUT' and report['network'][0]['phase'] == 'dns'
    assert report['network'][0]['dns_calls'] == 1
    assert 'PRIVATE' not in json.dumps(report)


@pytest.mark.parametrize('payload', [b'[]', b'null', b'PRIVATE', b'x'*16385,
    b'[[2,1,6,"",["example.com",443]]]', b'[[2,1,6,"",["192.0.2.1",80]]]',
    b'[[2,1,6,"",["::1",443]]]', b'[[2,2,6,"",["192.0.2.1",443]]]'])
def test_invalid_child_output_fails_closed_without_details(monkeypatch, payload):
    monkeypatch.setattr(dns.subprocess, 'run', lambda *a, **kw: SimpleNamespace(returncode=0, stdout=payload))
    with pytest.raises(OSError, match='^Invalid capture DNS result$'): resolve()


def test_expired_budget_never_launches_child(monkeypatch):
    monkeypatch.setattr(dns.subprocess, 'run', lambda *a, **kw: pytest.fail('unexpected child'))
    with pytest.raises(socket.timeout):
        dns.resolve_addresses('data-api.binance.vision', 443, socket.AF_INET,
                              socket.SOCK_STREAM, deadline=time.monotonic()-1)


def test_dns_consumes_tcp_budget_and_expiry_stops_connection(monkeypatch):
    now = [10.0]
    monkeypatch.setattr(transport.time, 'monotonic', lambda: now[0])
    def resolver(*args, **kwargs):
        now[0] += 6
        return [(socket.AF_INET, 1, 6, '', ('192.0.2.1', 443))]
    monkeypatch.setattr(transport, 'resolve_addresses', resolver)
    from tests.strategy.test_capture_transport import Socket, measurement
    sock = Socket()
    monkeypatch.setattr(transport.socket, 'socket', lambda *args: sock)
    conn = SimpleNamespace(_dns_host='data-api.binance.vision', port=443, timeout=5,
                           socket_options=[], source_address=None)
    with pytest.raises(socket.timeout): transport.measured_socket(conn, measurement())
    assert sock.closed and not hasattr(sock, 'address')


def test_adapter_shares_total_budget_with_urllib3(monkeypatch):
    seen = []
    def send(self, request, **kwargs):
        seen.append(kwargs['timeout'])
        return requests.Response()
    monkeypatch.setattr(requests.adapters.HTTPAdapter, 'send', send)
    adapter = transport.CaptureAdapter(CaptureDiagnostics())
    try: adapter.send(None, timeout=2)
    finally: adapter.close()
    assert seen[0].total == seen[0].connect_timeout == seen[0].read_timeout == 2
