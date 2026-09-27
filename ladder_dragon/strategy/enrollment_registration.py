# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: prepare encrypted operator enrollment claims without network authority.
"""Offline building blocks, not a production launcher or identity attestation.

A reviewed isolated caller must protect memory and select the credential source
before supplying private input. No environment discovery or plaintext file exists.
"""

import getpass
from decimal import InvalidOperation
import hashlib
import hmac
import re
import secrets
import subprocess
import warnings

from ladder_dragon.strategy.account_binding import _identifier, _object, _scope
from ladder_dragon.strategy.private_fill_capture import credential_scope
from ladder_dragon.strategy.private_fill_export import _encode

MAX_PLAIN = 4096
MAX_CIPHER = 16384


def hidden_uid():
    """Reject getpass echo fallback and require exact repeated decimal input."""
    try:
        with warnings.catch_warnings():
            warnings.simplefilter('error', getpass.GetPassWarning)
            first = getpass.getpass('Account UID (hidden): ')
            second = getpass.getpass('Repeat account UID (hidden): ')
        if (type(first) is not str or type(second) is not str
                or re.fullmatch('[1-9][0-9]{0,18}', first) is None
                or not hmac.compare_digest(first, second) or not _identifier(int(first))):
            raise ValueError
        return int(first)
    except (ValueError, TypeError, EOFError, OSError, getpass.GetPassWarning):
        raise ValueError('ENROLLMENT_INPUT_INVALID') from None


def claim(uid, api_key):
    """Generate a fresh reference; this binds an operator claim, not API truth."""
    if not _identifier(uid):
        raise ValueError('ENROLLMENT_INPUT_INVALID')
    return dict(schema='account_enrollment_claim_v1', reference=secrets.token_hex(16),
                uid=uid, credential_scope=credential_scope(api_key))


def encode_claim(value):
    if (type(value) is not dict or set(value) != {'schema', 'reference', 'uid', 'credential_scope'}
            or value['schema'] != 'account_enrollment_claim_v1'
            or type(value['reference']) is not str
            or re.fullmatch('[0-9a-f]{32}', value['reference']) is None
            or not _identifier(value['uid']) or not _scope(value['credential_scope'])):
        raise ValueError('ENROLLMENT_INPUT_INVALID')
    raw = _encode(value)
    if len(raw) > MAX_PLAIN:
        raise ValueError('ENROLLMENT_INPUT_INVALID')
    return raw


def encrypt_claim(value, *, recipient, expected_recipient_sha256, child_setup=None):
    """Use pinned age recipient and anonymous stdin; never persist plaintext."""
    try:
        raw = encode_claim(value)
        if (type(recipient) is not str
                or re.fullmatch(r'age1[023456789acdefghjklmnpqrstuvwxyz]{58}', recipient) is None
                or type(expected_recipient_sha256) is not str
                or hashlib.sha256(recipient.encode()).hexdigest() != expected_recipient_sha256):
            raise ValueError
        child_options = {'preexec_fn': child_setup} if child_setup is not None else {}
        result = subprocess.run(['/usr/bin/age', '-r', recipient], input=raw,
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, env={}, cwd='/',
            close_fds=True, timeout=5, check=False, **child_options)
        if (result.returncode != 0 or type(result.stdout) is not bytes
                or not 100 <= len(result.stdout) <= MAX_CIPHER
                or not result.stdout.startswith(b'age-encryption.org/v1\n')):
            raise ValueError
        return result.stdout
    except (OSError, ValueError, TypeError, subprocess.TimeoutExpired):
        raise ValueError('ENROLLMENT_ENCRYPTION_FAILED') from None


def verify_recovered(raw, *, expected_reference, expected_scope):
    """Validate operator-supplied decrypted bytes; never grant diagnostic consent."""
    try:
        value = _object(raw, MAX_PLAIN)
        encode_claim(value)
        if (value['reference'] != expected_reference or not _scope(expected_scope)
                or value['credential_scope'] != expected_scope):
            raise ValueError
        return value
    except (ValueError, TypeError, RecursionError, OverflowError, InvalidOperation):
        raise ValueError('ENROLLMENT_RECOVERY_INVALID') from None
