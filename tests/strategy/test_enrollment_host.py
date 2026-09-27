"""Host and private-file guards with synthetic process and filesystem state."""

import os
from pathlib import Path
import stat
from types import SimpleNamespace

import pytest

from ladder_dragon.strategy import enrollment_host as host
from ladder_dragon.strategy import enrollment_registration as reg


@pytest.mark.parametrize('rows,backing,ok',[
    ('Filename Type Size Used Priority\n','none',True),
    ('Filename Type Size Used Priority\n/dev/zram0 partition 1 0 1\n','none',True),
    ('Filename Type Size Used Priority\n/dev/zram0 partition 1 0 1\n','/dev/disk',False),
    ('Filename Type Size Used Priority\n/swapfile file 1 0 1\n','none',False),
    ('bad','none',False)])
def test_swap_boundaries(rows,backing,ok):
    if ok:host.memory_only_swap(rows,lambda name:backing)
    else:
        with pytest.raises(ValueError):host.memory_only_swap(rows,lambda name:backing)


@pytest.fixture
def synthetic_host(monkeypatch):
    state={'swaps':'Filename Type Size Used Priority\n','mounts':'tmpfs /run tmpfs rw 0 0',
           'core':'core','mode':stat.S_IFREG|0o755,'xattrs':[],'prctl':0,'ppid':99,'limits':[]}
    class P:
        def __init__(self,name):self.name=str(name)
        def __truediv__(self,name):return P(self.name+'/'+name)
        def read_text(self):
            return state[{'/proc/swaps':'swaps','/proc/self/mounts':'mounts','/proc/sys/kernel/core_pattern':'core'}[self.name]]
        def lstat(self):return SimpleNamespace(st_mode=state['mode'],st_uid=0)
    monkeypatch.setattr(host,'Path',P)
    monkeypatch.setattr(host.sys,'platform','linux')
    monkeypatch.setattr(host.sys,'flags',SimpleNamespace(isolated=1))
    monkeypatch.setattr(host.os,'geteuid',lambda:0)
    monkeypatch.setattr(host.os,'getppid',lambda:state['ppid'])
    monkeypatch.setattr(host.os,'listxattr',lambda path:state['xattrs'],raising=False)
    monkeypatch.setattr(host.os,'memfd_create',lambda *a:None,raising=False)
    monkeypatch.setattr(host.os,'environ',{'PYTHON_DOTENV_DISABLED':'1'})
    monkeypatch.setattr(host.resource,'setrlimit',lambda kind,limits:state['limits'].append(limits))
    monkeypatch.setattr(host.ctypes,'CDLL',lambda *a,**k:SimpleNamespace(prctl=lambda *a:state['prctl']))
    return state


def test_hardening_disables_core_in_worker(synthetic_host):
    host.os.environ.pop('PYTEST_CURRENT_TEST',None)
    host.harden(99)
    assert synthetic_host['limits']==[(0,0)]


@pytest.mark.parametrize('change',[dict(core='|/collector'),dict(mounts='root / ext4 rw 0 0'),
    dict(mode=stat.S_IFREG|0o4755),dict(xattrs=['security.capability']),dict(prctl=-1),dict(ppid=1)])
def test_host_uncertainty_blocks(synthetic_host,change):
    host.os.environ.pop('PYTEST_CURRENT_TEST',None)
    synthetic_host.update(change)
    with pytest.raises(ValueError):host.harden(99)


def test_environment_secret_blocks(synthetic_host):
    host.os.environ.pop('PYTEST_CURRENT_TEST',None)
    host.os.environ['SYNTHETIC_SECRET']='SENTINEL'
    with pytest.raises(ValueError):host.harden(99)


def test_parent_death_hook_race(monkeypatch):
    calls=[]
    monkeypatch.setattr(host.sys,'platform','linux')
    monkeypatch.setattr(host.threading,'active_count',lambda:1)
    monkeypatch.setattr(host.os,'getpid',lambda:123)
    monkeypatch.setattr(host.os,'getppid',lambda:123)
    monkeypatch.setattr(host.ctypes,'CDLL',lambda *a,**k:SimpleNamespace(prctl=lambda *a:calls.append(a) or 0))
    def exit(code):raise SystemExit(code)
    monkeypatch.setattr(host.os,'_exit',exit)
    setup=host.child_setup();setup()
    assert calls==[(1,9,0,0,0)]
    monkeypatch.setattr(host.os,'getppid',lambda:1)
    with pytest.raises(SystemExit,match='70'):setup()


def test_multithreaded_preexec_refused(monkeypatch):
    monkeypatch.setattr(host.sys,'platform','linux')
    monkeypatch.setattr(host.threading,'active_count',lambda:2)
    with pytest.raises(ValueError):host.child_setup()


@pytest.mark.parametrize('raw',[
    b'DASHBOARD_BINANCE_API_KEY=SYNTHETICKEY\n',
    b'DASHBOARD_BINANCE_API_KEY=OTHER\n',
    b'DASHBOARD_BINANCE_API_KEY=SYNTHETICKEY\nDASHBOARD_BINANCE_API_KEY=SYNTHETICKEY\n',
    b'BINANCE_API_KEY=SYNTHETICKEY\n',
    b'DASHBOARD_BINANCE_API_KEY=${OTHER}\n',
    b'DASHBOARD_BINANCE_API_KEY="broken\n'])
def test_exact_credential_source_and_scope(raw,monkeypatch):
    def read(path,**kwargs):
        assert path==host.CREDENTIAL and kwargs==dict(maximum=65536,private=True)
        return raw
    monkeypatch.setattr(host,'protected_read',read)
    if raw==b'DASHBOARD_BINANCE_API_KEY=SYNTHETICKEY\n':
        assert host.dashboard_key(reg.credential_scope('SYNTHETICKEY'))=='SYNTHETICKEY'
    else:
        with pytest.raises(ValueError):host.dashboard_key(reg.credential_scope('SYNTHETICKEY'))


@pytest.fixture
def private_file(tmp_path,monkeypatch):
    path=(tmp_path/'synthetic').resolve();path.write_bytes(b'SYNTHETIC');path.chmod(0o600)
    monkeypatch.setattr(host.pwd,'getpwnam',lambda name:SimpleNamespace(pw_uid=os.geteuid()))
    original=host.os.fstat
    def metadata(fd):
        result=original(fd)
        # Synthetic temp ancestors can be shared; file properties stay real.
        if stat.S_ISDIR(result.st_mode):
            fields=list(result);fields[0] &= ~0o022
            return os.stat_result(fields)
        return result
    monkeypatch.setattr(host.os,'fstat',metadata)
    return path


def test_protected_file(private_file):
    assert host.protected_read(private_file,maximum=100,private=True)==b'SYNTHETIC'


@pytest.mark.parametrize('damage',['mode','symlink','hardlink','size'])
def test_file_identity_and_permissions(private_file,damage):
    path=private_file
    if damage=='mode':path.chmod(0o644)
    elif damage=='symlink':
        path=path.with_name('link');path.symlink_to(private_file)
    elif damage=='hardlink':os.link(path,path.with_name('hard'))
    with pytest.raises((OSError,ValueError)):
        host.protected_read(path,maximum=1 if damage=='size' else 100,private=True)


def test_revision_pin_and_dirty_tree(monkeypatch):
    seen=[]
    monkeypatch.setattr(host,'PROJECT',Path(host.__file__).resolve().parents[2])
    def run(argv,**kwargs):
        seen.append(argv)
        return SimpleNamespace(stdout=b'1'*40+b'\n' if 'rev-parse' in argv else b'')
    monkeypatch.setattr(host.subprocess,'run',run)
    host.check_revision('1'*40)
    assert any('diff' in args for args in seen) and any('ls-files' in args for args in seen)
    with pytest.raises(ValueError):host.check_revision('2'*40)


def test_wrong_loaded_checkout_blocks(monkeypatch,tmp_path):
    monkeypatch.setattr(host,'PROJECT',tmp_path)
    monkeypatch.setattr(host.subprocess,'run',lambda *a,**k:pytest.fail('git'))
    with pytest.raises(ValueError):host.check_revision('1'*40)
