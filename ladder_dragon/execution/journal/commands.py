# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: define command-side order-journal contracts.

"""Command-side journal types used during incremental extraction."""

from typing import Protocol

from ladder_dragon.execution.journal.models import OrderIntent


class IntentWriter(Protocol):
    """Minimum command contract required by exchange mutation services."""

    def prepare(self, **fields: object) -> OrderIntent:
        """Persist an intent before an exchange mutation."""
