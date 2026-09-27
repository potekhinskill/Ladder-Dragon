"""Synthetic operator flow; no production input, filesystem, or exchange access."""

import io
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from types import SimpleNamespace

import pytest

from ladder_dragon.strategy import enrollment_operator as op, enrollment_host as host
from ladder_dragon.strategy import enrollment_registration as reg, enrollment_storage as storage
from ladder_dragon.strategy import enrollment_recovery as recovery
from tests.strategy.test_enrollment_registration import RECIPIENT, PIN, CIPHER

ROOT=Path(__file__).resolve().parents[2]


@pytest.fixture
def options():
    return dict(mode='create',confirmed=True,expected_code_sha='1'*40,
        expected_scope=reg.credential_scope('SYNTHETICKEY'),recipient=RECIPIENT,
        recipient_sha256=PIN,reference=None,ciphertext_sha256=None)


@pytest.fixture
def flow(options,tmp_path,monkeypatch):
    calls=[];claim=reg.claim(12345,'SYNTHETICKEY')
    monkeypatch.setattr(host,'EXTERNAL',tmp_path)
    monkeypatch.setattr(host,'harden',lambda parent:calls.append('host'))
    monkeypatch.setattr(host,'child_setup',lambda:None)
    monkeypatch.setattr(host,'check_revision',lambda sha:calls.append('revision'))
    monkeypatch.setattr(storage,'external_store',lambda root:tmp_path)
    monkeypatch.setattr(host,'dashboard_key',lambda scope:calls.append('credential') or 'SYNTHETICKEY')
    monkeypatch.setattr(reg,'hidden_uid',lambda:calls.append('uid') or 12345)
    monkeypatch.setattr(reg,'claim',lambda *a:dict(claim))
    monkeypatch.setattr(reg,'encrypt_claim',lambda *a,**k:calls.append('encrypt') or CIPHER)
    monkeypatch.setattr(recovery,'recover',lambda *a,**k:calls.append('recovery') or reg.encode_claim(claim))
    return calls,claim,tmp_path


def test_create_recovers_before_storage(options,flow):
    calls,claim,tmp=flow
    result=op.operate(options)
    assert calls==['host','revision','credential','uid','encrypt','recovery']
    assert result['status']=='RECOVERY_VERIFIED_CLAIM' and result['recovery_verified'] is True
    assert result['reference']==claim['reference']
    assert not any(result[k] for k in op.FALSE_FIELDS)
    assert (tmp/storage.SLOT/storage.FILE).read_bytes()==CIPHER
    assert len(list(tmp.rglob('*')))==2


@pytest.mark.parametrize('target,name,stage',[(host,'harden','host'),(host,'check_revision','revision'),
    (host,'dashboard_key','credential'),(reg,'hidden_uid','identity'),
    (reg,'encrypt_claim','encryption'),(recovery,'recover','recovery')])
def test_failure_stops_before_storage(options,flow,monkeypatch,target,name,stage):
    def fail(*a,**k):raise ValueError('SENTINEL')
    monkeypatch.setattr(target,name,fail)
    result=op.operate(options)
    assert result==op.blocked(stage)
    assert not list(flow[2].iterdir()) and 'SENTINEL' not in repr(result)
    if stage in ('host','revision','credential'):assert 'uid' not in flow[0]


def test_changed_recovered_identity_rejected(options,flow,monkeypatch):
    bad=dict(flow[1],uid=12346)
    monkeypatch.setattr(recovery,'recover',lambda *a,**k:reg.encode_claim(bad))
    assert op.operate(options)==op.blocked('recovery')
    assert not list(flow[2].iterdir())


def test_occupied_slot_rejects_before_private_input(options,flow):
    (flow[2]/storage.SLOT).mkdir()
    assert op.operate(options)==op.blocked('storage')
    assert flow[0]==['host','revision']


def test_verify_requires_pinned_ciphertext_and_reference(options,flow,monkeypatch):
    first=op.operate(options);flow[0].clear()
    options.update(mode='verify',reference=first['reference'],ciphertext_sha256=first['ciphertext_sha256'])
    monkeypatch.setattr(host,'protected_read',lambda *a,**k:CIPHER)
    assert op.operate(options)['recovery_verified'] is True
    assert flow[0]==['host','revision','credential','recovery']
    options['ciphertext_sha256']='0'*64;flow[0].clear()
    assert op.operate(options)==op.blocked('storage')
    assert flow[0]==['host','revision']


def test_verify_stale_reference_rejected(options,flow,monkeypatch):
    first=op.operate(options)
    options.update(mode='verify',reference='0'*32,ciphertext_sha256=first['ciphertext_sha256'])
    monkeypatch.setattr(host,'protected_read',lambda *a,**k:CIPHER)
    assert op.operate(options)==op.blocked('recovery')
    assert (flow[2]/storage.SLOT/storage.FILE).read_bytes()==CIPHER


@pytest.mark.parametrize('change',[dict(confirmed=False),dict(expected_code_sha='bad'),dict(expected_scope='bad'),
    dict(recipient_sha256='0'*64),dict(reference='0'*32),dict(mode='verify'),dict(extra='bad')])
def test_invalid_options_no_spawn(options,change,monkeypatch):
    options.update(change)
    monkeypatch.setattr(op.subprocess,'run',lambda *a,**k:pytest.fail('spawn'))
    assert op.run(options)['status']=='BLOCKED'


def test_clean_process_contract(options,monkeypatch):
    def execute(argv,**kwargs):
        assert argv[1:3]==['-I','-c'] and argv[-1]==str(os.getpid())
        assert kwargs['env']=={'PYTHON_DOTENV_DISABLED':'1'} and kwargs['close_fds'] is True
        assert kwargs['stderr']==subprocess.DEVNULL and kwargs['timeout']==300
        assert json.loads(kwargs['input'])==options
        return SimpleNamespace(returncode=0,stdout=json.dumps(op.blocked('host')).encode())
    monkeypatch.setattr(op.subprocess,'run',execute)
    assert op.run(options)==op.blocked('host')


def test_real_worker_rejects_nonproduction_host(options):
    result=op.run(options)
    assert result['status']=='BLOCKED' and result['stage'] in {'host','revision'}


def test_real_timeout_reaps_without_private_input(options,monkeypatch):
    original=subprocess.run;children=[];popen=subprocess.Popen
    def track(*args,**kwargs):
        child=popen(*args,**kwargs);children.append(child);return child
    def short(*args,**kwargs):
        kwargs['timeout']=1
        return original(*args,**kwargs)
    monkeypatch.setattr(op,'_WORKER','import time; time.sleep(60)')
    monkeypatch.setattr(subprocess,'Popen',track)
    monkeypatch.setattr(subprocess,'run',short)
    started=time.monotonic()
    assert op.run(options)==op.blocked('process')
    assert time.monotonic()-started<5
    assert len(children)==1 and children[0].poll() is not None
    with pytest.raises(ChildProcessError):os.waitpid(children[0].pid,os.WNOHANG)


@pytest.mark.parametrize('raw',[b'{}',b'null',b'x'*1025,b'{"x":NaN}',b'{"x":1e9999999999999999999999}'])
def test_invalid_worker_output(raw):
    assert op.safe_result(raw)==op.blocked('process')


@pytest.mark.parametrize('change',[dict(stage='SENTINEL'),dict(uid=12345),dict(replay_allowed=True),
    dict(recovery_verified=True),dict(account_authenticated=0)])
def test_worker_output_cannot_leak_or_escalate(change):
    value=op.blocked('host');value.update(change)
    assert op.safe_result(json.dumps(value).encode())==op.blocked('process')


def test_worker_bad_input_never_operates(monkeypatch):
    output=io.StringIO()
    monkeypatch.setattr(op.sys,'stdin',SimpleNamespace(buffer=io.BytesIO(b'x'*4097)))
    monkeypatch.setattr(op.sys,'stdout',output)
    monkeypatch.setattr(op,'operate',lambda *a,**k:pytest.fail('operate'))
    op.worker()
    assert json.loads(output.getvalue())==op.blocked('input')


def test_cli_default_and_bad_arguments_are_private(capsys):
    assert op.main([])==2
    assert json.loads(capsys.readouterr().out)==op.blocked('authorization')
    assert op.main(['--uid','SENTINEL'])==2
    captured=capsys.readouterr()
    assert 'SENTINEL' not in captured.out+captured.err


def test_registered_cli_help_is_offline():
    result=subprocess.run([sys.executable,'-m','bin.account_enrollment','--help'],cwd=ROOT,
        env={**os.environ,'PYTHON_DOTENV_DISABLED':'1'},capture_output=True,text=True,timeout=10)
    assert result.returncode==0 and '--recipient-sha256' in result.stdout
