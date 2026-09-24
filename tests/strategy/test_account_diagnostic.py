import io
import json
import os
import time

import pytest
import requests

from ladder_dragon.strategy import account_diagnostic as diagnostic
from ladder_dragon.strategy.account_enrollment import load_enrollment
from tests.strategy.test_account_binding import inputs


@pytest.fixture
def enrollment(tmp_path):
    parent = tmp_path.resolve() / 'protected'
    parent.mkdir(mode=0o700)
    path = parent / 'identity.json'
    record = dict(schema='account_enrollment_claim_v1', reference='b'*32, uid=123456789,
                  credential_scope=diagnostic.credential_scope('SENTINELKEY'))
    path.write_text(json.dumps(record)); path.chmod(0o600)
    return path, record


class Raw(io.BytesIO):
    def read1(self, size, decode_content=False):
        return self.read(size)


@pytest.fixture
def wire(monkeypatch):
    data = inputs()
    state = dict(calls=[], responses=[], status=200, failure=None,
                 account=data['account_body'], permissions=data['permission_body'])
    def request(session, method, url, **kwargs):
        state['calls'].append((method, url, kwargs))
        if state['failure']:
            raise state['failure']
        raw = (json.dumps({'serverTime': time.time_ns()//1000000}).encode() if url.endswith(diagnostic.TIME)
               else state['account'] if url.endswith(diagnostic.ACCOUNT) else state['permissions'])
        response = requests.Response(); response.status_code = state['status']
        response.raw = Raw(raw); state['responses'].append(response)
        return response
    monkeypatch.setattr(requests.Session, 'request', request)
    return state


def run(enrollment, **changes):
    path, record = enrollment
    args = dict(enrollment_path=path, expected_reference=record['reference'],
                credentials=('SENTINELKEY', 'SENTINELSECRET'))
    args.update(changes)
    return diagnostic.diagnose_account(**args)


def test_composed_diagnostic_is_bounded_and_has_no_admission(enrollment, wire):
    path, _ = enrollment; before = path.read_bytes()
    result = run(enrollment)
    assert result['status'] == 'DIAGNOSTIC_MATCH_ONLY'
    assert not any(result[k] for k in ('account_authenticated','private_fills_authenticated','replay_allowed'))
    assert [url for _, url, _ in wire['calls']] == [diagnostic.BASE+p for p in
        (diagnostic.TIME, diagnostic.ACCOUNT, diagnostic.PERMISSIONS)]
    for method, _, options in wire['calls']:
        assert method == 'GET' and options['verify'] is True and options['stream'] is True
        assert options['allow_redirects'] is False and options['proxies'] == {}
        assert 0 < options['timeout'] <= 5
    assert all(r.raw.closed for r in wire['responses'])
    assert path.read_bytes() == before
    assert list(path.parent.iterdir()) == [path]
    assert 'SENTINEL' not in repr(result) and '123456789' not in repr(result)


@pytest.mark.parametrize('mode',[0o644,0o640,0o666,0o700])
def test_unsafe_file_blocks_before_network(enrollment,wire,mode):
    enrollment[0].chmod(mode)
    assert run(enrollment)['stage'] == 'enrollment'
    assert not wire['calls']


@pytest.mark.parametrize('kind',['file_link','parent_link','hardlink','fifo','directory'])
def test_unsafe_paths_fail_closed(enrollment,wire,kind):
    path, _ = enrollment; other = path.with_name('other')
    if kind == 'file_link': other.symlink_to(path)
    elif kind == 'parent_link':
        other = path.parent.with_name('alias'); other.symlink_to(path.parent); other = other/path.name
    elif kind == 'hardlink': os.link(path,other)
    elif kind == 'fifo': os.mkfifo(other,0o600)
    else: other.mkdir(mode=0o700)
    assert run(enrollment,enrollment_path=other)['status'] == 'BLOCKED'
    assert not wire['calls']


@pytest.mark.parametrize('raw',[b'',b'x'*4097,b'{"private":"SENTINEL"',
    b'{"uid":1,"uid":1}',b'{"uid":1e999999999999999999999999999}'])
def test_malformed_enrollment_is_safe(enrollment,wire,raw):
    enrollment[0].write_bytes(raw)
    result = run(enrollment)
    assert result['status'] == 'BLOCKED' and not wire['calls']
    assert 'SENTINEL' not in repr(result)


def test_parent_permission_and_reference(enrollment,wire):
    enrollment[0].parent.chmod(0o755)
    assert run(enrollment)['status'] == 'BLOCKED'
    enrollment[0].parent.chmod(0o700)
    assert run(enrollment,expected_reference='c'*32)['status'] == 'BLOCKED'
    assert not wire['calls']


def test_change_during_read_rejected(enrollment,monkeypatch):
    read = os.read
    def mutate(fd,size):
        value = read(fd,size)
        enrollment[0].write_bytes(b'changed')
        return value
    monkeypatch.setattr(os,'read',mutate)
    with pytest.raises(ValueError,match='^ACCOUNT_ENROLLMENT_INVALID$'):
        load_enrollment(enrollment[0],expected_reference=enrollment[1]['reference'])


@pytest.mark.parametrize('credentials',[None,('SENTINELKEY',),('OTHERKEY','SECRET'),
    ('SENTINELKEY',''),('SENTINELKEY','../SENTINEL')])
def test_bad_credentials_stop_before_network(enrollment,wire,credentials):
    assert run(enrollment,credentials=credentials)['status'] == 'BLOCKED'
    assert not wire['calls']


@pytest.mark.parametrize('status',[301,400,401,429,500])
def test_http_failures_never_retry(enrollment,wire,status):
    wire['status'] = status
    assert run(enrollment)['status'] == 'BLOCKED'
    assert len(wire['calls']) == 1 and wire['responses'][0].raw.closed


@pytest.mark.parametrize('error',[requests.Timeout('SENTINEL'),requests.exceptions.SSLError('SENTINEL'),
    requests.ConnectionError('SENTINEL')])
def test_network_failure_safe(enrollment,wire,error):
    wire['failure'] = error
    result = run(enrollment)
    assert result['status'] == 'BLOCKED' and 'SENTINEL' not in repr(result)
    assert len(wire['calls']) == 1


@pytest.mark.parametrize('key,body',[('account',b'{"uid":999}'),
    ('account',b'x'*(diagnostic.MAX_ACCOUNT_BYTES+1)),
    ('permissions',b'x'*(diagnostic.MAX_PERMISSION_BYTES+1)),
    ('permissions',b'{"code":-1021,"msg":"SENTINEL"}')])
def test_invalid_responses_never_authorize(enrollment,wire,key,body):
    wire[key] = body
    result = run(enrollment)
    assert result['status'] == 'BLOCKED' and 'SENTINEL' not in repr(result)
    assert len(wire['calls']) <= 3 and all(r.raw.closed for r in wire['responses'])


def test_capability_and_deadline(wire):
    with diagnostic._DiagnosticSession() as session:
        for method,url in [('POST',diagnostic.BASE+diagnostic.ACCOUNT),
                           ('GET',diagnostic.BASE+'/api/v3/myTrades'),
                           ('GET','http://api.binance.com/api/v3/time')]:
            with pytest.raises(ValueError): session.request(method,url)
        session.calls = 3
        with pytest.raises(ValueError): session.get(diagnostic.BASE+diagnostic.TIME)
        session.calls = 0; session.deadline = 0
        with pytest.raises(ValueError): session.get(diagnostic.BASE+diagnostic.TIME)
    assert not wire['calls']


def test_clock_failure_prevents_private_requests(enrollment,wire,monkeypatch):
    def reject(*args,**kwargs):
        raise ValueError('SENTINEL')
    monkeypatch.setattr(diagnostic._DiagnosticClient,'refresh_clock',reject)
    result = run(enrollment)
    assert result['status'] == 'BLOCKED' and result['stage'] == 'clock'
    assert not wire['calls'] and 'SENTINEL' not in repr(result)


def test_wall_clock_jump_after_responses_blocks(enrollment,wire,monkeypatch):
    signed = diagnostic._DiagnosticClient.signed
    original_time = time.time_ns
    def jump(client,method,endpoint,**kwargs):
        result = signed(client,method,endpoint,**kwargs)
        if endpoint == diagnostic.PERMISSIONS:
            monkeypatch.setattr(time,'time_ns',lambda: original_time()+10000000000)
        return result
    monkeypatch.setattr(diagnostic._DiagnosticClient,'signed',jump)
    result = run(enrollment)
    assert result['status'] == 'BLOCKED' and result['stage'] == 'validation'


def test_protected_readonly_record(enrollment):
    path,record = enrollment
    path.chmod(0o400)
    assert load_enrollment(path,expected_reference=record['reference']) == record
