# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: reject unsafe enrollment hosts before private operator input.
"""Linux-only guards and one explicit protected dashboard credential source."""

import ctypes
import io
import os
from pathlib import Path
import pwd
import re
import resource
import stat
import subprocess
import sys
import threading

PROJECT = Path('/home/bot/apps/binance_bot')
EXTERNAL = Path('/mnt/usb1')
CREDENTIAL = PROJECT / '.env.dashboard'


def memory_only_swap(rows, read_backing):
    """Unknown swap devices or zram writeback block private input."""
    lines = rows.splitlines()
    if not lines or not lines[0].startswith('Filename'):
        raise ValueError
    for row in lines[1:]:
        fields = row.split()
        if len(fields) != 5 or re.fullmatch('/dev/zram[0-9]+', fields[0]) is None:
            raise ValueError
        name = fields[0].split('/')[-1]
        if read_backing(name).strip() != 'none':
            raise ValueError


def harden(expected_parent):
    """Only changes this disposable process; no swap or host configuration edits."""
    if (sys.platform != 'linux' or os.geteuid() != 0 or sys.flags.isolated != 1
            or type(expected_parent) is not int or expected_parent <= 1
            or os.environ.get('PYTHON_DOTENV_DISABLED') != '1'
            or set(os.environ) - {'PYTHON_DOTENV_DISABLED', 'LC_CTYPE'}):
        raise ValueError
    memory_only_swap(Path('/proc/swaps').read_text(),
        lambda name: (Path('/sys/class/block') / name / 'backing_dev').read_text())
    mounts = [line.split() for line in Path('/proc/self/mounts').read_text().splitlines()]
    if not any(len(row) >= 3 and row[1:3] == ['/run', 'tmpfs'] for row in mounts):
        raise ValueError
    # Piped core handlers can ignore RLIMIT_CORE; do not rely on that limit alone.
    if Path('/proc/sys/kernel/core_pattern').read_text().lstrip().startswith('|'):
        raise ValueError
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    libc = ctypes.CDLL(None, use_errno=True)
    if libc.prctl(4, 0, 0, 0, 0) != 0 or libc.prctl(3, 0, 0, 0, 0) != 0:
        raise ValueError
    if libc.prctl(1, 9, 0, 0, 0) != 0 or os.getppid() != expected_parent:
        raise ValueError
    if not hasattr(os, 'memfd_create'):
        raise ValueError
    for name in ('age', 'age-keygen'):
        executable = Path('/usr/bin') / name
        info = executable.lstat()
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o6022
                or 'security.capability' in os.listxattr(executable)):
            raise ValueError


def check_revision(expected):
    if type(expected) is not str or re.fullmatch('[0-9a-f]{40}', expected) is None:
        raise ValueError
    if Path(__file__).resolve().parents[2] != PROJECT.resolve():
        raise ValueError
    options = dict(cwd=PROJECT, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                   env={'GIT_CONFIG_NOSYSTEM': '1', 'GIT_CONFIG_GLOBAL': '/dev/null'},
                   close_fds=True, timeout=10, check=True)
    git = ['/usr/bin/git', '--no-replace-objects', '--no-optional-locks',
           '-c', 'core.fsmonitor=false', '-c', 'core.hooksPath=/dev/null',
           '-c', 'safe.directory='+str(PROJECT)]
    actual = subprocess.run(git + ['rev-parse', 'HEAD'], **options).stdout.strip()
    if actual != expected.encode('ascii'):
        raise ValueError
    subprocess.run(git + ['diff', '--no-ext-diff', '--no-textconv', '--quiet', 'HEAD', '--'], **options)
    extra = subprocess.run(git + ['ls-files', '--others', '--exclude-standard',
                                  '--', 'ladder_dragon', 'bin'], **options).stdout
    if extra:
        raise ValueError


def child_setup():
    """Prepare a minimal pre-exec hook only in the disposable single-thread worker."""
    if sys.platform != 'linux' or threading.active_count() != 1:
        raise ValueError
    libc = ctypes.CDLL(None, use_errno=True)
    parent = os.getpid()

    def setup():
        # PR_SET_PDEATHSIG plus a parent-race check closes inherited memfd lifetime.
        if libc.prctl(1, 9, 0, 0, 0) != 0 or os.getppid() != parent:
            os._exit(70)

    return setup


def protected_read(path, *, maximum, private):
    """Bound a stable regular file through symlink-free descriptors."""
    path = Path(path)
    if not path.is_absolute() or '..' in path.parts:
        raise ValueError
    owners = {0, pwd.getpwnam('bot').pw_uid}
    descriptors = []
    try:
        parent = os.open('/', os.O_RDONLY | os.O_DIRECTORY)
        descriptors.append(parent)
        for part in path.parts[1:-1]:
            parent = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent)
            descriptors.append(parent)
            info = os.fstat(parent)
            if info.st_uid not in owners or info.st_mode & 0o022:
                raise ValueError
        fd = os.open(path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent)
        descriptors.append(fd)
        before = os.fstat(fd)
        if (not stat.S_ISREG(before.st_mode) or before.st_nlink != 1 or before.st_uid not in owners
                or not 0 < before.st_size <= maximum or before.st_mode & 0o022
                or (private and stat.S_IMODE(before.st_mode) not in {0o400, 0o600})):
            raise ValueError
        raw = bytearray()
        while len(raw) <= maximum:
            chunk = os.read(fd, maximum+1-len(raw))
            if not chunk:
                break
            raw.extend(chunk)
        after = os.fstat(fd)
        attributes = ('st_dev', 'st_ino', 'st_size', 'st_mtime_ns', 'st_ctime_ns', 'st_mode', 'st_uid', 'st_nlink')
        if len(raw) != before.st_size or any(getattr(before, k) != getattr(after, k) for k in attributes):
            raise ValueError
        return bytes(raw)
    finally:
        for fd in reversed(descriptors):
            os.close(fd)


def dashboard_key(expected_scope):
    from dotenv.parser import parse_stream
    from ladder_dragon.strategy.private_fill_capture import credential_scope

    raw = protected_read(CREDENTIAL, maximum=65536, private=True)
    selected = []
    # No interpolation, environment mutation, fallback credential, or parser logging.
    for binding in parse_stream(io.StringIO(raw.decode('utf-8'))):
        if binding.error:
            raise ValueError
        if binding.key == 'DASHBOARD_BINANCE_API_KEY':
            selected.append(binding.value)
    if len(selected) != 1 or credential_scope(selected[0]) != expected_scope:
        raise ValueError
    return selected[0]
