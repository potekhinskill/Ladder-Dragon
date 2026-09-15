import json

import pytest
import requests
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from bin import record_bnb_public as command
from ladder_dragon.strategy import bnb_capture, capture_clock
from ladder_dragon.strategy.capture_diagnostics import CaptureDiagnostics, REASONS
from ladder_dragon.execution.market_http_body import MarketResponseError
from tests.strategy.test_signed_capture import Clock, PublicSession


@pytest.mark.parametrize('error,reason', [
    (ValueError('CAPTURE_CLOCK_ORDER'), 'CAPTURE_CLOCK_ORDER'),
    (ValueError('CAPTURE_CLOCK_ORDER PRIVATE_SECRET'), 'VALIDATION_FAILED'),
    (ValueError('PRIVATE_SECRET'), 'VALIDATION_FAILED'),
    (ValueError(['PRIVATE_SECRET']), 'VALIDATION_FAILED'),
    (ValueError('CAPTURE_CLOCK_ORDER', 'PRIVATE_SECRET'), 'VALIDATION_FAILED'),
    (requests.exceptions.SSLError('PRIVATE_SECRET'), 'TLS_ERROR'),
    (requests.Timeout('PRIVATE_SECRET'), 'TIMEOUT'),
    (requests.ConnectionError('PRIVATE_SECRET'), 'HTTP_TRANSPORT_ERROR'),
    (FileExistsError('PRIVATE_SECRET'), 'FILE_EXISTS'),
    (FileNotFoundError('PRIVATE_SECRET'), 'FILE_NOT_FOUND'),
    (PermissionError('PRIVATE_SECRET'), 'PERMISSION_DENIED'),
    (OSError('PRIVATE_SECRET'), 'IO_ERROR'),
    (MarketResponseError('PRIVATE_SECRET'), 'HTTP_BODY_INVALID'),
    (json.JSONDecodeError('PRIVATE_SECRET', 'PRIVATE_SECRET', 0), 'JSON_INVALID'),
    (UnicodeError('PRIVATE_SECRET'), 'ENCODING_INVALID'),
    (RuntimeError('PRIVATE_SECRET'), 'INTERNAL_ERROR'),
])
def test_reason_allowlist_never_exports_exception_payload(error, reason):
    diag = CaptureDiagnostics(); diag.mark('clock_validate')
    report = diag.failure(error)
    assert report['stage'] == 'clock_validate' and report['reason'] == reason
    assert report['replay_allowed'] is False and report['status'] == 'BLOCKED'
    assert 'PRIVATE_SECRET' not in json.dumps(report)


def test_unknown_stage_and_dynamic_exception_class_are_not_exported():
    diag = CaptureDiagnostics(); diag.stage = 'PRIVATE_SECRET'
    error = type('PRIVATE_SECRET', (ValueError,), {})('CAPTURE_CLOCK_ORDER')
    report = diag.failure(error)
    assert report['stage'] == 'unknown' and report['reason'] == 'VALIDATION_FAILED'
    assert 'PRIVATE_SECRET' not in json.dumps(report)
    assert CaptureDiagnostics().stage == 'options'


@pytest.mark.parametrize('options', [[], ['--external-mount', 'PRIVATE_SECRET', '--unknown', 'PRIVATE_SECRET'],
    ['--external-mount', 'PRIVATE_SECRET', '--duration-sec', 'PRIVATE_SECRET']])
def test_cli_argument_errors_are_safe_json(monkeypatch, capsys, options):
    monkeypatch.setattr('sys.argv', ['record']+options)
    assert command.main() == 2
    output = capsys.readouterr()
    assert not output.err and 'PRIVATE_SECRET' not in output.out
    assert json.loads(output.out)['reason'] == 'CAPTURE_OPTIONS_INVALID'


def test_cli_stage_does_not_leak_between_invocations(monkeypatch, capsys):
    def fail(root, **kwargs):
        kwargs['diagnostics'].mark('market_body')
        raise requests.Timeout('PRIVATE_SECRET')
    monkeypatch.setattr(command, 'collect', fail)
    monkeypatch.setattr('sys.argv', ['record', '--external-mount', '/unused'])
    assert command.main() == 2
    assert json.loads(capsys.readouterr().out)['stage'] == 'market_body'
    monkeypatch.setattr('sys.argv', ['record'])
    assert command.main() == 2
    assert json.loads(capsys.readouterr().out)['stage'] == 'options'


@pytest.mark.parametrize('fault,stage,reason', [
    ('credential', 'credential', 'CAPTURE_KEY_PIN_MISMATCH'),
    ('storage', 'storage', 'CAPTURE_DISK_RESERVE'),
    ('clock_request', 'clock_request', 'TIMEOUT'),
    ('clock_body', 'clock_body', 'HTTP_BODY_INVALID'),
    ('clock_validate', 'clock_validate', 'ATTESTATION_CLOCK_LIMIT'),
    ('market_request', 'market_request', 'TIMEOUT'),
    ('market_body', 'market_body', 'HTTP_BODY_INVALID'),
    ('market_validate', 'market_validate', 'CAPTURE_SEQUENCE_GAP'),
    ('receipt_validate', 'receipt_validate', 'ATTESTATION_CLOCK_EXPIRED'),
    ('observation_write', 'observation_write', 'IO_ERROR'),
    ('attestation_sign', 'attestation_sign', 'ATTESTATION_MANIFEST_INVALID'),
    ('attestation_write', 'attestation_write', 'IO_ERROR'),
])
def test_real_cli_capture_failure_stage(tmp_path, monkeypatch, capsys, fault, stage, reason):
    clock = Clock(); session = PublicSession(clock)
    key = Ed25519PrivateKey.generate()
    monkeypatch.setattr(command, 'load_capture_key', lambda *a, **k: key)
    monkeypatch.setattr(bnb_capture, 'external_store', lambda root: tmp_path)
    real_collect = bnb_capture.collect
    def collect(root, **kwargs):
        return real_collect(tmp_path, session_factory=lambda: session, wall=clock.wall,
                            mono=clock.mono, pause=lambda _: None, **kwargs)
    monkeypatch.setattr(command, 'collect', collect)
    def fail(*args, **kwargs):
        if reason == 'TIMEOUT': raise requests.Timeout('PRIVATE_SECRET')
        if reason == 'IO_ERROR': raise OSError('PRIVATE_SECRET')
        if reason == 'HTTP_BODY_INVALID': raise MarketResponseError('PRIVATE_SECRET')
        raise ValueError(reason)
    if fault == 'credential': monkeypatch.setattr(command, 'load_capture_key', fail)
    if fault == 'storage': monkeypatch.setattr(bnb_capture, 'external_store', fail)
    if fault in {'clock_request', 'market_request'}:
        get = session.get
        def request(url, **kwargs):
            if (fault == 'clock_request' and url == capture_clock.TIME_URL and len(session.calls) == 1
                    or fault == 'market_request' and url == bnb_capture.URL): fail()
            return get(url, **kwargs)
        monkeypatch.setattr(session, 'get', request)
    if fault == 'clock_body':
        read = capture_clock.read_body
        def clock_read(*args, **kwargs):
            if len(session.calls) == 2: fail()
            return read(*args, **kwargs)
        monkeypatch.setattr(capture_clock, 'read_body', clock_read)
    if fault == 'clock_validate': monkeypatch.setattr(capture_clock, 'derive_clock', fail)
    if fault == 'market_body': monkeypatch.setattr(bnb_capture, 'read_body', fail)
    if fault == 'market_validate': monkeypatch.setattr(bnb_capture, 'trades', fail)
    if fault == 'receipt_validate': monkeypatch.setattr(capture_clock.CaptureSigner, 'observe', fail)
    if fault == 'attestation_sign': monkeypatch.setattr(capture_clock, 'sign', fail)
    if fault in {'observation_write', 'attestation_write'}:
        fsync = bnb_capture.os.fsync
        calls = []
        def sync(fd):
            calls.append(fd)
            # Two observations, then manifest, then the first attestation file.
            if len(calls) == (1 if fault == 'observation_write' else 4): fail()
            return fsync(fd)
        monkeypatch.setattr(bnb_capture.os, 'fsync', sync)
    monkeypatch.setattr('sys.argv', ['record', '--external-mount', str(tmp_path), '--slot', 'signed-test',
        '--requests-limit', '4', '--duration-sec', '5', '--signing-credential', '/PRIVATE_SECRET',
        '--trusted-key-sha256', '0'*64, '--collector-id', 'test', '--clock-max-uncertainty-ms', '10',
        '--clock-ttl-ms', '10000', '--clock-drift-ppm', '100'])
    assert command.main() == 2
    output = capsys.readouterr()
    report = json.loads(output.out)
    assert report['stage'] == stage and report['reason'] == reason
    assert 'PRIVATE_SECRET' not in output.out+output.err
    assert report['replay_allowed'] is False
    assert len(session.calls) <= 4
    if fault not in {'credential', 'storage'}:
        assert session.closed
        assert (tmp_path/'bnb-public-capture-signed-test').exists()


def test_all_local_validation_tokens_have_fixed_diagnostics():
    import ast
    from pathlib import Path
    folder = Path(bnb_capture.__file__).parent
    for filename in ('bnb_capture.py', 'capture_storage.py', 'capture_credentials.py', 'capture_clock.py'):
        tree = ast.parse((folder/filename).read_text())
        tokens = {node.value for node in ast.walk(tree) if isinstance(node, ast.Constant)
                  and type(node.value) is str and node.value.startswith('CAPTURE_')}
        assert tokens <= REASONS
