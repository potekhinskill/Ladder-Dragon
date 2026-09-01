# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: own explicit default fee assumptions for research and replay models.
"""Named fee assumptions for non-authoritative strategy models."""

from decimal import Decimal


# These values preserve historical research and replay semantics. They are not
# an account fee attestation and cannot authorize LIVE execution.
DEFAULT_RESEARCH_MAKER_FEE_PCT = Decimal("0.00075")
DEFAULT_RESEARCH_TAKER_FEE_PCT = Decimal("0.001")
DEFAULT_RESEARCH_MAKER_FEE_TEXT = format(
    DEFAULT_RESEARCH_MAKER_FEE_PCT, "f"
)
