# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: validate worker bootstrap inputs before exchange access.

"""Worker bootstrap primitives."""

import re


def normalize_symbol(symbol: str) -> str:
    """Return a Binance symbol or fail before any exchange request."""
    normalized = str(symbol).strip().upper()
    if not re.fullmatch(r"[A-Z0-9]{5,20}", normalized):
        raise ValueError("symbol must match [A-Z0-9]{5,20}")
    return normalized
