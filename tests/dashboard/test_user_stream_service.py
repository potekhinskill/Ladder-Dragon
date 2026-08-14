"""User Stream dashboard metric regressions."""

from ladder_dragon.dashboard.services.user_stream import (
    current_soak_epoch_metrics,
)


def test_current_soak_epoch_metrics_preserve_lifetime_counter_context():
    metrics = current_soak_epoch_metrics({
        "current_soak_epoch_id": "transport-stability-2026-08-v1",
        "reconnects": 1_070,
        "order_events": 3,
        "soak_epochs": [{
            "id": "transport-stability-2026-08-v1",
            "started_at": 1_000,
            "baseline": {"reconnects": 1_069, "order_events": 2},
        }],
    }, now=1_000 + 1_800)

    assert metrics == {
        "soak_epoch_id": "transport-stability-2026-08-v1",
        "soak_epoch_hours": 0.5,
        "soak_epoch_reconnects": 1,
        "soak_epoch_order_events": 1,
        "soak_epoch_sessions": 0,
        "soak_epoch_planned_reconnects": 0,
        "soak_epoch_failure_reconnects": 0,
        "soak_epoch_connection_attempts": 0,
        "soak_epoch_disconnects": 0,
    }


def test_current_epoch_separates_planned_and_failure_reconnects():
    metrics = current_soak_epoch_metrics({
        "current_soak_epoch_id": "v5",
        "reconnects": 40,
        "idle_reconnects": 10,
        "controlled_reconnect_drills": 3,
        "transport_failure_reconnects": 7,
        "connection_attempts": 45,
        "disconnects": 20,
        "sessions": 25,
        "soak_epochs": [{
            "id": "v5",
            "started_at": 1_000,
            "baseline": {
                "reconnects": 35,
                "idle_reconnects": 8,
                "controlled_reconnect_drills": 2,
                "transport_failure_reconnects": 5,
                "connection_attempts": 40,
                "disconnects": 17,
                "sessions": 20,
            },
        }],
    }, now=4_600)

    assert metrics["soak_epoch_reconnects"] == 5
    assert metrics["soak_epoch_planned_reconnects"] == 3
    assert metrics["soak_epoch_failure_reconnects"] == 2
    assert metrics["soak_epoch_connection_attempts"] == 5
    assert metrics["soak_epoch_disconnects"] == 3
    assert metrics["soak_epoch_sessions"] == 5


def test_current_soak_epoch_metrics_hide_damaged_evidence():
    metrics = current_soak_epoch_metrics({
        "current_soak_epoch_id": "transport-stability-2026-08-v1",
        "soak_epochs": [],
    }, now=2_000)

    assert metrics["soak_epoch_id"] is None
