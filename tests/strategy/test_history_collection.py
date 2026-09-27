"""Synthetic-only history collection, trust limits, and private-data boundaries."""

import base64
from copy import deepcopy
import hashlib
import io
import json
import os
import time

import pytest
import requests
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

from ladder_dragon.strategy import history_pages as pages, history_archive as archive
from ladder_dragon.strategy import history_capture as capture, history_capture_process as process


def row(identity=0, stamp=None):
    return dict(symbol='SOLUSDT',id=identity,orderId=8,time=stamp or pages.CUTOFF_MS-1,
                isBuyer=True,isMaker=True,isBestMatch=True,price='100',qty='0.1',quoteQty='10',
                commission='0.001',commissionAsset='BNB')


def packet(body, start, **extra):
    return dict(body=json.dumps(body).encode(),started_ms=start,finished_ms=start+1,elapsed_ms=1,**extra)


@pytest.fixture
def case():
    now=pages.CUTOFF_MS+1000
    source=[packet([row()],now+2,from_id=0)]
    clocks=[packet({'serverTime':now},now),packet({'serverTime':now+4},now+4)]
    signing=Ed25519PrivateKey.generate(); encryption=Fernet.generate_key()
    public=signing.public_key().public_bytes(Encoding.Raw,PublicFormat.Raw)
    binding=dict(scope_sha256=capture.credential_scope('SYNTHETICKEY'),registration_sha256='2'*64,
                 code_sha256='3'*64,signer_sha256=hashlib.sha256(public).hexdigest(),collector_id='history-test',
                 encryption_key_sha256=hashlib.sha256(encryption).hexdigest())
    return source,clocks,dict(binding=binding,signing_key=signing,encryption_key=encryption),public


def test_ciphertext_roundtrip_exact_bytes_no_admission(case):
    source,clocks,args,public=case
    token=archive.seal(source,clocks,**args)
    assert b'SOLUSDT' not in token
    result=archive.open_bundle(token,binding=args['binding'],trusted_public_key=public,encryption_key=args['encryption_key'])
    assert base64.b64decode(result['pages'][0]['body'])==source[0]['body']
    assert result['summary']['records']==1
    for name in ('history_complete','private_fills_authenticated','replay_allowed'):
        assert result['summary'][name] is False


@pytest.mark.parametrize('change',[{'symbol':'ETHUSDT'},{'isBuyer':'false'},{'isMaker':0},
    {'commission':None},{'commissionAsset':''},{'price':'NaN'},{'qty':'1e-3'},{'quoteQty':'9'},
    {'id':True},{'id':-1},{'id':2**63},{'orderId':False},{'time':0},{'time':2**63}])
def test_invalid_fill_rejected_before_cursor(change):
    data=row();data.update(change)
    with pytest.raises(ValueError):pages.page(json.dumps([data]).encode(),0,0,pages.CUTOFF_MS+1)


@pytest.mark.parametrize('raw',[b'null',b'{}',b'[',b'[{"id":1,"id":2}]',b'NaN',b' '* (pages.MAX_BODY+1)])
def test_malformed_page(raw):
    with pytest.raises(ValueError):pages.page(raw,0,0,pages.CUTOFF_MS+1)


def test_cutoff_is_exclusive_and_numeric_id_gaps_allowed():
    result=pages.page(json.dumps([row(10),row(30,pages.CUTOFF_MS)]).encode(),0,0,pages.CUTOFF_MS+1)
    assert result['included']==1 and result['excluded']==1
    assert result['next_cursor']==31 and result['stop']=='CUTOFF_OBSERVED'


@pytest.mark.parametrize('rows,cursor,last', [([row(),row()],0,0),([row(2),row(1)],0,0),
    ([row(1)],2,0),([row(1)],0,pages.CUTOFF_MS),([row(i) for i in range(201)],0,0)])
def test_bad_sequence(rows,cursor,last):
    with pytest.raises(ValueError):pages.page(json.dumps(rows).encode(),cursor,last,pages.CUTOFF_MS+1)


@pytest.mark.parametrize('damage',['clock','elapsed','overlap','future','cursor','bool_cursor','extra','after_stop','premature'])
def test_capture_revalidation(case,damage):
    source,clocks,args,_=case
    if damage=='clock':clocks[1]['body']=b'{"serverTime":1}'
    elif damage=='elapsed':source[0]['elapsed_ms']=5001
    elif damage=='overlap':source[0]['started_ms']=clocks[0]['started_ms']
    elif damage=='future':source[0]['body']=json.dumps([row(0,source[0]['finished_ms']+1)]).encode()
    elif damage=='cursor':source[0]['from_id']=10
    elif damage=='bool_cursor':source[0]['from_id']=False
    elif damage=='extra':source[0]['complete']=True
    elif damage=='after_stop':source.append(dict(source[0]))
    elif damage=='premature':source[0]['body']=json.dumps([row(i) for i in range(200)]).encode()
    with pytest.raises(ValueError,match='^HISTORY_ARCHIVE_INVALID$'):archive.seal(source,clocks,**args)


def test_budget_hit_stays_incomplete_even_on_last_cutoff(case):
    _,_,_,_=case;now=pages.CUTOFF_MS+1000
    source=[packet([row(i*200+j) for j in range(200)],now+2+i*2,from_id=i*200) for i in range(20)]
    clocks=[packet({'serverTime':now},now),packet({'serverTime':now+42},now+42)]
    result=pages.validate_capture(source,clocks)
    assert result['records']==4000 and result['stop_reason']=='LIMIT_REACHED'
    assert result['history_complete'] is False


@pytest.mark.parametrize('damage',['cipher','binding','hash','authority','raw','domain'])
def test_tampering_and_resigned_false_claims(case,damage):
    source,clocks,args,public=case
    token=archive.seal(source,clocks,**args)
    if damage=='cipher':token=token[:-1]+b'x'
    elif damage=='binding':args['binding']=dict(args['binding'],scope_sha256='8'*64)
    else:
        body=archive.claim(source,clocks,args['binding'])
        if damage=='hash':body['pages'][0]['body_sha256']='0'*64
        elif damage=='authority':body['summary']['history_complete']=True
        elif damage=='raw':body['pages'][0]['body']=base64.b64encode(b'[]').decode()
        raw=archive._encode(body)
        signature=args['signing_key'].sign((b'wrong' if damage=='domain' else archive.DOMAIN)+raw)
        token=Fernet(args['encryption_key']).encrypt(archive._encode(dict(body=base64.b64encode(raw).decode(),signature=signature.hex())))
    with pytest.raises(ValueError,match='^HISTORY_ARCHIVE_INVALID$'):
        archive.open_bundle(token,binding=args['binding'],trusted_public_key=public,encryption_key=args['encryption_key'])


class Raw(io.BytesIO):
    def read1(self,size,decode_content=False):return super().read1(size)


@pytest.fixture
def wire(monkeypatch):
    state=dict(calls=[],responses=[],rows=[row()],status=200)
    def request(session,method,url,**kwargs):
        state['calls'].append((method,url,kwargs))
        payload=({'serverTime':time.time_ns()//1000000} if url.endswith(capture.TIME) else state['rows'])
        if callable(payload):payload=payload(kwargs['params'])
        r=requests.Response();r.status_code=state['status']
        r.raw=Raw(payload if type(payload) is bytes else json.dumps(payload).encode())
        state['responses'].append(r);return r
    monkeypatch.setattr(requests.Session,'request',request)
    return state


def fetch():return capture.fetch(credentials=('SYNTHETICKEY','SYNTHETICSECRET'),expected_scope=capture.credential_scope('SYNTHETICKEY'))


def test_actual_signing_transport_get_only_no_retries(wire):
    source,clocks=fetch()
    assert len(source)==1 and len(clocks)==2 and len(wire['calls'])==3
    for method,url,kwargs in wire['calls']:
        assert method=='GET' and url in {capture.BASE+capture.TIME,capture.BASE+capture.FILLS}
        assert kwargs['stream'] and kwargs['verify'] and not kwargs['allow_redirects']
        assert kwargs['proxies']=={} and kwargs['timeout']<=5
    params=wire['calls'][1][2]['params']
    assert params['fromId']==0 and params['limit']==200 and params['symbol']=='SOLUSDT'
    assert all(r.raw.closed for r in wire['responses'])


@pytest.mark.parametrize('status',[301,400,401,403,429,500])
def test_no_retry_on_failure(wire,status):
    wire['status']=status
    with pytest.raises(ValueError):fetch()
    assert len(wire['calls'])==1 and wire['responses'][0].raw.closed


@pytest.mark.parametrize('payload',[b'{"code":-1021,"msg":"SENTINEL"}',b' '* (pages.MAX_BODY+1),b'null'])
def test_provider_or_body_error_never_advances(wire,payload):
    wire['rows']=payload
    with pytest.raises((ValueError,RuntimeError)):fetch()
    assert len(wire['calls'])==2


def test_wrong_credential_prevents_network(wire):
    with pytest.raises(ValueError):capture.fetch(credentials=('OTHERKEY','SECRET'),expected_scope='0'*64)
    assert not wire['calls']


def test_exclusive_encrypted_storage_and_interrupted_write(case,tmp_path,monkeypatch):
    monkeypatch.setattr(archive,'external_store',lambda root:tmp_path)
    directory=archive.reserve(tmp_path)
    token=archive.seal(case[0],case[1],**case[2])
    try:
        result=archive.store(directory,token)
        assert result['status']=='ENCRYPTED_CLAIMS_ONLY'
        with pytest.raises(FileExistsError):archive.store(directory,token)
        with pytest.raises(FileExistsError):archive.reserve(tmp_path)
    finally:os.close(directory)
    assert (tmp_path/archive.SLOT/'bundle.fernet').read_bytes()==token
    assert len(list((tmp_path/archive.SLOT).iterdir()))==1


def test_collection_error_redacted_preserves_slot(case,tmp_path,monkeypatch):
    monkeypatch.setattr(archive,'external_store',lambda root:tmp_path)
    def fail(**kwargs):raise requests.Timeout('SENTINEL signed URL')
    monkeypatch.setattr(capture,'fetch',fail)
    result=capture.collect(tmp_path,credentials=('SYNTHETICKEY','SYNTHETICSECRET'),**case[2])
    assert result['status']=='BLOCKED' and 'SENTINEL' not in repr(result)
    assert (tmp_path/archive.SLOT).is_dir() and not list((tmp_path/archive.SLOT).iterdir())


def test_default_process_path_does_nothing(monkeypatch):
    monkeypatch.setattr(process.subprocess,'run',lambda *a,**k:pytest.fail('process started'))
    assert process.run('/no-such-path')['reason']=='AUTHORIZATION_REQUIRED'


def test_real_isolated_child_safe_failure_no_network(case,tmp_path):
    result=process.run(tmp_path/'absent',authorized=True,
        credentials=('SYNTHETICKEY','SYNTHETICSECRET'),**case[2])
    assert result['status']=='BLOCKED' and result['stage']=='preflight'


def test_outer_deadline_discards_partial_output(case,monkeypatch):
    def timeout(*args,**kwargs):
        assert kwargs['timeout']==150
        raise process.subprocess.TimeoutExpired(args[0],150,output=b'SENTINEL')
    monkeypatch.setattr(process.subprocess,'run',timeout)
    result=process.run('/unused',authorized=True,
        credentials=('SYNTHETICKEY','SYNTHETICSECRET'),**case[2])
    assert result['reason']=='PROCESS_TIMEOUT' and 'SENTINEL' not in repr(result)


def test_real_hung_child_is_terminated(case,monkeypatch):
    children=[];original=process.subprocess.Popen
    def track(*args,**kwargs):
        child=original(*args,**kwargs);children.append(child);return child
    monkeypatch.setattr(process.subprocess,'Popen',track)
    monkeypatch.setattr(process,'_WORKER','import time; time.sleep(60)')
    started=time.monotonic()
    result=process.run('/unused',authorized=True,deadline_sec=1,
        credentials=('SYNTHETICKEY','SYNTHETICSECRET'),**case[2])
    assert result['reason']=='PROCESS_TIMEOUT'
    assert time.monotonic()-started<5
    assert len(children)==1 and children[0].poll() is not None
    with pytest.raises(ChildProcessError):os.waitpid(children[0].pid,os.WNOHANG)


def test_multiple_pages_advance_after_whole_page_validation(wire):
    wire['rows']=lambda p:[row(i) for i in range(p['fromId'],p['fromId']+(200 if p['fromId']==0 else 1))]
    source,clocks=fetch()
    assert [p['from_id'] for p in source]==[0,200]
    assert pages.validate_capture(source,clocks)['records']==201
    assert len(wire['calls'])==4


def test_twenty_page_budget_no_twenty_first_request(wire):
    wire['rows']=lambda p:[row(i) for i in range(p['fromId'],p['fromId']+200)]
    source,clocks=fetch()
    assert len(wire['calls'])==22
    assert pages.validate_capture(source,clocks)['stop_reason']=='LIMIT_REACHED'


def test_unsafe_parent_and_existing_symlink_block_before_write(tmp_path,monkeypatch):
    monkeypatch.setattr(archive,'external_store',lambda root:tmp_path)
    tmp_path.chmod(0o777)
    with pytest.raises(ValueError):archive.reserve(tmp_path)
    tmp_path.chmod(0o700)
    (tmp_path/archive.SLOT).symlink_to(tmp_path,target_is_directory=True)
    with pytest.raises(FileExistsError):archive.reserve(tmp_path)


def test_failed_flush_retains_ciphertext(case,tmp_path,monkeypatch):
    monkeypatch.setattr(archive,'external_store',lambda root:tmp_path)
    directory=archive.reserve(tmp_path)
    token=archive.seal(case[0],case[1],**case[2])
    def fail(fd):raise OSError('SENTINEL')
    monkeypatch.setattr(archive.os,'fsync',fail)
    try:
        with pytest.raises(OSError):archive.store(directory,token)
    finally:os.close(directory)
    assert (tmp_path/archive.SLOT/'bundle.fernet').read_bytes()==token


def test_actual_collection_to_ciphertext_no_plaintext(wire,case,tmp_path,monkeypatch):
    monkeypatch.setattr(archive,'external_store',lambda root:tmp_path)
    result=capture.collect(tmp_path,credentials=('SYNTHETICKEY','SYNTHETICSECRET'),**case[2])
    assert result['status']=='ENCRYPTED_CLAIMS_ONLY'
    token=(tmp_path/archive.SLOT/'bundle.fernet').read_bytes()
    opened=archive.open_bundle(token,binding=case[2]['binding'],trusted_public_key=case[3],encryption_key=case[2]['encryption_key'])
    assert opened['summary']['records']==1 and not opened['summary']['history_complete']
    calls=len(wire['calls'])
    assert capture.collect(tmp_path,credentials=('SYNTHETICKEY','SYNTHETICSECRET'),**case[2])['status']=='BLOCKED'
    assert len(wire['calls'])==calls


def test_session_rejects_mutation_and_other_endpoints(wire):
    with capture.HistorySession() as session:
        for method,url in [('POST',capture.BASE+capture.FILLS),('GET',capture.BASE+'/api/v3/account')]:
            with pytest.raises(ValueError):session.request(method,url)
    assert not wire['calls']
