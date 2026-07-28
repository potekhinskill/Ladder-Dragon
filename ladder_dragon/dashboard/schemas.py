# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: define stable dashboard response contracts.

"""Typed dashboard response fragments."""

from typing import TypedDict


class RetryableError(TypedDict):
    ok: bool
    error: str
    retryable: bool
