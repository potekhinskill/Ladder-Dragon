"""Offline synthetic enrollment creation, recovery checks, and retention."""

import hashlib
import json
import os
from types import SimpleNamespace
import warnings

import pytest

from ladder_dragon.strategy import enrollment_registration as registration
from ladder_dragon.strategy import enrollment_storage as storage

RECIPIENT = 'age1'+'q'*58
PIN = hashlib.sha256(RECIPIENT.encode()).hexdigest()
CIPHER = b'age-encryption.org/v1\n'+b'x'*120


@pytest.fixture
def value():
    return registration.claim(12345, 'SYNTHETICKEY')


def test_fresh_reference_and_exact_schema(value):
    second=registration.claim(12345,'SYNTHETICKEY')
    assert value['reference']!=second['reference']
    assert len(value['reference'])==32
    assert set(value)=={'schema','reference','uid','credential_scope'}
    assert b'SYNTHETICKEY' not in registration.encode_claim(value)


@pytest.mark.parametrize('uid',[True,False,0,-1,2**63,'12345',None])
def test_invalid_identity(uid):
    with pytest.raises(ValueError):registration.claim(uid,'SYNTHETICKEY')


@pytest.mark.parametrize('inputs',[['12345','12345'],['12345','12346'],['01','01'],
    [' 123',' 123'],['１２３','１２３'],['9223372036854775808']*2,['1.0']*2])
def test_hidden_input_requires_exact_decimal_confirmation(inputs,monkeypatch):
    supplied=iter(inputs)
    monkeypatch.setattr(registration.getpass,'getpass',lambda prompt:next(supplied))
    if inputs==['12345','12345']:
        assert registration.hidden_uid()==12345
    else:
        with pytest.raises(ValueError,match='^ENROLLMENT_INPUT_INVALID$'):registration.hidden_uid()


def test_echo_fallback_refused(monkeypatch):
    def fallback(prompt):
        warnings.warn('SENTINEL',registration.getpass.GetPassWarning)
        pytest.fail('fallback input reached')
    monkeypatch.setattr(registration.getpass,'getpass',fallback)
    with pytest.raises(ValueError,match='^ENROLLMENT_INPUT_INVALID$'):registration.hidden_uid()


def test_encryption_uses_stdin_clean_environment(value,monkeypatch):
    def run(argv,**kwargs):
        assert str(value['uid']) not in repr(argv)
        assert 'SYNTHETICKEY' not in repr(argv)
        assert json.loads(kwargs['input'])==value
        assert kwargs['env']=={} and kwargs['close_fds'] is True
        assert kwargs['stderr']==registration.subprocess.DEVNULL and kwargs['timeout']==5
        return SimpleNamespace(returncode=0,stdout=CIPHER)
    monkeypatch.setattr(registration.subprocess,'run',run)
    assert registration.encrypt_claim(value,recipient=RECIPIENT,expected_recipient_sha256=PIN)==CIPHER


@pytest.mark.parametrize('recipient,pin',[(RECIPIENT,'0'*64),('--help',PIN),('bad',PIN)])
def test_recipient_pin_before_process(value,recipient,pin,monkeypatch):
    monkeypatch.setattr(registration.subprocess,'run',lambda *a,**k:pytest.fail('spawn'))
    with pytest.raises(ValueError,match='^ENROLLMENT_ENCRYPTION_FAILED$'):
        registration.encrypt_claim(value,recipient=recipient,expected_recipient_sha256=pin)


@pytest.mark.parametrize('code,raw',[(1,CIPHER),(0,b'plaintext'),(0,b''),(0,b'x'*16385)])
def test_encryption_output_fail_closed(value,code,raw,monkeypatch):
    monkeypatch.setattr(registration.subprocess,'run',lambda *a,**k:SimpleNamespace(returncode=code,stdout=raw))
    with pytest.raises(ValueError,match='^ENROLLMENT_ENCRYPTION_FAILED$'):
        registration.encrypt_claim(value,recipient=RECIPIENT,expected_recipient_sha256=PIN)


@pytest.mark.parametrize('error',[OSError('SENTINEL'),registration.subprocess.TimeoutExpired('SENTINEL',5)])
def test_encryption_failure_redaction(value,error,monkeypatch):
    def fail(*a,**k):raise error
    monkeypatch.setattr(registration.subprocess,'run',fail)
    with pytest.raises(ValueError,match='^ENROLLMENT_ENCRYPTION_FAILED$'):
        registration.encrypt_claim(value,recipient=RECIPIENT,expected_recipient_sha256=PIN)


@pytest.mark.parametrize('change',[{'uid':True},{'uid':0},{'reference':'x'},
    {'credential_scope':'bad'},{'schema':'wrong'},{'replay_allowed':True}])
def test_claim_validation(value,change):
    value.update(change)
    with pytest.raises(ValueError):registration.encode_claim(value)


def test_recovery_matches_only_exact_reference_and_scope(value):
    raw=registration.encode_claim(value)
    assert registration.verify_recovered(raw,expected_reference=value['reference'],expected_scope=value['credential_scope'])==value
    with pytest.raises(ValueError):
        registration.verify_recovered(raw,expected_reference='0'*32,expected_scope=value['credential_scope'])
    with pytest.raises(ValueError):
        registration.verify_recovered(raw,expected_reference=value['reference'],expected_scope='0'*64)


@pytest.mark.parametrize('raw',[b'{}',b'null',b'x'*4097,b'{"x":NaN}',b'{"x":1,"x":2}',b'{"x":1e999999999999999999999999}'])
def test_recovery_rejects_malformed(raw):
    with pytest.raises(ValueError,match='^ENROLLMENT_RECOVERY_INVALID$'):
        registration.verify_recovered(raw,expected_reference='0'*32,expected_scope='0'*64)


def test_default_refuses_without_encryption_or_storage(value,tmp_path,monkeypatch):
    monkeypatch.setattr(storage,'encrypt_claim',lambda *a,**k:pytest.fail('encrypt'))
    result=storage.create(tmp_path,value,recipient=RECIPIENT,expected_recipient_sha256=PIN)
    assert result['reason']=='AUTHORIZATION_REQUIRED' and not list(tmp_path.iterdir())


def test_only_ciphertext_is_persisted_and_second_run_preserves(value,tmp_path,monkeypatch):
    monkeypatch.setattr(storage,'external_store',lambda root:tmp_path)
    monkeypatch.setattr(storage,'encrypt_claim',lambda *a,**k:CIPHER)
    result=storage.create(tmp_path,value,recipient=RECIPIENT,expected_recipient_sha256=PIN,confirmed=True)
    assert result['status']=='ENCRYPTED_ENROLLMENT_CLAIM'
    assert result['reference']==value['reference'] and str(value['uid']) not in repr(result)
    assert not any(result[k] for k in ('recovery_verified','account_authenticated','private_fills_authenticated','replay_allowed'))
    path=tmp_path/storage.SLOT/storage.FILE
    assert path.read_bytes()==CIPHER
    assert list(path.parent.iterdir())==[path]
    assert storage.create(tmp_path,value,recipient=RECIPIENT,expected_recipient_sha256=PIN,confirmed=True)['status']=='BLOCKED'
    assert path.read_bytes()==CIPHER


def test_interrupted_ciphertext_is_preserved(value,tmp_path,monkeypatch):
    monkeypatch.setattr(storage,'external_store',lambda root:tmp_path)
    directory=storage.reserve(tmp_path)
    def fail(fd):raise OSError('SENTINEL')
    monkeypatch.setattr(storage.os,'fsync',fail)
    try:
        with pytest.raises(OSError):storage.store(directory,CIPHER)
    finally:os.close(directory)
    assert (tmp_path/storage.SLOT/storage.FILE).read_bytes()==CIPHER
    with pytest.raises(FileExistsError):storage.reserve(tmp_path)


def test_symlink_slot_preserved(tmp_path,monkeypatch):
    monkeypatch.setattr(storage,'external_store',lambda root:tmp_path)
    target=tmp_path/'untouched';target.mkdir()
    (tmp_path/storage.SLOT).symlink_to(target)
    with pytest.raises(FileExistsError):storage.reserve(tmp_path)
    assert not list(target.iterdir())


def test_group_writable_parent_rejected(tmp_path,monkeypatch):
    monkeypatch.setattr(storage,'external_store',lambda root:tmp_path)
    tmp_path.chmod(0o770)
    with pytest.raises(ValueError):storage.reserve(tmp_path)
    assert not list(tmp_path.iterdir())


def test_error_result_never_contains_input(value,tmp_path,monkeypatch):
    def fail(*a,**k):raise ValueError('SENTINEL '+str(value['uid']))
    monkeypatch.setattr(storage,'encrypt_claim',fail)
    result=storage.create(tmp_path,value,recipient=RECIPIENT,expected_recipient_sha256=PIN,confirmed=True)
    assert result['stage']=='encryption' and 'SENTINEL' not in repr(result)
    assert str(value['uid']) not in repr(result) and not list(tmp_path.iterdir())


def test_caller_mutation_cannot_change_stored_reference(value,tmp_path,monkeypatch):
    reference=value['reference']
    monkeypatch.setattr(storage,'external_store',lambda root:tmp_path)
    def encrypt(frozen,**kwargs):
        value['reference']='SENTINEL'
        assert frozen['reference']==reference
        return CIPHER
    monkeypatch.setattr(storage,'encrypt_claim',encrypt)
    result=storage.create(tmp_path,value,recipient=RECIPIENT,expected_recipient_sha256=PIN,confirmed=True)
    assert result['reference']==reference and 'SENTINEL' not in repr(result)
