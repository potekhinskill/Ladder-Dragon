"""Synthetic private-process protocol and secret-boundary regressions."""

import io
import json
from types import SimpleNamespace

import pytest

from ladder_dragon.strategy import history_capture_process as process
from ladder_dragon.strategy import history_process_contract as contract
from tests.strategy.test_history_collection import case


def arguments(case):
    return dict(credentials=('SYNTHETICKEY', 'SYNTHETICSECRET'), **case[2])


def test_anonymous_input_and_clean_environment(case, monkeypatch):
    monkeypatch.setenv('BINANCE_SECRET', 'INHERITED_SENTINEL')
    def execute(argv, **kwargs):
        assert argv[1:3] == ['-I', '-c']
        assert 'SYNTHETIC' not in repr(argv)
        assert kwargs['env'] == {'PYTHON_DOTENV_DISABLED': '1'}
        assert kwargs['close_fds'] is True and kwargs['cwd'] == '/'
        assert kwargs['stderr'] == process.subprocess.DEVNULL
        assert kwargs['timeout'] == 150
        root, private = contract.parse_request(kwargs['input'])
        assert root == '/unused' and private['credentials'] == arguments(case)['credentials']
        assert b'INHERITED_SENTINEL' not in kwargs['input']
        return SimpleNamespace(returncode=0, stdout=json.dumps(contract.blocked('IO')).encode())
    monkeypatch.setattr(process.subprocess, 'run', execute)
    assert process.run('/unused', authorized=True, **arguments(case))['reason'] == 'IO'


@pytest.mark.parametrize('deadline', [0, 151, True, 1.5, '35', None])
def test_invalid_deadline_does_not_start(deadline, monkeypatch):
    monkeypatch.setattr(process.subprocess, 'run', lambda *a, **k: pytest.fail('spawn'))
    assert process.run('/unused', authorized=True, deadline_sec=deadline)['reason'] == 'DEADLINE_INVALID'


@pytest.mark.parametrize('root', ['relative', '/', '/a/../b', '/a//b', '/a\nb'])
def test_invalid_request_does_not_start(case, root, monkeypatch):
    monkeypatch.setattr(process.subprocess, 'run', lambda *a, **k: pytest.fail('spawn'))
    assert process.run(root, authorized=True, **arguments(case))['reason'] == 'PROCESS_START_FAILED'


@pytest.mark.parametrize('raw', [b'', b'null', b'{}', b'x'*1025, b'{"x":NaN}',
    b'{"x":1,"x":2}', b'{"x":1e999999999999999999999999}', b'{"x":'+b'['*600+b'0'+b']'*600+b'}'])
def test_malformed_status_never_escapes(raw):
    assert contract.safe_result(raw)['reason'] == 'WORKER_RESULT_INVALID'


@pytest.mark.parametrize('change', [dict(reason='SENTINEL'), dict(stage='SENTINEL'),
    dict(extra='SENTINEL'), dict(replay_allowed=True), dict(history_complete=0),
    dict(private_fills_authenticated=True), dict(status='PASS')])
def test_child_cannot_escalate_or_leak(change):
    value=contract.blocked('IO');value.update(change)
    result=contract.safe_result(json.dumps(value).encode())
    assert result['reason']=='WORKER_RESULT_INVALID' and 'SENTINEL' not in repr(result)


@pytest.mark.parametrize('change', [{}, dict(bytes=True), dict(bytes=0),
    dict(bytes=16*1024*1024+1), dict(ciphertext_sha256='invalid'), dict(reason='IO')])
def test_exact_success_schema(change):
    value=dict(status='ENCRYPTED_CLAIMS_ONLY', bytes=128, ciphertext_sha256='a'*64,
        history_complete=False, private_fills_authenticated=False, replay_allowed=False)
    value.update(change)
    result=contract.safe_result(json.dumps(value).encode())
    assert result == value if not change else result['status']=='BLOCKED'


@pytest.mark.parametrize('raw', [b'{}', b'x'*8193, b'{"root":null}', b'{"x":NaN}'])
def test_worker_rejects_input_before_collection(raw, monkeypatch):
    from ladder_dragon.strategy import history_capture
    output=io.BytesIO()
    monkeypatch.setattr(process.sys, 'stdin', SimpleNamespace(buffer=io.BytesIO(raw)))
    monkeypatch.setattr(process.sys, 'stdout', SimpleNamespace(buffer=output))
    monkeypatch.setattr(history_capture, 'collect', lambda *a, **k: pytest.fail('collect'))
    process.worker()
    assert json.loads(output.getvalue())['reason']=='WORKER_INPUT_INVALID'
