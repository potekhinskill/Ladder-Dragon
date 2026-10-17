# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: verify protected encrypted launch inputs in a hardened offline worker.
"""No input creation, API requests, private output, or collection dispatch."""

from decimal import InvalidOperation
import getpass
from pathlib import Path
import subprocess
import time

from cryptography.exceptions import InvalidSignature
from cryptography.fernet import Fernet, InvalidToken

from ladder_dragon.strategy import enrollment_host as host
from ladder_dragon.strategy import enrollment_recovery as recovery
from ladder_dragon.strategy import enrollment_registration as registration
from ladder_dragon.strategy import history_input_contract as contract

MANIFEST = Path('/root/.config/ladder-dragon/history-launch-inputs.json')
ENROLLMENT = Path('/mnt/usb1/account-enrollment-v1/enrollment.age')
RECOVERY = Path('/mnt/usb1/history-launch-inputs-v1/export-key.age')
DIAGNOSTIC = Path('/mnt/usb1/history-launch-inputs-v1/diagnostic.fernet')
STAGES = {'manifest', 'enrollment', 'key_recovery', 'credential', 'diagnostic', 'inputs_verified'}


def verify(*, expected_manifest_sha256, code_sha):
    """Caller must harden its process and validate the host before this function."""
    stage = 'manifest'
    try:
        pins = contract.manifest(host.protected_read(MANIFEST, maximum=4096, private=True),
            expected_sha256=expected_manifest_sha256, code_sha=code_sha)
        child_setup = host.child_setup()
        stage = 'enrollment'
        cipher = host.protected_read(ENROLLMENT, maximum=registration.MAX_CIPHER, private=True)
        if contract.digest(cipher) != pins['enrollment_sha256']:
            raise ValueError
        enrollment = registration.verify_recovered(
            recovery.recover(cipher, recipient=pins['recipient'], child_setup=child_setup),
            expected_reference=pins['enrollment_reference'], expected_scope=pins['credential_scope'])
        stage = 'key_recovery'
        cipher = host.protected_read(RECOVERY, maximum=registration.MAX_CIPHER, private=True)
        if contract.digest(cipher) != pins['recovery_sha256']:
            raise ValueError
        key = recovery.recover(cipher, recipient=pins['recipient'], child_setup=child_setup)
        if len(key) != 44 or contract.digest(key) != pins['encryption_key_sha256']:
            raise ValueError
        decryptor = Fernet(key)
        stage = 'credential'
        # Read only the explicitly selected key, not a trade secret or fallback.
        host.dashboard_key(pins['credential_scope'])
        stage = 'diagnostic'
        cipher = host.protected_read(DIAGNOSTIC, maximum=contract.MAX_CIPHER, private=True)
        if contract.digest(cipher) != pins['diagnostic_sha256']:
            raise ValueError
        contract.verify_diagnostic(decryptor.decrypt(cipher), pins=pins, enrollment=enrollment,
                                   now_ms=time.time_ns()//1000000)
        return 'inputs_verified'
    except (OSError, ValueError, TypeError, KeyError, RecursionError, OverflowError,
            InvalidOperation, InvalidSignature, InvalidToken, RuntimeError, EOFError,
            subprocess.SubprocessError, getpass.GetPassWarning, KeyboardInterrupt):
        return stage
