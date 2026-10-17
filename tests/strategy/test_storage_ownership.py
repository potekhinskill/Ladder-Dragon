"""Named service-account trust only; no system ownership changes."""
from types import SimpleNamespace
import pytest

from ladder_dragon.strategy import storage_ownership as policy
from ladder_dragon.strategy import history_launcher as launcher
from tests.strategy.test_history_launcher import value, prepared


@pytest.fixture
def accounts(monkeypatch):
    monkeypatch.setattr(policy.os, 'geteuid', lambda: 0)
    monkeypatch.setattr(policy.pwd, 'getpwnam', lambda name: SimpleNamespace(pw_uid=1234) if name == 'bot' else None)


@pytest.mark.parametrize('uid,allowed', [(0,True), (1234,True), (1235,False), (True,False), (-1,False), ('1234',False)])
def test_exact_named_owner(accounts, uid, allowed):
    assert policy.mount_owner_allowed(uid) is allowed


def test_missing_service_account_does_not_expand_trust(accounts, monkeypatch):
    def missing(name): raise KeyError('bot')
    monkeypatch.setattr(policy.pwd, 'getpwnam', missing)
    assert policy.mount_owner_allowed(0)
    assert not policy.mount_owner_allowed(1234)


@pytest.mark.parametrize('mode,owner,expected', [(0o755,1234,'complete'), (0o775,1234,'storage'),
    (0o777,1234,'storage'), (0o755,1235,'storage')])
def test_preflight_bot_mount_only(value, prepared, accounts, monkeypatch, mode, owner, expected):
    original = launcher.Path.lstat
    def metadata(path):
        info = original(path)
        if path == launcher.ROOT:
            info.st_uid = owner
            info.st_mode = (info.st_mode & ~0o777) | mode
        return info
    monkeypatch.setattr(launcher.Path, 'lstat', metadata)
    assert launcher.prepare(value, 42) == launcher.result(expected)
