# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: bound private stdin and safe status at the history-process boundary.
"""No network, credential discovery, persistent record, or execution authority."""

import base64
from decimal import InvalidOperation
import os
import re

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PrivateFormat, NoEncryption

from ladder_dragon.strategy.account_binding import _object
from ladder_dragon.strategy.private_fill_capture import credential_scope
from ladder_dragon.strategy.private_fill_export import _encode, check_keys

MAX_INPUT = 8192
FALSE_FIELDS = {'history_complete', 'private_fills_authenticated', 'replay_allowed'}
FAILURE_REASONS = {'TLS', 'TIMEOUT', 'TRANSPORT', 'IO', 'VALIDATION', 'HTTP_STATUS',
                   'WORKER_INPUT_INVALID', 'WORKER_FAILED'}


def blocked(reason):
    return dict(status='BLOCKED', reason=reason, history_complete=False,
                private_fills_authenticated=False, replay_allowed=False)


def request(root, *, credentials, binding, signing_key, encryption_key):
    """Validate private fields before spawning; encode only for anonymous stdin."""
    root = os.fspath(root)
    if (type(root) is not str or not root.startswith('/') or len(root) > 4096
            or any(ord(c) < 32 for c in root)
            or any(p in {'', '.', '..'} for p in root.split('/')[1:])):
        raise ValueError
    if (type(credentials) is not tuple or len(credentials) != 2
            or any(type(v) is not str or not 1 <= len(v) <= 256
                   or not v.isascii() or not v.isalnum() for v in credentials)):
        raise ValueError
    check_keys(binding, signing_key, encryption_key)
    if credential_scope(credentials[0]) != binding['scope_sha256']:
        raise ValueError
    key = signing_key.private_bytes(Encoding.Raw, PrivateFormat.Raw, NoEncryption())
    raw = _encode(dict(root=root, credentials=list(credentials), binding=binding,
                       signing_key=base64.b64encode(key).decode('ascii'),
                       encryption_key=encryption_key.decode('ascii')))
    if len(raw) > MAX_INPUT:
        raise ValueError
    return raw


def parse_request(raw):
    value = _object(raw, MAX_INPUT)
    if set(value) != {'root', 'credentials', 'binding', 'signing_key', 'encryption_key'} or type(value['credentials']) is not list:
        raise ValueError
    kwargs = dict(credentials=tuple(value['credentials']), binding=value['binding'],
                  signing_key=Ed25519PrivateKey.from_private_bytes(base64.b64decode(value['signing_key'], validate=True)),
                  encryption_key=value['encryption_key'].encode('ascii'))
    if request(value['root'], **kwargs) != raw:
        raise ValueError
    return value['root'], kwargs


def safe_result(raw):
    """Allow fixed fields and bounded values, never arbitrary provider messages."""
    try:
        value = _object(raw, 1024)
        if any(value.get(k) is not False for k in FALSE_FIELDS):
            raise ValueError
        if value.get('status') == 'ENCRYPTED_CLAIMS_ONLY':
            if (set(value) != FALSE_FIELDS | {'status', 'bytes', 'ciphertext_sha256'}
                    or type(value['bytes']) is not int or not 0 < value['bytes'] <= 16*1024*1024
                    or type(value['ciphertext_sha256']) is not str
                    or re.fullmatch('[0-9a-f]{64}', value['ciphertext_sha256']) is None):
                raise ValueError
        elif value.get('status') == 'BLOCKED':
            if (set(value) not in (FALSE_FIELDS | {'status','reason'}, FALSE_FIELDS | {'status','stage','reason'})
                    or type(value.get('reason')) is not str or value['reason'] not in FAILURE_REASONS
                    or ('stage' in value and (type(value['stage']) is not str
                        or value['stage'] not in {'preflight','retrieval','storage'}))):
                raise ValueError
        else:
            raise ValueError
        return value
    except (ValueError, TypeError, RecursionError, OverflowError, InvalidOperation):
        return blocked('WORKER_RESULT_INVALID')
