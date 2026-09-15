import json

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

from ladder_dragon.strategy import capture_attestation as att

POLICY = dict(max_uncertainty_ns=10000000, max_ttl_ns=60000000000, max_drift_ppm=100)


@pytest.fixture
def evidence():
    key = Ed25519PrivateKey.generate()
    manifest = json.dumps(dict(schema='bnb_rest_capture_v1', status='DIAGNOSTIC_ONLY',
                              symbol='BNBUSDT', events=1, bytes=100, archive_sha256='a'*64,
                              replay_allowed=False, source_authenticated=False,
                              clock_verified=False, signature=None)).encode()
    clock = dict(measured_wall_ns=10000000000, measured_mono_ns=1000000000,
                 offset_ns=-1000000, uncertainty_ns=2000000, ttl_ns=30000000000,
                 drift_ppm=50, synchronized=True, source='collector-clock-v1')
    return key, manifest, clock


def sign(evidence):
    key, manifest, clock = evidence
    return att.sign(manifest, clock, collector_id='test-collector', private_key=key, **POLICY)


def verify(evidence, body, signature, **changes):
    key, manifest, _ = evidence
    params = dict(trusted_public_key=key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw),
                  expected_collector_id='test-collector', **POLICY)
    params.update(changes)
    return att.verify(manifest, body, signature, **params)


def test_round_trip_and_strict_order(evidence):
    body, signature = sign(evidence)
    clock = verify(evidence, body, signature)
    low, high = clock.receipt_interval(11000000000, 2000000000)
    assert low == 10996950000 and high == 11001050000
    assert att.require_before_fill(clock, wall_ns=11000000000, mono_ns=2000000000, fill_time_ms=11002) == (low, high)
    with pytest.raises(ValueError, match='ORDER_UNKNOWN'):
        att.require_before_fill(clock, wall_ns=11000000000, mono_ns=2000000000, fill_time_ms=11001)


@pytest.mark.parametrize('change', [dict(synchronized=False), dict(synchronized=1),
    dict(uncertainty_ns=0), dict(uncertainty_ns=10000001), dict(ttl_ns=0),
    dict(ttl_ns=60000000001), dict(drift_ppm=0), dict(drift_ppm=101),
    dict(offset_ns=True), dict(source='untrusted'), dict(measured_wall_ns=-1)])
def test_bad_clock_not_signed(evidence, change):
    key, manifest, clock = evidence
    with pytest.raises(ValueError):
        sign((key, manifest, clock | change))


@pytest.mark.parametrize('change', [dict(wall_ns=10000000000, mono_ns=999999999),
    dict(wall_ns=40000000000, mono_ns=31000000000),
    dict(wall_ns=11010000000, mono_ns=2000000000),
    dict(wall_ns=True, mono_ns=2000000000)])
def test_clock_age_and_jump(evidence, change):
    clock = verify(evidence, *sign(evidence))
    with pytest.raises(ValueError):
        clock.receipt_interval(**change)


@pytest.mark.parametrize('mode', ['bytes', 'manifest', 'key', 'collector', 'signature', 'domain', 'policy'])
def test_binding_rejected(evidence, mode):
    body, signature = sign(evidence)
    changes = {}
    if mode == 'bytes':
        body = body.replace(b'2000000', b'1000000')
    elif mode == 'manifest':
        evidence = evidence[0], evidence[1]+b' ', evidence[2]
    elif mode == 'key':
        changes['trusted_public_key'] = Ed25519PrivateKey.generate().public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
    elif mode == 'collector':
        changes['expected_collector_id'] = 'other'
    elif mode == 'signature':
        signature = signature[:-1]
    elif mode == 'domain':
        signature = evidence[0].sign(body)
    else:
        changes['max_uncertainty_ns'] = 1000000
    with pytest.raises(ValueError):
        verify(evidence, body, signature, **changes)


@pytest.mark.parametrize('raw', [b'{}', b'null', b'x'*16385, b'{"x":1,"x":2}'])
def test_bad_signed_payload(evidence, raw):
    signature = evidence[0].sign(att.DOMAIN+raw)
    with pytest.raises(ValueError):
        verify(evidence, raw, signature)


def test_authentic_signature_cannot_upgrade_flags(evidence):
    body, _ = sign(evidence)
    value = json.loads(body)
    value['replay_allowed'] = True
    altered = json.dumps(value).encode()
    with pytest.raises(ValueError):
        verify(evidence, altered, evidence[0].sign(att.DOMAIN+altered))


def test_untrusted_claims_remain_explicit(evidence):
    body, signature = sign(evidence)
    assert b'private' not in body and len(signature) == 64
    verify(evidence, body, signature)
    assert json.loads(evidence[1])['clock_verified'] is False
    assert json.loads(body)['replay_allowed'] is False


def test_wrong_signer_rejected(evidence):
    with pytest.raises(ValueError, match='SIGNER_INVALID'):
        att.sign(evidence[1], evidence[2], collector_id='test', private_key=object(), **POLICY)


def test_same_interval_used_by_causal_converter(evidence):
    from ladder_dragon.strategy.prediction.causal_commission import value_bnb_commission
    window = verify(evidence, *sign(evidence))
    _, upper = att.require_before_fill(window, wall_ns=11000000000, mono_ns=2000000000, fill_time_ms=11003)
    result = value_bnb_commission(symbol='SOLUSDT', commission_amount='0.001',
        fill_time_ms=11003, max_age_ms=1000,
        price_evidence=dict(symbol='BNBUSDT', price='600', market_time_ms=11000,
                            available_at_ms=(upper+999999)//1000000, source_sha256='a'*64))
    assert result.reason == 'CAUSAL_REFERENCE_ONLY'
    assert str(result.quote_value) == '0.600'
