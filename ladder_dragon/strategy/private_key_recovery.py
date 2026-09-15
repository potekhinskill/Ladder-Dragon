# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: wrap one in-memory export key for an independently selected age recipient.
"""No key generation, credential discovery, plaintext files, or archive writes."""
import hashlib
import re
import subprocess

from cryptography.fernet import Fernet


def wrap_key(key, *, recipient, expected_recipient_sha256):
    """Send only the key on stdin; exclude all inherited credential environment."""
    try:
        if (type(key) is not bytes or len(key) != 44 or type(recipient) is not str
                or re.fullmatch(r'age1[023456789acdefghjklmnpqrstuvwxyz]{58}', recipient) is None
                or type(expected_recipient_sha256) is not str
                or hashlib.sha256(recipient.encode()).hexdigest() != expected_recipient_sha256):
            raise ValueError
        Fernet(key)
        result = subprocess.run(['/usr/bin/age', '-r', recipient], input=key,
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, env={}, cwd='/',
            close_fds=True, timeout=5, check=False)
        if (result.returncode != 0 or type(result.stdout) is not bytes
                or not 100 <= len(result.stdout) <= 16384
                or not result.stdout.startswith(b'age-encryption.org/v1\n')):
            raise ValueError
        return result.stdout
    except (OSError, ValueError, TypeError, subprocess.TimeoutExpired):
        raise ValueError('PRIVATE_KEY_RECOVERY_FAILED') from None
