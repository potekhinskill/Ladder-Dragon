# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: verify cutoff-safe L2 veto extraction and sequential cancellation.
"""Tests for the future SHADOW entry-veto selection contract."""

from __future__ import annotations

from decimal import Decimal
import hashlib
import json

import pytest

from ladder_dragon.strategy.market_replay import BookLevel, MarketEvent
from ladder_dragon.strategy.prediction.entry_veto_replay import (
    EntryVetoOpportunity,
    l2_features_before_fill,
    replay_cancel_policy,
    validate_archive,
)


D = Decimal


def _book(timestamp: int, bid: str, bid_qty: str, ask_qty: str) -> MarketEvent:
    price = D(bid)
    return MarketEvent(
        ts_ms=timestamp,
        bids=(BookLevel(price, D(bid_qty)),),
        asks=(BookLevel(price + D("0.01"), D(ask_qty)),),
    )


def test_cancel_latency_keeps_late_fill_and_frees_slot_after_safe_cancel():
    rows = [
        EntryVetoOpportunity(
            "late", 0, 100_000, 300_000, D("-0.12"), 50_000
        ),
        EntryVetoOpportunity(
            "blocked", 120_000, 130_000, 200_000, D("0.03"), None
        ),
        EntryVetoOpportunity(
            "safe", 310_000, 500_000, 700_000, D("-0.12"), 400_000
        ),
        EntryVetoOpportunity(
            "freed", 410_000, 600_000, 650_000, D("0.03"), None
        ),
    ]

    report = replay_cancel_policy(rows, cancel_latency_ms=1_000)

    assert report["late_cancel_signals"] == 1
    assert report["vetoed_before_possible_fill"] == 1
    assert report["skipped_while_position_active"] == 1
    assert report["retained_episode_ids"] == ["late", "freed"]
    assert report["retained_net_pnl_quote"] == "-0.09"


def test_l2_features_use_only_events_before_the_fill_boundary():
    events = [
        _book(1, "100", "10", "10"),
        MarketEvent(
            ts_ms=60_000,
            bids=(BookLevel(D("99.9"), D("2")),),
            asks=(BookLevel(D("99.91"), D("15")),),
            trades=((D("99.9"), D("5"), "SELL"),),
        ),
        MarketEvent(
            ts_ms=120_000,
            bids=(BookLevel(D("99.8"), D("1")),),
            asks=(BookLevel(D("99.81"), D("20")),),
            trades=((D("99.8"), D("5"), "SELL"),),
        ),
        # This future event must not alter any pre-fill feature.
        _book(300_001, "120", "100", "1"),
    ]

    report = l2_features_before_fill(events, fill_ts_ms=300_001)

    assert D(report["prefill_price_change_bps"]) < 0
    assert report["window_ended_at_ms"] == 300_000
    assert report["event_count"] == 3
    assert report["candidate_signal_ts_ms"]


def test_archive_identity_rejects_metadata_that_claims_secrets(tmp_path):
    archive = tmp_path / "SOLUSDT.jsonl"
    row = {
        "lastUpdateId": 1,
        "E": 1,
        "s": "SOLUSDT",
        "bids": [["100", "1"]],
        "asks": [["101", "1"]],
    }
    encoded = (json.dumps(row) + "\n").encode()
    archive.write_bytes(encoded)
    archive.with_suffix(".jsonl.metadata.json").write_text(json.dumps({
        "archive_sha256": hashlib.sha256(encoded).hexdigest(),
        "contains_secrets": True,
    }))

    with pytest.raises(ValueError, match="public source"):
        validate_archive(archive)
