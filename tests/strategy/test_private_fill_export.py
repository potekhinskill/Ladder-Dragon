import base64
from copy import deepcopy
import hashlib
import json

import pytest
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

from ladder_dragon.strategy import private_fill_export as export
from tests.test_verify_bnb_orders import OrderClient


@pytest.fixture
def case():
    source = OrderClient()
    key = Ed25519PrivateKey.generate()
    public = key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
    encryption_key = Fernet.generate_key()
    binding = dict(scope_sha256='1'*64, registration_sha256='2'*64, code_sha256='3'*64,
                   signer_sha256=hashlib.sha256(public).hexdigest(), collector_id='diagnostic',
                   encryption_key_sha256=hashlib.sha256(encryption_key).hexdigest())
    packet = dict(symbol='SOLUSDT', order_id=8, scope_sha256='1'*64, started_ms=2000,
                  finished_ms=3000, order_body=json.dumps(source.order).encode(),
                  fills_body=json.dumps(source.fills).encode())
    return [packet], dict(binding=binding, signing_key=key, encryption_key=encryption_key), public


def opened(case, token):
    _, args, public = case
    return export.open_bundle(token, binding=args['binding'], encryption_key=args['encryption_key'], trusted_public_key=public)


def test_roundtrip_exact_bytes_and_no_authority(case):
    packets, args, _ = case
    token = export.seal(packets, **args)
    value = opened(case, token)
    for field in ('order_body','fills_body'):
        assert base64.b64decode(value['records'][0][field]) == packets[0][field]
    assert b'SOLUSDT' not in token and packets[0]['fills_body'] not in token
    assert not value['private_fills_authenticated'] and not value['replay_allowed']


@pytest.mark.parametrize('field,value', [('scope_sha256','4'*64),('order_id',9),('order_id',True),
    ('symbol','ETHUSDT'),('started_ms',3001),('finished_ms',999),('finished_ms',True),
    ('finished_ms',40000),('order_body',b'{"secret":"SENTINEL"}'),('fills_body',b'null'),
    ('fills_body',b'x'*65537),('fills_body',b'[{"id":1,"id":2}]')])
def test_invalid_source_packets_fail_without_details(case, field, value):
    packets, args, _ = case
    packets[0][field] = value
    with pytest.raises(ValueError, match='^PRIVATE_EXPORT_INVALID$'):
        export.seal(packets, **args)


@pytest.mark.parametrize('change', [dict(time=3001),dict(time=None),dict(orderId=9),dict(symbol='ETHUSDT'),
    dict(isBuyer='false'),dict(commission=None),dict(qty='0.5',quoteQty='50'),dict(quoteQty='99')])
def test_fill_mutations_share_completeness_boundary(case, change):
    packets, args, _ = case
    fills=json.loads(packets[0]['fills_body']); fills[0].update(change)
    packets[0]['fills_body']=json.dumps(fills).encode()
    with pytest.raises(ValueError): export.seal(packets, **args)


@pytest.mark.parametrize('mode', ['empty','too_many','duplicate','mixed_scope','overlap'])
def test_packet_set_bounds_and_scope(case, mode):
    packets,args,_=case
    second=deepcopy(packets[0]); second['started_ms']=3000; second['finished_ms']=4000
    if mode=='empty': packets=[]
    elif mode=='too_many': packets*=9
    else:
        if mode=='mixed_scope': second['scope_sha256']='5'*64
        if mode=='overlap': second['started_ms']=2999
        packets.append(second)
    with pytest.raises(ValueError): export.seal(packets,**args)


@pytest.mark.parametrize('field', ['scope_sha256','registration_sha256','code_sha256','signer_sha256','collector_id','encryption_key_sha256'])
def test_reader_requires_independent_bindings(case, field):
    packets,args,public=case
    token=export.seal(packets,**args)
    binding=dict(args['binding']); binding[field]='other' if field=='collector_id' else '9'*64
    with pytest.raises(ValueError,match='^PRIVATE_EXPORT_INVALID$'):
        export.open_bundle(token,binding=binding,encryption_key=args['encryption_key'],trusted_public_key=public)


@pytest.mark.parametrize('mode', ['truncate','change','wrong_key','wrong_signer','capacity'])
def test_encryption_integrity_and_key_separation(case,mode):
    packets,args,public=case
    token=export.seal(packets,**args)
    if mode=='truncate': token=token[:-1]
    if mode=='change': token=b'x'+token[1:]
    if mode=='wrong_key': args['encryption_key']=Fernet.generate_key()
    if mode=='wrong_signer': public=b'x'*32
    if mode=='capacity': token=b'x'*(export.MAX_CIPHER+1)
    with pytest.raises(ValueError,match='^PRIVATE_EXPORT_INVALID$'):
        export.open_bundle(token,binding=args['binding'],encryption_key=args['encryption_key'],trusted_public_key=public)


def test_encryption_key_holder_cannot_forge_collector_claim(case):
    packets,args,_=case
    token=export.seal(packets,**args)
    cipher=Fernet(args['encryption_key'])
    envelope=json.loads(cipher.decrypt(token))
    body=json.loads(base64.b64decode(envelope['body']))
    body['replay_allowed']=True
    envelope['body']=base64.b64encode(json.dumps(body).encode()).decode()
    forged=cipher.encrypt(json.dumps(envelope).encode())
    with pytest.raises(ValueError): opened(case,forged)


@pytest.mark.parametrize('mode', ['timestamp','hash','authority','extra'])
def test_reader_revalidates_even_correctly_signed_invalid_claims(case, mode):
    packets,args,_=case
    cipher=Fernet(args['encryption_key'])
    envelope=json.loads(cipher.decrypt(export.seal(packets,**args)))
    body=json.loads(base64.b64decode(envelope['body']))
    if mode=='timestamp': body['records'][0]['finished_ms']=999
    if mode=='hash': body['records'][0]['fills_body_sha256']='0'*64
    if mode=='authority': body['private_fills_authenticated']=True
    if mode=='extra': body['records'][0]['headers']={'secret':'SENTINEL'}
    raw=json.dumps(body).encode()
    envelope['body']=base64.b64encode(raw).decode()
    envelope['signature']=args['signing_key'].sign(export.DOMAIN+raw).hex()
    with pytest.raises(ValueError,match='^PRIVATE_EXPORT_INVALID$'):
        opened(case,cipher.encrypt(json.dumps(envelope).encode()))


@pytest.mark.parametrize('side,status', [('BUY','FILLED'),('SELL','FILLED'),('BUY','CANCELED')])
def test_terminal_sides_and_partial_quantity(case,side,status):
    packets,args,_=case
    order=json.loads(packets[0]['order_body']); order.update(side=side,status=status)
    if status=='CANCELED': order['origQty']='2'
    fills=json.loads(packets[0]['fills_body']); fills[0]['isBuyer']=side=='BUY'
    packets[0].update(order_body=json.dumps(order).encode(),fills_body=json.dumps(fills).encode())
    assert opened(case,export.seal(packets,**args))['records']


def test_exclusive_external_ciphertext_only(case,tmp_path,monkeypatch):
    packets,args,_=case
    monkeypatch.setattr(export,'external_store',lambda root:tmp_path)
    report=export.export(tmp_path,packets,**args)
    path=tmp_path/'private-fill-export'/'bundle.fernet'
    assert list(tmp_path.iterdir())==[path.parent]
    before=path.read_bytes()
    assert b'SOLUSDT' not in before and opened(case,before)['records']
    assert report['status']=='ENCRYPTED_CLAIMS_ONLY'
    with pytest.raises(FileExistsError): export.export(tmp_path,packets,**args)
    assert path.read_bytes()==before


def test_root_device_and_symlink_rejected(case,tmp_path):
    packets,args,_=case
    with pytest.raises(ValueError): export.export(tmp_path,packets,**args)
    assert not list(tmp_path.iterdir())


def test_occupied_symlink_preserves_target(case,tmp_path,monkeypatch):
    packets,args,_=case
    monkeypatch.setattr(export,'external_store',lambda root:tmp_path)
    protected=tmp_path/'protected'; protected.mkdir()
    (tmp_path/'private-fill-export').symlink_to(protected,target_is_directory=True)
    with pytest.raises(FileExistsError): export.export(tmp_path,packets,**args)
    assert not list(protected.iterdir())


def test_failed_flush_retains_only_ciphertext_and_blocks_retry(case,tmp_path,monkeypatch):
    packets,args,_=case
    monkeypatch.setattr(export,'external_store',lambda root:tmp_path)
    def fail(_): raise OSError('synthetic I/O failure')
    monkeypatch.setattr(export.os,'fsync',fail)
    with pytest.raises(OSError): export.export(tmp_path,packets,**args)
    path=tmp_path/'private-fill-export'/'bundle.fernet'
    assert b'SOLUSDT' not in path.read_bytes()
    with pytest.raises(FileExistsError): export.export(tmp_path,packets,**args)


def test_encryption_failure_opens_no_files(case,tmp_path,monkeypatch):
    packets,args,_=case
    args['encryption_key']=b'SENTINEL'
    monkeypatch.setattr(export,'external_store',lambda root:pytest.fail('storage reached'))
    with pytest.raises(ValueError,match='^PRIVATE_EXPORT_INVALID$'): export.export(tmp_path,packets,**args)
    assert not list(tmp_path.iterdir())
