# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: expose explicit offline enrollment and recovery in an isolated process.
"""Public pins only on argv; UID and recovery identity use the operator terminal."""

import argparse
from decimal import InvalidOperation
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys

FALSE_FIELDS = {'account_authenticated', 'private_fills_authenticated', 'replay_allowed'}
STAGES = {'authorization', 'input', 'process', 'host', 'revision', 'storage', 'credential', 'identity', 'encryption', 'recovery', 'complete'}
_WORKER = '''
import sys
sys.path.insert(0, sys.argv[1])
from ladder_dragon.strategy.enrollment_operator import worker
worker(expected_parent=int(sys.argv[2]))
'''


def blocked(stage):
    return dict(status='BLOCKED', stage=stage, recovery_verified=False,
                account_authenticated=False, private_fills_authenticated=False, replay_allowed=False)


def validate_options(value):
    if (type(value) is not dict or set(value) != {'mode', 'confirmed', 'expected_code_sha',
            'expected_scope', 'recipient', 'recipient_sha256', 'reference', 'ciphertext_sha256'}
            or value['mode'] not in ('create', 'verify') or value['confirmed'] is not True):
        raise ValueError
    for name, size in (('expected_code_sha', 40), ('expected_scope', 64), ('recipient_sha256', 64)):
        if type(value[name]) is not str or re.fullmatch('[0-9a-f]{'+str(size)+'}', value[name]) is None:
            raise ValueError
    if (type(value['recipient']) is not str
            or re.fullmatch('age1[023456789acdefghjklmnpqrstuvwxyz]{58}', value['recipient']) is None
            or hashlib.sha256(value['recipient'].encode()).hexdigest() != value['recipient_sha256']):
        raise ValueError
    for name, size in (('reference', 32), ('ciphertext_sha256', 64)):
        if value['mode'] == 'create':
            if value[name] is not None:
                raise ValueError
        elif type(value[name]) is not str or re.fullmatch('[0-9a-f]{'+str(size)+'}', value[name]) is None:
            raise ValueError
    return value


def safe_result(raw):
    try:
        from ladder_dragon.strategy.account_binding import _object
        value = _object(raw, 1024)
        base = FALSE_FIELDS | {'status', 'stage', 'recovery_verified'}
        if (any(value.get(k) is not False for k in FALSE_FIELDS)
                or type(value.get('stage')) is not str or value['stage'] not in STAGES):
            raise ValueError
        if value.get('status') == 'BLOCKED':
            if set(value) != base or value['recovery_verified'] is not False:
                raise ValueError
        elif value.get('status') == 'RECOVERY_VERIFIED_CLAIM':
            if (set(value) != base | {'reference', 'ciphertext_sha256'}
                    or value['recovery_verified'] is not True or value['stage'] != 'complete'):
                raise ValueError
            for name, size in (('reference', 32), ('ciphertext_sha256', 64)):
                if type(value[name]) is not str or re.fullmatch('[0-9a-f]{'+str(size)+'}', value[name]) is None:
                    raise ValueError
        else:
            raise ValueError
        return value
    except (ValueError, TypeError, RecursionError, OverflowError, InvalidOperation):
        return blocked('process')


def run(value):
    if type(value) is not dict or value.get('confirmed') is not True:
        return blocked('authorization')
    try:
        raw = json.dumps(validate_options(dict(value))).encode()
    except (ValueError, TypeError):
        return blocked('input')
    try:
        result = subprocess.run([sys.executable, '-I', '-c', _WORKER,
                                 str(Path(__file__).resolve().parents[2]), str(os.getpid())],
            input=raw, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            env={'PYTHON_DOTENV_DISABLED': '1'}, cwd='/', close_fds=True,
            timeout=300, check=False)
        return safe_result(result.stdout) if result.returncode == 0 else blocked('process')
    except (OSError, ValueError, TypeError, subprocess.SubprocessError, KeyboardInterrupt):
        return blocked('process')


def operate(value, *, expected_parent=None):
    """Guard host and pinned sources before terminal input; no diagnostic chaining."""
    from ladder_dragon.strategy import enrollment_host as host, enrollment_storage as storage
    from ladder_dragon.strategy import enrollment_registration as registration, enrollment_recovery as recovery
    import getpass
    import os

    directory = None
    stage = 'input'
    try:
        value = validate_options(dict(value))
        stage = 'host'
        host.harden(expected_parent)
        child_setup = host.child_setup()
        stage = 'revision'
        host.check_revision(value['expected_code_sha'])
        stage = 'storage'
        storage.external_store(host.EXTERNAL)
        path = host.EXTERNAL / storage.SLOT / storage.FILE
        if value['mode'] == 'create':
            if os.path.lexists(path.parent):
                raise ValueError
            ciphertext = None
        else:
            ciphertext = host.protected_read(path, maximum=registration.MAX_CIPHER, private=False)
            if hashlib.sha256(ciphertext).hexdigest() != value['ciphertext_sha256']:
                raise ValueError
        stage = 'credential'
        api_key = host.dashboard_key(value['expected_scope'])
        stage = 'identity'
        if value['mode'] == 'create':
            claim = registration.claim(registration.hidden_uid(), api_key)
            stage = 'encryption'
            ciphertext = registration.encrypt_claim(claim, recipient=value['recipient'],
                                 expected_recipient_sha256=value['recipient_sha256'], child_setup=child_setup)
            reference = claim['reference']
        else:
            claim, reference = None, value['reference']
        stage = 'recovery'
        raw = recovery.recover(ciphertext, recipient=value['recipient'], child_setup=child_setup)
        recovered = registration.verify_recovered(raw, expected_reference=reference, expected_scope=value['expected_scope'])
        if claim is not None and registration.encode_claim(recovered) != registration.encode_claim(claim):
            raise ValueError
        if value['mode'] == 'create':
            stage = 'storage'
            directory = storage.reserve(host.EXTERNAL)
            storage.store(directory, ciphertext)
        result = dict(status='RECOVERY_VERIFIED_CLAIM', stage='complete', recovery_verified=True,
            reference=reference, ciphertext_sha256=hashlib.sha256(ciphertext).hexdigest(),
            account_authenticated=False, private_fills_authenticated=False, replay_allowed=False)
        return safe_result(json.dumps(result).encode())
    except (OSError, ValueError, TypeError, KeyError, RuntimeError, EOFError,
            subprocess.SubprocessError, getpass.GetPassWarning, KeyboardInterrupt):
        return blocked(stage)
    finally:
        if directory is not None:
            os.close(directory)


def worker(*, expected_parent=None):
    from decimal import InvalidOperation
    from ladder_dragon.strategy.account_binding import _object
    try:
        value = validate_options(_object(sys.stdin.buffer.read(4097), 4096))
        result = operate(value, expected_parent=expected_parent)
    except (OSError, ValueError, TypeError, KeyError, RecursionError, OverflowError, InvalidOperation):
        result = blocked('input')
    sys.stdout.write(json.dumps(safe_result(json.dumps(result).encode())))


class Parser(argparse.ArgumentParser):
    def error(self, message):
        # Do not echo accidentally supplied private input in parser errors.
        raise ValueError


def main(argv=None):
    parser = Parser(description='Offline operator enrollment. Never pass UID or private keys as arguments.')
    parser.add_argument('--mode', choices=('create', 'verify'), default='create')
    parser.add_argument('--confirmed', action='store_true', help='explicitly permit this one offline operation')
    for name in ('expected-code-sha', 'expected-scope', 'recipient', 'recipient-sha256', 'reference', 'ciphertext-sha256'):
        parser.add_argument('--'+name)
    try:
        value = vars(parser.parse_args(argv))
        result = run(value)
    except ValueError:
        result = blocked('input')
    print(json.dumps(result))
    return 0 if result['status'] == 'RECOVERY_VERIFIED_CLAIM' else 2
