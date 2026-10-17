"""Synthetic encrypted inputs; no operator keys, account files, or API access."""
import base64
import json
from types import SimpleNamespace

import pytest
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

from ladder_dragon.strategy import history_input_contract as contract
from ladder_dragon.strategy import history_input_loader as loader
from ladder_dragon.strategy import history_launcher as launcher
from ladder_dragon.strategy import account_binding as account
from ladder_dragon.strategy import enrollment_registration as registration
from ladder_dragon.strategy.private_fill_capture import credential_scope


def encode(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':')).encode()


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    import requests
    def forbidden(*args,**kwargs):pytest.fail('network access in offline verification')
    monkeypatch.setattr(requests.sessions.Session,'request',forbidden)


@pytest.fixture
def evidence():
    signer=Ed25519PrivateKey.generate()
    public=signer.public_key().public_bytes(Encoding.Raw,PublicFormat.Raw)
    key=Fernet.generate_key()
    claim=registration.claim(12345,'SYNTHETICKEY')
    permissions={k:False for k in account.BOOLEAN_FIELDS}
    permissions.update(enableReading=True,createTime=1)
    payload=dict(schema='history_account_diagnostic_v1',code_sha='2'*40,
        credential_scope=claim['credential_scope'],enrollment_sha256=contract.digest(b'E'*100),
        enrollment_reference=claim['reference'], started_ms=100000,finished_ms=101000,elapsed_ms=1000,
        account_body=base64.b64encode(encode({'uid':12345})).decode(),
        permissions_body=base64.b64encode(encode(permissions)).decode(),clock_checked=True,request_count=3)
    pins=dict(schema='history_launch_inputs_v1',code_sha='1'*40,diagnostic_code_sha='2'*40,
        credential_scope=claim['credential_scope'],enrollment_reference=claim['reference'],
        recipient='age1'+'q'*58,enrollment_sha256=payload['enrollment_sha256'],
        recovery_sha256=contract.digest(b'R'*100),encryption_key_sha256=contract.digest(key),
        diagnostic_sha256='0'*64,diagnostic_signer_sha256=contract.digest(public),diagnostic_public_key=public.hex())
    def signed(value,domain=contract.DOMAIN):
        body=encode(value)
        return encode(dict(body=base64.b64encode(body).decode(),signature=signer.sign(domain+body).hex()))
    return SimpleNamespace(signer=signer,key=key,claim=claim,payload=payload,pins=pins,signed=signed)


def test_exact_signed_claims(evidence):
    e=evidence
    assert contract.verify_diagnostic(e.signed(e.payload),pins=e.pins,enrollment=e.claim,now_ms=102000)


@pytest.mark.parametrize('field,value',[
    ('schema','DIAGNOSTIC_MATCH_ONLY'),('code_sha','3'*40),('credential_scope','0'*64),
    ('enrollment_sha256','0'*64),('enrollment_reference','0'*32),('started_ms',True),
    ('finished_ms',True),('elapsed_ms',True),('elapsed_ms',35001),('elapsed_ms',10),
    ('request_count',True),('request_count',4),('clock_checked',1),('clock_checked',False),
    ('account_body','INVALID'),('permissions_body','INVALID')])
def test_reject_signed_wrong_binding(evidence,field,value):
    e=evidence;e.payload[field]=value
    with pytest.raises(ValueError):
        contract.verify_diagnostic(e.signed(e.payload),pins=e.pins,enrollment=e.claim,now_ms=102000)


@pytest.mark.parametrize('now', [True,100999,401001])
def test_freshness_and_future_rejected(evidence,now):
    e=evidence
    with pytest.raises(ValueError):
        contract.verify_diagnostic(e.signed(e.payload),pins=e.pins,enrollment=e.claim,now_ms=now)


@pytest.mark.parametrize('case',['uid','trade','missing_permission','unknown_permission','summary','wrong_domain'])
def test_recompute_permissions_not_summary(evidence,case):
    e=evidence
    if case=='uid':
        e.payload['account_body']=base64.b64encode(encode({'uid':67890})).decode()
    elif case in ('trade','missing_permission','unknown_permission'):
        p=json.loads(base64.b64decode(e.payload['permissions_body']))
        if case=='trade':p['enableSpotAndMarginTrading']=True
        elif case=='missing_permission':p.pop('enableWithdrawals')
        else:p['newPermission']=False
        e.payload['permissions_body']=base64.b64encode(encode(p)).decode()
    elif case=='summary':e.payload={'status':'DIAGNOSTIC_MATCH_ONLY'}
    from cryptography.exceptions import InvalidSignature
    with pytest.raises((ValueError,InvalidSignature)):
        contract.verify_diagnostic(e.signed(e.payload,b'wrong' if case=='wrong_domain' else contract.DOMAIN),
                                   pins=e.pins,enrollment=e.claim,now_ms=102000)


@pytest.mark.parametrize('damage',['digest','code','public','extra','duplicate'])
def test_manifest_pins(evidence,damage):
    pins=evidence.pins.copy()
    if damage=='code':pins['code_sha']='4'*40
    if damage=='public':pins['diagnostic_public_key']='0'*64
    if damage=='extra':pins['trust_on_first_use']=True
    raw=encode(pins)
    if damage=='duplicate':raw=raw[:-1]+b',"schema":"history_launch_inputs_v1"}'
    with pytest.raises(ValueError):
        contract.manifest(raw,expected_sha256='0'*64 if damage=='digest' else contract.digest(raw),code_sha='1'*40)


@pytest.fixture
def flow(evidence,monkeypatch):
    e=evidence;calls=[]
    diagnostic=Fernet(e.key).encrypt(e.signed(e.payload))
    e.pins['diagnostic_sha256']=contract.digest(diagnostic)
    sources={loader.MANIFEST:encode(e.pins),loader.ENROLLMENT:b'E'*100,
             loader.RECOVERY:b'R'*100,loader.DIAGNOSTIC:diagnostic}
    def read(path,*,maximum,private):
        calls.append(path);assert private is True and len(sources[path])<=maximum
        return sources[path]
    def recover(raw,*,recipient,child_setup):
        assert recipient==e.pins['recipient'] and child_setup=='CHILD_GUARD'
        return registration.encode_claim(e.claim) if raw==sources[loader.ENROLLMENT] else e.key
    monkeypatch.setattr(loader.host,'protected_read',read)
    monkeypatch.setattr(loader.host,'child_setup',lambda:'CHILD_GUARD')
    monkeypatch.setattr(loader.host,'dashboard_key',lambda pin: 'SYNTHETICKEY' if pin==credential_scope('SYNTHETICKEY') else pytest.fail('scope'))
    monkeypatch.setattr(loader.recovery,'recover',recover)
    monkeypatch.setattr(loader.time,'time_ns',lambda:102000*1000000)
    return sources,calls


def verify(flow):
    return loader.verify(expected_manifest_sha256=contract.digest(flow[0][loader.MANIFEST]),code_sha='1'*40)


def test_protected_load_and_actual_decryption(flow):
    assert verify(flow)=='inputs_verified'
    assert flow[1]==[loader.MANIFEST,loader.ENROLLMENT,loader.RECOVERY,loader.DIAGNOSTIC]


@pytest.mark.parametrize('path,stage',[(loader.MANIFEST,'manifest'),(loader.ENROLLMENT,'enrollment'),
    (loader.RECOVERY,'key_recovery'),(loader.DIAGNOSTIC,'diagnostic')])
def test_changed_source_rejected_without_details(flow,path,stage):
    original=contract.digest(flow[0][loader.MANIFEST]);flow[0][path]+=b'PRIVATE_SENTINEL'
    assert loader.verify(expected_manifest_sha256=original,code_sha='1'*40)==stage


@pytest.mark.parametrize('which,stage',[(1,'enrollment'),(2,'key_recovery')])
def test_wrong_recovered_bytes(flow,monkeypatch,which,stage):
    original=loader.recovery.recover;calls=[]
    def recover(*a,**k):
        calls.append(1)
        return b'PRIVATE_SENTINEL' if len(calls)==which else original(*a,**k)
    monkeypatch.setattr(loader.recovery,'recover',recover)
    assert verify(flow)==stage


@pytest.mark.parametrize('source',['protected_read','dashboard_key','child_setup'])
def test_failure_sanitized(flow,monkeypatch,source):
    def fail(*a,**k):raise ValueError('PRIVATE_SENTINEL')
    monkeypatch.setattr(loader.host,source,fail)
    assert verify(flow) in loader.STAGES-{'inputs_verified'}


def test_default_launcher_does_not_load_inputs(monkeypatch):
    monkeypatch.setattr(loader,'verify',lambda **kw:pytest.fail('private input accessed'))
    assert launcher.run({})==launcher.result('authorization')


@pytest.mark.parametrize('case',['cipher','signature','stale','scope'])
def test_loader_rejects_pinned_but_invalid_evidence(evidence,flow,monkeypatch,case):
    e=evidence
    if case=='cipher':flow[0][loader.DIAGNOSTIC]=b'PRIVATE_SENTINEL'
    elif case=='signature':
        envelope=json.loads(e.signed(e.payload));envelope['signature']='0'*128
        flow[0][loader.DIAGNOSTIC]=Fernet(e.key).encrypt(encode(envelope))
    elif case=='stale':monkeypatch.setattr(loader.time,'time_ns',lambda:401001*1000000)
    else:
        def changed(*a):raise ValueError('PRIVATE_SENTINEL')
        monkeypatch.setattr(loader.host,'dashboard_key',changed)
    e.pins['diagnostic_sha256']=contract.digest(flow[0][loader.DIAGNOSTIC])
    flow[0][loader.MANIFEST]=encode(e.pins)
    assert verify(flow)==('credential' if case=='scope' else 'diagnostic')


def test_full_worker_deadline_and_safe_result(monkeypatch):
    def run(argv,**kw):
        assert kw['timeout']==300 and kw['env']=={'PYTHON_DOTENV_DISABLED':'1'}
        return SimpleNamespace(returncode=0,stdout=encode(launcher.result('inputs_verified')))
    monkeypatch.setattr(launcher.subprocess,'run',run)
    result=launcher.run(dict(confirmed=True,expected_code_sha='1'*40,expected_device=123,manifest_sha256='2'*64))
    assert result['status']=='INPUT_CLAIMS_VERIFIED_ONLY'
    assert result['collection_allowed'] is False and result['replay_allowed'] is False
