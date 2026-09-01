# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: share immutable v23 producer and consumer contract identifiers.
"""Identifiers shared by every v23 confirmation evidence boundary."""

V23_CONFIRMATION_CAPACITY_POLICY = (
    "bonferroni_clopper_pearson_capacity_preflight_v2"
)
V23_CONFIRMATION_COHORT_SCHEMA_VERSION = 3
V23_CONFIRMATION_REQUEST_SCHEMA_VERSION = 2
V23_CONFIRMATION_BLOCK_SCHEMA_VERSION = 1

V23_CONFIRMATION_REQUEST_FIELDS = frozenset({
    "request_schema_version",
    "cohort_contract",
    "stability_block_index",
    "policy",
    "paths",
})


__all__ = [
    "V23_CONFIRMATION_BLOCK_SCHEMA_VERSION",
    "V23_CONFIRMATION_CAPACITY_POLICY",
    "V23_CONFIRMATION_COHORT_SCHEMA_VERSION",
    "V23_CONFIRMATION_REQUEST_FIELDS",
    "V23_CONFIRMATION_REQUEST_SCHEMA_VERSION",
]
