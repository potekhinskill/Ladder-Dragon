import json
import os
import subprocess
import time

import pytest

from ladder_dragon.strategy import account_diagnostic_process as process


def args():
    return dict(enrollment_path='/nonexistent/ladder-dragon-synthetic/identity.json',
                expected_reference='a'*32, credentials=('SENTINELKEY','SENTINELSECRET'),
                confirmed=True)


def matched():
    return dict(status='DIAGNOSTIC_MATCH_ONLY', stage='validation', reason='MATCH',
                account_authenticated=False, private_fills_authenticated=False, replay_allowed=False)


def test_clean_process_boundary_and_pipe(monkeypatch):
    calls=[]
    def run(command,**options):
        calls.append((command,options))
        return subprocess.CompletedProcess(command,0,json.dumps(matched()).encode())
    monkeypatch.setattr(subprocess,'run',run)
    assert process.run_isolated_diagnostic(**args()) == matched()
    command,options = calls[0]
    assert command[1] == '-I' and 'SENTINEL' not in repr(command)
    assert options['env'] == {'PYTHON_DOTENV_DISABLED':'1'}
    assert options['stderr'] == subprocess.DEVNULL and options['close_fds'] is True
    assert options['cwd'] == '/' and options['timeout'] == 35
    assert json.loads(options['input'])['credentials'] == ['SENTINELKEY','SENTINELSECRET']


@pytest.mark.parametrize('confirmed',[False,None,1,'YES'])
def test_confirmation_before_spawn(monkeypatch,confirmed):
    monkeypatch.setattr(subprocess,'run',lambda *a,**k: pytest.fail('spawned'))
    values=args(); values['confirmed']=confirmed
    assert process.run_isolated_diagnostic(**values)['reason']=='AUTHORIZATION_REQUIRED'


@pytest.mark.parametrize('deadline',[0,-1,36,True,'35',1.5])
def test_deadline_validation(monkeypatch,deadline):
    monkeypatch.setattr(subprocess,'run',lambda *a,**k: pytest.fail('spawned'))
    assert process.run_isolated_diagnostic(**args(),deadline_sec=deadline)['reason']=='DEADLINE_INVALID'


@pytest.mark.parametrize('raw',[b'',b'[]',b'{}',b'null',b'\xff',b'x'*1025,
    b'{"status":"SENTINEL"}',b'{"x":1e9999999999999999999999999}',
    b'{"x":0,"x":0}',b'['*500+b']'*500])
def test_worker_output_invalid_and_secret_safe(monkeypatch,raw):
    monkeypatch.setattr(subprocess,'run',lambda *a,**k: subprocess.CompletedProcess([],0,raw))
    result=process.run_isolated_diagnostic(**args())
    assert result['status']=='BLOCKED' and 'SENTINEL' not in repr(result)


@pytest.mark.parametrize('key,value',[
    ('account_authenticated',True),('private_fills_authenticated',True),('replay_allowed',True),
    ('replay_allowed',0),('stage','SENTINEL'),('reason','SENTINEL'),('uid',123456789),
    ('status','PASS'),('stage',[]),('reason',{}),
])
def test_child_cannot_grant_authority(monkeypatch,key,value):
    report=matched();report[key]=value
    monkeypatch.setattr(subprocess,'run',lambda *a,**k: subprocess.CompletedProcess([],0,json.dumps(report).encode()))
    result=process.run_isolated_diagnostic(**args())
    assert result['status']=='BLOCKED' and 'SENTINEL' not in repr(result)


def test_nonzero_exit_blocks_even_valid_payload(monkeypatch):
    monkeypatch.setattr(subprocess,'run',lambda *a,**k: subprocess.CompletedProcess([],1,json.dumps(matched()).encode()))
    assert process.run_isolated_diagnostic(**args())['reason']=='WORKER_FAILED'


def test_actual_isolated_child_rejects_missing_enrollment():
    result=process.run_isolated_diagnostic(**args(),deadline_sec=10)
    assert result['status']=='BLOCKED' and result['stage']=='enrollment'
    assert 'SENTINEL' not in repr(result)


def test_actual_stalled_child_is_killed_and_reaped(monkeypatch):
    # The replacement is synthetic code, not a live diagnostic or DNS request.
    monkeypatch.setattr(process,'_WORKER','import time; time.sleep(60)')
    original=subprocess.Popen; children=[]
    def record(*a,**k):
        child=original(*a,**k);children.append(child);return child
    monkeypatch.setattr(subprocess,'Popen',record)
    started=time.monotonic()
    result=process.run_isolated_diagnostic(**args(),deadline_sec=1)
    assert result['reason']=='PROCESS_DEADLINE' and time.monotonic()-started<10
    assert len(children)==1 and children[0].returncode is not None
    with pytest.raises(ChildProcessError):os.waitpid(children[0].pid,os.WNOHANG)


def test_timeout_does_not_echo_partial_output_or_retry(monkeypatch):
    calls=[]
    def fail(*a,**k):
        calls.append(1)
        raise subprocess.TimeoutExpired('SENTINEL',1,output=b'SENTINEL',stderr=b'SENTINEL')
    monkeypatch.setattr(subprocess,'run',fail)
    result=process.run_isolated_diagnostic(**args())
    assert result['reason']=='PROCESS_DEADLINE' and 'SENTINEL' not in repr(result)
    assert len(calls)==1


@pytest.mark.parametrize('key,value',[('enrollment_path','relative'),('expected_reference','bad'),
    ('credentials',('SENTINELKEY','')),('credentials',['SENTINELKEY','SENTINELSECRET'])])
def test_input_validation_before_process(monkeypatch,key,value):
    monkeypatch.setattr(subprocess,'run',lambda *a,**k: pytest.fail('spawned'))
    values=args();values[key]=value
    assert process.run_isolated_diagnostic(**values)['status']=='BLOCKED'
