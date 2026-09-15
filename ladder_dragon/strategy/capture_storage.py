# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: bound two exclusive public capture slots without deleting evidence.
"""Only fixed slot names and metadata checks; never read archive contents."""

import os
import stat

SLOTS = {'original': 'bnb-public-capture', 'signed-test': 'bnb-public-capture-signed-test'}
FILES = {'observations.jsonl', 'manifest.json', 'clock.json', 'attestation.json', 'attestation.sig'}
SLOT_BYTES = 64 * 1024 * 1024


def check_slots(mount):
    total = 0
    device = mount.stat().st_dev
    for name in SLOTS.values():
        path = mount / name
        try:
            info = path.lstat()
        except FileNotFoundError:
            continue
        if not stat.S_ISDIR(info.st_mode) or info.st_dev != device:
            raise ValueError('CAPTURE_SLOT_DIRECTORY')
        size = 0
        fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            opened = os.fstat(fd)
            if (opened.st_dev, opened.st_ino) != (info.st_dev, info.st_ino):
                raise ValueError('CAPTURE_SLOT_CHANGED')
            with os.scandir(fd) as entries:
                for count, entry in enumerate(entries, 1):
                    if count > len(FILES) or entry.name not in FILES:
                        raise ValueError('CAPTURE_SLOT_CONTENTS')
                    entry_info = entry.stat(follow_symlinks=False)
                    if (not stat.S_ISREG(entry_info.st_mode) or entry_info.st_dev != device
                            or entry_info.st_nlink != 1):
                        raise ValueError('CAPTURE_SLOT_FILE')
                    size += entry_info.st_size
                    if size > SLOT_BYTES:
                        raise ValueError('CAPTURE_SLOT_CAPACITY')
        finally:
            os.close(fd)
        total += size
    if total > 2 * SLOT_BYTES:
        raise ValueError('CAPTURE_TOTAL_CAPACITY')
    return total


def prepare_slot(mount, slot):
    if not isinstance(slot, str) or slot not in SLOTS:
        raise ValueError('CAPTURE_SLOT_INVALID')
    check_slots(mount)
    target = mount / SLOTS[slot]
    target.mkdir(mode=0o700)
    return target
