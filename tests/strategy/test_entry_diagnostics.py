# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: verify cutoff-safe post-fill SHADOW diagnostics.
"""Tests for persistent entry-quality diagnostics."""

from __future__ import annotations

from decimal import Decimal
import hashlib
import json
import sqlite3

import pytest

from ladder_dragon.strategy.market_replay import BookLevel, MarketEvent
from ladder_dragon.strategy.prediction.entry_diagnostics import (
    EntryApproachTracker,
    advance_entry_diagnostics,
    entry_diagnostic_report,
    fee_aware_candidate_economics,
    import_entry_veto_l2_history,
    start_entry_diagnostic,
)
from ladder_dragon.strategy.prediction.experiment_lifecycle import candidate_rule
from ladder_dragon.strategy.prediction.experiments import ShadowVariant
from ladder_dragon.strategy.prediction.models import TradePlan
from ladder_dragon.strategy.prediction.episode_evidence import (
    record_episode_result,
    record_episode_start,
)
from ladder_dragon.strategy.prediction.execution_episode import (
    ExecutionEpisodeResult,
    ExecutionEpisodeSpec,
)
from ladder_dragon.strategy.prediction.runtime import PredictionShadowStore


D = Decimal


def _event(timestamp_ms: int, bid: str, *, sell_flow: bool = False) -> MarketEvent:
    price = D(bid)
    return MarketEvent(
        ts_ms=timestamp_ms,
        bids=(BookLevel(price, D("2")),),
        asks=(BookLevel(price + D("0.01"), D("1")),),
        trades=((price, D("1"), "SELL" if sell_flow else "BUY"),),
    )


def _spec(episode_id: str, fingerprint: str) -> ExecutionEpisodeSpec:
    return ExecutionEpisodeSpec(
        episode_id=episode_id,
        symbol="SOLUSDT",
        generation="v22",
        variant_id="v22_maker_ttl90_gap48_tp80",
        candidate_fingerprint=fingerprint,
        execution_model_rule="minute_l2_fifo_oco_gap_v3",
        evidence_semantics_fingerprint="b" * 64,
        start_regime="RANGE",
        started_at_ms=1,
        entry_deadline_ms=5_400_001,
        diagnostic_at_ms=18_000_001,
        primary_deadline_ms=21_600_001,
        entry_price=D("99"),
        take_profit_price=D("100"),
        stop_trigger_price=D("98"),
        stop_limit_price=D("97.9"),
        quantity=D("0.1"),
        maker_buy_fee_pct=D("0.001"),
        maker_sell_fee_pct=D("0.001"),
        taker_sell_fee_pct=D("0.001"),
    )


def _result(episode_id: str, fingerprint: str) -> ExecutionEpisodeResult:
    return ExecutionEpisodeResult(
        episode_id=episode_id,
        symbol="SOLUSDT",
        generation="v22",
        variant_id="v22_maker_ttl90_gap48_tp80",
        candidate_fingerprint=fingerprint,
        execution_model_rule="minute_l2_fifo_oco_gap_v3",
        evidence_semantics_fingerprint="b" * 64,
        start_regime="RANGE",
        started_at_ms=1,
        terminal_at_ms=120_001,
        terminal_reason="STOP_LIMIT",
        entry_filled_quantity=D("0.1"),
        entry_fill_fraction=D("1"),
        entry_notional_quote=D("9.9"),
        exit_filled_quantity=D("0.1"),
        gross_pnl_quote=D("-0.1"),
        net_pnl_quote=D("-0.12"),
        total_fee_quote=D("0.02"),
        adverse_selection_pct=D("0.01"),
        diagnostic_300m_net_pnl_quote=None,
        stop_triggered=True,
        stop_limit_unfilled=False,
        panic_veto=False,
        eligible_for_promotion=True,
    )


def _parameters() -> dict[str, object]:
    return {
        "target_return": "0.008",
        "stop_distance": "0.01035",
        "fee_schedule": {
            "maker_buy_fee_pct": "0.001",
            "maker_sell_fee_pct": "0.001",
            "taker_sell_fee_pct": "0.001",
        },
    }


def test_entry_path_survives_strategy_exit_and_is_cutoff_safe(tmp_path):
    store = PredictionShadowStore(tmp_path / "prediction.sqlite3")
    fingerprint = "a" * 64
    record_episode_start(store, _spec("episode-1", fingerprint))
    record_episode_result(store, _result("episode-1", fingerprint))
    seed = _event(60_001, "99", sell_flow=True)
    approach = EntryApproachTracker.from_seed(_event(1, "100"))
    approach.observe(seed)
    start_entry_diagnostic(
        store,
        episode_id="episode-1",
        symbol="SOLUSDT",
        generation="v22",
        candidate_fingerprint=fingerprint,
        average_entry_price=D("99"),
        event=seed,
        approach=approach.snapshot(fill_ts_ms=seed.ts_ms),
    )
    for minute in range(1, 361):
        bid = (
            D("99") + D(minute) * D("0.1")
            if minute <= 8 else D("99.4")
        )
        advance_entry_diagnostics(
            store,
            symbol="SOLUSDT",
            event=_event(seed.ts_ms + minute * 60_000, format(bid, "f")),
        )

    before = entry_diagnostic_report(
        store,
        symbol="SOLUSDT",
        generation="v22",
        candidate_fingerprint=fingerprint,
        cutoff_ts_ms=seed.ts_ms + 360 * 60_000 - 1,
        target_return=D("0.008"),
        candidate_parameters=_parameters(),
    )
    complete = entry_diagnostic_report(
        store,
        symbol="SOLUSDT",
        generation="v22",
        candidate_fingerprint=fingerprint,
        cutoff_ts_ms=seed.ts_ms + 360 * 60_000,
        target_return=D("0.008"),
        candidate_parameters=_parameters(),
    )

    assert before["completed_filled_paths"] == 0
    assert complete["completed_filled_paths"] == 1
    assert complete["target_reachability"] == "1"
    assert complete["affects_v22_promotion"] is False
    with store._connect() as connection:
        raw = connection.execute(
            "SELECT summary_json FROM prediction_entry_diagnostic_summaries"
        ).fetchone()[0]
        payload = json.loads(str(raw))
        assert set(payload["horizon_samples"]) == {
            "1", "5", "15", "30", "60", "180", "360"
        }
        assert payload["threshold_hit_ms"]["20"] == 120_000
        assert D(payload["horizon_samples"]["360"][
            "profit_giveback_pct"
        ]) > D("0")
        with pytest.raises(sqlite3.IntegrityError, match="immutable"):
            connection.execute(
                "UPDATE prediction_entry_diagnostic_summaries "
                "SET status='DATA_GAP'"
            )


def test_diagnostic_gap_fails_closed_without_touching_episode_result(tmp_path):
    store = PredictionShadowStore(tmp_path / "prediction.sqlite3")
    fingerprint = "c" * 64
    record_episode_start(store, _spec("episode-gap", fingerprint))
    record_episode_result(store, _result("episode-gap", fingerprint))
    seed = _event(60_001, "99")
    approach = EntryApproachTracker.from_seed(seed)
    start_entry_diagnostic(
        store,
        episode_id="episode-gap",
        symbol="SOLUSDT",
        generation="v22",
        candidate_fingerprint=fingerprint,
        average_entry_price=D("99"),
        event=seed,
        approach=approach.snapshot(fill_ts_ms=seed.ts_ms),
    )

    assert advance_entry_diagnostics(
        store,
        symbol="SOLUSDT",
        event=_event(seed.ts_ms + 181_000, "98"),
    ) == 1
    with store._connect() as connection:
        status = connection.execute(
            "SELECT status FROM prediction_entry_diagnostic_summaries"
        ).fetchone()[0]
        eligible = connection.execute(
            "SELECT eligible_for_promotion FROM "
            "prediction_execution_episode_results"
        ).fetchone()[0]
    assert status == "DATA_GAP"
    assert eligible == 1


def test_diagnostic_rejects_damaged_restart_progress(tmp_path):
    store = PredictionShadowStore(tmp_path / "prediction.sqlite3")
    fingerprint = "e" * 64
    record_episode_start(store, _spec("episode-damaged", fingerprint))
    seed = _event(60_001, "99")
    approach = EntryApproachTracker.from_seed(seed)
    start_entry_diagnostic(
        store,
        episode_id="episode-damaged",
        symbol="SOLUSDT",
        generation="v22",
        candidate_fingerprint=fingerprint,
        average_entry_price=D("99"),
        event=seed,
        approach=approach.snapshot(fill_ts_ms=seed.ts_ms),
    )
    hidden = entry_diagnostic_report(
        store,
        symbol="SOLUSDT",
        generation="v22",
        candidate_fingerprint=fingerprint,
        cutoff_ts_ms=seed.ts_ms - 1,
        target_return=D("0.008"),
        candidate_parameters=_parameters(),
    )
    visible = entry_diagnostic_report(
        store,
        symbol="SOLUSDT",
        generation="v22",
        candidate_fingerprint=fingerprint,
        cutoff_ts_ms=seed.ts_ms,
        target_return=D("0.008"),
        candidate_parameters=_parameters(),
    )
    assert hidden["active_paths"] == 0
    assert visible["active_paths"] == 1
    with store._connect() as connection:
        connection.execute(
            "UPDATE prediction_entry_diagnostic_progress "
            "SET progress_json='{}' WHERE episode_id='episode-damaged'"
        )
    with pytest.raises(ValueError, match="fingerprint differs"):
        advance_entry_diagnostics(
            store,
            symbol="SOLUSDT",
            event=_event(seed.ts_ms + 60_000, "99"),
        )


def test_l2_history_import_uses_terminal_fill_despite_later_diagnostic_gap(
    tmp_path,
):
    store = PredictionShadowStore(tmp_path / "prediction.sqlite3")
    fingerprint = "f" * 64
    record_episode_start(store, _spec("episode-history", fingerprint))
    record_episode_result(store, _result("episode-history", fingerprint))
    summary = {
        "contract_version": "entry_path_shadow_v2",
        "complete": False,
        "episode_id": "episode-history",
        "fill_ts_ms": 360_001,
    }
    encoded_summary = json.dumps(
        summary, sort_keys=True, separators=(",", ":")
    )
    with store._connect() as connection:
        connection.execute(
            """INSERT INTO prediction_entry_diagnostic_summaries
               (episode_id,symbol,generation,candidate_fingerprint,fill_ts_ms,
                completed_at_ms,status,summary_json,summary_sha256,created_at_ms)
               VALUES(?,?,?,?,?,?,?,?,?,?)""",
            (
                "episode-history", "SOLUSDT", "v22", fingerprint, 360_001,
                22_000_000, "DATA_GAP", encoded_summary,
                hashlib.sha256(encoded_summary.encode()).hexdigest(), 22_000_000,
            ),
        )
    archive_directory = tmp_path / "archives"
    archive_directory.mkdir()
    archive = archive_directory / "SOLUSDT-history.jsonl"
    rows = [
        {
            "lastUpdateId": 1, "E": 60_001, "s": "SOLUSDT",
            "bids": [["100", "10"]], "asks": [["100.01", "10"]],
        },
        {
            "e": "depthUpdate", "E": 120_001, "U": 2, "u": 2,
            "b": [["100", "0"], ["99.9", "5"]],
            "a": [["100.01", "0"], ["99.91", "15"]],
        },
        {
            "e": "aggTrade", "E": 121_000, "p": "99.9", "q": "2",
            "m": True,
        },
        {
            "e": "depthUpdate", "E": 240_001, "U": 3, "u": 3,
            "b": [["99.9", "0"], ["99.8", "4"]],
            "a": [["99.91", "0"], ["99.81", "18"]],
        },
        {
            "e": "aggTrade", "E": 241_000, "p": "99.8", "q": "3",
            "m": True,
        },
        {
            "e": "depthUpdate", "E": 359_000, "U": 4, "u": 4,
            "b": [["99.8", "0"], ["99.7", "3"]],
            "a": [["99.81", "0"], ["99.71", "20"]],
        },
        {
            "e": "aggTrade", "E": 359_500, "p": "99.7", "q": "4",
            "m": True,
        },
        {
            "e": "depthUpdate", "E": 420_001, "U": 5, "u": 5,
            "b": [["99.7", "0"], ["99.8", "3"]],
            "a": [["99.71", "0"], ["99.81", "20"]],
        },
    ]
    encoded_archive = "".join(json.dumps(row) + "\n" for row in rows)
    archive.write_text(encoded_archive)
    archive.with_suffix(".jsonl.metadata.json").write_text(json.dumps({
        "schema_version": 1,
        "symbol": "SOLUSDT",
        "started_at_ms": 60_001,
        "finished_at_ms": 420_001,
        "archive_sha256": hashlib.sha256(encoded_archive.encode()).hexdigest(),
        "contains_secrets": False,
    }))

    report = import_entry_veto_l2_history(store, archive_directory)
    repeated = import_entry_veto_l2_history(store, archive_directory)

    assert report["status"] == "PASS", report
    assert report["matched_archives"] == 1
    assert report["validated_archives"] == 1
    assert report["imported_paths"] == 1
    assert repeated["imported_paths"] == 0
    with store._connect() as connection:
        payload = json.loads(connection.execute(
            "SELECT feature_json FROM prediction_entry_l2_features"
        ).fetchone()[0])
    assert payload["contract_version"] == "binance_diff_depth_entry_veto_v3"
    selection = entry_diagnostic_report(
        store,
        symbol="SOLUSDT",
        generation="v22",
        candidate_fingerprint=fingerprint,
        cutoff_ts_ms=22_000_000,
        target_return=D("0.008"),
        candidate_parameters=_parameters(),
    )
    assert selection["completed_filled_paths"] == 0
    assert selection["selection_filled_paths"] == 1
    assert selection["incomplete_paths"] == 1

def test_fee_aware_geometry_matches_conservative_spot_costs():
    economics = fee_aware_candidate_economics(
        _parameters(), target_reachability=D("0.25")
    )

    assert economics["expected_net_win_pct"] == "0.005992"
    assert economics["expected_stop_loss_pct"] == "-0.01233965"
    assert economics["minimum_break_even_win_rate"] == (
        "0.6731336240873025614170028339"
    )
    assert economics["target_reachability"] == "0.25"


def test_future_manifest_rule_binds_veto_and_fee_aware_economics():
    plan = TradePlan(
        entry_price=D("100"),
        take_profit_price=D("100.8"),
        stop_price=D("98.965"),
        notional_quote=D("6"),
        fee_pct=D("0.001"),
        slippage_pct=D("0"),
        entry_ttl_sec=5_400,
        maker_buy_fee_pct=D("0.001"),
        maker_sell_fee_pct=D("0.001"),
        taker_buy_fee_pct=D("0.001"),
        taker_sell_fee_pct=D("0.001"),
        maximum_holding_min=360,
    )
    variant = ShadowVariant(
        variant_id="v23_maker_ttl90_gap48_veto",
        dimension="entry_adverse_selection_veto",
        kind="EXPERIMENT_V23_MAKER_TTL90_GAP48_VETO",
        plan=plan,
        baseline_plan=plan,
        maker_only=True,
        entry_gap_bps=D("48"),
        regime_policy="range_only",
        candidate_rule_version=8,
        execution_model_rule="minute_l2_fifo_oco_gap_v3",
        execution_model_promotion_ready=True,
        evidence_semantics_fingerprint="d" * 64,
        entry_veto_rule={
            "contract_version": "l2_adverse_selection_cancel_v4",
            "prefill_price_change_max_bps": -10,
            "prefill_signed_trade_flow_max": "-0.20",
            "prefill_order_flow_imbalance_max": "-0.10",
            "cancel_latency_ms": 1000,
            "signal_window_ms": 300000,
            "selection_artifact_sha256": "e" * 64,
        },
        target_reachability=D("0.25"),
    )

    rule = candidate_rule(variant, generation="v23", horizons_min=(300, 360))

    assert rule["candidate_rule_version"] == 8
    assert rule["entry_veto_rule"]["prefill_price_change_max_bps"] == "-10"
    assert rule["entry_veto_rule"]["cancel_latency_ms"] == 1000
    assert rule["entry_veto_rule"]["selection_artifact_sha256"] == "e" * 64
    assert rule["candidate_economics"]["target_reachability"] == "0.25"
    assert rule["candidate_economics"][
        "minimum_break_even_win_rate"
    ] == "0.6731336240873025614170028339"


def test_future_entry_veto_contract_rejects_unknown_fields():
    from ladder_dragon.strategy.prediction.entry_diagnostics import (
        normalize_entry_veto_rule,
    )

    with pytest.raises(ValueError, match="fields are invalid"):
        normalize_entry_veto_rule({
            "contract_version": "prefill_momentum_flow_v1",
            "prefill_price_change_max_bps": "-10",
            "prefill_signed_trade_flow_max": "-0.20",
            "unreviewed_runtime_switch": True,
        })


def test_prefill_tracker_keeps_only_completed_five_minute_window():
    tracker = EntryApproachTracker.from_seed(_event(1, "100"))
    for minute in range(1, 8):
        tracker.observe(_event(minute * 60_000 + 1, str(100 - minute)))

    snapshot = tracker.snapshot(fill_ts_ms=480_001)

    assert snapshot["prefill_window_contract"] == (
        "completed_intervals_before_fill_v1"
    )
    assert snapshot["approach_started_at_ms"] == 120_001
    assert snapshot["prefill_duration_ms"] == 360_000
