"""Synthetic subprocesses and private fixtures; no production access."""
from contextlib import contextmanager
import io
import json
import os
import subprocess
import time

import pytest
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives.serialization import Encoding, PrivateFormat, NoEncryption

from ladder_dragon.strategy import diagnostic_launch as launch
from ladder_dragon.strategy import diagnostic_launch_worker as worker
from ladder_dragon.strategy import history_input_contract as contract
from tests.strategy.test_diagnostic_package import setup, enrollment, wire


@pytest.fixture
def value():
    return dict(confirmed=True, expected_code_sha='a'*40, expected_device=123, manifest_sha256='b'*64)


@pytest.fixture
def private(setup, enrollment, tmp_path, monkeypatch):
    raw_enrollment = json.dumps(enrollment[1]).encode()
    enrollment_cipher, recovery_cipher = b'E'*100, b'R'*100
    pins = dict(setup['pins'], schema='diagnostic_launch_v1', code_sha='a'*40,
                recipient='age1'+'q'*58, recovery_sha256=contract.digest(recovery_cipher))
    pins['enrollment_sha256'] = contract.digest(enrollment_cipher)
    raw_manifest = json.dumps(pins).encode()
    data = {worker.MANIFEST: raw_manifest, worker.locations.ENROLLMENT: enrollment_cipher,
            worker.locations.RECOVERY: recovery_cipher,
            worker.SIGNER: setup['signer'].private_bytes(Encoding.PEM, PrivateFormat.PKCS8, NoEncryption()),
            worker.host.CREDENTIAL: b'DASHBOARD_BINANCE_API_KEY=SENTINELKEY\nDASHBOARD_BINANCE_API_SECRET=SENTINELSECRET\n'}
    monkeypatch.setattr(worker.host, 'protected_read', lambda path, **kw: data[path])
    monkeypatch.setattr(worker.host, 'child_setup', lambda: lambda: None)
    def recover(cipher, **kwargs):
        return raw_enrollment if cipher == enrollment_cipher else setup['encryption_key']
    monkeypatch.setattr(worker.recovery, 'recover', recover)
    folder = tmp_path / 'destination'; folder.mkdir(mode=0o700)
    monkeypatch.setattr(worker.storage, 'ROOT', folder.parent)
    monkeypatch.setattr(worker.storage, 'DIRECTORY', folder.name)
    monkeypatch.setattr(os.path, 'ismount', lambda path: path == folder.parent)
    @contextmanager
    def reserve(device):
        directory = os.open(folder, os.O_RDONLY | os.O_DIRECTORY)
        fd = None
        try:
            fd = os.open(worker.storage.NAME, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600, dir_fd=directory)
            yield directory, fd
        finally:
            if fd is not None: os.close(fd)
            os.close(directory)
    monkeypatch.setattr(worker.storage, 'reserve', reserve)
    monkeypatch.setattr(launch.preparation, 'prepare', lambda *args: launch.preparation.result('complete'))
    options = dict(confirmed=True, expected_code_sha='a'*40, expected_device=folder.stat().st_dev,
                   manifest_sha256=contract.digest(raw_manifest))
    return options, data, folder / worker.storage.NAME, pins


def test_protected_worker_to_saved_verifier(private, setup, enrollment, wire):
    value, data, destination, pins = private
    calls = []
    def begin():
        assert destination.exists() and destination.stat().st_size == 0
        assert not wire['calls']
        calls.append('barrier')
    result = worker.execute(value, begin)
    assert result['status'] == 'DIAGNOSTIC_SAVED_ONLY' and calls == ['barrier']
    cipher = destination.read_bytes()
    assert result['ciphertext_sha256'] == contract.digest(cipher)
    assert result['bytes'] == len(cipher)
    assert contract.verify_diagnostic(Fernet(setup['encryption_key']).decrypt(cipher), pins=pins,
                                      enrollment=enrollment[1], now_ms=time.time_ns()//1_000_000)
    assert len(wire['calls']) == 3 and 'SENTINEL' not in repr(result)
    assert '123456789' not in repr(result)
    result = worker.execute(value, lambda: pytest.fail('repeat network'))
    assert result['stage'] == 'storage' and destination.read_bytes() == cipher
    assert len(wire['calls']) == 3


@pytest.mark.parametrize('failure,stage', [('manifest','manifest'), ('enrollment','enrollment'),
    ('recovery','key_recovery'), ('signer','signer'), ('credential','credential'),
    ('duplicate','credential'), ('recheck','halt'), ('barrier','requests')])
def test_private_failures_before_network(private, wire, monkeypatch, failure, stage):
    value, data, destination, _ = private
    begin = lambda: pytest.fail('unexpected barrier')
    if failure == 'manifest': value['manifest_sha256'] = '0'*64
    elif failure == 'enrollment': data[worker.locations.ENROLLMENT] = b'bad'
    elif failure == 'recovery': data[worker.locations.RECOVERY] = b'bad'
    elif failure == 'signer': data[worker.SIGNER] = b'SENTINEL'
    elif failure == 'credential': data[worker.host.CREDENTIAL] = b'DASHBOARD_BINANCE_API_KEY=OTHER\n'
    elif failure == 'duplicate': data[worker.host.CREDENTIAL] += b'DASHBOARD_BINANCE_API_KEY=SENTINELKEY\n'
    elif failure == 'recheck':
        monkeypatch.setattr(launch.preparation, 'prepare', lambda *args: launch.preparation.result('halt'))
    else:
        def begin(): raise ValueError('SENTINEL')
    result = worker.execute(value, begin)
    assert result['stage'] == stage and result['status'] == 'BLOCKED'
    assert not wire['calls'] and 'SENTINEL' not in repr(result)
    if failure != 'manifest': assert destination.read_bytes() == b''


def test_request_failure_keeps_empty_slot(private, wire):
    wire['status'] = 429
    result = worker.execute(private[0], lambda: None)
    assert result['status'] == 'BLOCKED'
    assert private[2].read_bytes() == b'' and len(wire['calls']) == 1


@pytest.mark.parametrize('kind', ['enrollment', 'key'])
def test_recovery_mismatch_prevents_requests(private, wire, monkeypatch, kind):
    original = worker.recovery.recover
    def damaged(cipher, **kwargs):
        raw = original(cipher, **kwargs)
        if kind == 'enrollment' and cipher == b'E'*100:
            value = json.loads(raw); value['reference'] = '0'*32
            return json.dumps(value).encode()
        if kind == 'key' and cipher == b'R'*100: return Fernet.generate_key()
        return raw
    monkeypatch.setattr(worker.recovery, 'recover', damaged)
    result = worker.execute(private[0], lambda: pytest.fail('barrier'))
    assert result['stage'] == ('enrollment' if kind == 'enrollment' else 'key_recovery')
    assert not wire['calls'] and private[2].read_bytes() == b''


def test_manifest_has_no_self_attested_output(private):
    value, data, _, pins = private
    for changed in (dict(pins, diagnostic_sha256='0'*64), dict(pins, diagnostic_code_sha='c'*40)):
        raw = json.dumps(changed).encode()
        with pytest.raises(ValueError): worker.manifest(raw, contract.digest(raw), value['expected_code_sha'])


def test_no_opt_in_no_process(monkeypatch):
    monkeypatch.setattr(subprocess, 'Popen', lambda *a, **k: pytest.fail('started'))
    assert launch.run({}) == launch.report('authorization')


@pytest.mark.parametrize('field,bad', [('confirmed',1), ('expected_device',True),
    ('expected_code_sha','invalid'), ('manifest_sha256','invalid')])
def test_invalid_options_no_process(value, monkeypatch, field, bad):
    monkeypatch.setattr(subprocess, 'Popen', lambda *a, **k: pytest.fail('started'))
    value[field] = bad
    assert launch.run(value)['status'] == 'BLOCKED'


@pytest.mark.parametrize('field', ['collection_allowed', 'history_complete', 'private_fills_authenticated', 'replay_allowed'])
@pytest.mark.parametrize('bad', [True, 0, None])
def test_safe_output_rejects_authority(field, bad):
    value = launch.report('complete', bytes=10, ciphertext_sha256='a'*64)
    value[field] = bad
    assert launch.safe_result(json.dumps(value).encode()) == launch.report('process')


def test_real_child_timeout_kills_and_reaps(value, monkeypatch):
    monkeypatch.setattr(launch, 'REQUEST_SECONDS', 0.1)
    monkeypatch.setattr(launch, 'WORKER', '''
import sys, time
sys.stdin.readline()
print('{"stage":"requests"}', flush=True)
assert sys.stdin.readline() == 'GO\\n'
time.sleep(20)
''')
    actual = subprocess.Popen
    processes = []
    def spawn(argv, **kwargs):
        assert argv[1] == '-I' and kwargs['env'] == {'PYTHON_DOTENV_DISABLED':'1'}
        assert kwargs['cwd'] == '/' and kwargs['close_fds'] is True
        process = actual(argv, **kwargs); processes.append(process); return process
    monkeypatch.setattr(subprocess, 'Popen', spawn)
    assert launch.run(value) == launch.report('deadline')
    assert processes[0].poll() is not None
    with pytest.raises(ChildProcessError): os.waitpid(processes[0].pid, os.WNOHANG)


def test_real_child_success_requires_acknowledgement(value, monkeypatch):
    final = launch.report('complete', bytes=10, ciphertext_sha256='a'*64)
    script = '''
import sys
sys.stdin.readline()
print('{"stage":"requests"}', flush=True)
assert sys.stdin.readline() == 'GO\\n'
'''
    monkeypatch.setattr(launch, 'WORKER', script+'print('+repr(json.dumps(final))+', flush=True)')
    assert launch.run(value) == final


@pytest.mark.parametrize('kind', ['preparation_timeout', 'duplicate_barrier', 'oversize', 'private_text', 'early_success', 'after_final'])
def test_real_child_protocol_refusals(value, monkeypatch, kind):
    final = json.dumps(launch.report('complete', bytes=10, ciphertext_sha256='a'*64))
    if kind == 'preparation_timeout':
        monkeypatch.setattr(launch, 'PREPARATION_SECONDS', 0.1)
        script = 'import time; time.sleep(20)'
    elif kind == 'duplicate_barrier':
        script = 'print(\'{"stage":"requests"}\', flush=True); sys.stdin.readline(); print(\'{"stage":"requests"}\', flush=True)'
    elif kind == 'oversize': script = "print('X'*3000, flush=True)"
    elif kind == 'private_text': script = "print('SENTINEL', flush=True)"
    elif kind == 'early_success': script = 'print('+repr(final)+', flush=True)'
    else: script = 'print('+repr(json.dumps(launch.report('input')))+', flush=True); print("extra", flush=True)'
    monkeypatch.setattr(launch, 'WORKER', 'import sys\nsys.stdin.readline()\n'+script)
    result = launch.run(value)
    assert result == launch.report('deadline' if kind == 'preparation_timeout' else 'process')


def test_worker_host_failure_no_private_access(value, monkeypatch, capsys):
    monkeypatch.setattr(launch.sys, 'stdin', io.TextIOWrapper(io.BytesIO(json.dumps(value).encode()+b'\n')))
    monkeypatch.setattr(launch.preparation, 'prepare', lambda *args: launch.preparation.result('host'))
    monkeypatch.setattr(worker, 'execute', lambda *a: pytest.fail('private input'))
    launch.worker(123)
    assert json.loads(capsys.readouterr().out) == launch.report('host')
