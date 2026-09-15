# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: merge journal diagnostics without accepting unverified settlement evidence.
"""Transactional metadata updates with settlement exclusion."""

from __future__ import annotations

import json
from typing import Any
from ladder_dragon.execution.journal.buy_inventory import SETTLEMENT_KEY
from ladder_dragon.execution.journal.models import OrderIntent


def update_metadata(
    self,
    client_order_id: str,
    values: dict[str, Any],
) -> OrderIntent:
    """Merge sanitized execution telemetry into an existing intent.

    Metadata is reserved for non-secret lifecycle diagnostics.  Keeping the
    observed market range beside the durable order intent lets cleanup after
    a restart explain why a passive order never traded.
    """
    if SETTLEMENT_KEY in values:
        raise ValueError("BUY settlement requires its verified journal writer")
    with self._session(write=True) as con:
        current = self._from_row(self._row(con, client_order_id))
        if current is None:
            raise KeyError(f"unknown order intent {client_order_id}")
        metadata = dict(current.metadata or {})
        metadata.update(values)
        row = self._update_row(
            con,
            client_order_id,
            {
                "metadata_json": json.dumps(
                    metadata, sort_keys=True, separators=(",", ":")
                )
            },
        )
    updated = self._from_row(row)
    if updated is None:
        raise RuntimeError(f"order intent disappeared: {client_order_id}")
    return updated
