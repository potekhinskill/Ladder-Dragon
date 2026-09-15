# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: stop a stalled public resolver without retaining signing credentials.
"""Resolve the fixed capture host in an isolated, disposable interpreter."""

import ipaddress
import json
import socket
import subprocess
import sys
import time


_RESOLVER = '''
import json, socket, sys
try:
    rows = socket.getaddrinfo(sys.argv[1], 443, int(sys.argv[2]), socket.SOCK_STREAM)
except OSError:
    sys.exit(2)
if not 0 < len(rows) <= 32:
    sys.exit(3)
print(json.dumps([[af, kind, proto, '', address] for af, kind, proto, _, address in rows]))
'''


def remaining(deadline):
    budget = deadline - time.monotonic()
    if budget <= 0:
        raise socket.timeout('Capture network deadline')
    return budget


def resolve_addresses(host, port, family, kind, *, deadline):
    """Kill and reap a timed-out resolver; never fall back to blocking DNS."""
    if (host != 'data-api.binance.vision' or port != 443
            or family not in (socket.AF_UNSPEC, socket.AF_INET, socket.AF_INET6)
            or kind != socket.SOCK_STREAM):
        raise OSError('Invalid capture resolver target')
    try:
        result = subprocess.run(
            [sys.executable, '-I', '-S', '-c', _RESOLVER, host, str(int(family))],
            stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            # Pi's libc resolver uses TCP; never inherit operator resolver options.
            env={'RES_OPTIONS': 'use-vc'}, cwd='/', close_fds=True,
            timeout=remaining(deadline), check=False,
        )
    except subprocess.TimeoutExpired:
        raise socket.timeout('Capture DNS deadline') from None
    remaining(deadline)
    if result.returncode != 0:
        raise socket.gaierror('Capture DNS failed')
    if len(result.stdout) > 16384:
        raise OSError('Invalid capture DNS result')
    try:
        rows = json.loads(result.stdout)
        if not isinstance(rows, list) or not 0 < len(rows) <= 32:
            raise ValueError
        validated = []
        for row in rows:
            if not isinstance(row, list) or len(row) != 5:
                raise ValueError
            af, socktype, protocol, canonical, address = row
            if (type(af) is not int or af not in (socket.AF_INET, socket.AF_INET6)
                    or type(socktype) is not int or socktype != socket.SOCK_STREAM
                    or type(protocol) is not int or protocol != socket.IPPROTO_TCP
                    or canonical != '' or not isinstance(address, list)
                    or len(address) != (2 if af == socket.AF_INET else 4)):
                raise ValueError
            if type(address[0]) is not str or len(address[0]) > 64:
                raise ValueError
            ip = ipaddress.ip_address(address[0])
            if ip.version != (4 if af == socket.AF_INET else 6):
                raise ValueError
            if type(address[1]) is not int or address[1] != 443:
                raise ValueError
            if any(type(value) is not int or not 0 <= value < 2**32 for value in address[2:]):
                raise ValueError
            validated.append((af, socktype, protocol, '', tuple(address)))
        return validated
    except (ValueError, TypeError, UnicodeError):
        raise OSError('Invalid capture DNS result') from None
