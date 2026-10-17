"""Synthetic wire responses only; no production keys or requests."""
import base64
import json
import time

import pytest
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

from ladder_dragon.strategy import account_diagnostic as diagnostic
from ladder_dragon.strategy import diagnostic_package as producer
from ladder_dragon.strategy import history_input_contract as contract
from tests.strategy.test_account_diagnostic import enrollment, wire


@pytest.fixture
def setup(enrollment, wire, monkeypatch):
    # Advance both clocks at each synthetic response, without real sleeps.
    original = diagnostic._DiagnosticClient._payload
    clock = [time.time_ns()]
    monkeypatch.setattr(time, 'time_ns', lambda: clock[0])
    monkeypatch.setattr(time, 'monotonic_ns', lambda: clock[0])
    def payload(self, response, *, endpoint):
        clock[0] += 2_000_000
        return original(self, response, endpoint=endpoint)
    monkeypatch.setattr(diagnostic._DiagnosticClient, '_payload', payload)
    signer = Ed25519PrivateKey.generate()
    public = signer.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
    key = Fernet.generate_key()
    path, claim = enrollment
    pins = dict(diagnostic_code_sha='a'*40, credential_scope=claim['credential_scope'],
                enrollment_reference=claim['reference'], enrollment_sha256='b'*64,
                diagnostic_public_key=public.hex(), diagnostic_signer_sha256=contract.digest(public),
                encryption_key_sha256=contract.digest(key))
    return dict(enrollment_path=path, expected_reference=claim['reference'],
                credentials=('SENTINELKEY', 'SENTINELSECRET'), pins=pins,
                signer=signer, encryption_key=key, confirmed=True)


def test_producer_consumer_round_trip(setup, enrollment, wire):
    result, cipher = producer.collect_signed_diagnostic(**setup)
    assert result['status'] == 'ENCRYPTED_DIAGNOSTIC_ONLY'
    assert all(result[k] is False for k in ('collection_allowed', 'history_complete',
                                          'private_fills_authenticated', 'replay_allowed'))
    assert len(wire['calls']) == 3
    assert all(r.raw.closed for r in wire['responses'])
    raw = Fernet(setup['encryption_key']).decrypt(cipher)
    assert contract.verify_diagnostic(raw, pins=setup['pins'], enrollment=enrollment[1],
                                      now_ms=time.time_ns()//1_000_000)
    body = json.loads(base64.b64decode(json.loads(raw)['body']))
    assert base64.b64decode(body['account_body']) == wire['account']
    assert base64.b64decode(body['permissions_body']) == wire['permissions']
    assert body['request_count'] == 3 and body['elapsed_ms'] == 6
    assert b'SENTINEL' not in cipher and '123456789' not in repr(result)
    assert list(enrollment[0].parent.iterdir()) == [enrollment[0]]


@pytest.mark.parametrize('confirmed', [False, None, 1, 'YES'])
def test_no_confirmation_no_requests(setup, wire, confirmed):
    setup['confirmed'] = confirmed
    result, cipher = producer.collect_signed_diagnostic(**setup)
    assert result['stage'] == 'authorization' and cipher is None and not wire['calls']


@pytest.mark.parametrize('field', ['credential_scope', 'enrollment_reference',
    'diagnostic_public_key', 'diagnostic_signer_sha256', 'encryption_key_sha256'])
def test_wrong_binding_before_requests(setup, wire, field):
    setup['pins'][field] = '0'*len(setup['pins'][field])
    result, cipher = producer.collect_signed_diagnostic(**setup)
    assert result['status'] == 'BLOCKED' and cipher is None and not wire['calls']


@pytest.mark.parametrize('field', ['diagnostic_code_sha', 'enrollment_sha256', 'enrollment_reference'])
def test_malformed_pin_before_requests(setup, wire, field):
    setup['pins'][field] = 'SENTINEL'
    result, cipher = producer.collect_signed_diagnostic(**setup)
    assert result['status'] == 'BLOCKED' and cipher is None and not wire['calls']
    assert 'SENTINEL' not in repr(result)


@pytest.mark.parametrize('failure', ['http', 'identity', 'permissions', 'clock', 'count', 'signing'])
def test_failed_chain_cannot_release_package(setup, wire, monkeypatch, failure):
    if failure == 'http':
        wire['status'] = 429
    elif failure == 'identity':
        wire['account'] = b'{"uid":99}'
    elif failure == 'permissions':
        value = json.loads(wire['permissions']); value['enableWithdrawals'] = True
        wire['permissions'] = json.dumps(value).encode()
    elif failure == 'clock':
        def reject(*args, **kwargs): raise ValueError('SENTINEL')
        monkeypatch.setattr(diagnostic._DiagnosticClient, 'refresh_clock', reject)
    elif failure == 'count':
        original = diagnostic._DiagnosticClient.signed
        def signed(self, method, endpoint, **kwargs):
            result = original(self, method, endpoint, **kwargs)
            if endpoint == diagnostic.PERMISSIONS: self._session.calls = 2
            return result
        monkeypatch.setattr(diagnostic._DiagnosticClient, 'signed', signed)
    else:
        def reject(*args, **kwargs): raise ValueError('SENTINEL')
        monkeypatch.setattr(producer._Package, 'finish', reject)
    result, cipher = producer.collect_signed_diagnostic(**setup)
    assert result['status'] == 'BLOCKED' and cipher is None
    assert 'SENTINEL' not in repr(result)
    assert len(wire['calls']) <= 3


def test_fake_summary_is_not_observation(setup, wire, monkeypatch):
    monkeypatch.setattr(producer, '_diagnose', lambda **kwargs:
        dict(status='DIAGNOSTIC_MATCH_ONLY', stage='validation'))
    result, cipher = producer.collect_signed_diagnostic(**setup)
    assert result['status'] == 'BLOCKED' and cipher is None and not wire['calls']


def test_cipher_tampering_and_stale_consumer(setup, enrollment):
    from cryptography.fernet import InvalidToken
    _, cipher = producer.collect_signed_diagnostic(**setup)
    decryptor = Fernet(setup['encryption_key'])
    with pytest.raises(InvalidToken): decryptor.decrypt(cipher[:-10] + b'0'*10)
    with pytest.raises(ValueError):
        contract.verify_diagnostic(decryptor.decrypt(cipher), pins=setup['pins'],
            enrollment=enrollment[1], now_ms=time.time_ns()//1_000_000 + 300001)
