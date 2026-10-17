# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: distinguish the trusted mount owner from the private output owner.
"""The production caller is root after hardening; only the mount can belong to bot."""

import os
import pwd


def mount_owner_allowed(uid):
    if type(uid) is not int or uid < 0:
        return False
    if uid == os.geteuid():
        return True
    try:
        bot_uid = pwd.getpwnam('bot').pw_uid
    except (KeyError, OSError):
        return False
    return type(bot_uid) is int and bot_uid > 0 and uid == bot_uid
