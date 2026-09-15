import io
import json
import time

import pytest
import requests

from ladder_dragon.strategy import private_fill_capture as capture, private_fill_export as export
from tests.strategy.test_private_fill_export import case
from tests.test_verify_bnb_orders import OrderClient

CREDENTIALS = ('SENTINELAPIKEY', 'SENTINELAPISECRET')
SCOPE = capture.credential_scope(CREDENTIALS[0])


class Raw(io.BytesIO):
    def read1(self, size, decode_content=False):
        return super().read1(size)


@pytest.fixture
def wire(monkeypatch):
    source=OrderClient()
    calls=[]; responses=[]
    state=dict(order=source.order,fills=source.fills,status=200,failure=None)
    def request(session, method, url, **kwargs):
        calls.append((method,url,kwargs))
        if state['failure']:
            raise state['failure']
        data=(state.get('clock',{'serverTime':time.time_ns()//1000000}) if url.endswith(capture.TIME)
              else state['order'] if url.endswith(capture.ORDER) else state['fills'])
        response=requests.Response(); response.status_code=state['status']
        response.raw=Raw(data if type(data) is bytes else json.dumps(data,indent=1).encode())
        responses.append(response)
        return response
    monkeypatch.setattr(requests.Session,'request',request)
    state.update(calls=calls,responses=responses)
    return state


def fetch():
    return capture.fetch([('SOLUSDT',8)],credentials=CREDENTIALS,expected_scope=SCOPE)


def test_actual_signing_adapter_retains_exact_bodies(wire):
    packets=fetch()
    assert len(wire['calls'])==3
    assert packets[0]['order_body']==json.dumps(wire['order'],indent=1).encode()
    assert packets[0]['fills_body']==json.dumps(wire['fills'],indent=1).encode()
    assert packets[0]['scope_sha256']==SCOPE
    for method,url,options in wire['calls']:
        assert method=='GET' and url in {capture.BASE+p for p in (capture.TIME,capture.ORDER,capture.FILLS)}
        assert options['verify'] is True and options['stream'] is True and options['proxies']=={}
        assert options['allow_redirects'] is False and 0<options['timeout']<=5
        if not url.endswith(capture.TIME):
            assert options['headers']['X-MBX-APIKEY']==CREDENTIALS[0]
            assert len(options['params']['signature'])==64
    assert all(r.raw.closed for r in wire['responses'])
    assert 'SENTINEL' not in repr(packets)


@pytest.mark.parametrize('orders', [[],[('SOLUSDT',True)],[('SOLUSDT',-1)], [('SOLUSDT',8)]*2,
    [('SOLUSDT',i) for i in range(9)],[('../bad market',8)]])
def test_bad_selection_before_network(wire,orders):
    with pytest.raises(ValueError,match='^PRIVATE_CAPTURE_FAILED_CLOSED$'):
        capture.fetch(orders,credentials=CREDENTIALS,expected_scope=SCOPE)
    assert not wire['calls']


@pytest.mark.parametrize('credentials,scope', [(('OTHERAPIKEY',CREDENTIALS[1]),SCOPE),
    (CREDENTIALS,'0'*64),(('',CREDENTIALS[1]),SCOPE),(('SENTINELAPIKEY',''),SCOPE),
    (['SENTINELAPIKEY','SENTINELAPISECRET'],SCOPE)])
def test_scope_pinned_before_network(wire,credentials,scope):
    with pytest.raises(ValueError,match='^PRIVATE_CAPTURE_FAILED_CLOSED$'):
        capture.fetch([('SOLUSDT',8)],credentials=credentials,expected_scope=scope)
    assert not wire['calls']


@pytest.mark.parametrize('status', [301,302,400,401,403,429,500])
def test_non_success_closes_without_retry(wire,status):
    wire['status']=status
    with pytest.raises(ValueError,match='^PRIVATE_CAPTURE_FAILED_CLOSED$'): fetch()
    assert len(wire['calls'])==1 and wire['responses'][0].raw.closed


@pytest.mark.parametrize('failure', [requests.Timeout('SENTINEL signed-url'),
    requests.ConnectionError('SENTINEL'),requests.exceptions.SSLError('SENTINEL')])
def test_network_errors_are_sanitized_without_retry(wire,failure):
    wire['failure']=failure
    with pytest.raises(ValueError,match='^PRIVATE_CAPTURE_FAILED_CLOSED$') as error: fetch()
    assert error.value.__suppress_context__ and len(wire['calls'])==1


@pytest.mark.parametrize('order', [dict(code=-1021,msg='SENTINEL'),dict(symbol='ETHUSDT'),
    b'{"symbol":"SOLUSDT","symbol":"ETHUSDT"}',b'x'*65537])
def test_order_error_stops_before_fills_and_never_retries(wire,order):
    wire['order']=order
    with pytest.raises(ValueError,match='^PRIVATE_CAPTURE_FAILED_CLOSED$'): fetch()
    assert len(wire['calls'])==2 and all(r.raw.closed for r in wire['responses'])


@pytest.mark.parametrize('change', [dict(time=2**62),dict(orderId=9),dict(symbol='ETHUSDT'),
    dict(qty='0.5',quoteQty='50'),dict(commission=None),dict(isBuyer='false')])
def test_complete_fills_still_required(wire,change):
    wire['fills'][0].update(change)
    with pytest.raises(ValueError,match='^PRIVATE_CAPTURE_FAILED_CLOSED$'): fetch()
    assert len(wire['calls'])==3


@pytest.mark.parametrize('method,url', [('POST',capture.BASE+capture.ORDER),
    ('DELETE',capture.BASE+capture.ORDER),('HEAD',capture.BASE+capture.ORDER),
    ('GET','https://other.example/api/v3/order'),('GET',capture.BASE+'/api/v3/account')])
def test_session_capability(wire,method,url):
    with capture._Session(3) as session:
        with pytest.raises(ValueError): session.request(method,url)
    assert not wire['calls']


def test_expired_budget_stops_network(wire):
    with capture._Session(3) as session:
        session.deadline=time.monotonic()-1
        with pytest.raises(ValueError): session.get(capture.BASE+capture.TIME)
    assert not wire['calls']


def test_request_count_is_a_hard_ceiling(wire):
    with capture._Session(1) as session:
        response=session.get(capture.BASE+capture.TIME); response.close()
        with pytest.raises(ValueError): session.get(capture.BASE+capture.TIME)
        assert session.trust_env is False and session.get_adapter(capture.BASE).max_retries.total==0
    assert len(wire['calls'])==1


@pytest.mark.parametrize('clock', [dict(serverTime=True),dict(serverTime=1),dict(serverTime='123'),
    dict(serverTime=0),dict(serverTime=2**63),dict(code=-1021),b'x'*1025])
def test_clock_gate_before_signed_reads(wire,clock):
    wire['clock']=clock
    with pytest.raises(ValueError,match='^PRIVATE_CAPTURE_FAILED_CLOSED$'): fetch()
    assert len(wire['calls'])==1 and wire['responses'][0].raw.closed


def test_end_to_end_only_ciphertext(case,wire,tmp_path,monkeypatch):
    _,args,public=case
    args['binding']['scope_sha256']=SCOPE
    monkeypatch.setattr(capture,'external_store',lambda root:tmp_path)
    monkeypatch.setattr(export,'external_store',lambda root:tmp_path)
    report=capture.collect_and_export(tmp_path,[('SOLUSDT',8)],credentials=CREDENTIALS,**args)
    token=(tmp_path/'private-fill-export'/'bundle.fernet').read_bytes()
    value=export.open_bundle(token,binding=args['binding'],trusted_public_key=public,encryption_key=args['encryption_key'])
    assert value['records'][0]['scope_sha256']==SCOPE
    assert report['status']=='ENCRYPTED_CLAIMS_ONLY' and not report['private_fills_authenticated']
    assert b'SENTINEL' not in token and b'SOLUSDT' not in token
    before=len(wire['calls'])
    with pytest.raises(ValueError): capture.collect_and_export(tmp_path,[('SOLUSDT',8)],credentials=CREDENTIALS,**args)
    assert len(wire['calls'])==before


def test_wrong_export_key_prevents_network(case,wire,tmp_path,monkeypatch):
    _,args,_=case
    args['encryption_key']=b'SENTINEL'
    monkeypatch.setattr(capture,'external_store',lambda root:tmp_path)
    with pytest.raises(ValueError): capture.collect_and_export(tmp_path,[('SOLUSDT',8)],credentials=CREDENTIALS,**args)
    assert not wire['calls'] and not list(tmp_path.iterdir())


def test_incomplete_collection_creates_no_export(case,wire,tmp_path,monkeypatch):
    _,args,_=case
    args['binding']['scope_sha256']=SCOPE
    wire['fills']=[]
    monkeypatch.setattr(capture,'external_store',lambda root:tmp_path)
    with pytest.raises(ValueError): capture.collect_and_export(tmp_path,[('SOLUSDT',8)],credentials=CREDENTIALS,**args)
    assert not list(tmp_path.iterdir())
