"""Temporary synthetic files only; preserve every failed reservation."""
import os
from pathlib import Path
import stat
from types import SimpleNamespace

import pytest

from ladder_dragon.strategy import diagnostic_store as store
from ladder_dragon.strategy import storage_ownership as policy


@pytest.fixture
def target(tmp_path, monkeypatch):
    root = tmp_path.resolve()
    directory = root / store.DIRECTORY
    directory.mkdir(mode=0o700)
    device = root.stat().st_dev
    original = os.fstat
    root_identity = Path('/').stat().st_ino
    def synthetic(fd):
        info = original(fd)
        fields = {k: getattr(info, k) for k in dir(info) if k.startswith('st_')}
        if stat.S_ISDIR(info.st_mode) and info.st_ino != directory.stat().st_ino:
            fields.update(st_uid=os.geteuid(), st_mode=info.st_mode & ~0o022)
        if info.st_ino == root_identity:
            fields['st_dev'] = device + 1
        return SimpleNamespace(**fields)
    monkeypatch.setattr(store, 'ROOT', root)
    monkeypatch.setattr(os, 'fstat', synthetic)
    monkeypatch.setattr(os.path, 'ismount', lambda p: p == root)
    monkeypatch.setattr(os, 'fstatvfs', lambda fd: SimpleNamespace(f_bavail=store.RESERVE, f_frsize=1))
    return directory, device


def test_exclusive_persistence(target):
    directory, device = target
    with store.reserve(device) as (folder, fd):
        result = store.store(folder, fd, b'synthetic-ciphertext', device)
        with pytest.raises(ValueError): store.store(folder, fd, b'changed', device)
    path = directory / store.NAME
    assert path.read_bytes() == b'synthetic-ciphertext'
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert result['bytes'] == 20
    with pytest.raises(FileExistsError):
        with store.reserve(device): pytest.fail('reused slot')


@pytest.mark.parametrize('kind', ['file', 'symlink', 'broken_link', 'directory', 'hardlink'])
def test_occupied_slots_survive(target, kind):
    directory, device = target
    path = directory / store.NAME
    original = directory / 'protected'
    original.write_bytes(b'KEEP')
    if kind == 'file': path.write_bytes(b'KEEP')
    elif kind == 'symlink': path.symlink_to(original)
    elif kind == 'broken_link': path.symlink_to(directory / 'missing')
    elif kind == 'directory': path.mkdir()
    else: os.link(original, path)
    with pytest.raises(FileExistsError):
        with store.reserve(device): pytest.fail('occupied slot')
    assert original.read_bytes() == b'KEEP' and os.path.lexists(path)


def test_failed_attempt_preserves_reservation(target):
    directory, device = target
    with pytest.raises(RuntimeError):
        with store.reserve(device): raise RuntimeError('synthetic failure')
    assert (directory / store.NAME).read_bytes() == b''


def test_partial_write_survives(target, monkeypatch):
    directory, device = target
    original = os.write
    count = []
    def partial(fd, data):
        if count: raise OSError('PRIVATE_SENTINEL')
        count.append(1)
        return original(fd, data[:4])
    with pytest.raises(OSError):
        with store.reserve(device) as (folder, fd):
            monkeypatch.setattr(os, 'write', partial)
            store.store(folder, fd, b'encrypted-only', device)
    assert (directory / store.NAME).read_bytes() == b'encr'


@pytest.mark.parametrize('case', ['device', 'space', 'permissions', 'mount', 'parent_link'])
def test_bad_storage_blocks_before_reservation(target, monkeypatch, case):
    directory, device = target
    if case == 'device': device += 2
    elif case == 'space': monkeypatch.setattr(os, 'fstatvfs', lambda fd: SimpleNamespace(f_bavail=0, f_frsize=1))
    elif case == 'permissions': directory.chmod(0o755)
    elif case == 'mount': monkeypatch.setattr(os.path, 'ismount', lambda p: False)
    else:
        other = directory.with_name('actual')
        directory.rename(other)
        directory.symlink_to(other, target_is_directory=True)
    with pytest.raises((ValueError, OSError)):
        with store.reserve(device): pytest.fail('unsafe storage')
    assert not (directory / store.NAME).exists()


def test_replaced_name_cannot_report_success(target):
    directory, device = target
    with store.reserve(device) as (folder, fd):
        (directory / store.NAME).rename(directory / 'retained')
        (directory / store.NAME).write_bytes(b'KEEP')
        with pytest.raises(ValueError): store.store(folder, fd, b'cipher', device)
    assert (directory / store.NAME).read_bytes() == b'KEEP'


def test_failed_fsync_retains_ciphertext(target, monkeypatch):
    directory, device = target
    with store.reserve(device) as (folder, fd):
        def fail(number): raise OSError('synthetic persistence failure')
        monkeypatch.setattr(os, 'fsync', fail)
        with pytest.raises(OSError): store.store(folder, fd, b'ciphertext', device)
    assert (directory / store.NAME).read_bytes() == b'ciphertext'


@pytest.fixture
def bot_mount(target, monkeypatch):
    directory, device = target
    bot_uid = os.geteuid() + 10000
    monkeypatch.setattr(policy.pwd, 'getpwnam', lambda name: SimpleNamespace(pw_uid=bot_uid))
    original = os.fstat
    inode = store.ROOT.stat().st_ino
    def metadata(fd):
        info = original(fd)
        if info.st_ino == inode: info.st_uid = bot_uid
        return info
    monkeypatch.setattr(os, 'fstat', metadata)
    return directory, device, bot_uid


def test_bot_mount_private_root_directory(bot_mount):
    directory, device, _ = bot_mount
    with store.reserve(device) as (folder, fd):
        assert store.store(folder, fd, b'ciphertext', device)['bytes'] == 10
    assert (directory / store.NAME).read_bytes() == b'ciphertext'


@pytest.mark.parametrize('kind', ['private_directory', 'ancestor', 'unknown_mount', 'writable_mount', 'writable_private'])
def test_mount_exception_never_expands_to_private_paths(bot_mount, monkeypatch, kind):
    directory, device, bot_uid = bot_mount
    original = os.fstat
    dir_ino, root_ino, ancestor_ino = directory.stat().st_ino, store.ROOT.stat().st_ino, store.ROOT.parent.stat().st_ino
    def metadata(fd):
        info = original(fd)
        if kind == 'private_directory' and info.st_ino == dir_ino: info.st_uid = bot_uid
        if kind == 'ancestor' and info.st_ino == ancestor_ino: info.st_uid = bot_uid
        if kind == 'unknown_mount' and info.st_ino == root_ino: info.st_uid = bot_uid+1
        if kind == 'writable_mount' and info.st_ino == root_ino: info.st_mode |= 0o020
        if kind == 'writable_private' and info.st_ino == dir_ino: info.st_mode |= 0o020
        return info
    monkeypatch.setattr(os, 'fstat', metadata)
    with pytest.raises(ValueError):
        with store.reserve(device): pytest.fail('unsafe ownership accepted')
    assert not (directory / store.NAME).exists()


@pytest.mark.parametrize('kind', ['replace', 'symlink', 'rename'])
def test_bot_parent_directory_substitution_fails_closed(bot_mount, kind):
    directory, device, _ = bot_mount
    retained = directory.with_name('retained')
    with store.reserve(device) as (folder, fd):
        directory.rename(retained)
        if kind == 'replace': directory.mkdir(mode=0o700)
        elif kind == 'symlink': directory.symlink_to(retained, target_is_directory=True)
        with pytest.raises((ValueError, OSError)): store.store(folder, fd, b'ciphertext', device)
    assert (retained / store.NAME).read_bytes() == b''


def test_directory_swap_during_write_cannot_report_success(bot_mount, monkeypatch):
    directory, device, _ = bot_mount
    original = os.write
    retained = directory.with_name('retained')
    def swapped(fd, data):
        written = original(fd, data)
        directory.rename(retained)
        directory.mkdir(mode=0o700)
        return written
    with store.reserve(device) as (folder, fd):
        monkeypatch.setattr(os, 'write', swapped)
        with pytest.raises(ValueError): store.store(folder, fd, b'ciphertext', device)
    assert (retained / store.NAME).read_bytes() == b'ciphertext'
    assert not (directory / store.NAME).exists()
