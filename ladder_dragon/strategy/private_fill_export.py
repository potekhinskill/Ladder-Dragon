# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: encrypt bounded private-source claims without granting replay authority.
"""Offline encrypted source claims, not an authenticated exchange collector.

Callers supply in-memory keys, independently reviewed bindings, and bounded
response bytes. No credentials, network, journal, or replay capabilities exist.
"""
import base64
import hashlib
import json
import os
import re

from cryptography.exceptions import InvalidSignature
from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

from ladder_dragon.execution.order_fill_evidence import complete_fills
from ladder_dragon.strategy.bnb_capture import external_store, pairs

DOMAIN = b'LadderDragon:private-fill-source:v1\x00'
MAX_PLAIN = 2 * 1024 * 1024
MAX_CIPHER = 4 * 1024 * 1024
HASH_FIELDS = {'scope_sha256', 'registration_sha256', 'code_sha256', 'signer_sha256', 'encryption_key_sha256'}


def _json(raw, limit):
    if type(raw) is not bytes or not 0 < len(raw) <= limit:
        raise ValueError
    return json.loads(raw, object_pairs_hook=pairs)


def _encode(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()


def _bindings(value):
    if type(value) is not dict or set(value) != HASH_FIELDS | {'collector_id'}:
        raise ValueError
    for name in HASH_FIELDS:
        if type(value[name]) is not str or re.fullmatch('[0-9a-f]{64}', value[name]) is None:
            raise ValueError
    if type(value['collector_id']) is not str or re.fullmatch('[a-zA-Z0-9_-]{1,64}', value['collector_id']) is None:
        raise ValueError


def _records(packets, binding):
    _bindings(binding)
    if type(packets) is not list or not 1 <= len(packets) <= 8:
        raise ValueError
    result, identities = [], set()
    fields = {'symbol', 'order_id', 'scope_sha256', 'started_ms', 'finished_ms', 'order_body', 'fills_body'}
    previous_end = 0
    for packet in packets:
        if type(packet) is not dict or set(packet) != fields or packet['scope_sha256'] != binding['scope_sha256']:
            raise ValueError
        start, end = packet['started_ms'], packet['finished_ms']
        if (type(start) is not int or type(end) is not int
                or not 0 < start <= end < 2**63 or end-start > 30000 or start < previous_end):
            raise ValueError
        order = _json(packet['order_body'], 65536)
        fills = _json(packet['fills_body'], 65536)
        indexed = complete_fills(order, fills, packet['symbol'], packet['order_id'])
        identity = (packet['symbol'], packet['order_id'])
        if identity in identities or any(fill['time'] > end for fill in indexed.values()):
            raise ValueError
        identities.add(identity)
        previous_end = end
        record = {key: packet[key] for key in fields - {'order_body', 'fills_body'}}
        for key in ('order_body', 'fills_body'):
            record[key] = base64.b64encode(packet[key]).decode('ascii')
            record[key+'_sha256'] = hashlib.sha256(packet[key]).hexdigest()
        result.append(record)
    return result


def check_keys(binding, signing_key, encryption_key):
    """Reject unexpected key material before a caller starts private retrieval."""
    try:
        _bindings(binding)
        if not isinstance(signing_key, Ed25519PrivateKey):
            raise ValueError
        public = signing_key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
        if (hashlib.sha256(public).hexdigest() != binding['signer_sha256']
                or type(encryption_key) is not bytes or len(encryption_key) != 44
                or hashlib.sha256(encryption_key).hexdigest() != binding['encryption_key_sha256']):
            raise ValueError
        Fernet(encryption_key)
    except (ValueError, TypeError, KeyError):
        raise ValueError('PRIVATE_EXPORT_INVALID') from None


def seal(packets, *, binding, signing_key, encryption_key):
    """Validate, sign, and encrypt before any file can be opened for writing."""
    try:
        records = _records(packets, binding)
        check_keys(binding, signing_key, encryption_key)
        body = _encode({'schema': 'private_fill_source_claim_v1', 'binding': binding, 'records': records,
                        'private_fills_authenticated': False, 'replay_allowed': False})
        signature = signing_key.sign(DOMAIN+body)
        plain = _encode({'body': base64.b64encode(body).decode('ascii'), 'signature': signature.hex()})
        if (len(plain) > MAX_PLAIN or type(encryption_key) is not bytes or len(encryption_key) != 44
                or hashlib.sha256(encryption_key).hexdigest() != binding['encryption_key_sha256']):
            raise ValueError
        token = Fernet(encryption_key).encrypt(plain)
        if len(token) > MAX_CIPHER:
            raise ValueError
        return token
    except (ValueError, TypeError, KeyError, RecursionError, OverflowError):
        raise ValueError('PRIVATE_EXPORT_INVALID') from None


def open_bundle(token, *, binding, trusted_public_key, encryption_key):
    """Return validated claims only; a signature cannot prove actual retrieval."""
    try:
        _bindings(binding)
        if type(token) is not bytes or not 0 < len(token) <= MAX_CIPHER:
            raise ValueError
        if type(trusted_public_key) is not bytes or len(trusted_public_key) != 32:
            raise ValueError
        if hashlib.sha256(trusted_public_key).hexdigest() != binding['signer_sha256']:
            raise ValueError
        if (type(encryption_key) is not bytes or len(encryption_key) != 44
                or hashlib.sha256(encryption_key).hexdigest() != binding['encryption_key_sha256']):
            raise ValueError
        plain = _json(Fernet(encryption_key).decrypt(token), MAX_PLAIN)
        if type(plain) is not dict or set(plain) != {'body', 'signature'}:
            raise ValueError
        body = base64.b64decode(plain['body'], validate=True)
        signature = bytes.fromhex(plain['signature'])
        Ed25519PublicKey.from_public_bytes(trusted_public_key).verify(signature, DOMAIN+body)
        value = _json(body, MAX_PLAIN)
        if (type(value) is not dict or set(value) != {'schema','binding','records','private_fills_authenticated','replay_allowed'}
                or value['schema'] != 'private_fill_source_claim_v1' or value['binding'] != binding
                or value['private_fills_authenticated'] is not False or value['replay_allowed'] is not False
                or type(value['records']) is not list or not 1 <= len(value['records']) <= 8):
            raise ValueError
        packets = []
        for record in value['records']:
            if type(record) is not dict:
                raise ValueError
            packet = {key: val for key, val in record.items() if key not in {'order_body_sha256', 'fills_body_sha256'}}
            for key in ('order_body', 'fills_body'):
                packet[key] = base64.b64decode(record[key], validate=True)
            packets.append(packet)
        if _records(packets, binding) != value['records']:
            raise ValueError
        return value
    except (ValueError, TypeError, KeyError, RecursionError, OverflowError, InvalidSignature, InvalidToken):
        raise ValueError('PRIVATE_EXPORT_INVALID') from None


def export(root, packets, *, binding, signing_key, encryption_key):
    """Write one exclusive external slot; retain interrupted ciphertext forever."""
    token = seal(packets, binding=binding, signing_key=signing_key, encryption_key=encryption_key)
    mount = external_store(root)
    parent = os.open(mount, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        if os.fstat(parent).st_dev != mount.stat().st_dev:
            raise ValueError('PRIVATE_EXPORT_DEVICE_CHANGED')
        os.mkdir('private-fill-export', mode=0o700, dir_fd=parent)
        directory = os.open('private-fill-export', os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent)
        try:
            if os.fstat(directory).st_dev != os.fstat(parent).st_dev:
                raise ValueError('PRIVATE_EXPORT_DEVICE_CHANGED')
            fd = os.open('bundle.fernet', os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=directory)
            with os.fdopen(fd, 'wb') as output:
                output.write(token)
                output.flush()
                os.fsync(output.fileno())
            os.fsync(directory)
            os.fsync(parent)
        finally:
            os.close(directory)
    finally:
        os.close(parent)
    return {'status': 'ENCRYPTED_CLAIMS_ONLY', 'bytes': len(token),
            'ciphertext_sha256': hashlib.sha256(token).hexdigest(),
            'private_fills_authenticated': False, 'replay_allowed': False}
