# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: kill and reap a stalled account diagnostic without credential output.
"""Isolated-interpreter deadline wrapper, not an operating-system sandbox.

No enrollment is created, and no production caller or automatic job is wired.
Credentials cross an anonymous stdin pipe, never argv or inherited environment.
"""

from decimal import InvalidOperation
import json
from pathlib import Path
import re
import subprocess
import sys

from ladder_dragon.strategy.account_binding import _object


_WORKER = '''
import sys
sys.path.insert(0, sys.argv[1])
from ladder_dragon.strategy.account_diagnostic_process import worker
worker()
'''
_STAGES = frozenset({'enrollment', 'credential', 'clock', 'account', 'permissions', 'validation'})
_REASONS = frozenset({
    'BINDING_INVALID', 'CREDENTIAL_SCOPE_MISMATCH', 'ACCOUNT_BODY_INVALID',
    'ACCOUNT_IDENTITY_INVALID', 'ACCOUNT_IDENTITY_MISMATCH', 'PERMISSION_BODY_INVALID',
    'PERMISSION_SCHEMA_INVALID', 'READ_PERMISSION_REQUIRED', 'MUTATION_PERMISSION_ENABLED',
    'ACCOUNT_DIAGNOSTIC_FAILED',
})


def _blocked(reason):
    return dict(status='BLOCKED', stage='process', reason=reason,
                account_authenticated=False, private_fills_authenticated=False, replay_allowed=False)


def _request(path, reference, credentials):
    if (type(path) is not str or not 0 < len(path) <= 4096 or '\x00' in path
            or not path.startswith('/') or type(reference) is not str
            or re.fullmatch('[0-9a-f]{32}', reference) is None
            or type(credentials) is not tuple or len(credentials) != 2
            or any(type(v) is not str or not 1 <= len(v) <= 256
                   or not v.isascii() or not v.isalnum() for v in credentials)):
        raise ValueError
    raw = json.dumps(dict(enrollment_path=path, expected_reference=reference,
                          credentials=credentials)).encode()
    if len(raw) > 8192:
        raise ValueError
    return raw


def _safe_result(raw):
    try:
        value = _object(raw, 1024)
        if (set(value) != {'status', 'stage', 'reason', 'account_authenticated',
                           'private_fills_authenticated', 'replay_allowed'}
                or any(value[k] is not False for k in ('account_authenticated',
                        'private_fills_authenticated', 'replay_allowed'))
                or value['stage'] not in _STAGES):
            raise ValueError
        if value['status'] == 'DIAGNOSTIC_MATCH_ONLY':
            if value['reason'] != 'MATCH' or value['stage'] != 'validation':
                raise ValueError
        elif value['status'] != 'BLOCKED' or value['reason'] not in _REASONS:
            raise ValueError
        return value
    except (ValueError, TypeError, RecursionError, OverflowError, InvalidOperation):
        return _blocked('WORKER_RESULT_INVALID')


def run_isolated_diagnostic(*, enrollment_path, expected_reference, credentials,
                           confirmed=False, deadline_sec=35):
    """Run once with a bounded deadline; subprocess.run kills and reaps on timeout.

    Explicit confirmation is a caller interlock, not independent authorization.
    The operating system can delay process creation or termination; no hard
    real-time guarantee is made. No automatic retry is permitted.
    """
    if confirmed is not True:
        return _blocked('AUTHORIZATION_REQUIRED')
    if type(deadline_sec) is not int or not 1 <= deadline_sec <= 35:
        return _blocked('DEADLINE_INVALID')
    try:
        raw = _request(enrollment_path, expected_reference, credentials)
        result = subprocess.run(
            [sys.executable, '-I', '-c', _WORKER, str(Path(__file__).resolve().parents[2])],
            input=raw, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            env={'PYTHON_DOTENV_DISABLED': '1'}, cwd='/', close_fds=True,
            timeout=deadline_sec, check=False,
        )
    except subprocess.TimeoutExpired:
        return _blocked('PROCESS_DEADLINE')
    except (OSError, ValueError, TypeError):
        return _blocked('PROCESS_START_FAILED')
    if result.returncode != 0:
        return _blocked('WORKER_FAILED')
    return _safe_result(result.stdout)


def worker():
    """Internal stdin boundary; only the fixed validated status reaches stdout."""
    from ladder_dragon.strategy.account_diagnostic import diagnose_account

    try:
        value = _object(sys.stdin.buffer.read(8193), 8192)
        if set(value) != {'enrollment_path', 'expected_reference', 'credentials'}:
            raise ValueError
        if type(value['credentials']) is not list:
            raise ValueError
        value['credentials'] = tuple(value['credentials'])
        _request(value['enrollment_path'], value['expected_reference'], value['credentials'])
        result = diagnose_account(**value)
        result = _safe_result(json.dumps(result).encode())
    except (ValueError, TypeError, KeyError, RecursionError, OverflowError, OSError, InvalidOperation):
        result = _blocked('WORKER_INPUT_INVALID')
    sys.stdout.write(json.dumps(result))
