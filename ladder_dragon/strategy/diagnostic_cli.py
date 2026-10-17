# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: expose one explicitly approved diagnostic through its bounded parent.
"""No default execution, scheduler, historical collection, or direct worker call."""

import json
import os

from ladder_dragon.strategy import diagnostic_launch as launch
from ladder_dragon.strategy.history_launcher import Parser


def terminal_available():
    try:
        fd = os.open('/dev/tty', os.O_RDWR | os.O_NOCTTY)
        try:
            return os.isatty(fd)
        finally:
            os.close(fd)
    except OSError:
        return False


def main(argv=None):
    parser = Parser(description='One approved diagnostic attempt; no historical collection.', allow_abbrev=False)
    parser.add_argument('--confirmed', action='store_true')
    parser.add_argument('--expected-code-sha')
    parser.add_argument('--expected-device', type=int)
    parser.add_argument('--manifest-sha256')
    try:
        value = vars(parser.parse_args(argv))
        if value['confirmed'] is not True:
            result = launch.report('authorization')
        else:
            value = launch.options(value)
            result = launch.run(value) if terminal_available() else launch.report('host')
            result = launch.safe_result(json.dumps(result).encode())
    except (ValueError, TypeError):
        result = launch.report('input')
    print(json.dumps(result))
    return 0 if result['status'] == 'DIAGNOSTIC_SAVED_ONLY' else 2
