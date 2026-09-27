# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: bound private history retrieval independently of operating-system DNS.
"""Clean-interpreter deadline wrapper, not an operating-system sandbox."""

from decimal import InvalidOperation
from pathlib import Path
import subprocess
import sys

from ladder_dragon.strategy.history_process_contract import (
    MAX_INPUT, blocked, request, parse_request, safe_result,
)
from ladder_dragon.strategy.private_fill_export import _encode

_WORKER = '''
import sys
sys.path.insert(0, sys.argv[1])
from ladder_dragon.strategy.history_capture_process import worker
worker()
'''


def run(root, *, authorized=False, deadline_sec=150, **kwargs):
    """Authorization is a caller interlock, not proof of operator or source consent."""
    if authorized is not True:
        return blocked('AUTHORIZATION_REQUIRED')
    if type(deadline_sec) is not int or not 1 <= deadline_sec <= 150:
        return blocked('DEADLINE_INVALID')
    try:
        raw = request(root, **kwargs)
        result = subprocess.run(
            [sys.executable, '-I', '-c', _WORKER, str(Path(__file__).resolve().parents[2])],
            input=raw, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            env={'PYTHON_DOTENV_DISABLED': '1'}, cwd='/', close_fds=True,
            timeout=deadline_sec, check=False,
        )
    except subprocess.TimeoutExpired:
        return blocked('PROCESS_TIMEOUT')
    except (OSError, ValueError, TypeError, OverflowError):
        return blocked('PROCESS_START_FAILED')
    if result.returncode != 0:
        return blocked('WORKER_FAILED')
    return safe_result(result.stdout)


def worker():
    """Read bounded private input, emit only validated status, never tracebacks."""
    from ladder_dragon.strategy.history_capture import collect

    try:
        root, kwargs = parse_request(sys.stdin.buffer.read(MAX_INPUT + 1))
        result = safe_result(_encode(collect(root, **kwargs)))
    except (OSError, ValueError, TypeError, KeyError, AttributeError,
            RecursionError, OverflowError, InvalidOperation):
        result = blocked('WORKER_INPUT_INVALID')
    sys.stdout.buffer.write(_encode(result))
