# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: preserve bounded historical source claims in an exclusive encrypted slot.
"""Source claims remain unresolved evidence, never accounting or replay authority."""

import base64
import hashlib
import json
import os
import stat

from cryptography.exceptions import InvalidSignature
from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from ladder_dragon.strategy.bnb_capture import external_store
from ladder_dragon.strategy.private_fill_export import _bindings, _encode, check_keys
from ladder_dragon.strategy.history_pages import SYMBOL, CUTOFF_MS, decode, validate_capture

DOMAIN = b'LadderDragon:historical-sol-source:v1\x00'
SLOT = 'historical-sol-source-v1'
MAX_CIPHER = 16 * 1024 * 1024
MAX_PLAIN = 12 * 1024 * 1024


def records(packets):
    return [{**{k:v for k,v in p.items() if k != 'body'},
             'body':base64.b64encode(p['body']).decode('ascii'),
             'body_sha256':hashlib.sha256(p['body']).hexdigest()} for p in packets]


def claim(pages, clocks, binding):
    _bindings(binding)
    summary = validate_capture(pages, clocks)
    return dict(schema='historical_sol_source_claim_v1', symbol=SYMBOL, cutoff_ms=CUTOFF_MS,
                binding=binding, pages=records(pages), clocks=records(clocks), summary=summary)


def seal(pages, clocks, *, binding, signing_key, encryption_key):
    try:
        check_keys(binding, signing_key, encryption_key)
        body = _encode(claim(pages, clocks, binding))
        plain = _encode(dict(body=base64.b64encode(body).decode('ascii'), signature=signing_key.sign(DOMAIN+body).hex()))
        if len(plain) > MAX_PLAIN:
            raise ValueError
        token = Fernet(encryption_key).encrypt(plain)
        if len(token) > MAX_CIPHER:
            raise ValueError
        return token
    except (ValueError, TypeError, KeyError, RecursionError, OverflowError):
        raise ValueError('HISTORY_ARCHIVE_INVALID') from None


def open_bundle(token, *, binding, trusted_public_key, encryption_key):
    """Verify integrity and rederive claims; authentication flags stay false."""
    try:
        _bindings(binding)
        if (type(token) is not bytes or not 0 < len(token) <= MAX_CIPHER
                or type(trusted_public_key) is not bytes or len(trusted_public_key) != 32
                or hashlib.sha256(trusted_public_key).hexdigest() != binding['signer_sha256']
                or type(encryption_key) is not bytes or len(encryption_key) != 44
                or hashlib.sha256(encryption_key).hexdigest() != binding['encryption_key_sha256']):
            raise ValueError
        envelope = decode(Fernet(encryption_key).decrypt(token), MAX_PLAIN)
        if type(envelope) is not dict or set(envelope) != {'body','signature'}:
            raise ValueError
        body = base64.b64decode(envelope['body'], validate=True)
        Ed25519PublicKey.from_public_bytes(trusted_public_key).verify(bytes.fromhex(envelope['signature']),DOMAIN+body)
        value = decode(body, MAX_PLAIN)
        packets = []
        for name, maximum in (('pages',20),('clocks',2)):
            source = value[name]
            if type(source) is not list or not 1 <= len(source) <= maximum:
                raise ValueError
            if any(type(p) is not dict for p in source):
                raise ValueError
            packets.append([{**{k:v for k,v in p.items() if k not in {'body','body_sha256'}},
                             'body':base64.b64decode(p['body'],validate=True)} for p in source])
        # Canonical bytes also reject boolean/integer substitutions and extra claims.
        if _encode(claim(packets[0],packets[1],binding)) != body:
            raise ValueError
        return value
    except (ValueError, TypeError, KeyError, RecursionError, OverflowError, InvalidToken, InvalidSignature):
        raise ValueError('HISTORY_ARCHIVE_INVALID') from None


def reserve(root):
    """Reserve an exclusive owner-only slot before retrieval; never clean up failure."""
    mount = external_store(root)
    parent = os.open(mount, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        info = os.fstat(parent)
        if (info.st_dev != mount.stat().st_dev or info.st_uid != os.geteuid()
                or stat.S_IMODE(info.st_mode) & 0o022):
            raise ValueError('HISTORY_DEVICE_CHANGED')
        os.mkdir(SLOT, 0o700, dir_fd=parent)
        directory = os.open(SLOT, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent)
        info = os.fstat(directory)
        if (info.st_dev != os.fstat(parent).st_dev or info.st_uid != os.geteuid()
                or stat.S_IMODE(info.st_mode) != 0o700):
            os.close(directory)
            raise ValueError('HISTORY_DIRECTORY_UNSAFE')
        os.fsync(parent)
        return directory
    finally:
        os.close(parent)


def store(directory, token):
    """No plaintext files, no replacement, no deletion after interrupted writes."""
    if type(token) is not bytes or not 0 < len(token) <= MAX_CIPHER:
        raise ValueError('HISTORY_CIPHERTEXT_INVALID')
    fd = os.open('bundle.fernet', os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=directory)
    with os.fdopen(fd, 'wb') as output:
        output.write(token)
        output.flush()
        os.fsync(output.fileno())
    os.fsync(directory)
    return dict(status='ENCRYPTED_CLAIMS_ONLY', bytes=len(token),
                ciphertext_sha256=hashlib.sha256(token).hexdigest(),
                history_complete=False, private_fills_authenticated=False, replay_allowed=False)
