# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: load a bounded pinned Ed25519 credential without exposing key material.
"""Local credential loader, not production key creation or enrollment."""

import hashlib
import os
from pathlib import Path
import re
import stat

from cryptography.exceptions import UnsupportedAlgorithm
from cryptography.hazmat.primitives.serialization import load_pem_private_key, Encoding, PublicFormat
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey


def load_capture_key(path, *, expected_public_sha256):
    """Resolve every component without symlinks; pin the resulting public key."""
    if (not isinstance(expected_public_sha256, str)
            or re.fullmatch('[0-9a-f]{64}', expected_public_sha256) is None):
        raise ValueError('CAPTURE_KEY_PIN_INVALID')
    path = os.fspath(path)
    if (not isinstance(path, str) or not path.startswith('/') or len(path) > 4096
            or '\x00' in path or any(p in {'.', '..', ''} for p in path.split('/')[1:])):
        raise ValueError('CAPTURE_KEY_PATH_INVALID')
    parts = Path(path).parts[1:]
    if not 2 <= len(parts) <= 32:
        raise ValueError('CAPTURE_KEY_PATH_INVALID')
    descriptors = []
    try:
        parent = os.open('/', os.O_RDONLY | os.O_DIRECTORY)
        descriptors.append(parent)
        for component in parts[:-1]:
            parent = os.open(component, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent)
            descriptors.append(parent)
        directory = os.fstat(parent)
        owners = {0, os.geteuid()}
        if directory.st_uid not in owners or directory.st_mode & 0o077:
            raise ValueError('CAPTURE_KEY_DIRECTORY_PERMISSIONS')
        fd = os.open(parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent)
        descriptors.append(fd)
        before = os.fstat(fd)
        if (not stat.S_ISREG(before.st_mode) or before.st_nlink != 1
                or before.st_uid not in owners or stat.S_IMODE(before.st_mode) not in {0o400, 0o600}
                or not 0 < before.st_size <= 4096):
            raise ValueError('CAPTURE_KEY_FILE_PERMISSIONS')
        raw = bytearray()
        while len(raw) <= 4096:
            chunk = os.read(fd, min(1024, 4097-len(raw)))
            if not chunk:
                break
            raw.extend(chunk)
        after = os.fstat(fd)
        fields = ('st_dev', 'st_ino', 'st_size', 'st_mtime_ns', 'st_ctime_ns', 'st_mode', 'st_uid', 'st_nlink')
        if len(raw) != before.st_size or any(getattr(before, k) != getattr(after, k) for k in fields):
            raise ValueError('CAPTURE_KEY_CHANGED')
        try:
            key = load_pem_private_key(bytes(raw), password=None)
        except (ValueError, TypeError, UnsupportedAlgorithm):
            raise ValueError('CAPTURE_KEY_FORMAT_INVALID') from None
        if not isinstance(key, Ed25519PrivateKey):
            raise ValueError('CAPTURE_KEY_ALGORITHM_INVALID')
        public = key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
        if hashlib.sha256(public).hexdigest() != expected_public_sha256:
            raise ValueError('CAPTURE_KEY_PIN_MISMATCH')
        return key
    finally:
        for fd in reversed(descriptors):
            os.close(fd)
