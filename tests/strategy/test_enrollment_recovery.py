"""Recovery identity stays in anonymous memory; all subprocess outcomes are bounded."""

from types import SimpleNamespace
import warnings

import pytest

from ladder_dragon.strategy import enrollment_recovery as recovery
from tests.strategy.test_enrollment_registration import RECIPIENT,CIPHER


@pytest.mark.parametrize('identity',['AGE-SECRET-KEY-1'+'Q'*58,'bad','AGE-SECRET-KEY-1'+'Q'*58+' '])
def test_hidden_identity_is_strict(identity,monkeypatch):
    monkeypatch.setattr(recovery.getpass,'getpass',lambda prompt:identity)
    if identity.endswith('Q'):
        assert recovery.hidden_identity()==identity.encode()+b'\n'
    else:
        with pytest.raises(ValueError):recovery.hidden_identity()


def test_no_echo_fallback(monkeypatch):
    def fallback(prompt):warnings.warn('SENTINEL',recovery.getpass.GetPassWarning)
    monkeypatch.setattr(recovery.getpass,'getpass',fallback)
    with pytest.raises(recovery.getpass.GetPassWarning):recovery.hidden_identity()


@pytest.mark.parametrize('damage',[None,'recipient','decrypt','size','interrupt'])
def test_memfd_closed_and_keys_never_in_argv(damage,monkeypatch):
    events=[];secret=b'SYNTHETIC_PRIVATE_IDENTITY\n'
    monkeypatch.setattr(recovery,'hidden_identity',lambda:secret)
    monkeypatch.setattr(recovery.os,'memfd_create',lambda *a:42,raising=False)
    for name in ('MFD_CLOEXEC','MFD_ALLOW_SEALING'):
        monkeypatch.setattr(recovery.os,name,1,raising=False)
    for name in ('F_ADD_SEALS','F_SEAL_WRITE','F_SEAL_GROW','F_SEAL_SHRINK','F_SEAL_SEAL'):
        monkeypatch.setattr(recovery.fcntl,name,1,raising=False)
    monkeypatch.setattr(recovery.os,'write',lambda fd,data:events.append(('write',fd,data)) or len(data))
    monkeypatch.setattr(recovery.os,'lseek',lambda *a:0)
    monkeypatch.setattr(recovery.os,'close',lambda fd:events.append(('close',fd)))
    monkeypatch.setattr(recovery.fcntl,'fcntl',lambda *a:events.append(('seal',a[0])))
    guard=lambda:None
    def run(argv,**kwargs):
        assert 'SYNTHETIC' not in repr(argv)
        assert kwargs['env']=={} and kwargs['pass_fds']==(42,) and kwargs['timeout']==5
        assert kwargs['preexec_fn'] is guard
        if 'age-keygen' in argv[0]:
            return SimpleNamespace(stdout=(b'wrong' if damage=='recipient' else RECIPIENT.encode()))
        assert kwargs['input']==CIPHER
        if damage=='decrypt':raise OSError('SENTINEL')
        if damage=='interrupt':raise KeyboardInterrupt
        return SimpleNamespace(stdout=b'x'*4097 if damage=='size' else b'{}')
    monkeypatch.setattr(recovery.subprocess,'run',run)
    if damage:
        with pytest.raises((ValueError,OSError,KeyboardInterrupt)):
            recovery.recover(CIPHER,recipient=RECIPIENT,child_setup=guard)
    else:assert recovery.recover(CIPHER,recipient=RECIPIENT,child_setup=guard)==b'{}'
    assert events[-1]==('close',42) and ('seal',42) in events
