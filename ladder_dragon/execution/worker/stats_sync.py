# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: describe worker statistics synchronization state explicitly.

"""Small statistics synchronization contracts."""

from dataclasses import dataclass


@dataclass(frozen=True)
class StatsSyncConfig:
    """Validated, immutable worker statistics configuration."""

    enabled: bool
    database_path: str

    @property
    def active(self) -> bool:
        return self.enabled and bool(self.database_path.strip())
