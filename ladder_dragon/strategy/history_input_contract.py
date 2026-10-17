# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: verify independently pinned diagnostic claims without network authority.
"""Signatures attest a reviewed collector, not the exchange or historical fills."""

import base64
import hashlib
import re

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from ladder_dragon.strategy.account_binding import (
    _object, validate_account_claims, MAX_ACCOUNT_BYTES, MAX_PERMISSION_BYTES,
)

DOMAIN = b'LadderDragon:history-account-diagnostic:v1\x00'
MAX_DIAGNOSTIC = 2 * 1024 * 1024
MAX_CIPHER = 3 * 1024 * 1024
MAX_AGE_MS = 300000
HASHES = {'credential_scope', 'enrollment_sha256', 'recovery_sha256',
          'encryption_key_sha256', 'diagnostic_sha256', 'diagnostic_signer_sha256'}
FIELDS = HASHES | {'schema', 'code_sha', 'diagnostic_code_sha', 'enrollment_reference',
                   'recipient', 'diagnostic_public_key'}


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def manifest(raw, *, expected_sha256, code_sha):
    """The expected digest is supplied independently, never learned from this file."""
    if (type(expected_sha256) is not str or re.fullmatch('[0-9a-f]{64}', expected_sha256) is None
            or type(raw) is not bytes or digest(raw) != expected_sha256):
        raise ValueError
    value = _object(raw, 4096)
    if set(value) != FIELDS or value['schema'] != 'history_launch_inputs_v1' or value['code_sha'] != code_sha:
        raise ValueError
    for key in HASHES | {'diagnostic_public_key'}:
        if type(value[key]) is not str or re.fullmatch('[0-9a-f]{64}', value[key]) is None:
            raise ValueError
    for key in ('code_sha', 'diagnostic_code_sha'):
        if type(value[key]) is not str or re.fullmatch('[0-9a-f]{40}', value[key]) is None:
            raise ValueError
    if (type(value['enrollment_reference']) is not str
            or re.fullmatch('[0-9a-f]{32}', value['enrollment_reference']) is None
            or type(value['recipient']) is not str
            or re.fullmatch('age1[023456789acdefghjklmnpqrstuvwxyz]{58}', value['recipient']) is None
            or digest(bytes.fromhex(value['diagnostic_public_key'])) != value['diagnostic_signer_sha256']):
        raise ValueError
    return value


def verify_diagnostic(raw, *, pins, enrollment, now_ms):
    """Recheck exact signed responses; a summary PASS is never a substitute."""
    envelope = _object(raw, MAX_DIAGNOSTIC)
    if set(envelope) != {'body', 'signature'} or any(type(v) is not str for v in envelope.values()):
        raise ValueError
    body = base64.b64decode(envelope['body'], validate=True)
    if re.fullmatch('[0-9a-f]{128}', envelope['signature']) is None:
        raise ValueError
    Ed25519PublicKey.from_public_bytes(bytes.fromhex(pins['diagnostic_public_key'])).verify(
        bytes.fromhex(envelope['signature']), DOMAIN + body)
    value = _object(body, MAX_DIAGNOSTIC)
    fields = {'schema', 'code_sha', 'credential_scope', 'enrollment_sha256', 'enrollment_reference',
              'started_ms', 'finished_ms', 'elapsed_ms', 'account_body', 'permissions_body',
              'clock_checked', 'request_count'}
    if (set(value) != fields or value['schema'] != 'history_account_diagnostic_v1'
            or value['code_sha'] != pins['diagnostic_code_sha']
            or any(value[k] != pins[k] for k in ('credential_scope','enrollment_sha256','enrollment_reference'))
            or value['clock_checked'] is not True
            or type(value['request_count']) is not int or value['request_count'] != 3):
        raise ValueError
    times = [value[k] for k in ('started_ms', 'finished_ms', 'elapsed_ms')]
    if type(now_ms) is not int or any(type(t) is not int or not 0 < t < 2**63 for t in times):
        raise ValueError
    start, finish, elapsed = times
    if (not start <= finish <= now_ms or not 0 < elapsed <= 35000
            or abs((finish-start)-elapsed) > 2 or now_ms-finish > MAX_AGE_MS):
        raise ValueError
    responses = {}
    for field, limit in (('account_body',MAX_ACCOUNT_BYTES), ('permissions_body',MAX_PERMISSION_BYTES)):
        if type(value[field]) is not str:
            raise ValueError
        responses[field] = base64.b64decode(value[field], validate=True)
        if not 0 < len(responses[field]) <= limit:
            raise ValueError
    checked = validate_account_claims(expected_uid=enrollment['uid'],
        expected_scope=enrollment['credential_scope'], account_scope=value['credential_scope'],
        permission_scope=value['credential_scope'], account_body=responses['account_body'],
        permission_body=responses['permissions_body'])
    if checked['status'] != 'CLAIMS_MATCH_ONLY':
        raise ValueError
    return True
