# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: define immutable order-journal records.

"""Order journal models."""

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class OrderIntent:
    """Represent one durable exchange mutation intent."""

    client_order_id: str
    symbol: str
    side: str
    purpose: str
    order_type: str
    quantity: str
    price: str
    state: str
    parent_client_order_id: str | None = None
    exchange_order_id: int | None = None
    exchange_order_list_id: int | None = None
    executed_qty: str = "0"
    cumulative_quote_qty: str = "0"
    metadata: dict[str, Any] | None = None
    last_error: str | None = None
