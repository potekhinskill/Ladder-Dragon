# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: define read-side order-journal contracts.

"""Query-side journal contracts."""

from typing import Protocol

from ladder_dragon.execution.journal.models import OrderIntent


class IntentReader(Protocol):
    """Minimum read contract used by recovery."""

    def unresolved(self, symbol: str | None = None) -> list[OrderIntent]:
        """Return non-terminal journal intents."""
