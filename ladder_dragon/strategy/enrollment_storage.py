# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: preserve one encrypted enrollment claim without replacing prior evidence.
"""External ciphertext only; no network, plaintext staging, or scheduled reuse."""

import hashlib
import json
import os
import stat

from ladder_dragon.strategy.bnb_capture import external_store
from ladder_dragon.strategy.enrollment_registration import MAX_CIPHER, encode_claim, encrypt_claim

SLOT = 'account-enrollment-v1'
FILE = 'enrollment.age'


def reserve(root):
    """Pin directory descriptors; preserve occupied or partially created slots."""
    mount = external_store(root)
    expected = mount.stat()
    parent = os.open(mount, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    directory = None
    try:
        observed = os.fstat(parent)
        if ((observed.st_dev, observed.st_ino) != (expected.st_dev, expected.st_ino)
                or observed.st_mode & 0o022):
            raise ValueError
        os.mkdir(SLOT, 0o700, dir_fd=parent)
        created = os.stat(SLOT, dir_fd=parent, follow_symlinks=False)
        directory = os.open(SLOT, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent)
        opened = os.fstat(directory)
        if ((opened.st_dev, opened.st_ino) != (created.st_dev, created.st_ino)
                or opened.st_dev != observed.st_dev or opened.st_mode & 0o022):
            raise ValueError
        # exFAT can expose fixed read modes. Only ciphertext enters this directory.
        os.fsync(parent)
        result, directory = directory, None
        return result
    finally:
        if directory is not None:
            os.close(directory)
        os.close(parent)


def store(directory, ciphertext):
    if (type(ciphertext) is not bytes or not 100 <= len(ciphertext) <= MAX_CIPHER
            or not ciphertext.startswith(b'age-encryption.org/v1\n')):
        raise ValueError
    fd = os.open(FILE, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=directory)
    with os.fdopen(fd, 'wb') as output:
        metadata = os.fstat(output.fileno())
        if (not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1
                or metadata.st_dev != os.fstat(directory).st_dev):
            raise ValueError
        output.write(ciphertext)
        output.flush()
        os.fsync(output.fileno())
    os.fsync(directory)


def create(root, value, *, recipient, expected_recipient_sha256, confirmed=False):
    """Caller interlock only; approved custody and protected input remain external."""
    result = dict(status='BLOCKED', stage='authorization', reason='AUTHORIZATION_REQUIRED',
                  recovery_verified=False, account_authenticated=False,
                  private_fills_authenticated=False, replay_allowed=False)
    if confirmed is not True:
        return result
    directory = None
    stage = 'validation'
    try:
        # Freeze the validated claim before subprocess I/O releases the caller.
        value = json.loads(encode_claim(value))
        stage = 'encryption'
        ciphertext = encrypt_claim(value, recipient=recipient,
                                   expected_recipient_sha256=expected_recipient_sha256)
        stage = 'storage'
        directory = reserve(root)
        store(directory, ciphertext)
        result.update(status='ENCRYPTED_ENROLLMENT_CLAIM', stage='complete', reason='CLAIM_ONLY',
                      reference=value['reference'], ciphertext_sha256=hashlib.sha256(ciphertext).hexdigest())
    except (OSError, ValueError, TypeError, OverflowError):
        result.update(stage=stage, reason='ENROLLMENT_CREATE_FAILED')
    finally:
        if directory is not None:
            os.close(directory)
    return result
