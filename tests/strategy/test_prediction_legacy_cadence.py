from __future__ import annotations

from ladder_dragon.strategy.prediction.legacy_cadence import (
    LEGACY_EVIDENCE_CADENCE_MS,
)
from ladder_dragon.strategy.prediction.runtime import (
    PredictionShadowStore,
)


def _insert_legacy_snapshot(store: PredictionShadowStore, snapshot_ts_ms: int) -> None:
    with store._connect() as connection:
        connection.execute(
            """INSERT INTO prediction_decisions
               (decision_id,schema_version,kind,symbol,snapshot_ts_ms,
                feature_json,plan_json,prediction_json,algorithm_decision,
                created_at_ms,evidence_role)
               VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            (
                "a" * 64,
                7,
                "STRATEGY",
                "SOLUSDT",
                snapshot_ts_ms,
                "{}",
                "{}",
                "[]",
                "WAIT",
                snapshot_ts_ms,
                "LEGACY",
            ),
        )


def test_legacy_snapshot_cadence_survives_store_restart(tmp_path):
    path = tmp_path / "prediction.sqlite3"
    store = PredictionShadowStore(path)
    snapshot = 10 * LEGACY_EVIDENCE_CADENCE_MS + 10_000

    assert store.legacy_snapshot_due(
        kind="STRATEGY", symbol="SOLUSDT", snapshot_ts_ms=snapshot
    ) is True
    _insert_legacy_snapshot(store, snapshot)

    restarted = PredictionShadowStore(path)
    assert restarted.legacy_snapshot_due(
        kind="STRATEGY", symbol="SOLUSDT", snapshot_ts_ms=snapshot + 30_000
    ) is False
    assert restarted.legacy_snapshot_due(
        kind="STRATEGY",
        symbol="SOLUSDT",
        snapshot_ts_ms=snapshot + LEGACY_EVIDENCE_CADENCE_MS,
    ) is True
