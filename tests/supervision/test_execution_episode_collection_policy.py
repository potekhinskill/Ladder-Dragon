# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: verify selection-only episode collection after superseding version 22.
"""Tests for immutable episode collection lifecycle boundaries."""

from ladder_dragon.supervision.execution_episode_shadow import (
    _episode_collection_role,
)


def _manifest(status: str, *, deadline: int = 2_000) -> dict[str, object]:
    return {
        "current_status": status,
        "confirmation_deadline_ts_ms": deadline,
    }


def test_superseded_v22_collects_only_future_selection_before_deadline():
    assert _episode_collection_role(
        _manifest("SUPERSEDED"), generation="v22", now_ms=1_000
    ) == "FUTURE_SELECTION"
    assert _episode_collection_role(
        _manifest("SUPERSEDED"), generation="v23", now_ms=1_000
    ) is None
    assert _episode_collection_role(
        _manifest("SUPERSEDED"), generation="v22", now_ms=2_001
    ) is None


def test_confirmation_collection_requires_active_lifecycle():
    assert _episode_collection_role(
        _manifest("CONFIRMING"), generation="v22", now_ms=1_000
    ) == "CONFIRMATION"
    assert _episode_collection_role(
        _manifest("REJECTED"), generation="v22", now_ms=1_000
    ) is None
    assert _episode_collection_role(
        None, generation="v22", now_ms=1_000
    ) == "PREBOOTSTRAP"
