# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: reserve one bounded diagnostic ciphertext without replacement.
"""Keep empty reservations and interrupted ciphertext; never unlink them."""

from contextlib import contextmanager
import os
from pathlib import Path
import stat

from ladder_dragon.strategy.history_input_contract import MAX_CIPHER, digest
from ladder_dragon.strategy.storage_ownership import mount_owner_allowed

ROOT = Path('/mnt/usb1')
DIRECTORY = 'history-launch-inputs-v1'
NAME = 'diagnostic.fernet'
RESERVE = 8 * 1024**3 + MAX_CIPHER


@contextmanager
def reserve(expected_device):
    descriptors = []
    try:
        parent = os.open('/', os.O_RDONLY | os.O_DIRECTORY)
        descriptors.append(parent)
        for index, part in enumerate(ROOT.parts[1:], start=1):
            parent = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent)
            descriptors.append(parent)
            info = os.fstat(parent)
            owner_ok = (mount_owner_allowed(info.st_uid) if index == len(ROOT.parts)-1
                        else info.st_uid == os.geteuid())
            if not owner_ok or info.st_mode & 0o022:
                raise ValueError
        info = os.fstat(parent)
        if (not os.path.ismount(ROOT) or info.st_dev != expected_device
                or info.st_dev == os.fstat(descriptors[0]).st_dev):
            raise ValueError
        directory = os.open(DIRECTORY, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent)
        descriptors.append(directory)
        info = os.fstat(directory)
        space = os.fstatvfs(directory)
        if (info.st_dev != expected_device or info.st_uid != os.geteuid()
                or stat.S_IMODE(info.st_mode) != 0o700 or space.f_bavail * space.f_frsize < RESERVE):
            raise ValueError
        fd = os.open(NAME, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=directory)
        descriptors.append(fd)
        os.fsync(fd)
        os.fsync(directory)
        yield directory, fd
    finally:
        for fd in reversed(descriptors):
            os.close(fd)


def check(directory, fd, expected_device, *, size):
    folder, info = os.fstat(directory), os.fstat(fd)
    # A trusted mount owner can rename a root-owned child. Never accept a
    # detached or substituted directory merely because its old descriptor works.
    root = os.open(ROOT, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        mount = os.fstat(root)
        if (mount.st_dev != expected_device or not mount_owner_allowed(mount.st_uid)
                or mount.st_mode & 0o022 or not os.path.ismount(ROOT)):
            raise ValueError
        current = os.open(DIRECTORY, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=root)
        try:
            named_folder = os.fstat(current)
            if (folder.st_dev, folder.st_ino) != (named_folder.st_dev, named_folder.st_ino):
                raise ValueError
        finally:
            os.close(current)
    finally:
        os.close(root)
    named = os.stat(NAME, dir_fd=directory, follow_symlinks=False)
    if (not stat.S_ISDIR(folder.st_mode) or folder.st_uid != os.geteuid()
            or stat.S_IMODE(folder.st_mode) != 0o700 or folder.st_dev != expected_device
            or not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid()
            or stat.S_IMODE(info.st_mode) != 0o600 or info.st_dev != expected_device
            or info.st_nlink != 1 or info.st_size != size
            or (info.st_dev, info.st_ino) != (named.st_dev, named.st_ino)):
        raise ValueError


def store(directory, fd, ciphertext, expected_device):
    if type(ciphertext) is not bytes or not 0 < len(ciphertext) <= MAX_CIPHER:
        raise ValueError
    check(directory, fd, expected_device, size=0)
    offset = 0
    while offset < len(ciphertext):
        written = os.write(fd, ciphertext[offset:])
        if written <= 0:
            raise OSError
        offset += written
    os.fsync(fd)
    check(directory, fd, expected_device, size=len(ciphertext))
    os.fsync(directory)
    return dict(bytes=len(ciphertext), ciphertext_sha256=digest(ciphertext))
