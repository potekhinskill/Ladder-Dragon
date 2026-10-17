# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: encrypt signed observations from the canonical diagnostic request chain.
"""Library integration only; no CLI, storage writer, or production activation.

The caller must verify host isolation, code and enrollment custody, key recovery,
and independent pins before entry. An outer process deadline remains mandatory.
Signatures attest collector claims, not exchange signatures or history completeness.
"""

import base64
import json
import re

from cryptography.fernet import Fernet
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

from ladder_dragon.strategy.account_diagnostic import _diagnose
from ladder_dragon.strategy import history_input_contract as contract


def _encode(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':')).encode('ascii')


class _Package:
    """Private one-shot sink; never returns raw responses to the public caller."""

    def __init__(self, *, pins, signer, encryption_key):
        fields = {'diagnostic_code_sha', 'credential_scope', 'enrollment_sha256',
                  'enrollment_reference', 'diagnostic_public_key',
                  'diagnostic_signer_sha256', 'encryption_key_sha256'}
        if type(pins) is not dict or set(pins) != fields:
            raise ValueError
        self.pins = pins.copy()
        for name in fields:
            size = 40 if name == 'diagnostic_code_sha' else 32 if name == 'enrollment_reference' else 64
            if type(pins[name]) is not str or re.fullmatch('[0-9a-f]{%d}' % size, pins[name]) is None:
                raise ValueError
        if not isinstance(signer, Ed25519PrivateKey):
            raise ValueError
        public = signer.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
        if (public.hex() != pins['diagnostic_public_key']
                or contract.digest(public) != pins['diagnostic_signer_sha256']
                or type(encryption_key) is not bytes or len(encryption_key) != 44
                or contract.digest(encryption_key) != pins['encryption_key_sha256']):
            raise ValueError
        self.encryptor = Fernet(encryption_key)
        self.signer = signer
        self.ciphertext = None

    def bind(self, record):
        if (record['reference'] != self.pins['enrollment_reference']
                or record['credential_scope'] != self.pins['credential_scope']):
            raise ValueError

    def finish(self, *, record, **observations):
        if self.ciphertext is not None:
            raise ValueError
        value = dict(observations, schema='history_account_diagnostic_v1',
                     code_sha=self.pins['diagnostic_code_sha'], clock_checked=True)
        for name in ('credential_scope', 'enrollment_sha256', 'enrollment_reference'):
            value[name] = self.pins[name]
        for name in ('account_body', 'permissions_body'):
            value[name] = base64.b64encode(value[name]).decode('ascii')
        body = _encode(value)
        raw = _encode(dict(body=base64.b64encode(body).decode('ascii'),
                           signature=self.signer.sign(contract.DOMAIN + body).hex()))
        # Round-trip the consumer contract before releasing any ciphertext.
        contract.verify_diagnostic(raw, pins=self.pins, enrollment=record,
                                   now_ms=value['finished_ms'])
        cipher = self.encryptor.encrypt(raw)
        if len(cipher) > contract.MAX_CIPHER:
            raise ValueError
        self.ciphertext = cipher


def collect_signed_diagnostic(*, enrollment_path, expected_reference, credentials,
                              pins, signer, encryption_key, confirmed=False, recovered=None):
    """Return (safe summary, encrypted bytes or None); never log the second item.

    Confirmation is an interlock, not authorization. No files or trust manifests
    are created. Production callers need a separately reviewed protected wrapper.
    """
    result = dict(status='BLOCKED', stage='authorization', collection_allowed=False,
                  history_complete=False, private_fills_authenticated=False, replay_allowed=False)
    if confirmed is not True:
        return result, None
    result['stage'] = 'package_binding'
    try:
        package = _Package(pins=pins, signer=signer, encryption_key=encryption_key)
    except (ValueError, TypeError, KeyError):
        return result, None
    diagnostic = _diagnose(enrollment_path=enrollment_path,
        expected_reference=expected_reference, credentials=credentials, package=package, recovered=recovered)
    result['stage'] = diagnostic['stage']
    if diagnostic['status'] != 'DIAGNOSTIC_MATCH_ONLY' or package.ciphertext is None:
        return result, None
    result.update(status='ENCRYPTED_DIAGNOSTIC_ONLY', stage='complete')
    return result, package.ciphertext
