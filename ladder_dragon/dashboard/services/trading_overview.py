# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: normalize trading-overview provenance for presentation.

"""Trading overview presentation helpers."""


def provenance_label(value: object) -> str:
    """Return a bounded machine label; localization happens in the frontend."""
    label = str(value or "unknown").strip().lower()
    return label if label else "unknown"
