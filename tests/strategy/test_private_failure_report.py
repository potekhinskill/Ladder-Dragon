import json

import pytest
import requests

from ladder_dragon.strategy import private_fill_capture as capture
from tests.strategy.test_private_fill_capture import wire, CREDENTIALS, SCOPE
from tests.strategy.test_private_fill_export import case


@pytest.mark.parametrize('fault,stage,reason,status,calls', [
    ('http', 'clock', 'HTTP_STATUS', 429, 1),
    ('clock', 'clock', 'CLOCK_INVALID', None, 1),
    ('timeout', 'clock', 'TIMEOUT', None, 1),
    ('tls', 'clock', 'TLS', None, 1),
    ('order', 'order', 'VALIDATION', None, 2),
    ('fills', 'fills', 'VALIDATION', None, 3),
    ('validation', 'validation', 'VALIDATION', None, 3),
])
def test_collection_failure_reaches_json_without_export(
        case, wire, tmp_path, monkeypatch, capsys, fault, stage, reason, status, calls):
    _, args, _ = case
    args['binding']['scope_sha256'] = SCOPE
    monkeypatch.setattr(capture, 'external_store', lambda root: tmp_path)
    if fault == 'http': wire['status'] = 429
    if fault == 'clock': wire['clock'] = {'serverTime': 1}
    if fault == 'timeout': wire['failure'] = requests.Timeout('SENTINEL signed-url')
    if fault == 'tls': wire['failure'] = requests.exceptions.SSLError('SENTINEL key')
    if fault == 'order': wire['order'] = {}
    if fault == 'fills': wire['fills'] = b'not json SENTINEL'
    if fault == 'validation': wire['fills'] = []
    try:
        capture.collect_and_export(tmp_path, [('SOLUSDT', 8)], credentials=CREDENTIALS, **args)
    except capture.CaptureFailure as error:
        print(json.dumps(capture.failure_report(error)), flush=True)
    else:
        pytest.fail('expected failure')
    output = capsys.readouterr()
    assert not output.err and 'SENTINEL' not in output.out
    assert json.loads(output.out) == dict(status='BLOCKED', stage=stage, reason=reason,
        http_status=status, private_fills_authenticated=False, replay_allowed=False)
    assert len(wire['calls']) == calls
    assert all(response.raw.closed for response in wire['responses'])
    assert not list(tmp_path.iterdir())


@pytest.mark.parametrize('value', ['SENTINEL', [], {}, True, None])
def test_mutated_metadata_is_revalidated(value):
    error = capture.CaptureFailure('clock', 'HTTP_STATUS', 403)
    error.stage = error.reason = error.http_status = value
    report = capture.failure_report(error)
    assert report['stage'] == 'unknown' and report['reason'] == 'UNKNOWN'
    assert report['http_status'] is None
    assert 'SENTINEL' not in json.dumps(report)


@pytest.mark.parametrize('status', [True, '403', 99, 600, {}, None])
def test_http_status_requires_bounded_integer(status):
    report = capture.failure_report(capture.CaptureFailure('clock', 'HTTP_STATUS', status))
    assert report['http_status'] is None


def test_unknown_exception_is_not_stringified():
    class Hostile(ValueError):
        def __str__(self):
            pytest.fail('exception text accessed')
    report = capture.failure_report(Hostile('SENTINEL'))
    assert report['reason'] == 'UNKNOWN' and report['stage'] == 'unknown'
    assert 'SENTINEL' not in json.dumps(report)


def test_unrelated_status_is_not_published():
    report = capture.failure_report(capture.CaptureFailure('clock', 'TLS', 403))
    assert report['http_status'] is None
