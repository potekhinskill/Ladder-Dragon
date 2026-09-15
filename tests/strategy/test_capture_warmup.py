import json
import time

import pytest
import requests
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from ladder_dragon.strategy import bnb_capture, capture_clock
from ladder_dragon.strategy.capture_diagnostics import CaptureDiagnostics
from tests.strategy.test_signed_capture import Clock, PublicSession, POLICY, TIME_URL
from tests.strategy.test_bnb_capture import Response


def setup(tmp_path, monkeypatch, *, policy=POLICY):
    monkeypatch.setattr(bnb_capture, 'external_store', lambda root: tmp_path)
    clock = Clock()
    session = PublicSession(clock)
    diagnostics = CaptureDiagnostics()
    signer = capture_clock.CaptureSigner(private_key=Ed25519PrivateKey.generate(),
        collector_id='test', policy=policy, diagnostics=diagnostics)
    def collect(limit=3, duration=5):
        return bnb_capture.collect(tmp_path, requests_limit=limit, duration_sec=duration,
            session_factory=lambda: session, wall=clock.wall, mono=clock.mono,
            pause=lambda _: None, attestor=signer, diagnostics=diagnostics)
    return clock, session, signer, diagnostics, collect


@pytest.mark.parametrize('limit', [3, 4, 5])
def test_one_slow_warmup_is_discarded_and_total_limit_preserved(tmp_path, monkeypatch, limit):
    clock, session, signer, diag, collect = setup(tmp_path, monkeypatch)
    original = session.get
    first = Response(None, raw=b'WARMUP_BYTES_DISCARDED')
    def get(url, **kwargs):
        if not session.calls:
            clock.now += 1100000000
            session.calls.append(url)
            return first
        assert first.closed
        return original(url, **kwargs)
    session.get = get
    collect(limit=limit)
    assert session.calls == [TIME_URL, TIME_URL]+[bnb_capture.URL]*(limit-2)
    assert session.closed and signer.clock['uncertainty_ns'] <= POLICY['max_uncertainty_ns']
    measurement = json.loads(signer.measurement)
    assert measurement['finished_mono_ns']-measurement['started_mono_ns'] == 2000000
    folder = tmp_path/'bnb-public-capture'
    assert set(path.name for path in folder.iterdir()) == {
        'observations.jsonl', 'manifest.json', 'clock.json', 'attestation.json', 'attestation.sig'}
    assert b'WARMUP_BYTES_DISCARDED' not in (folder/'clock.json').read_bytes()


@pytest.mark.parametrize('fault,stage', [('timeout','clock_warmup_request'),
    ('status','clock_warmup_request'), ('body','clock_warmup_body'), ('close','clock_warmup_close')])
def test_warmup_failure_closes_session_and_never_retries(tmp_path, monkeypatch, fault, stage):
    clock, session, signer, diag, collect = setup(tmp_path, monkeypatch)
    class Reply(Response):
        def __exit__(self, *args):
            super().__exit__(*args)
            if fault == 'close': raise OSError('PRIVATE')
    reply = Reply({}, status=503 if fault == 'status' else 200,
                  raw=b'x'*1025 if fault == 'body' else b'{}')
    def get(url, **kwargs):
        session.calls.append(url)
        if fault == 'timeout': raise requests.Timeout('PRIVATE')
        return reply
    session.get = get
    with pytest.raises((ValueError, RuntimeError, OSError, requests.RequestException)) as failure:
        collect()
    assert diag.failure(failure.value)['stage'] == stage
    assert session.calls == [TIME_URL] and session.closed
    assert fault == 'timeout' or reply.closed
    assert signer.measurement is None and signer.clock is None
    with pytest.raises(ValueError, match='SIGNER_REUSE'):
        signer.start(session, clock.wall, clock.mono, time.monotonic()+5)
    assert session.calls == [TIME_URL]
    assert not (tmp_path/'bnb-public-capture'/'manifest.json').exists()


def test_warmup_close_cannot_restart_total_duration(tmp_path, monkeypatch):
    clock, session, signer, diag, collect = setup(tmp_path, monkeypatch)
    monkeypatch.setattr(capture_clock.time, 'monotonic', lambda: clock.mono()/1000000000)
    class Reply(Response):
        def __exit__(self, *args):
            super().__exit__(*args)
            clock.now += 1000000000
    reply = Reply({})
    def get(url, **kwargs):
        session.calls.append(url)
        return reply
    session.get = get
    with pytest.raises(ValueError, match='CLOCK_DEADLINE'): collect(duration=1)
    assert session.calls == [TIME_URL] and session.closed and reply.closed
    assert signer.clock is None


def test_bad_qualifying_sample_cannot_fall_back_to_warmup(tmp_path, monkeypatch):
    clock, session, signer, diag, collect = setup(tmp_path, monkeypatch,
                                               policy=POLICY | {'max_uncertainty_ns': 500000000})
    original = session.get
    def get(url, **kwargs):
        if len(session.calls) == 1: clock.now += 1100000000
        return original(url, **kwargs)
    session.get = get
    with pytest.raises(ValueError, match='ATTESTATION_CLOCK_LIMIT'): collect()
    assert session.calls == [TIME_URL, TIME_URL] and session.closed
    assert signer.clock is None and diag.stage == 'clock_validate'
    assert not (tmp_path/'bnb-public-capture'/'attestation.sig').exists()
