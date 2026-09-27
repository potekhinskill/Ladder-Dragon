# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: verify an operator-held age identity without persistent private files.
"""Anonymous sealed RAM descriptor only; no installed recovery-key discovery."""

import fcntl
import getpass
import os
import re
import subprocess
import warnings

from ladder_dragon.strategy.enrollment_registration import MAX_CIPHER, MAX_PLAIN


def hidden_identity():
    with warnings.catch_warnings():
        warnings.simplefilter('error', getpass.GetPassWarning)
        value = getpass.getpass('Operator-held age identity (hidden): ')
    if type(value) is not str or re.fullmatch('AGE-SECRET-KEY-1[023456789ACDEFGHJKLMNPQRSTUVWXYZ]{58}', value) is None:
        raise ValueError
    return value.encode('ascii') + b'\n'


def recover(ciphertext, *, recipient, child_setup=None):
    """Require the supplied private identity to derive the independently pinned recipient."""
    if (type(ciphertext) is not bytes or not 100 <= len(ciphertext) <= MAX_CIPHER
            or type(recipient) is not str
            or re.fullmatch('age1[023456789acdefghjklmnpqrstuvwxyz]{58}', recipient) is None):
        raise ValueError
    fd = None
    try:
        identity = hidden_identity()
        fd = os.memfd_create('ld-enrollment-recovery', os.MFD_CLOEXEC | os.MFD_ALLOW_SEALING)
        if os.write(fd, identity) != len(identity):
            raise ValueError
        os.lseek(fd, 0, os.SEEK_SET)
        fcntl.fcntl(fd, fcntl.F_ADD_SEALS, fcntl.F_SEAL_WRITE | fcntl.F_SEAL_GROW | fcntl.F_SEAL_SHRINK | fcntl.F_SEAL_SEAL)
        options = dict(stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, env={}, cwd='/',
                       close_fds=True, pass_fds=(fd,), timeout=5, check=True)
        if child_setup is not None:
            options['preexec_fn'] = child_setup
        reference = '/proc/self/fd/' + str(fd)
        public = subprocess.run(['/usr/bin/age-keygen', '-y', reference], **options).stdout.strip()
        if public != recipient.encode('ascii'):
            raise ValueError
        os.lseek(fd, 0, os.SEEK_SET)
        raw = subprocess.run(['/usr/bin/age', '-d', '-i', reference], input=ciphertext, **options).stdout
        if not 0 < len(raw) <= MAX_PLAIN:
            raise ValueError
        return raw
    finally:
        if fd is not None:
            os.close(fd)
