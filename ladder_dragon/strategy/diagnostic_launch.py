# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: externally bound protected diagnostic preparation and request execution.
"""Explicit opt-in library; no CLI, scheduler, history dispatch, or HALT mutation."""

from decimal import InvalidOperation
import json
import os
from pathlib import Path
import re
import selectors
import subprocess
import sys
import time

from ladder_dragon.strategy.account_binding import _object
from ladder_dragon.strategy.history_input_contract import MAX_CIPHER
from ladder_dragon.strategy import history_launcher as preparation
from ladder_dragon.strategy.diagnostic_launch_result import STAGES, report

READY = b'{"stage":"requests"}'
PREPARATION_SECONDS = 300
REQUEST_SECONDS = 35
WORKER = '''
import sys
sys.path.insert(0, sys.argv[1])
from ladder_dragon.strategy.diagnostic_launch import worker
worker(int(sys.argv[2]))
'''


def safe_result(raw):
    try:
        value = _object(raw, 1024)
        stage = value['stage']
        details = {}
        if stage == 'complete':
            size, digest = value['bytes'], value['ciphertext_sha256']
            if (type(size) is not int or not 0 < size <= MAX_CIPHER or type(digest) is not str
                    or re.fullmatch('[0-9a-f]{64}', digest) is None):
                raise ValueError
            details = dict(bytes=size, ciphertext_sha256=digest)
        if type(stage) is not str or stage not in STAGES or value != report(stage, **details):
            raise ValueError
        if any(value[name] is not False for name in (
                'collection_allowed', 'history_complete', 'private_fills_authenticated', 'replay_allowed')):
            raise ValueError
        return value
    except (ValueError, TypeError, KeyError, RecursionError, OverflowError, InvalidOperation):
        return report('process')


def options(value):
    if type(value) is not dict or set(value) != {'confirmed', 'expected_code_sha', 'expected_device', 'manifest_sha256'}:
        raise ValueError
    return preparation.options(value)


def _supervise(process):
    """Bound all output; require one request barrier; kill/reap belongs to run()."""
    deadline = time.monotonic() + PREPARATION_SECONDS
    begun, final, pending, total = False, None, b'', 0
    with selectors.DefaultSelector() as selector:
        selector.register(process.stdout, selectors.EVENT_READ)
        while True:
            left = deadline - time.monotonic()
            if left <= 0 or not selector.select(left):
                return report('deadline')
            chunk = os.read(process.stdout.fileno(), 1024)
            if not chunk:
                if pending or final is None:
                    return report('process')
                try:
                    code = process.wait(timeout=max(0, deadline-time.monotonic()))
                except subprocess.TimeoutExpired:
                    return report('deadline')
                return final if code == 0 else report('process')
            total += len(chunk)
            if total > 2048 or time.monotonic() >= deadline:
                return report('process')
            pending += chunk
            while b'\n' in pending:
                line, pending = pending.split(b'\n', 1)
                if line == READY and not begun and final is None:
                    begun = True
                    deadline = time.monotonic() + REQUEST_SECONDS
                    process.stdin.write(b'GO\n')
                    process.stdin.flush()
                elif final is None and line != READY:
                    final = safe_result(line)
                    if final['stage'] == 'complete' and not begun:
                        return report('process')
                else:
                    return report('process')


def run(value):
    if type(value) is not dict or value.get('confirmed') is not True:
        return report('authorization')
    try:
        raw = json.dumps(options(value)).encode() + b'\n'
    except (ValueError, TypeError):
        return report('input')
    process = None
    try:
        process = subprocess.Popen(
            [sys.executable, '-I', '-c', WORKER, str(Path(__file__).resolve().parents[2]), str(os.getpid())],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            env={'PYTHON_DOTENV_DISABLED': '1'}, cwd='/', close_fds=True)
        process.stdin.write(raw)
        process.stdin.flush()
        return _supervise(process)
    except (OSError, ValueError, subprocess.SubprocessError, KeyboardInterrupt):
        return report('process')
    finally:
        if process is not None:
            if process.poll() is None:
                process.kill()
            process.wait()
            process.stdin.close()
            process.stdout.close()


def worker(parent):
    def begin():
        sys.stdout.buffer.write(READY + b'\n')
        sys.stdout.buffer.flush()
        if sys.stdin.buffer.readline(4) != b'GO\n':
            raise ValueError
    try:
        value = options(_object(sys.stdin.buffer.readline(1025), 1024))
        base = {k: v for k, v in value.items() if k != 'manifest_sha256'}
        checked = preparation.prepare(base, parent)
        if checked['stage'] != 'complete':
            result = report(checked['stage'])
        else:
            from ladder_dragon.strategy.diagnostic_launch_worker import execute
            result = execute(value, begin)
    except (OSError, ValueError, TypeError, KeyError, RecursionError, OverflowError, InvalidOperation):
        result = report('input')
    print(json.dumps(safe_result(json.dumps(result).encode())), flush=True)
