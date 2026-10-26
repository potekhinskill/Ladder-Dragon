# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: keep recovered secrets local to one hardened diagnostic process.
"""Only safe status crosses the process boundary; no secret serialization."""

from decimal import InvalidOperation
import getpass
import io
import json
import os
from pathlib import Path
import subprocess

from cryptography.exceptions import UnsupportedAlgorithm, InvalidSignature
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives.serialization import load_pem_private_key

from ladder_dragon.strategy import enrollment_host as host
from ladder_dragon.strategy import enrollment_registration as registration
from ladder_dragon.strategy import enrollment_recovery as recovery
from ladder_dragon.strategy import history_input_contract as contract
from ladder_dragon.strategy import history_input_loader as locations
from ladder_dragon.strategy import diagnostic_store as storage
from ladder_dragon.strategy.diagnostic_package import _Package, collect_signed_diagnostic
from ladder_dragon.strategy.private_fill_capture import credential_scope

MANIFEST = Path('/root/.config/ladder-dragon/diagnostic-launch.json')
SIGNER = Path('/root/.config/ladder-dragon/diagnostic-signing.pem')
PIN_FIELDS = {'diagnostic_code_sha', 'credential_scope', 'enrollment_sha256',
              'enrollment_reference', 'diagnostic_public_key',
              'diagnostic_signer_sha256', 'encryption_key_sha256'}


def manifest(raw, expected, code_sha):
    value = contract._object(raw, 4096)
    if (contract.digest(raw) != expected or set(value) != contract.FIELDS - {'diagnostic_sha256'}
            or value['schema'] != 'diagnostic_launch_v1' or value['diagnostic_code_sha'] != code_sha):
        raise ValueError
    # Reuse the pin grammar without claiming an output already exists.
    candidate = dict(value, schema='history_launch_inputs_v1', diagnostic_sha256='0'*64)
    encoded = json.dumps(candidate).encode()
    contract.manifest(encoded, expected_sha256=contract.digest(encoded), code_sha=code_sha)
    return value


def execute(value, begin):
    """Host guards precede entry. Recovered bytes never leave this worker process."""
    from dotenv.parser import parse_stream
    from ladder_dragon.strategy.diagnostic_launch_result import report

    stage = 'manifest'
    try:
        pins = manifest(host.protected_read(MANIFEST, maximum=4096, private=True),
                        value['manifest_sha256'], value['expected_code_sha'])
        stage = 'storage'
        # expected_device still pins the external historical archive disk in
        # preparation. Diagnostic inputs must instead remain on the root disk.
        input_device = storage.system_device()
        with storage.reserve(input_device) as (directory, fd):
            setup = host.child_setup()
            stage = 'enrollment'
            cipher = host.protected_read(locations.ENROLLMENT, maximum=registration.MAX_CIPHER, private=True)
            if contract.digest(cipher) != pins['enrollment_sha256']:
                raise ValueError
            enrollment = recovery.recover(cipher, recipient=pins['recipient'], child_setup=setup)
            registration.verify_recovered(enrollment, expected_reference=pins['enrollment_reference'],
                                          expected_scope=pins['credential_scope'])
            stage = 'key_recovery'
            cipher = host.protected_read(locations.RECOVERY, maximum=registration.MAX_CIPHER, private=True)
            if contract.digest(cipher) != pins['recovery_sha256']:
                raise ValueError
            key = recovery.recover(cipher, recipient=pins['recipient'], child_setup=setup)
            if type(key) is not bytes or len(key) != 44 or contract.digest(key) != pins['encryption_key_sha256']:
                raise ValueError
            Fernet(key)
            stage = 'signer'
            signer = load_pem_private_key(host.protected_read(SIGNER, maximum=4096, private=True), password=None)
            selected = {name: pins[name] for name in PIN_FIELDS}
            _Package(pins=selected, signer=signer, encryption_key=key)
            stage = 'credential'
            raw = host.protected_read(host.CREDENTIAL, maximum=65536, private=True)
            names = ('DASHBOARD_BINANCE_API_KEY', 'DASHBOARD_BINANCE_API_SECRET')
            found = {name: [] for name in names}
            for binding in parse_stream(io.StringIO(raw.decode('utf-8'))):
                if binding.error:
                    raise ValueError
                if binding.key in found:
                    found[binding.key].append(binding.value)
            if any(len(values) != 1 for values in found.values()):
                raise ValueError
            pair = tuple(found[name][0] for name in names)
            if (any(type(v) is not str or not 1 <= len(v) <= 256 or not v.isascii() or not v.isalnum() for v in pair)
                    or credential_scope(pair[0]) != pins['credential_scope']):
                raise ValueError
            stage = 'requests'
            # Recovery can take minutes. Repeat host gates before the request barrier.
            from ladder_dragon.strategy import history_launcher as preparation
            checked = preparation.prepare({k: v for k, v in value.items() if k != 'manifest_sha256'}, os.getppid())
            if checked['stage'] != 'complete':
                return report(checked['stage'])
            storage.check(directory, fd, input_device, size=0)
            # Parent arms its 35-second deadline before acknowledging this barrier.
            begin()
            result, ciphertext = collect_signed_diagnostic(enrollment_path=None,
                expected_reference=pins['enrollment_reference'], credentials=pair,
                pins=selected, signer=signer, encryption_key=key, recovered=enrollment, confirmed=True)
            if result['status'] != 'ENCRYPTED_DIAGNOSTIC_ONLY' or ciphertext is None:
                return report(result['stage'])
            stage = 'persist'
            details = storage.store(directory, fd, ciphertext, input_device)
            return report('complete', **details)
    except (OSError, ValueError, TypeError, KeyError, RuntimeError, RecursionError, OverflowError,
            InvalidOperation, UnsupportedAlgorithm, InvalidSignature, EOFError,
            getpass.GetPassWarning, subprocess.SubprocessError):
        return report(stage)
