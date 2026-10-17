# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: check the protected history-launch environment without private input.
"""Offline preparation and optional protected input verification; never collect."""

import argparse
from decimal import InvalidOperation
import json
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import sys

from ladder_dragon.strategy.storage_ownership import mount_owner_allowed

STAGES = {'authorization', 'input', 'process', 'host', 'revision', 'halt', 'storage', 'complete',
          'manifest', 'enrollment', 'key_recovery', 'credential', 'diagnostic', 'inputs_verified'}
HALT = Path('/var/lib/ladder-dragon/control/circuit_halt.json')
ROOT = Path('/mnt/usb1')
SLOT = ROOT / 'historical-sol-source-v1'
RESERVE = 8 * 1024**3 + 16 * 1024**2
WORKER = '''
import sys
sys.path.insert(0, sys.argv[1])
from ladder_dragon.strategy.history_launcher import worker
worker(int(sys.argv[2]))
'''


def result(stage):
    status = {'complete':'PREPARATION_ONLY', 'inputs_verified':'INPUT_CLAIMS_VERIFIED_ONLY'}.get(stage, 'BLOCKED')
    return dict(status=status,
                stage=stage, collection_allowed=False, history_complete=False,
                private_fills_authenticated=False, replay_allowed=False)


def options(value):
    if (type(value) is not dict
            or set(value) not in ({'confirmed', 'expected_code_sha', 'expected_device'},
                                 {'confirmed', 'expected_code_sha', 'expected_device', 'manifest_sha256'})
            or value['confirmed'] is not True
            or type(value['expected_code_sha']) is not str
            or re.fullmatch('[0-9a-f]{40}', value['expected_code_sha']) is None
            or type(value['expected_device']) is not int
            or not 0 < value['expected_device'] < 2**63):
        raise ValueError
    if 'manifest_sha256' in value and (type(value['manifest_sha256']) is not str
            or re.fullmatch('[0-9a-f]{64}', value['manifest_sha256']) is None):
        raise ValueError
    return value


def safe_result(raw):
    from ladder_dragon.strategy.account_binding import _object
    try:
        value = _object(raw, 1024)
        if (type(value.get('stage')) is not str or value['stage'] not in STAGES
                or value != result(value['stage'])):
            raise ValueError
        # Equality alone accepts 0 in place of False.
        if any(value[k] is not False for k in (
                'collection_allowed', 'history_complete', 'private_fills_authenticated', 'replay_allowed')):
            raise ValueError
        return value
    except (ValueError, TypeError, RecursionError, OverflowError, InvalidOperation):
        return result('process')


def prepare(value, parent):
    from ladder_dragon.strategy import enrollment_host as host
    stage = 'input'
    try:
        value = options(value)
        stage = 'host'
        host.harden(parent)
        stage = 'revision'
        host.check_revision(value['expected_code_sha'])
        stage = 'halt'
        # Inspect only metadata: the halt reason can contain private details.
        info = HALT.lstat()
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
            raise ValueError
        stage = 'storage'
        info = ROOT.lstat()
        if (not stat.S_ISDIR(info.st_mode) or not os.path.ismount(ROOT)
                or info.st_dev != value['expected_device']
                or info.st_dev == Path('/').stat().st_dev
                or not mount_owner_allowed(info.st_uid) or info.st_mode & 0o022
                or shutil.disk_usage(ROOT).free < RESERVE or os.path.lexists(SLOT)):
            raise ValueError
        if 'manifest_sha256' in value:
            # No private-input import or access before every host guard passes.
            from ladder_dragon.strategy.history_input_loader import verify
            return result(verify(expected_manifest_sha256=value['manifest_sha256'],
                                 code_sha=value['expected_code_sha']))
        return result('complete')
    except (OSError, ValueError, TypeError, KeyError, RuntimeError, subprocess.SubprocessError):
        return result(stage)


def run(value):
    if type(value) is not dict or value.get('confirmed') is not True:
        return result('authorization')
    try:
        raw = json.dumps(options(value)).encode()
    except (ValueError, TypeError):
        return result('input')
    try:
        completed = subprocess.run(
            [sys.executable, '-I', '-c', WORKER, str(Path(__file__).resolve().parents[2]), str(os.getpid())],
            input=raw, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            env={'PYTHON_DOTENV_DISABLED': '1'}, cwd='/', close_fds=True,
            timeout=300 if 'manifest_sha256' in value else 35, check=False)
        return safe_result(completed.stdout) if completed.returncode == 0 else result('process')
    except (OSError, ValueError, subprocess.SubprocessError, KeyboardInterrupt):
        return result('process')


def worker(parent):
    from ladder_dragon.strategy.account_binding import _object
    try:
        value = options(_object(sys.stdin.buffer.read(1025), 1024))
        report = prepare(value, parent)
    except (OSError, ValueError, TypeError, KeyError, RecursionError, OverflowError, InvalidOperation):
        report = result('input')
    print(json.dumps(safe_result(json.dumps(report).encode())))


class Parser(argparse.ArgumentParser):
    def error(self, message):
        # Never echo an accidentally supplied credential or UID.
        raise ValueError


def main(argv=None):
    parser = Parser(description='Offline history preparation. Optional pinned input verification; no API requests.')
    parser.add_argument('--confirmed', action='store_true')
    parser.add_argument('--expected-code-sha')
    parser.add_argument('--expected-device', type=int)
    parser.add_argument('--manifest-sha256', default=argparse.SUPPRESS,
                        help='independently reviewed manifest digest; explicitly enables private input verification')
    try:
        report = run(vars(parser.parse_args(argv)))
    except ValueError:
        report = result('input')
    print(json.dumps(report))
    # Preparation success is deliberately not collection admission.
    return 2
