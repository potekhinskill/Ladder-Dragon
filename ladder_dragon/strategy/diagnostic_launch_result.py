# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: share safe diagnostic status without a launcher/worker import cycle.
"""No private data or execution authority in this contract."""

STAGES = {'authorization', 'input', 'process', 'deadline', 'host', 'revision', 'halt', 'storage',
          'manifest', 'enrollment', 'key_recovery', 'signer', 'credential', 'requests', 'persist',
          'package_binding', 'clock', 'account', 'permissions', 'validation', 'package', 'complete'}


def report(stage, **details):
    if stage not in STAGES:
        stage = 'process'
    return dict(status='DIAGNOSTIC_SAVED_ONLY' if stage == 'complete' else 'BLOCKED',
                stage=stage, collection_allowed=False, history_complete=False,
                private_fills_authenticated=False, replay_allowed=False, **details)
