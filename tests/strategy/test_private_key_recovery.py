import hashlib
import subprocess
from types import SimpleNamespace

import pytest
from cryptography.fernet import Fernet

from ladder_dragon.strategy import private_key_recovery as recovery
from ladder_dragon.strategy import private_fill_capture as capture
from tests.strategy.test_private_fill_capture import wire, fetch

RECIPIENT = 'age1'+'q'*58
PIN = hashlib.sha256(RECIPIENT.encode()).hexdigest()
CIPHER = b'age-encryption.org/v1\n'+b'x'*120


def test_key_only_on_stdin_and_no_parent_environment(monkeypatch):
    key=Fernet.generate_key(); seen=[]
    def run(args,**kwargs):
        seen.append((args,kwargs))
        return SimpleNamespace(returncode=0,stdout=CIPHER)
    monkeypatch.setattr(recovery.subprocess,'run',run)
    assert recovery.wrap_key(key,recipient=RECIPIENT,expected_recipient_sha256=PIN)==CIPHER
    args,options=seen[0]
    assert key.decode() not in repr(args)
    assert options['input']==key and options['env']=={} and options['close_fds'] is True
    assert options['stderr']==subprocess.DEVNULL and options['timeout']==5


@pytest.mark.parametrize('recipient,pin',[(RECIPIENT,'0'*64),('age1bad',PIN),('--help',PIN)])
def test_recipient_rejected_before_process(monkeypatch,recipient,pin):
    monkeypatch.setattr(recovery.subprocess,'run',lambda *a,**k:pytest.fail('process'))
    with pytest.raises(ValueError,match='^PRIVATE_KEY_RECOVERY_FAILED$'):
        recovery.wrap_key(Fernet.generate_key(),recipient=recipient,expected_recipient_sha256=pin)


@pytest.mark.parametrize('code,raw',[(1,CIPHER),(0,b'plaintext'),(0,b'x'*16385),(0,b'')])
def test_invalid_output_rejected(monkeypatch,code,raw):
    monkeypatch.setattr(recovery.subprocess,'run',lambda *a,**k:SimpleNamespace(returncode=code,stdout=raw))
    with pytest.raises(ValueError,match='^PRIVATE_KEY_RECOVERY_FAILED$'):
        recovery.wrap_key(Fernet.generate_key(),recipient=RECIPIENT,expected_recipient_sha256=PIN)


@pytest.mark.parametrize('error',[subprocess.TimeoutExpired('SENTINEL',5),OSError('SENTINEL')])
def test_process_errors_do_not_leak(monkeypatch,error):
    def fail(*args,**kwargs): raise error
    monkeypatch.setattr(recovery.subprocess,'run',fail)
    with pytest.raises(ValueError,match='^PRIVATE_KEY_RECOVERY_FAILED$'):
        recovery.wrap_key(Fernet.generate_key(),recipient=RECIPIENT,expected_recipient_sha256=PIN)


@pytest.mark.parametrize('stage', ['clock','order','fills','validation'])
def test_capture_failure_has_safe_stage(wire,stage):
    if stage=='clock': wire['status']=500
    if stage=='order': wire['order']={}
    if stage=='fills': wire['fills']=b'not json SENTINEL'
    if stage=='validation': wire['fills']=[]
    with pytest.raises(capture.CaptureFailure) as error: fetch()
    assert error.value.stage==stage and str(error.value)=='PRIVATE_CAPTURE_FAILED_CLOSED'


@pytest.mark.parametrize('status',[403,429,500])
def test_http_failure_retains_only_numeric_status(wire,status):
    wire['status']=status
    with pytest.raises(capture.CaptureFailure) as error: fetch()
    assert error.value.reason=='HTTP_STATUS' and error.value.http_status==status


def test_clock_failure_has_fixed_reason(wire):
    wire['clock']={'serverTime':1}
    with pytest.raises(capture.CaptureFailure) as error: fetch()
    assert error.value.reason=='CLOCK_INVALID'


@pytest.mark.parametrize('kind,reason',[('timeout','TIMEOUT'),('tls','TLS')])
def test_transport_cause_does_not_leak(wire,kind,reason):
    import requests
    wire['failure']=requests.Timeout('SENTINEL') if kind=='timeout' else requests.exceptions.SSLError('SENTINEL')
    with pytest.raises(capture.CaptureFailure) as error: fetch()
    assert error.value.reason==reason and error.value.http_status is None
    assert 'SENTINEL' not in str(error.value) and error.value.__suppress_context__
