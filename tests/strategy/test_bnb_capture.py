import hashlib
import io
import json
from pathlib import Path

import pytest
import requests

from ladder_dragon.strategy import bnb_capture as capture


def row(identity=1):
    return dict(a=identity, p='600.01', q='0.1', f=identity, l=identity,
                T=1000, m=True, M=True)


class Response:
    def __init__(self, rows, status=200, raw=None):
        self.status_code = status
        self.headers = {}
        data = json.dumps(rows).encode() if raw is None else raw
        self.raw = type('Raw', (), {'read1': lambda _, n, **kw: self.body.read(n)})()
        self.body = io.BytesIO(data)
        self.closed = False

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.closed = True


class Session:
    def __init__(self, replies):
        self.replies = iter(replies)
        self.calls = []
        self.headers = {}
        self.cookies = {}
        self.closed = False

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.closed = True

    def get(self, url, **kwargs):
        assert url == capture.URL
        assert kwargs['stream'] and not kwargs['allow_redirects']
        assert not self.trust_env and self.auth is None
        assert not self.headers and not self.cookies
        self.calls.append(kwargs)
        reply = next(self.replies)
        if isinstance(reply, Exception):
            raise reply
        return reply


def run(tmp_path, monkeypatch, replies, **kwargs):
    monkeypatch.setattr(capture, 'external_store', lambda root: Path(root))
    session = Session(replies)
    result = capture.collect(tmp_path, session_factory=lambda: session,
                             requests_limit=len(replies), wall=lambda: 2_000_000_000,
                             mono=lambda: 100, pause=lambda _: None, **kwargs)
    return result, session


def test_capture_and_restart(tmp_path, monkeypatch):
    replies = [Response([row()]), Response([row(2)])]
    result, session = run(tmp_path, monkeypatch, replies)
    folder = tmp_path / 'bnb-public-capture'
    raw = (folder / 'observations.jsonl').read_bytes()
    assert result['archive_sha256'] == hashlib.sha256(raw).hexdigest()
    assert result['events'] == 2 and result['replay_allowed'] is False
    assert result['signature'] is None and not result['clock_verified']
    assert session.calls[1]['params']['fromId'] == 2
    assert session.closed and all(r.closed for r in replies)
    observation = json.loads(raw.splitlines()[0])
    assert observation['clock_uncertainty_ns'] is None
    assert 'E' not in json.loads(observation['response_utf8'])[0]
    with pytest.raises(FileExistsError):
        run(tmp_path, monkeypatch, [Response([row()])])
    assert (folder / 'observations.jsonl').read_bytes() == raw


@pytest.mark.parametrize('change', [dict(a=True), dict(T=0), dict(p='NaN'),
                                  dict(q='0'), dict(m='false'), dict(f=3),
                                  dict(p='1'*65), dict(secret='must-not-persist')])
def test_invalid_rows(change):
    bad = row() | change
    with pytest.raises(ValueError):
        capture.trades(json.dumps([bad]).encode(), None)


@pytest.mark.parametrize('raw', [b'null', b'{}', b'[{"a":1,"a":2}]', b' '*65537])
def test_invalid_bodies(raw):
    with pytest.raises(ValueError):
        capture.trades(raw, None)


@pytest.mark.parametrize('second', [1, 3])
def test_duplicate_or_gap(second):
    with pytest.raises(ValueError, match='SEQUENCE'):
        capture.trades(json.dumps([row(second)]).encode(), row())


@pytest.mark.parametrize('reply', [Response([], status=302), Response([], raw=b'x'*65537),
                                  requests.Timeout('secret'), Response([row(3)])])
def test_interrupted_run_has_no_manifest(tmp_path, monkeypatch, reply):
    with pytest.raises((ValueError, RuntimeError, requests.RequestException)):
        run(tmp_path, monkeypatch, [Response([row()]), reply])
    folder = tmp_path / 'bnb-public-capture'
    assert not (folder / 'manifest.json').exists()
    assert (folder / 'observations.jsonl').exists()


def test_clock_jump(tmp_path, monkeypatch):
    monkeypatch.setattr(capture, 'external_store', lambda root: Path(root))
    wall = iter([2_000_000_000, 1_000_000_000])
    with pytest.raises(ValueError, match='CLOCK_JUMP'):
        capture.collect(tmp_path, requests_limit=1, session_factory=lambda: Session([Response([row()])]),
                        wall=lambda: next(wall), mono=lambda: 1)
    assert not (tmp_path / 'bnb-public-capture' / 'manifest.json').exists()


def test_external_storage_required(tmp_path):
    with pytest.raises(ValueError, match='MOUNT'):
        capture.collect(tmp_path)
    assert list(tmp_path.iterdir()) == []


def test_root_device_rejected(monkeypatch):
    monkeypatch.setattr(capture.os.path, 'ismount', lambda _: True)
    with pytest.raises(ValueError, match='ROOT_DEVICE'):
        capture.external_store('/')


def test_invalid_budget_before_storage(tmp_path):
    for value in (0, 101, True):
        with pytest.raises(ValueError, match='LIMIT'):
            capture.collect(tmp_path, requests_limit=value)


def test_empty_capture_not_complete(tmp_path, monkeypatch):
    with pytest.raises(ValueError, match='NO_TRADES'):
        run(tmp_path, monkeypatch, [Response([])])


def test_total_budget(tmp_path, monkeypatch):
    monkeypatch.setattr(capture, 'STORE_LIMIT', 4096)
    with pytest.raises(ValueError, match='STORE_LIMIT'):
        run(tmp_path, monkeypatch, [Response([row()])])


def test_cli_safe_error(monkeypatch, capsys):
    from bin import record_bnb_public as command
    monkeypatch.setattr('sys.argv', ['record_bnb_public', '--external-mount', '/unused'])
    def fail(*args, **kwargs):
        raise requests.Timeout('PRIVATE_SECRET')
    monkeypatch.setattr(command, 'collect', fail)
    assert command.main() == 2
    output = capsys.readouterr().out
    assert 'PRIVATE_SECRET' not in output and 'Timeout' in output


def test_replay_rejects_even_relabelled_manifest(tmp_path, monkeypatch):
    from ladder_dragon.strategy.prediction.commission_archive import extract_price_record
    report, _ = run(tmp_path, monkeypatch, [Response([row()])])
    for change in ({}, {'replay_allowed': True, 'signature': 'invented'}):
        manifest = json.dumps(report | change).encode()
        with (tmp_path / 'bnb-public-capture' / 'observations.jsonl').open('rb') as source:
            with pytest.raises(ValueError):
                extract_price_record(source, manifest_bytes=manifest,
                                     manifest_sha256=hashlib.sha256(manifest).hexdigest(),
                                     symbol='BNBUSDT', aggregate_trade_id=1,
                                     maximum_archive_bytes=65536)


def test_compressed_expansion(tmp_path, monkeypatch):
    import gzip
    reply = Response([], raw=gzip.compress(b' ' * 65537))
    reply.headers['Content-Encoding'] = 'gzip'
    with pytest.raises(RuntimeError):
        run(tmp_path, monkeypatch, [reply])
    assert reply.closed


def test_future_event(tmp_path, monkeypatch):
    with pytest.raises(ValueError, match='FUTURE'):
        run(tmp_path, monkeypatch, [Response([row() | {'T': 3000}])])


def test_mount_disappears_before_request(tmp_path, monkeypatch):
    calls = []
    def check(root):
        calls.append(root)
        if len(calls) > 1:
            raise ValueError('CAPTURE_EXTERNAL_MOUNT_REQUIRED')
        return Path(root)
    monkeypatch.setattr(capture, 'external_store', check)
    session = Session([])
    with pytest.raises(ValueError, match='MOUNT'):
        capture.collect(tmp_path, session_factory=lambda: session)
    assert session.calls == [] and session.closed


def test_deadline_after_response(tmp_path, monkeypatch):
    monkeypatch.setattr(capture, 'external_store', lambda root: Path(root))
    clock = iter([0, 0, 2_000_000_000])
    with pytest.raises(ValueError, match='DEADLINE'):
        capture.collect(tmp_path, duration_sec=1,
                        mono=lambda: next(clock), wall=lambda: 2_000_000_000,
                        session_factory=lambda: Session([Response([row()])]))
