# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: attribute durable order intents to one immutable CHAMPION policy.
"""Build validated, secret-free CHAMPION order metadata."""

from __future__ import annotations

import os
from typing import Mapping


def execution_attribution(
    metadata: Mapping[str, object] | None = None,
) -> dict[str, object]:
    """Attach a complete CHAMPION identity when the supervisor supplies one."""
    output = dict(metadata or {})
    fields = {
        "activation_id": os.getenv("BOT_CHAMPION_ACTIVATION_ID", "").strip(),
        "champion_fingerprint": os.getenv(
            "BOT_CHAMPION_FINGERPRINT", ""
        ).strip().lower(),
        "execution_policy_fingerprint": os.getenv(
            "BOT_CHAMPION_POLICY_FINGERPRINT", ""
        ).strip().lower(),
    }
    present = [bool(value) for value in fields.values()]
    if any(present) and not all(present):
        raise ValueError("CHAMPION order attribution is incomplete")
    if not all(present):
        return output
    if len(fields["activation_id"]) > 120:
        raise ValueError("CHAMPION activation identity is invalid")
    for name in ("champion_fingerprint", "execution_policy_fingerprint"):
        value = fields[name]
        if len(value) != 64 or any(
            character not in "0123456789abcdef" for character in value
        ):
            raise ValueError(f"CHAMPION {name} is invalid")
    output["champion"] = fields
    return output


__all__ = ["execution_attribution"]
