# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: load protected operator claims without creating account authority.
"""Read-only enrollment loader; no enrollment creation or identity attestation."""

from decimal import InvalidOperation
import os
from pathlib import Path
import re
import stat

from ladder_dragon.strategy.account_binding import _identifier, _object, _scope


def load_enrollment(path, *, expected_reference):
    """Read one protected, bounded record through symlink-free descriptors.

    The independent operator must review the contents before supplying the
    reference. Permissions and reference matching do not authenticate the UID.
    """
    descriptors = []
    try:
        path = os.fspath(path)
        if (type(path) is not str or not path.startswith('/') or len(path) > 4096
                or '\x00' in path or any(p in {'', '.', '..'} for p in path.split('/')[1:])
                or type(expected_reference) is not str
                or re.fullmatch('[0-9a-f]{32}', expected_reference) is None):
            raise ValueError
        parts = Path(path).parts[1:]
        if not 2 <= len(parts) <= 32:
            raise ValueError
        parent = os.open('/', os.O_RDONLY | os.O_DIRECTORY)
        descriptors.append(parent)
        for component in parts[:-1]:
            parent = os.open(component, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                             dir_fd=parent)
            descriptors.append(parent)
        owners = {0, os.geteuid()}
        directory = os.fstat(parent)
        if directory.st_uid not in owners or directory.st_mode & 0o077:
            raise ValueError
        fd = os.open(parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent)
        descriptors.append(fd)
        before = os.fstat(fd)
        if (not stat.S_ISREG(before.st_mode) or before.st_nlink != 1
                or before.st_uid not in owners or stat.S_IMODE(before.st_mode) not in {0o400, 0o600}
                or not 0 < before.st_size <= 4096):
            raise ValueError
        raw = bytearray()
        while len(raw) <= 4096:
            chunk = os.read(fd, 4097-len(raw))
            if not chunk:
                break
            raw.extend(chunk)
        after = os.fstat(fd)
        fields = ('st_dev', 'st_ino', 'st_size', 'st_mtime_ns', 'st_ctime_ns', 'st_mode', 'st_uid', 'st_nlink')
        if len(raw) != before.st_size or any(getattr(before, k) != getattr(after, k) for k in fields):
            raise ValueError
        record = _object(bytes(raw), 4096)
        if (set(record) != {'schema', 'reference', 'uid', 'credential_scope'}
                or record['schema'] != 'account_enrollment_claim_v1'
                or record['reference'] != expected_reference
                or not _identifier(record['uid']) or not _scope(record['credential_scope'])):
            raise ValueError
        return record
    except (OSError, ValueError, TypeError, RecursionError, OverflowError, InvalidOperation):
        raise ValueError('ACCOUNT_ENROLLMENT_INVALID') from None
    finally:
        for fd in reversed(descriptors):
            os.close(fd)
