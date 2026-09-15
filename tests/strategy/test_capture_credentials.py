import hashlib
import os

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PrivateFormat, PublicFormat, NoEncryption

from ladder_dragon.strategy.capture_credentials import load_capture_key


@pytest.fixture
def credential(tmp_path):
    # Only ephemeral generated test material is serialized; no production key is read.
    folder = tmp_path.resolve() / 'protected'
    folder.mkdir(mode=0o700)
    key = Ed25519PrivateKey.generate()
    path = folder / 'signer.pem'
    path.write_bytes(key.private_bytes(Encoding.PEM, PrivateFormat.PKCS8, NoEncryption()))
    path.chmod(0o600)
    public = key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
    return path, hashlib.sha256(public).hexdigest(), key


def test_load_exact_key(credential):
    path, pin, expected = credential
    actual = load_capture_key(path, expected_public_sha256=pin)
    assert actual.sign(b'test') == expected.sign(b'test')
    path.chmod(0o400)
    assert load_capture_key(path, expected_public_sha256=pin).sign(b'test') == actual.sign(b'test')


@pytest.mark.parametrize('mode', [0o644, 0o640, 0o666, 0o700])
def test_reject_unsafe_file_mode(credential, mode):
    path, pin, _ = credential
    path.chmod(mode)
    with pytest.raises(ValueError):
        load_capture_key(path, expected_public_sha256=pin)


def test_reject_public_directory(credential):
    path, pin, _ = credential
    path.parent.chmod(0o755)
    with pytest.raises(ValueError, match='DIRECTORY'):
        load_capture_key(path, expected_public_sha256=pin)


@pytest.mark.parametrize('kind', ['file', 'parent', 'hardlink', 'fifo'])
def test_reject_indirect_file(credential, tmp_path, kind):
    path, pin, _ = credential
    if kind == 'file':
        target = path.with_name('link')
        target.symlink_to(path)
    elif kind == 'parent':
        link = tmp_path.resolve()/'alias'
        link.symlink_to(path.parent, target_is_directory=True)
        target = link / path.name
    elif kind == 'hardlink':
        target = path.with_name('link')
        os.link(path, target)
    else:
        target = path.with_name('pipe')
        os.mkfifo(target, 0o600)
    with pytest.raises((OSError, ValueError)):
        load_capture_key(target, expected_public_sha256=pin)


@pytest.mark.parametrize('data', [b'', b'x'*4097, b'not a key'])
def test_reject_bad_bytes_without_exposure(credential, data):
    path, pin, _ = credential
    path.write_bytes(data)
    with pytest.raises(ValueError) as error:
        load_capture_key(path, expected_public_sha256=pin)
    assert 'not a key' not in str(error.value)


def test_reject_wrong_pin(credential):
    path, _, _ = credential
    with pytest.raises(ValueError, match='PIN_MISMATCH'):
        load_capture_key(path, expected_public_sha256='0'*64)


@pytest.mark.parametrize('path', ['relative/key', '/tmp/../key', '/tmp//key', '/key'])
def test_reject_unsafe_paths(path):
    with pytest.raises(ValueError, match='PATH'):
        load_capture_key(path, expected_public_sha256='0'*64)


def test_changed_file_detected(credential, monkeypatch):
    import ladder_dragon.strategy.capture_credentials as module
    path, pin, _ = credential
    read = os.read
    changed = False
    def mutate(fd, size):
        nonlocal changed
        result = read(fd, size)
        if not changed:
            changed = True
            path.write_bytes(b'changed')
        return result
    monkeypatch.setattr(module.os, 'read', mutate)
    with pytest.raises(ValueError, match='CHANGED'):
        load_capture_key(path, expected_public_sha256=pin)


def test_other_algorithm_rejected(credential):
    from cryptography.hazmat.primitives.asymmetric.ec import generate_private_key, SECP256R1
    path, pin, _ = credential
    path.write_bytes(generate_private_key(SECP256R1()).private_bytes(Encoding.PEM, PrivateFormat.PKCS8, NoEncryption()))
    with pytest.raises(ValueError, match='ALGORITHM'):
        load_capture_key(path, expected_public_sha256=pin)


def test_encrypted_key_not_prompted_for(credential):
    from cryptography.hazmat.primitives.serialization import BestAvailableEncryption
    path, pin, key = credential
    path.write_bytes(key.private_bytes(Encoding.PEM, PrivateFormat.PKCS8, BestAvailableEncryption(b'synthetic')))
    with pytest.raises(ValueError, match='FORMAT'):
        load_capture_key(path, expected_public_sha256=pin)


def test_foreign_owner_rejected(credential, monkeypatch):
    import stat
    from types import SimpleNamespace
    path, pin, _ = credential
    original = os.fstat
    def changed_owner(fd):
        result = original(fd)
        if stat.S_ISREG(result.st_mode):
            return SimpleNamespace(st_mode=result.st_mode, st_nlink=result.st_nlink, st_uid=987654321)
        return result
    monkeypatch.setattr(os, 'fstat', changed_owner)
    with pytest.raises(ValueError, match='PERMISSIONS'):
        load_capture_key(path, expected_public_sha256=pin)
