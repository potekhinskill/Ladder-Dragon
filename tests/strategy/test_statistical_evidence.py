from __future__ import annotations

import json

from ladder_dragon.strategy.prediction.runtime import PredictionShadowStore
from ladder_dragon.strategy.prediction.statistical_evidence import (
    resolved_independent_evidence,
)


def _outcome(horizon: int, resolved_at: int) -> str:
    return json.dumps({
        "horizon_min": horizon,
        "buy_filled": True,
        "tp_before_stop": True,
        "net_pnl_quote": "1",
        "mae_pct": "0.01",
        "time_to_fill_sec": 30,
        "exit_reason": "TP",
        "resolved_at_ms": resolved_at,
    })


def test_full_history_reader_reaches_gate_without_loading_overlaps(tmp_path):
    store = PredictionShadowStore(tmp_path / "prediction.sqlite3")
    horizons = (300, 360)
    cadence_ms = 5 * 60_000
    rows = []
    outcomes = []
    for index in range(9_000):
        snapshot = index * cadence_ms
        decision_id = f"decision-{index:04d}"
        rows.append((
            decision_id, 2, "EXPERIMENT_TEST", "SOLUSDT", snapshot,
            '{"regime":"RANGE"}', "{}", "{}", "[]", "test", snapshot,
            "selection:v1:SOLUSDT", "SELECTION", "candidate", "baseline",
        ))
        for horizon in horizons:
            resolved_at = snapshot + horizon * 60_000
            payload = _outcome(horizon, resolved_at)
            outcomes.append((
                decision_id, horizon, resolved_at, resolved_at, payload,
                payload, None, None, None,
            ))
    with store._connect() as connection:
        connection.executemany(
            "INSERT INTO prediction_decisions VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            rows,
        )
        connection.executemany(
            "INSERT INTO prediction_outcomes VALUES(?,?,?,?,?,?,?,?,?)",
            outcomes,
        )
        connection.commit()

    bounded = store.resolved_samples(
        "SOLUSDT",
        kind="EXPERIMENT_TEST",
        experiment_id="selection:v1:SOLUSDT",
        evidence_role="SELECTION",
    )
    evidence = resolved_independent_evidence(
        store,
        "SOLUSDT",
        kind="EXPERIMENT_TEST",
        experiment_id="selection:v1:SOLUSDT",
        evidence_role="SELECTION",
        required_horizons_min=horizons,
    )

    assert len({row.snapshot_ts_ms for row in bounded}) == 1_000
    assert len({row.snapshot_ts_ms for row in evidence.samples}) >= 120
    assert len(evidence.samples) <= 512 * len(horizons)
    assert evidence.excluded_overlapping_snapshots > 0


def test_full_history_reader_stops_at_first_independent_pending_snapshot(tmp_path):
    store = PredictionShadowStore(tmp_path / "prediction.sqlite3")
    with store._connect() as connection:
        for index, snapshot in enumerate((0, 16 * 60_000, 32 * 60_000)):
            decision_id = f"decision-{index}"
            connection.execute(
                "INSERT INTO prediction_decisions VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    decision_id, 2, "CONTROL_TEST", "SOLUSDT", snapshot,
                    '{"regime":"RANGE"}', "{}", "{}", "[]", "test", snapshot,
                    None, "LEGACY", None, None,
                ),
            )
            for horizon in (1, 5, 15):
                resolved_at = snapshot + horizon * 60_000
                payload = None if index == 1 else _outcome(horizon, resolved_at)
                connection.execute(
                    "INSERT INTO prediction_outcomes VALUES(?,?,?,?,?,?,?,?,?)",
                    (
                        decision_id, horizon, resolved_at,
                        resolved_at if payload else None, payload, payload,
                        None, None, None,
                    ),
                )
        connection.commit()

    evidence = resolved_independent_evidence(
        store,
        "SOLUSDT",
        kind="CONTROL_TEST",
        required_horizons_min=(1, 5, 15),
    )

    assert {row.snapshot_ts_ms for row in evidence.samples} == {0}
    assert evidence.stopped_at_pending_snapshot is True


def test_control_reader_keeps_late_binding_rows_after_nonbinding_capacity(tmp_path):
    store = PredictionShadowStore(tmp_path / "prediction.sqlite3")
    with store._connect() as connection:
        for index in range(9):
            snapshot = index * 2 * 60_000
            decision_id = f"control-{index}"
            metadata = json.dumps({"binding": index >= 6})
            connection.execute(
                "INSERT INTO prediction_decisions VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    decision_id, 2, "CONTROL_EXPECTANCY_V4", "SOLUSDT",
                    snapshot, '{"regime":"RANGE"}',
                    '{"notional_quote":"10"}',
                    '{"notional_quote":"10"}', "[]",
                    metadata, snapshot, None, "LEGACY", None, None,
                ),
            )
            resolved_at = snapshot + 60_000
            payload = _outcome(1, resolved_at)
            connection.execute(
                "INSERT INTO prediction_outcomes VALUES(?,?,?,?,?,?,?,?,?)",
                (decision_id, 1, resolved_at, resolved_at, payload, payload,
                 None, None, None),
            )
        connection.commit()

    evidence = resolved_independent_evidence(
        store, "SOLUSDT", kind="CONTROL_EXPECTANCY_V4",
        required_horizons_min=(1,), maximum_snapshots=3,
        prefer_binding=True,
    )

    assert evidence.total_independent_snapshots == 9
    assert evidence.retained_binding_snapshots == 3
    assert evidence.discarded_nonbinding_snapshots == 3
    assert len({row.snapshot_ts_ms for row in evidence.samples}) == 6
    assert evidence.cohort_summary["independent_snapshots"] == 9
    assert evidence.cohort_summary["binding_snapshots"] == 3
