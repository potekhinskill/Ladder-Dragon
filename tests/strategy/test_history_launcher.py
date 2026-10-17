"""Synthetic preparation checks; never access Pi, credentials, or exchange APIs."""
import json
from pathlib import Path
import stat
import subprocess
from types import SimpleNamespace

import pytest

from ladder_dragon.strategy import history_launcher as launcher, enrollment_host as host


@pytest.fixture
def value():
    return dict(confirmed=True, expected_code_sha='1'*40, expected_device=123)


@pytest.fixture
def prepared(monkeypatch):
    calls = []
    monkeypatch.setattr(host, 'harden', lambda parent: calls.append('host'))
    monkeypatch.setattr(host, 'check_revision', lambda sha: calls.append('revision'))
    monkeypatch.setattr(Path, 'lstat', lambda path: SimpleNamespace(
        st_mode=(stat.S_IFREG | 0o600) if path == launcher.HALT else (stat.S_IFDIR | 0o755),
        st_nlink=1, st_dev=123, st_uid=launcher.os.geteuid()))
    monkeypatch.setattr(Path, 'stat', lambda path: SimpleNamespace(st_dev=1))
    monkeypatch.setattr(launcher.os.path, 'ismount', lambda path: True)
    monkeypatch.setattr(launcher.os.path, 'lexists', lambda path: False)
    monkeypatch.setattr(launcher.shutil, 'disk_usage', lambda path: SimpleNamespace(free=launcher.RESERVE))
    return calls


def test_preparation_never_grants_admission(value, prepared):
    assert launcher.prepare(value, 42) == launcher.result('complete')
    assert prepared == ['host', 'revision']


@pytest.mark.parametrize('key,bad', [('confirmed',False), ('confirmed',1),
    ('expected_code_sha','bad'), ('expected_device',True), ('expected_device',0)])
def test_invalid_input_never_inspects_host(value, prepared, key, bad):
    value[key] = bad
    assert launcher.prepare(value, 42) == launcher.result('input')
    assert prepared == []


@pytest.mark.parametrize('name,stage', [('harden','host'),('check_revision','revision')])
def test_host_failure_is_sanitized(value, prepared, monkeypatch, name, stage):
    def fail(*args):
        raise ValueError('PRIVATE_SENTINEL')
    monkeypatch.setattr(host, name, fail)
    assert launcher.prepare(value,42) == launcher.result(stage)


@pytest.mark.parametrize('case', ['space','occupied','unmounted','device','symlink','owner','writable','missing_halt'])
def test_storage_and_halt_refusals(value, prepared, monkeypatch, case):
    if case == 'space':
        monkeypatch.setattr(launcher.shutil,'disk_usage',lambda p:SimpleNamespace(free=launcher.RESERVE-1))
    elif case == 'occupied':
        monkeypatch.setattr(launcher.os.path,'lexists',lambda p:True)
    elif case == 'unmounted':
        monkeypatch.setattr(launcher.os.path,'ismount',lambda p:False)
    elif case == 'device':
        value['expected_device'] = 124
    else:
        old = Path.lstat
        def changed(p):
            if case == 'missing_halt' and p == launcher.HALT:
                raise FileNotFoundError
            s = old(p)
            if p == launcher.ROOT:
                if case == 'symlink': s.st_mode = stat.S_IFLNK | 0o777
                if case == 'owner': s.st_uid += 1
                if case == 'writable': s.st_mode |= 0o020
            return s
        monkeypatch.setattr(Path, 'lstat', changed)
    assert launcher.prepare(value,42) == launcher.result('halt' if case == 'missing_halt' else 'storage')


def test_default_no_process(monkeypatch):
    monkeypatch.setattr(subprocess,'run',lambda *a,**k:pytest.fail('process started'))
    assert launcher.run({}) == launcher.result('authorization')


def test_isolated_child_contract(value, monkeypatch):
    def child(argv, **kw):
        assert argv[1] == '-I'
        assert kw['env'] == {'PYTHON_DOTENV_DISABLED':'1'}
        assert kw['cwd'] == '/' and kw['close_fds'] is True and kw['timeout'] == 35
        assert json.loads(kw['input']) == value
        return SimpleNamespace(returncode=0,stdout=json.dumps(launcher.result('complete')).encode())
    monkeypatch.setattr(subprocess,'run',child)
    assert launcher.run(value) == launcher.result('complete')


def test_timeout_sanitized(value,monkeypatch):
    def fail(*a,**k): raise subprocess.TimeoutExpired('PRIVATE_SENTINEL',35)
    monkeypatch.setattr(subprocess,'run',fail)
    assert launcher.run(value) == launcher.result('process')


@pytest.mark.parametrize('field', ['collection_allowed','history_complete','private_fills_authenticated','replay_allowed'])
@pytest.mark.parametrize('bad', [True,0,None])
def test_child_cannot_grant_authority(field,bad):
    data=launcher.result('complete'); data[field]=bad
    assert launcher.safe_result(json.dumps(data).encode()) == launcher.result('process')


def test_parser_does_not_echo_private_arguments(capsys):
    assert launcher.main(['--unknown','PRIVATE_SENTINEL']) == 2
    output=capsys.readouterr()
    assert 'PRIVATE_SENTINEL' not in output.out+output.err


def test_extreme_json_exponent_is_sanitized():
    raw = b'{"stage":1e99999999999999999999999999999999999999999}'
    assert launcher.safe_result(raw) == launcher.result('process')


def test_no_network_or_private_source_dependency():
    import ast
    tree=ast.parse(Path(launcher.__file__).read_text())
    for node in ast.walk(tree):
        if isinstance(node,ast.Import):
            assert not any(n.name.split('.')[0] in {'requests','socket'} for n in node.names)
        if isinstance(node,ast.ImportFrom):
            assert 'history_capture' not in (node.module or '')
        if isinstance(node,ast.Call) and isinstance(node.func,ast.Attribute):
            assert node.func.attr not in {'dashboard_key','protected_read','load_capture_key'}


def test_private_loader_only_after_guards(value,prepared,monkeypatch):
    from ladder_dragon.strategy import history_input_loader as loader
    calls=[]
    def verify(**kwargs):
        assert prepared==['host','revision']
        calls.append(kwargs)
        return 'inputs_verified'
    monkeypatch.setattr(loader,'verify',verify)
    assert launcher.prepare(value,42)==launcher.result('complete')
    assert calls==[]
    prepared.clear();value['manifest_sha256']='2'*64
    assert launcher.prepare(value,42)==launcher.result('inputs_verified')
    assert calls==[dict(expected_manifest_sha256='2'*64,code_sha='1'*40)]
    calls.clear()
    monkeypatch.setattr(launcher.os.path,'lexists',lambda path:True)
    assert launcher.prepare(value,42)==launcher.result('storage')
    assert calls==[]
