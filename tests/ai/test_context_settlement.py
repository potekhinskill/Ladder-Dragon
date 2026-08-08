# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: verify bounded AI settlement and exact historical price selection.

import sqlite3

import pytest

from ladder_dragon.ai.context.runtime import AdvisorDecisionStore
from ladder_dragon.ai.context.settlement import (
    SETTLEMENT_BATCH_SIZE,
    exact_horizon_open,
)


def _record_decision(store: AdvisorDecisionStore, created_at: int) -> str:
    return store.record(
        symbol="SOLUSDT",
        price="100",
        deterministic_mode="FLAT",
        recommended_mode="UP",
        width_scale=1,
        cap_scale=1,
        confidence=0.8,
        applied=False,
        now=created_at,
    )


def test_settlement_retries_decisions_older_than_one_day(tmp_path):
    store = AdvisorDecisionStore(str(tmp_path / "ai.db"))
    decision_id = _record_decision(store, 1_000)

    assert store.settle(
        "SOLUSDT",
        "999",
        now=1_000 + 172_800,
        price_lookup=lambda _symbol, _target_ms: "101",
    ) == 1

    with sqlite3.connect(store.path) as connection:
        result = connection.execute(
            "SELECT return_15m_text,return_1h_text,return_4h_text "
            "FROM ai_decisions WHERE decision_id=?",
            (decision_id,),
        ).fetchone()
    assert result == ("0.01", "0.01", "0.01")


def test_settlement_batch_includes_oldest_and_newest_due_rows(tmp_path):
    store = AdvisorDecisionStore(str(tmp_path / "ai.db"))
    decision_ids = [
        _record_decision(store, 1_000 + index)
        for index in range(SETTLEMENT_BATCH_SIZE + 8)
    ]

    assert store.settle(
        "SOLUSDT",
        "999",
        now=100_000,
        price_lookup=lambda _symbol, _target_ms: "101",
    ) == SETTLEMENT_BATCH_SIZE

    with sqlite3.connect(store.path) as connection:
        settled = {
            row[0]
            for row in connection.execute(
                "SELECT decision_id FROM ai_decisions WHERE return_4h IS NOT NULL"
            )
        }
    assert decision_ids[0] in settled
    assert decision_ids[-1] in settled
    assert len(settled) == SETTLEMENT_BATCH_SIZE


def test_exact_horizon_open_uses_containing_minute():
    calls = []

    def get_klines(symbol, interval, **params):
        calls.append((symbol, interval, params))
        return [[120_000, "101.25"]]

    assert exact_horizon_open(get_klines, "SOLUSDT", 154_000) == "101.25"
    assert calls == [("SOLUSDT", "1m", {"limit": 1, "startTime": 120_000})]


def test_exact_horizon_open_rejects_later_candle():
    def get_klines(_symbol, _interval, **_params):
        return [[180_000, "999"]]

    with pytest.raises(ValueError, match="does not match"):
        exact_horizon_open(get_klines, "SOLUSDT", 154_000)
