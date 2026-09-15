import hashlib
import io
import json
from pathlib import Path

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

from ladder_dragon.strategy import bnb_capture
from ladder_dragon.strategy.capture_clock import CaptureSigner, TIME_URL, derive_clock
from ladder_dragon.strategy.prediction.signed_capture import value_signed_capture
from tests.strategy.test_bnb_capture import Response, Session, row
from tests.strategy.test_commission_evidence import evidence, encoded, run as websocket_value

POLICY = dict(max_uncertainty_ns=10000000, max_ttl_ns=10000000000, max_drift_ppm=100)


class Clock:
    now = 1500000000

    def wall(self):
        return self.now

    def mono(self):
        return self.now-1000000000


class PublicSession(Session):
    def __init__(self, clock):
        super().__init__([])
        self.clock = clock
        self.trade_calls = 0

    def get(self, url, **kwargs):
        assert url in {TIME_URL, bnb_capture.URL}
        assert kwargs['stream'] and not kwargs['allow_redirects']
        assert not self.trust_env and self.auth is None
        assert not self.headers and not self.cookies
        self.calls.append(url)
        if url == TIME_URL:
            self.clock.now += 2000000
            return Response({'serverTime': 1501})
        self.clock.now += 100000000
        self.trade_calls += 1
        assert kwargs['params']['symbol'] == 'BNBUSDT'
        if self.trade_calls > 1:
            assert kwargs['params']['fromId'] == 76+self.trade_calls
        return Response([row(76+self.trade_calls) | dict(T=1450+100*self.trade_calls, p='600')])


@pytest.fixture
def capture(tmp_path, monkeypatch, evidence):
    monkeypatch.setattr(bnb_capture, 'external_store', lambda root: Path(root))
    key = Ed25519PrivateKey.generate()
    signer = CaptureSigner(private_key=key, collector_id='test', policy=POLICY)
    clock = Clock()
    session = PublicSession(clock)
    report = bnb_capture.collect(tmp_path, requests_limit=4, duration_sec=5,
        session_factory=lambda: session, wall=clock.wall, mono=clock.mono, pause=lambda _: None, attestor=signer)
    folder = tmp_path/'bnb-public-capture'
    files = {name: (folder/name).read_bytes() for name in
             ('manifest.json', 'clock.json', 'attestation.json', 'attestation.sig', 'observations.jsonl')}
    args = dict(manifest_bytes=files['manifest.json'], measurement_bytes=files['clock.json'],
        attestation_bytes=files['attestation.json'], signature=files['attestation.sig'],
        trusted_public_key=key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw),
        expected_collector_id='test', clock_policy=POLICY, aggregate_trade_id=77,
        parent=evidence[0].get('buy'), trade_id=1, fills_bytes=encoded(evidence[1]),
        fills_sha256=hashlib.sha256(encoded(evidence[1])).hexdigest(), max_age_ms=1000,
        maximum_archive_bytes=65536)
    return files, args, report, session


def evaluate(capture, **changes):
    files, args, _, _ = capture
    args = args | {'stream': io.BytesIO(files['observations.jsonl'])} | changes
    return value_signed_capture(**args)


def test_real_pipeline_without_network_or_journal_mutation(capture, evidence):
    files, _, report, session = capture
    before = evidence[0].get('buy')
    result = evaluate(capture)
    assert result.commission.valuation.quote_value == websocket_value(evidence).valuation.quote_value
    assert result.commission.valuation.reason == 'CAUSAL_REFERENCE_ONLY'
    assert result.archive_sha256 == report['archive_sha256']
    assert result.measurement_sha256 == hashlib.sha256(files['clock.json']).hexdigest()
    assert not result.replay_allowed and report['replay_allowed'] is False
    assert session.calls == [TIME_URL, TIME_URL, bnb_capture.URL, bnb_capture.URL]
    assert session.closed and evidence[0].get('buy') == before


@pytest.mark.parametrize('field', ['manifest_bytes', 'measurement_bytes', 'attestation_bytes', 'signature', 'fills_bytes'])
def test_changed_bytes_rejected(capture, field):
    value = capture[1][field]
    with pytest.raises((ValueError, RuntimeError)):
        evaluate(capture, **{field: value+b' '})


@pytest.mark.parametrize('mode', ['truncate', 'tail', 'replace', 'capacity', 'key', 'absent', 'expiry', 'age'])
def test_full_chain_rejections(capture, mode):
    raw = capture[0]['observations.jsonl']
    changes = {}
    if mode == 'truncate':
        changes['stream'] = io.BytesIO(raw[:-10])
    elif mode == 'tail':
        changes['stream'] = io.BytesIO(raw+b'{}\n')
    elif mode == 'replace':
        changes['stream'] = io.BytesIO(raw.replace(b'600', b'601'))
    elif mode == 'capacity':
        changes['maximum_archive_bytes'] = len(raw)-1
    elif mode == 'key':
        changes['trusted_public_key'] = b'x'*32
    elif mode == 'absent':
        changes['aggregate_trade_id'] = 999
    elif mode == 'expiry':
        changes['clock_policy'] = POLICY | {'max_ttl_ns': 1}
    else:
        result = evaluate(capture, max_age_ms=1)
        assert result.commission.valuation.quote_value is None
        assert result.commission.valuation.reason == 'PRICE_STALE'
        return
    with pytest.raises((ValueError, RuntimeError)):
        evaluate(capture, **changes)


@pytest.mark.parametrize('change', [dict(source='other'), dict(finished_mono_ns=1),
    dict(finished_wall_ns=1000000000), dict(response_utf8='{}'),
    dict(response_utf8='{"serverTime":true}'), dict(response_utf8='x'*1025)])
def test_measurement_rederived_not_flag_trusted(capture, change):
    raw = encoded(json.loads(capture[0]['clock.json']) | change)
    with pytest.raises(ValueError):
        derive_clock(raw, **POLICY)


def test_time_body_bounded_and_no_completion(tmp_path, monkeypatch):
    monkeypatch.setattr(bnb_capture, 'external_store', lambda root: Path(root))
    session = Session([])
    response = Response([], raw=b'x'*1025)
    session.get = lambda *a, **k: response
    signer = CaptureSigner(private_key=Ed25519PrivateKey.generate(), collector_id='test', policy=POLICY)
    with pytest.raises(RuntimeError):
        bnb_capture.collect(tmp_path, requests_limit=3, session_factory=lambda: session, attestor=signer)
    assert response.closed and session.closed
    assert not (tmp_path/'bnb-public-capture'/'manifest.json').exists()


def test_signing_failure_preserves_unsigned_data(tmp_path, monkeypatch):
    monkeypatch.setattr(bnb_capture, 'external_store', lambda root: Path(root))
    clock = Clock()
    signer = CaptureSigner(private_key=Ed25519PrivateKey.generate(), collector_id='test', policy=POLICY)
    def fail(*args):
        raise OSError('test disk failure')
    monkeypatch.setattr(signer, 'publish', fail)
    with pytest.raises(OSError):
        bnb_capture.collect(tmp_path, requests_limit=3, session_factory=lambda: PublicSession(clock),
                            attestor=signer, wall=clock.wall, mono=clock.mono)
    folder = tmp_path/'bnb-public-capture'
    assert (folder/'observations.jsonl').stat().st_size > 0
    assert json.loads((folder/'manifest.json').read_bytes())['replay_allowed'] is False
    assert not (folder/'attestation.sig').exists()


@pytest.mark.parametrize('limit', [1, 2])
def test_clock_request_counts_against_limit(tmp_path, limit):
    with pytest.raises(ValueError, match='REQUEST_BUDGET'):
        bnb_capture.collect(tmp_path, requests_limit=limit, attestor=object())
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize('mode', ['gap', 'reverse', 'flags'])
def test_signed_rehashed_malformed_archive_rejected(capture, mode):
    from ladder_dragon.strategy.capture_attestation import sign
    raw = capture[0]['observations.jsonl']
    if mode == 'gap':
        raw = raw.replace(b'78', b'79')
    elif mode == 'reverse':
        raw = b'\n'.join(reversed(raw.splitlines())) + b'\n'
    else:
        raw = raw.replace(b'"replay_allowed":false', b'"replay_allowed":true')
    manifest = json.loads(capture[0]['manifest.json'])
    manifest.update(bytes=len(raw), archive_sha256=hashlib.sha256(raw).hexdigest())
    manifest_raw = encoded(manifest)
    key = Ed25519PrivateKey.generate()
    clock = derive_clock(capture[0]['clock.json'], **POLICY)
    body, signature = sign(manifest_raw, clock, collector_id='test', private_key=key, **POLICY)
    with pytest.raises(ValueError):
        evaluate(capture, stream=io.BytesIO(raw), manifest_bytes=manifest_raw,
                 attestation_bytes=body, signature=signature,
                 trusted_public_key=key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw))


@pytest.mark.parametrize('policy', [POLICY | {'max_uncertainty_ns': 1}, POLICY | {'max_ttl_ns': 1}])
def test_live_measurement_failure_blocks_signing(tmp_path, monkeypatch, policy):
    monkeypatch.setattr(bnb_capture, 'external_store', lambda root: Path(root))
    clock = Clock()
    signer = CaptureSigner(private_key=Ed25519PrivateKey.generate(), collector_id='test', policy=policy)
    with pytest.raises(ValueError):
        bnb_capture.collect(tmp_path, requests_limit=3, session_factory=lambda: PublicSession(clock),
                            attestor=signer, wall=clock.wall, mono=clock.mono)
    assert not (tmp_path/'bnb-public-capture'/'attestation.sig').exists()
